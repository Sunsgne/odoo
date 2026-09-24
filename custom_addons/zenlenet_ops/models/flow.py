import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.flow import (
    STATES,
    can_convert,
    can_reclaim,
    next_state,
    normalize_assignment,
    prev_state,
    resource_reference,
    resource_slot,
    step_label,
    team_for,
    team_for_move,
    transition_allowed,
)

TEAMS = [
    ('sales', '销售'),
    ('allocator', '资源'),
    ('delivery', '交付'),
    ('service', '售后'),
    ('procurement', '采购'),
]
DEFAULT_TASKS = [
    ('allocate', '按业务类型分配资源'),
    ('deliver', '开通配置'),
    ('deliver', '连通性 / 带宽测试'),
    ('accept', '客户验收确认'),
]
TASK_STAGES = [
    ('allocate', '分配资源'),
    ('deliver', '交付'),
    ('accept', '验收'),
]
SERVICE_TYPES = [
    ('ipt', 'IPT / RMIPT'),
    ('pl', '专线'),
    ('sdwan', 'SD-WAN'),
    ('vm', '云主机'),
    ('colo', '托管'),
    ('resale', '转售'),
    ('ip', 'IP 地址段'),
    ('ip_single', '单个 IP'),
    ('line', '线路'),
]


class ZenlenetFlow(models.Model):
    _name = 'zenlenet.flow'
    _description = '业务流转'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'zenlenet.deletable']
    _order = 'id desc'

    name = fields.Char(string='编号', required=True, copy=False, default='/', tracking=True)
    kind = fields.Selection([
        ('test', '测试'),
        ('business', '商务'),
    ], string='类型', required=True, default='business', tracking=True)
    move = fields.Selection([
        ('out', '出：开通'),
        ('in', '进：入库'),
        ('back', '退：退回'),
        ('cutover', '割接'),
    ], string='流转', required=True, default='out', tracking=True)
    supplier_id = fields.Many2one(
        'res.partner', string='供应商', domain=[('supplier_rank', '>', 0)], tracking=True,
    )
    return_to = fields.Selection([
        ('stock', '退回库存，还能再卖'),
        ('supplier', '退回供应商'),
    ], string='退到哪里', default='stock', tracking=True)
    place = fields.Char(string='割接地点', tracking=True)
    reason = fields.Char(string='事由')
    impact = fields.Text(string='影响范围')
    window_start = fields.Datetime(string='开始（北京时间）')
    window_end = fields.Datetime(string='结束（北京时间）')
    notice_subject = fields.Char(string='通知主题')
    notice_body = fields.Text(string='通知正文')
    step_name = fields.Char(string='这一步', compute='_compute_step_name')
    state = fields.Selection(
        STATES, string='阶段', default='company', required=True, tracking=True, copy=False,
        group_expand='_group_expand_states',
    )
    user_id = fields.Many2one(
        'res.users', string='当前负责人', required=True, tracking=True,
        default=lambda self: self.env.user, domain=[('share', '=', False)],
    )
    sales_user_id = fields.Many2one(
        'res.users', string='销售', tracking=True, default=lambda self: self.env.user,
        domain="[('share', '=', False), ('zenlenet_in_sales', '=', True)]",
    )
    allocator_user_id = fields.Many2one(
        'res.users', string='资源', tracking=True,
        domain="[('share', '=', False), ('zenlenet_in_allocator', '=', True)]",
    )
    delivery_user_id = fields.Many2one(
        'res.users', string='交付', tracking=True,
        domain="[('share', '=', False), ('zenlenet_in_delivery', '=', True)]",
    )
    service_user_id = fields.Many2one(
        'res.users', string='售后', tracking=True,
        domain="[('share', '=', False), ('zenlenet_in_service', '=', True)]",
    )
    procurement_user_id = fields.Many2one(
        'res.users', string='采购', tracking=True,
        domain="[('share', '=', False), ('zenlenet_in_procurement', '=', True)]",
    )
    can_act = fields.Boolean(compute='_compute_can_act')
    team = fields.Selection(TEAMS, string='分组', compute='_compute_team', store=True, group_expand='_group_expand_teams')
    partner_id = fields.Many2one('res.partner', string='客户', tracking=True, domain=[('is_company', '=', True)])
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='期望数据中心', tracking=True)
    pending_count = fields.Integer(string='待分配', compute='_compute_pending')
    order_id = fields.Many2one(
        'sale.order', string='服务订单', tracking=True, domain="[('partner_id', '=', partner_id)]",
    )
    contract_id = fields.Many2one('zenlenet.contract', string='合同', compute='_compute_contract')
    contract_state = fields.Selection(related='contract_id.state', string='合同状态')
    contract_monthly = fields.Monetary(related='contract_id.monthly_amount', string='合同月费', currency_field='currency_id')
    currency_id = fields.Many2one(related='contract_id.currency_id')
    order_line_ids = fields.One2many(related='order_id.order_line', string='订单明细')
    resource_ids = fields.One2many('zenlenet.flow.resource', 'flow_id', string='资源')
    task_ids = fields.One2many('zenlenet.flow.task', 'flow_id', string='交付任务')
    task_progress = fields.Float(string='任务进度', compute='_compute_task_progress')
    pm_user_id = fields.Many2one('res.users', string='项目经理', tracking=True, domain=[('share', '=', False)])
    planned_date = fields.Date(string='计划交付日期', tracking=True)
    actual_date = fields.Date(string='实际交付日期', readonly=True, copy=False)
    risk = fields.Selection([('normal', '正常'), ('at_risk', '有风险'), ('blocked', '阻塞')], string='风险', compute='_compute_health', store=True)
    next_task_id = fields.Many2one('zenlenet.flow.task', string='下一步', compute='_compute_health', store=True)
    overdue_tasks = fields.Integer(string='逾期任务', compute='_compute_health', store=True)
    blocked_tasks = fields.Integer(string='阻塞任务', compute='_compute_health', store=True)
    ticket_ids = fields.One2many('zenlenet.ticket', 'flow_id', string='工单')
    ticket_count = fields.Integer(compute='_compute_ticket_count')
    address_ids = fields.Many2many('zenlenet.address', string='IP资源')
    line_ids = fields.Many2many('zenlenet.line', string='线路')
    resource_note = fields.Text(string='资源说明')
    note = fields.Text(string='备注')

    def _delete_snapshot(self):
        return {'state': self.state, 'allocated': bool(self.resource_ids.filtered('resource_ref'))}

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'state' in fields_list:
            values['state'] = 'company'
        return values

    def init(self):
        self.env.cr.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'zenlenet_flow' AND column_name = 'move'"
        )
        if self.env.cr.fetchone():
            self.env.cr.execute("UPDATE zenlenet_flow SET move = 'out' WHERE move IS NULL")

    @api.depends('state', 'move')
    def _compute_step_name(self):
        for record in self:
            record.step_name = step_label(record.move, record.state)

    @api.depends('state', 'move')
    def _compute_team(self):
        for record in self:
            record.team = team_for_move(record.move, record.state) or False

    @api.depends('state', 'move')
    @api.depends_context('uid')
    def _compute_can_act(self):
        for record in self:
            record.can_act = record._user_may(record.state)

    @api.model
    def zenlenet_refresh_teams(self):
        records = self.sudo().search([])
        if records:
            self.env.add_to_compute(self._fields['team'], records)
            records._recompute_recordset(['team'])

    @api.depends('resource_ids.resource_ref', 'resource_ids.spec', 'resource_ids.service_type')
    def _compute_pending(self):
        for record in self:
            record.pending_count = len(record.resource_ids.filtered(lambda item: item.needs_resource and not item.resource_ref))

    @api.depends('task_ids.done')
    def _compute_task_progress(self):
        for record in self:
            total = len(record.task_ids)
            done = len(record.task_ids.filtered('done'))
            record.task_progress = round(done * 100.0 / total, 0) if total else 0.0

    @api.depends('task_ids.state', 'task_ids.due_date', 'planned_date', 'state')
    def _compute_health(self):
        today = fields.Date.context_today(self)
        for record in self:
            open_tasks = record.task_ids.filtered(lambda task: task.state not in ('done', 'skipped')).sorted(lambda task: (task.sequence, task.id))
            record.next_task_id = open_tasks[:1]
            record.blocked_tasks = len(open_tasks.filtered(lambda task: task.state == 'blocked'))
            record.overdue_tasks = len(open_tasks.filtered(lambda task: task.due_date and task.due_date < today))
            if record.state in ('done', 'cancel'):
                record.risk = 'normal'
            elif record.blocked_tasks:
                record.risk = 'blocked'
            elif record.overdue_tasks or (record.planned_date and record.planned_date < today):
                record.risk = 'at_risk'
            else:
                record.risk = 'normal'

    def action_open_tasks(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_flow_tasks').read()[0]
        action['domain'] = [('flow_id', '=', self.id)]
        action['context'] = {'default_flow_id': self.id, 'search_default_open': 1}
        action['display_name'] = f'{self.name} · 交付任务'
        return action

    @api.depends('ticket_ids')
    def _compute_ticket_count(self):
        for record in self:
            record.ticket_count = len(record.ticket_ids)

    @api.depends('order_id')
    def _compute_contract(self):
        Contract = self.env['zenlenet.contract']
        for record in self:
            record.contract_id = Contract.search([('order_ids', 'in', record.order_id.id)], limit=1) if record.order_id else False

    def action_open_order(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': self.order_id.id, 'view_mode': 'form', 'target': 'current'}

    def action_open_contract(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'zenlenet.contract', 'res_id': self.contract_id.id, 'view_mode': 'form', 'target': 'current'}

    def action_load_order(self):
        """Create one resource row per service line of the order; rows that already exist are kept."""
        Resource = self.env['zenlenet.flow.resource']
        for record in self:
            if not record.order_id:
                raise UserError('请先选择服务订单。')
            if not record.partner_id:
                record.partner_id = record.order_id.partner_id.commercial_partner_id
            have = set(record.resource_ids.mapped('order_line_id').ids)
            for line in record.order_id.order_line.filtered(lambda item: not item.display_type):
                if line.id in have:
                    continue
                Resource.create({
                    'flow_id': record.id,
                    'service_type': line._zenlenet_service_type(),
                    'order_id': record.order_id.id,
                    'order_line_id': line.id,
                    'spec': f'{line.name or line.product_id.name} × {line.product_uom_qty:g} {line.zenlenet_unit or ""}'.strip(),
                })
            record._ensure_default_tasks()
        return True

    def action_print_delivery(self):
        return self.env.ref('zenlenet_ops.report_delivery').report_action(self)

    def action_open_tickets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} · 工单',
            'res_model': 'zenlenet.ticket',
            'view_mode': 'kanban,list,form',
            'domain': [('flow_id', '=', self.id)],
            'context': {'default_flow_id': self.id, 'default_partner_id': self.partner_id.id, 'default_kind': 'change'},
        }

    @api.model
    def _group_expand_states(self, states, domain):
        return [key for key, _label in STATES if key != 'cancel']

    @api.model
    def _group_expand_teams(self, values, domain):
        return [key for key, _label in TEAMS]

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('zenlenet.flow') or '/'
            vals['state'] = 'company'
        records = super().create(vals_list)
        records._sync_assignee()
        records.filtered(lambda record: (record.move or 'out') == 'out')._ensure_default_tasks()
        return records

    def _ensure_default_tasks(self, service_types=None):
        """Load tasks from templates for the ticket's business types; fall back to the built-in list."""
        Task = self.env['zenlenet.flow.task']
        Template = self.env['zenlenet.task.template']
        for record in self:
            types = set(service_types or record.resource_ids.mapped('service_type'))
            templates = Template.search([('service_type', 'in', list(types | {'all'}))]) if types else Template.search([('service_type', '=', 'all')])
            have = {(task.stage, task.name) for task in record.task_ids}
            start = record.planned_date or fields.Date.context_today(self)
            rows = [(template.stage, template.name, template.team, template.days, template.estimate_hours, template.priority) for template in templates]
            if not rows and not record.task_ids:
                rows = [(stage, name, team_for(stage), 1, 0.0, '0') for stage, name in DEFAULT_TASKS]
            cursor = start
            for index, (stage, name, team, days, hours, priority) in enumerate(rows):
                if (stage, name) in have:
                    continue
                if stage == 'allocate':
                    team = 'allocator'
                person = record._person_for_team(team) or record._person_for(stage)
                cursor = fields.Date.add(cursor, days=max(days or 0, 0))
                Task.create({
                    'flow_id': record.id,
                    'sequence': (len(have) + index + 1) * 10,
                    'stage': stage,
                    'name': name,
                    'user_id': person.id if person else False,
                    'due_date': cursor,
                    'estimate_hours': hours,
                    'priority': priority,
                })
                have.add((stage, name))

    def write(self, vals):
        if {'state', 'kind', 'move'} & set(vals):
            for record in self:
                new_state = vals.get('state', record.state)
                new_kind = vals.get('kind', record.kind)
                new_move = vals.get('move', record.move)
                if new_state != record.state or new_move != record.move or new_kind != record.kind:
                    record._ensure_role(record.state)
                if not transition_allowed(record.kind, record.state, new_kind, new_state, record.move, new_move):
                    raise UserError('请按顺序推进，不能跳步。')
        result = super().write(vals)
        watched = {
            'state', 'move', 'sales_user_id', 'allocator_user_id', 'delivery_user_id',
            'service_user_id', 'procurement_user_id',
        }
        if watched & set(vals):
            self._sync_assignee()
        if {'state', 'kind', 'move', 'address_ids', 'partner_id', 'resource_ids', 'return_to'} & set(vals):
            self._apply_resources()
        return result

    def _person_for_team(self, team):
        self.ensure_one()
        return {
            'sales': self.sales_user_id,
            'allocator': self.allocator_user_id,
            'delivery': self.delivery_user_id,
            'service': self.service_user_id,
            'procurement': self.procurement_user_id,
        }.get(team)

    def _person_for(self, state):
        self.ensure_one()
        return self._person_for_team(team_for_move(self.move, state))

    def _stamp_actor(self):
        field_by_team = {
            'sales': 'sales_user_id',
            'allocator': 'allocator_user_id',
            'delivery': 'delivery_user_id',
            'service': 'service_user_id',
            'procurement': 'procurement_user_id',
        }
        for record in self:
            field = field_by_team.get(team_for_move(record.move, record.state))
            if field and not record[field]:
                record[field] = self.env.user

    def _sync_assignee(self):
        for record in self:
            person = record._person_for(record.state)
            if person and record.user_id != person:
                record.user_id = person

    def _linked_addresses(self):
        self.ensure_one()
        picked = self.resource_ids.mapped('address_id')
        blocks = self.resource_ids.mapped('prefix_id')
        return picked | blocks.mapped('address_ids') | self.address_ids

    def _has_allocation(self):
        self.ensure_one()
        if (self.resource_note or '').strip() or self.address_ids or self.line_ids:
            return True
        return any(
            item.resource_ref or item.order_id or item.address_id or item.prefix_id or item.line_id or (item.spec or '').strip()
            for item in self.resource_ids
        )

    def migrate_resources(self):
        Resource = self.env['zenlenet.flow.resource'].sudo()
        for flow in self.sudo().search([]):
            have_addresses = set(flow.resource_ids.mapped('address_id').ids)
            for address in flow.address_ids:
                if address.id not in have_addresses:
                    Resource.create({
                        'flow_id': flow.id,
                        'service_type': 'ip_single',
                        'address_id': address.id,
                    })
            have_lines = set(flow.resource_ids.mapped('line_id').ids)
            for line in flow.line_ids:
                if line.id not in have_lines:
                    Resource.create({
                        'flow_id': flow.id,
                        'service_type': 'line',
                        'line_id': line.id,
                    })

    ROLE_BY_TEAM = {
        'sales': ('zenlenet_ops.group_sales', '销售'),
        'allocator': ('zenlenet_ops.group_allocator', '资源分配'),
        'delivery': ('zenlenet_ops.group_delivery', '交付'),
        'service': ('zenlenet_ops.group_service', '售后'),
        'procurement': ('zenlenet_ops.group_procurement', '采购'),
    }

    def _user_may(self, state):
        self.ensure_one()
        user = self.env.user
        if user.has_group('zenlenet_ops.group_manager'):
            return True
        team = team_for_move(self.move, state)
        role = self.ROLE_BY_TEAM.get(team)
        if not role:
            return True
        return user.has_group(role[0])

    def _ensure_role(self, state):
        self.ensure_one()
        if self._user_may(state):
            return
        team = team_for_move(self.move, state)
        role = self.ROLE_BY_TEAM.get(team)
        label = role[1] if role else ''
        raise UserError(f'这一步（{step_label(self.move, state)}）由{label}操作。')

    def _check_exit(self):
        self.ensure_one()
        self._ensure_role(self.state)
        move = self.move or 'out'
        if move == 'in':
            if self.state == 'company' and not self.supplier_id:
                raise UserError('入库要先写供应商。')
            if self.state == 'company' and not self.datacenter_id:
                raise UserError('入库要先写进哪个数据中心。')
            if self.state == 'allocate' and not self._has_allocation():
                raise UserError('请先写上要入库的网段、IP 或线路。')
            if self.state == 'allocate':
                busy = self.resource_ids.mapped('prefix_id').filtered('partner_id')
                busy_ip = self.resource_ids.mapped('address_id').filtered(
                    lambda address: address.status in ('allocated', 'testing', 'reserved', 'returning', 'transferring')
                )
                busy_line = self.resource_ids.mapped('line_id').filtered('partner_id')
                taken = (busy[:1].mapped('prefix') or busy_ip[:1].mapped('address') or busy_line[:1].mapped('name'))
                if taken:
                    raise UserError(f'{taken[0]} 已经分给客户或预留了，不能再入库。入库只收还没分出去的资源。')
            return
        if move == 'back':
            if self.state == 'company' and not self._has_allocation():
                raise UserError('请先写上要退的网段、IP 或线路。')
            if self.state == 'company' and self.return_to == 'supplier' and not self.supplier_id:
                raise UserError('退回供应商要先选供应商。')
            if self.state == 'company' and self.return_to != 'supplier' and not self.partner_id:
                raise UserError('退回库存要先写是哪家客户退的。')
            return
        if move == 'cutover':
            if self.state == 'company' and not self.partner_id:
                raise UserError('割接要先写客户。')
            if self.state == 'company' and not (self.place or self.datacenter_id):
                raise UserError('割接要先写地点或数据中心。')
            if self.state == 'company' and not self.window_start:
                raise UserError('割接要先写开始时间。')
            if self.state == 'allocate':
                missing = self.resource_ids.filtered(lambda item: item.needs_resource and not item._cutover_ready())
                if missing:
                    raise UserError('割接每一行都要写原资源，以及换成的另一条资源，不能是同一条。')
            return
        if self.state == 'company':
            if not self.partner_id:
                raise UserError('请先录入客户，再进入下一步。')
            if not self.sales_user_id:
                raise UserError('请指定销售。')
            if not self.delivery_user_id:
                raise UserError('请指定交付。')
        if self.state == 'allocate':
            if not self.delivery_user_id:
                raise UserError('请指定交付。')
            if not self._has_allocation():
                raise UserError('请先按业务类型分配资源，或写上资源说明。')
        if self.state == 'deliver' and not self.service_user_id:
            raise UserError('请指定售后。')
        pending = self.task_ids.filtered(lambda task: task.stage == self.state and not task.done)
        if pending:
            names = '、'.join(pending.mapped('name'))
            raise UserError(f'还有任务没完成：{names}。勾掉之后再推进。')

    def _apply_resources(self):
        for record in self.with_context(zenlenet_flow_apply=True):
            move = record.move or 'out'
            addresses = record._linked_addresses()
            blocks = record.resource_ids.mapped('prefix_id')
            lines = record.resource_ids.mapped('line_id')
            partner = record.partner_id.id or False
            if move == 'in':
                if record.state in ('deliver', 'done'):
                    held = ('allocated', 'testing', 'reserved', 'returning', 'transferring')
                    clear_blocks = blocks.filtered(
                        lambda item: not item.partner_id and not item.address_ids.filtered(lambda address: address.status in held)
                    )
                    clear_addresses = addresses.filtered(lambda address: address.status not in held)
                    clear_lines = lines.filtered(lambda item: not item.partner_id)
                    if clear_blocks:
                        clear_blocks.write({'status': 'active'})
                    if clear_addresses:
                        clear_addresses.write({'status': 'free', 'partner_id': False})
                    if clear_lines:
                        clear_lines.write({'status': 'active'})
                continue
            if move == 'back':
                if record.state == 'reclaim':
                    if blocks:
                        blocks.write({'partner_id': False})
                    if addresses:
                        addresses.write({'status': 'returning', 'partner_id': False})
                    if lines:
                        lines.write({'partner_id': False, 'status': 'deprovisioning'})
                elif record.state == 'done':
                    supplier = record.return_to == 'supplier'
                    if blocks:
                        blocks.write({'partner_id': False, 'status': 'deprecated' if supplier else 'active'})
                    if addresses:
                        payload = {'status': 'returning' if supplier else 'free', 'partner_id': False}
                        if supplier:
                            payload['usage'] = '已退供应商'
                        addresses.write(payload)
                    if lines:
                        lines.write({'partner_id': False, 'status': 'decommissioned' if supplier else 'active'})
                    if supplier:
                        record._log_supplier_return()
                continue
            if move == 'cutover':
                if record.state in ('allocate', 'accept', 'done'):
                    record._apply_cutover(partner)
                continue
            if blocks:
                if record.kind == 'test' and record.state in ('reclaim', 'done'):
                    blocks.write({'partner_id': False})
                elif record.state in ('allocate', 'deliver', 'accept', 'decide', 'done'):
                    blocks.write({'partner_id': partner})
            if lines:
                if record.kind == 'test' and record.state in ('reclaim', 'done'):
                    lines.write({'partner_id': False, 'status': 'active'})
                elif record.state in ('allocate', 'deliver', 'accept', 'decide', 'done'):
                    lines.write({'partner_id': partner, 'status': 'active'})
            if not addresses:
                continue
            if record.kind == 'test' and record.state == 'reclaim':
                addresses.write({'status': 'returning', 'partner_id': False})
            elif record.kind == 'test' and record.state == 'done':
                addresses.write({'status': 'free', 'partner_id': False})
            elif record.kind == 'test' and record.state in ('allocate', 'deliver', 'accept', 'decide'):
                addresses.write({'status': 'testing', 'partner_id': partner})
            elif record.kind == 'business' and record.state in ('allocate', 'deliver', 'accept', 'done'):
                addresses.write({'status': 'allocated', 'partner_id': partner})

    def _apply_cutover(self, partner):
        self.ensure_one()
        for item in self.resource_ids:
            if item.prefix_id:
                item.prefix_id.write({'partner_id': partner, 'status': 'active'})
            if item.address_id:
                item.address_id.write({'partner_id': partner, 'status': 'allocated'})
            if item.line_id:
                item.line_id.write({'partner_id': partner, 'status': 'active'})
            if item.from_prefix_id and item.from_prefix_id != item.prefix_id:
                item.from_prefix_id.write({'partner_id': False, 'status': 'active'})
            if item.from_address_id and item.from_address_id != item.address_id:
                item.from_address_id.write({'partner_id': False, 'status': 'free'})
            if item.from_line_id and item.from_line_id != item.line_id:
                item.from_line_id.write({'partner_id': False, 'status': 'active'})

    def _log_supplier_return(self):
        self.ensure_one()
        Return = self.env['zenlenet.supplier.return']
        today = fields.Date.to_string(fields.Date.context_today(self))
        note = f'工单 {self.name}'
        for item in self.resource_ids:
            label = item.prefix_id.prefix or item.address_id.address or item.line_id.name or item.spec
            if not label or Return.search_count([('resource', '=', label), ('note', '=', note)]):
                continue
            Return.create({
                'supplier_id': self.supplier_id.id,
                'supplier': self.supplier_id.name or '',
                'resource': label,
                'when_text': today,
                'note': note,
            })

    def _post(self, text):
        for record in self:
            who = record.user_id.name or ''
            record.message_post(body=f'{who}：{text}')

    def action_next(self):
        for record in self:
            nxt = next_state(record.kind, record.state, record.move)
            if not nxt:
                if (record.move or 'out') == 'out' and record.kind == 'test' and record.state == 'decide':
                    raise UserError('测试单请选择回收或转商务。')
                continue
            record._ensure_role(record.state)
            record._stamp_actor()
            record._check_exit()
            record.state = nxt
            if record.move == 'cutover' and nxt == 'deliver' and not record.notice_body:
                record._fill_cutover_notice()
            record._post(f'进入{step_label(record.move, nxt)}')
            if nxt == 'done':
                record.actual_date = fields.Date.context_today(self)
            if nxt == 'done' and (record.move or 'out') == 'out' and record.kind == 'business' and record.order_id:
                record.order_id.action_mark_active()

    def _fill_cutover_notice(self):
        self.ensure_one()
        notice = self.env['zenlenet.maintenance'].new({
            'kind': 'cutover',
            'place': self.place or self.datacenter_id.name or '',
            'impact': self.impact or '',
            'reason': self.reason or '',
            'window_start': self.window_start,
            'window_end': self.window_end,
        })
        subject, body = notice._render_notice()
        self.write({'notice_subject': subject, 'notice_body': body})

    def action_fill_notice(self):
        for record in self:
            if record.move != 'cutover':
                raise UserError('只有割接工单生成割接通知。')
            record._fill_cutover_notice()

    def action_prev(self):
        for record in self:
            previous = prev_state(record.kind, record.state, record.move)
            if not previous or record.state in ('done', 'cancel'):
                continue
            record.state = previous
            record._post(f'退回{step_label(record.move, record.state)}')

    def action_reclaim(self):
        for record in self:
            record._ensure_role(record.state)
            if not can_reclaim(record.kind, record.state, record.move):
                raise UserError('只有测试单可以回收。客户退租请另开「退：退回」工单。')
            record.state = 'reclaim'
            record._post('进入回收')

    def action_to_business(self):
        for record in self:
            record._ensure_role(record.state)
            if not can_convert(record.kind, record.state, record.move):
                raise UserError('只有测试单在验收、测试结论或回收时可以转商务。')
            record.write({'kind': 'business', 'state': 'deliver'})
            record._post('转商务，进入交付')

    def action_cancel(self):
        for record in self:
            if record.state in ('done', 'cancel'):
                continue
            record.state = 'cancel'
            record._post('已取消')


TASK_STATES = [
    ('todo', '待开始'),
    ('doing', '进行中'),
    ('blocked', '阻塞'),
    ('done', '已完成'),
    ('skipped', '跳过'),
]


class ZenlenetFlowTask(models.Model):
    _name = 'zenlenet.flow.task'
    _description = '交付任务'
    _order = 'flow_id, sequence, id'
    _inherit = ['mail.thread', 'zenlenet.deletable']

    flow_id = fields.Many2one('zenlenet.flow', string='交付工单', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one(related='flow_id.partner_id', string='客户', store=True)
    sequence = fields.Integer(default=10)
    stage = fields.Selection(TASK_STAGES, string='阶段', required=True, default='deliver')
    name = fields.Char(string='任务', required=True)
    state = fields.Selection(TASK_STATES, string='状态', default='todo', required=True, index=True, tracking=True,
                             group_expand='_group_expand_states')
    priority = fields.Selection([('0', '普通'), ('1', '重要'), ('2', '关键路径')], string='优先级', default='0')
    user_id = fields.Many2one('res.users', string='负责人', domain=[('share', '=', False)], tracking=True)
    planned_start = fields.Date(string='计划开始')
    due_date = fields.Date(string='计划完成', tracking=True)
    actual_start = fields.Datetime(string='实际开始', readonly=True)
    done_at = fields.Datetime(string='实际完成', readonly=True)
    estimate_hours = fields.Float(string='预计工时')
    depends_on_id = fields.Many2one('zenlenet.flow.task', string='前置任务', domain="[('flow_id', '=', flow_id), ('id', '!=', id)]")
    blocker = fields.Char(string='阻塞原因')
    note = fields.Text(string='说明')
    done = fields.Boolean(string='完成', compute='_compute_done', inverse='_inverse_done', store=True)
    overdue = fields.Boolean(string='逾期', compute='_compute_overdue', search='_search_overdue')
    color = fields.Integer(compute='_compute_color')

    def _delete_snapshot(self):
        return {'state': self.state, 'flow_state': self.flow_id.state}

    @api.model
    def _group_expand_states(self, states, domain):
        return [key for key, _label in TASK_STATES]

    @api.depends('state')
    def _compute_done(self):
        for task in self:
            task.done = task.state in ('done', 'skipped')

    def _inverse_done(self):
        for task in self:
            if task.done and task.state not in ('done', 'skipped'):
                task.state = 'done'
            elif not task.done and task.state in ('done', 'skipped'):
                task.state = 'todo'

    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for task in self:
            task.overdue = bool(task.due_date) and task.due_date < today and task.state not in ('done', 'skipped')

    def _search_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        domain = [('due_date', '<', today), ('state', 'not in', ('done', 'skipped'))]
        return domain if (operator == '=' and value) or (operator == '!=' and not value) else ['!'] + domain

    @api.depends('state', 'priority')
    def _compute_color(self):
        for task in self:
            task.color = {'blocked': 1, 'doing': 4, 'done': 10, 'skipped': 0}.get(task.state, 2 if task.priority == '2' else 0)

    def write(self, vals):
        if vals.get('state') == 'doing':
            for task in self.filtered(lambda item: not item.actual_start):
                super(ZenlenetFlowTask, task).write({'actual_start': fields.Datetime.now()})
        if 'state' in vals:
            vals['done_at'] = fields.Datetime.now() if vals['state'] in ('done', 'skipped') else False
            if vals['state'] != 'blocked':
                vals.setdefault('blocker', False)
        if 'done' in vals and 'state' not in vals:
            vals['done_at'] = fields.Datetime.now() if vals['done'] else False
        return super().write(vals)

    def action_start(self):
        self.write({'state': 'doing'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_block(self):
        self.write({'state': 'blocked'})

    def action_reopen(self):
        self.write({'state': 'todo'})


class ZenlenetTaskTemplate(models.Model):
    """Default task list per business type; applied when a delivery ticket loads its order lines."""

    _name = 'zenlenet.task.template'
    _description = '交付任务模板'
    _order = 'service_type, stage, sequence, id'

    service_type = fields.Selection(SERVICE_TYPES + [('all', '所有业务')], string='业务类型', required=True, default='all')
    stage = fields.Selection(TASK_STAGES, string='阶段', required=True, default='deliver')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='任务', required=True)
    team = fields.Selection(TEAMS, string='默认负责分组')
    days = fields.Integer(string='计划用时（天）', default=1)
    estimate_hours = fields.Float(string='预计工时')
    priority = fields.Selection([('0', '普通'), ('1', '重要'), ('2', '关键路径')], string='优先级', default='0')
    active = fields.Boolean(default=True)


class ZenlenetFlowResource(models.Model):
    _name = 'zenlenet.flow.resource'
    _description = '流转资源'
    _order = 'id'
    _inherit = ['zenlenet.deletable']

    flow_id = fields.Many2one('zenlenet.flow', required=True, ondelete='cascade')
    service_type = fields.Selection(SERVICE_TYPES, string='业务类型', required=True)
    order_id = fields.Many2one('sale.order', string='订单')
    order_line_id = fields.Many2one('sale.order.line', string='订单行', ondelete='set null')
    resource_ref = fields.Reference(
        selection=[('zenlenet.prefix', 'IP 地址段'), ('zenlenet.address', '单个 IP'), ('zenlenet.line', '线路')],
        string='交付资源',
    )
    partner_id = fields.Many2one(related='flow_id.partner_id', string='客户', store=True)
    flow_state = fields.Selection(related='flow_id.state', string='工单阶段', store=True)
    datacenter_id = fields.Many2one(related='flow_id.datacenter_id', string='期望数据中心', store=True)
    flow_user_id = fields.Many2one(related='flow_id.delivery_user_id', string='交付负责人')
    needs_resource = fields.Boolean(string='需要资源', compute='_compute_needs_resource', store=True)
    prefix_id = fields.Many2one('zenlenet.prefix', string='网段', index=True)
    address_id = fields.Many2one('zenlenet.address', string='IP', index=True)
    line_id = fields.Many2one('zenlenet.line', string='线路', index=True)
    from_prefix_id = fields.Many2one('zenlenet.prefix', string='原网段', index=True)
    from_address_id = fields.Many2one('zenlenet.address', string='原 IP', index=True)
    from_line_id = fields.Many2one('zenlenet.line', string='原线路', index=True)
    flow_move = fields.Selection(related='flow_id.move', string='流转')
    spec = fields.Char(string='规格 / 说明')

    def _delete_snapshot(self):
        return {'assigned': bool(self.resource_ref), 'flow_state': self.flow_id.state}

    def _cutover_ready(self):
        self.ensure_one()
        slot = resource_slot(self.service_type)
        pairs = {
            'prefix': (self.prefix_id, self.from_prefix_id),
            'address': (self.address_id, self.from_address_id),
            'line': (self.line_id, self.from_line_id),
        }
        new, old = pairs.get(slot, (False, False))
        return bool(new and old and new != old)

    @api.depends('service_type')
    def _compute_needs_resource(self):
        for record in self:
            record.needs_resource = record.service_type in ('ipt', 'pl', 'sdwan', 'ip', 'ip_single', 'line')

    def _wanted_prefixlen(self):
        self.ensure_one()
        found = re.search(r'/(\d{1,3})', self.spec or '')
        if found:
            return int(found.group(1))
        return 24 if self.service_type in ('ipt', 'ip') else 0

    def action_suggest(self):
        """Fill the one slot this business uses: a free block, a free host, or a free circuit."""
        Prefix = self.env['zenlenet.prefix']
        Address = self.env['zenlenet.address']
        Line = self.env['zenlenet.line']
        for record in self:
            if record.resource_ref:
                continue
            slot = resource_slot(record.service_type)
            dc = [('datacenter_id', '=', record.datacenter_id.id)] if record.datacenter_id else []
            if slot == 'line':
                line = Line.search([('status', 'in', ('planned', 'provisioning', 'active')), ('partner_id', '=', False)] + dc, limit=1, order='name')
                if not line:
                    raise UserError(f'{record.datacenter_id.name or "库里"}没有空闲线路，请先采购或录入。')
                record.line_id = line
            elif slot == 'address':
                address = Address.search([('status', '=', 'free')] + dc, limit=1, order='address')
                if not address:
                    raise UserError(f'{record.datacenter_id.name or "库里"}没有未分配的 IP。')
                record.address_id = address
            elif slot == 'prefix':
                wanted = record._wanted_prefixlen()
                base = [('status', 'in', ('active', 'reserved')), ('partner_id', '=', False), ('child_ids', '=', False)]
                if wanted:
                    base.append(('prefixlen', '=', wanted))
                candidates = Prefix.search(base + dc, limit=1, order='prefix') or Prefix.search(base, limit=1, order='prefix')
                if not candidates:
                    raise UserError(f'没有空闲的 /{wanted or "任意"} 网段，请先切割或录入。')
                record.prefix_id = candidates
            else:
                raise UserError('这项业务不需要分配网段、IP 或线路。')
        return True

    def action_open_flow(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'zenlenet.flow',
            'res_id': self.flow_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_finish_allocation(self):
        """Header button on the queue: advance every fully allocated ticket from 分配资源 to 交付."""
        flows = self.mapped('flow_id').filtered(lambda flow: flow.state == 'allocate' and not flow.pending_count)
        if not flows:
            raise UserError('勾选的工单还有没挂资源的行，或者不在「分配资源」阶段。')
        flows.mapped('task_ids').filtered(lambda task: task.stage == 'allocate' and not task.done).write({'done': True})
        flows.action_next()
        return True

    def _assignment_vals(self, vals, current=None):
        """Force the row onto the single slot its business type allows, and mirror it into resource_ref."""
        current = current or self.env['zenlenet.flow.resource']
        service = vals.get('service_type', current.service_type if current else None)
        prefix = vals['prefix_id'] if 'prefix_id' in vals else (current.prefix_id.id if current else None)
        address = vals['address_id'] if 'address_id' in vals else (current.address_id.id if current else None)
        line = vals['line_id'] if 'line_id' in vals else (current.line_id.id if current else None)
        ref = vals.get('resource_ref')
        if ref and not isinstance(ref, str):
            ref = f'{ref._name},{ref.id}' if ref else False
        prefix, address, line = normalize_assignment(service, prefix, address, line, ref if not any((prefix, address, line)) else None)
        vals = dict(vals)
        vals['prefix_id'] = prefix or False
        vals['address_id'] = address or False
        vals['line_id'] = line or False
        vals['resource_ref'] = resource_reference(prefix, address, line) or False
        return vals

    def _check_single_holder(self):
        """One network resource belongs to one open ticket. Finished tickets do not block a return or cutover."""
        slots = (
            ('prefix_id', 'from_prefix_id', '网段'),
            ('address_id', 'from_address_id', 'IP'),
            ('line_id', 'from_line_id', '线路'),
        )
        for record in self:
            for field, other, label in slots:
                for target in (record[field], record[other]):
                    if not target:
                        continue
                    clash = self.search([
                        ('id', '!=', record.id),
                        ('flow_state', 'not in', ('done', 'cancel')),
                        '|', (field, '=', target.id), (other, '=', target.id),
                    ], limit=1)
                    if clash:
                        raise UserError(f'{target.display_name} 已经挂在工单 {clash.flow_id.name}。一个{label}同时只走一张未完成的工单。')
            if (record.flow_id.move or 'out') != 'out':
                continue
            for target in (record.prefix_id, record.address_id, record.line_id):
                partner = target.partner_id if target else False
                if partner and partner != record.flow_id.partner_id:
                    raise UserError(f'{target.display_name} 还在 {partner.name} 名下。换客户要先走退回或割接。')

    def _release_dropped(self, before):
        """Clear a customer only when an 开通 ticket drops the resource. 退 and 割接 release on their own steps."""
        for record_id, (old_prefix, old_address, old_line, move) in before.items():
            if (move or 'out') != 'out':
                continue
            current = self.browse(record_id).exists()
            if old_prefix and old_prefix != (current.prefix_id if current else old_prefix.browse()) and not self.search_count([('prefix_id', '=', old_prefix.id), ('flow_state', 'not in', ('cancel',))]):
                old_prefix.with_context(zenlenet_flow_apply=True).write({'partner_id': False})
            if old_address and old_address != (current.address_id if current else old_address.browse()) and not self.search_count([('address_id', '=', old_address.id), ('flow_state', 'not in', ('cancel',))]):
                old_address.with_context(zenlenet_flow_apply=True).write({'partner_id': False, 'status': 'free'})
            if old_line and old_line != (current.line_id if current else old_line.browse()) and not self.search_count([('line_id', '=', old_line.id), ('flow_state', 'not in', ('cancel',))]):
                old_line.with_context(zenlenet_flow_apply=True).write({'partner_id': False})

    def unlink(self):
        before = {
            record.id: (record.prefix_id, record.address_id, record.line_id, record.flow_id.move or 'out')
            for record in self
        }
        flows = self.flow_id
        result = super().unlink()
        self._release_dropped(before)
        flows._apply_resources()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._assignment_vals(dict(vals)) for vals in vals_list]
        records = super().create(vals_list)
        records._check_single_holder()
        records.flow_id._apply_resources()
        return records

    def write(self, vals):
        keys = {'prefix_id', 'address_id', 'line_id', 'resource_ref', 'service_type'}
        before = {}
        if keys & set(vals):
            before = {
                record.id: (record.prefix_id, record.address_id, record.line_id, record.flow_id.move or 'out')
                for record in self
            }
            if len(self) == 1:
                vals = self._assignment_vals(vals, self)
            else:
                for record in self:
                    super(ZenlenetFlowResource, record).write(record._assignment_vals(dict(vals), record))
                self._check_single_holder()
                self._release_dropped(before)
                self.flow_id._apply_resources()
                return True
        result = super().write(vals)
        if keys & set(vals):
            self._check_single_holder()
            self._release_dropped(before)
            self.flow_id._apply_resources()
        return result

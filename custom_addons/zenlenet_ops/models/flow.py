import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.flow import (
    STATES,
    can_convert,
    can_reclaim,
    next_state,
    prev_state,
    state_label,
    team_for,
    transition_allowed,
)

TEAMS = [
    ('sales', '销售'),
    ('delivery', '交付'),
    ('service', '售后'),
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
    ('pl', '专线 / SD-WAN'),
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
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='编号', required=True, copy=False, default='/', tracking=True)
    kind = fields.Selection([
        ('test', '测试'),
        ('business', '商务'),
    ], string='类型', required=True, default='business', tracking=True)
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
        domain="['&', ('share', '=', False), '|', ('zenlenet_team', '=', 'sales'), ('zenlenet_team', '=', False)]",
    )
    delivery_user_id = fields.Many2one(
        'res.users', string='交付', tracking=True, default=lambda self: self.env.user,
        domain="['&', ('share', '=', False), '|', ('zenlenet_team', '=', 'delivery'), ('zenlenet_team', '=', False)]",
    )
    service_user_id = fields.Many2one(
        'res.users', string='售后', tracking=True, default=lambda self: self.env.user,
        domain="['&', ('share', '=', False), '|', ('zenlenet_team', '=', 'service'), ('zenlenet_team', '=', False)]",
    )
    team = fields.Selection(TEAMS, string='分组', compute='_compute_team', store=True, group_expand='_group_expand_teams')
    partner_id = fields.Many2one('res.partner', string='公司', tracking=True, domain=[('is_company', '=', True)])
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='期望数据中心', tracking=True, help='销售录入时填，分资源的人按这个找网段和线路。')
    pending_count = fields.Integer(string='待分配', compute='_compute_pending')
    order_id = fields.Many2one(
        'sale.order', string='服务订单', tracking=True, domain="[('partner_id', '=', partner_id)]",
        help='从哪张订单来的交付。选好后点「从订单带入」生成业务行。',
    )
    resource_ids = fields.One2many('zenlenet.flow.resource', 'flow_id', string='资源')
    task_ids = fields.One2many('zenlenet.flow.task', 'flow_id', string='交付任务')
    task_progress = fields.Float(string='任务进度', compute='_compute_task_progress')
    ticket_ids = fields.One2many('zenlenet.ticket', 'flow_id', string='工单')
    ticket_count = fields.Integer(compute='_compute_ticket_count')
    address_ids = fields.Many2many('zenlenet.address', string='IP资源')
    line_ids = fields.Many2many('zenlenet.line', string='线路')
    resource_note = fields.Text(string='资源说明')
    note = fields.Text(string='备注')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'state' in fields_list:
            values['state'] = 'company'
        return values

    @api.depends('state')
    def _compute_team(self):
        for record in self:
            record.team = team_for(record.state) or False

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

    @api.depends('ticket_ids')
    def _compute_ticket_count(self):
        for record in self:
            record.ticket_count = len(record.ticket_ids)

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
        records._ensure_default_tasks()
        return records

    def _ensure_default_tasks(self):
        Task = self.env['zenlenet.flow.task']
        for record in self:
            if record.task_ids:
                continue
            Task.create([
                {
                    'flow_id': record.id,
                    'sequence': (index + 1) * 10,
                    'stage': stage,
                    'name': name,
                    'user_id': record._person_for(stage).id if record._person_for(stage) else False,
                }
                for index, (stage, name) in enumerate(DEFAULT_TASKS)
            ])

    def write(self, vals):
        if 'state' in vals or 'kind' in vals:
            for record in self:
                new_state = vals.get('state', record.state)
                new_kind = vals.get('kind', record.kind)
                if not transition_allowed(record.kind, record.state, new_kind, new_state):
                    raise UserError('请按顺序推进，不能跳步。')
        result = super().write(vals)
        if {'state', 'sales_user_id', 'delivery_user_id', 'service_user_id'} & set(vals):
            self._sync_assignee()
        if {'state', 'kind', 'address_ids', 'partner_id', 'resource_ids'} & set(vals):
            self._apply_resources()
        return result

    def _person_for(self, state):
        self.ensure_one()
        team = team_for(state)
        return {
            'sales': self.sales_user_id,
            'delivery': self.delivery_user_id,
            'service': self.service_user_id,
        }.get(team)

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
        'delivery': ('zenlenet_ops.group_delivery', '交付'),
        'service': ('zenlenet_ops.group_service', '售后'),
    }

    def _ensure_role(self, state):
        team = team_for(state)
        role = self.ROLE_BY_TEAM.get(team)
        if not role:
            return
        user = self.env.user
        if user.has_group('zenlenet_ops.group_manager') or user.has_group(role[0]):
            return
        if state == 'allocate' and user.has_group('zenlenet_ops.group_allocator'):
            return
        raise UserError(f'这一步（{state_label(state)}）由{role[1]}岗位操作，你的岗位没有权限。')

    def _check_exit(self):
        self.ensure_one()
        self._ensure_role(self.state)
        if self.state == 'company':
            if not self.partner_id:
                raise UserError('请先录入公司，再进入下一步。')
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
        for record in self:
            addresses = record._linked_addresses()
            blocks = record.resource_ids.mapped('prefix_id')
            if not addresses and not blocks:
                continue
            partner = record.partner_id.id or False
            if blocks:
                if record.kind == 'test' and record.state in ('reclaim', 'done'):
                    blocks.write({'partner_id': False})
                elif record.state in ('allocate', 'deliver', 'accept', 'decide', 'done'):
                    blocks.write({'partner_id': partner})
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

    def _post(self, text):
        for record in self:
            who = record.user_id.name or ''
            record.message_post(body=f'{who}：{text}')

    def action_next(self):
        for record in self:
            nxt = next_state(record.kind, record.state)
            if not nxt:
                if record.kind == 'test' and record.state == 'decide':
                    raise UserError('测试单请选择回收或转商务。')
                continue
            record._check_exit()
            record.state = nxt
            record._post(f'进入{state_label(nxt)}')
            if nxt == 'done' and record.kind == 'business' and record.order_id:
                record.order_id.action_mark_active()

    def action_prev(self):
        for record in self:
            previous = prev_state(record.kind, record.state)
            if not previous or record.state in ('done', 'cancel'):
                continue
            record.state = previous
            record._post(f'退回{state_label(record.state)}')

    def action_reclaim(self):
        for record in self:
            record._ensure_role('accept')
            if not can_reclaim(record.kind, record.state):
                raise UserError('只有测试单可以回收。')
            record.state = 'reclaim'
            record._post('进入回收')

    def action_to_business(self):
        for record in self:
            record._ensure_role('accept')
            if not can_convert(record.kind, record.state):
                raise UserError('只有测试单在验收、测试结论或回收时可以转商务。')
            record.write({'kind': 'business', 'state': 'deliver'})
            record._post('转商务，进入交付')

    def action_cancel(self):
        for record in self:
            if record.state in ('done', 'cancel'):
                continue
            record.state = 'cancel'
            record._post('已取消')


class ZenlenetFlowTask(models.Model):
    _name = 'zenlenet.flow.task'
    _description = '交付任务'
    _order = 'sequence, id'

    flow_id = fields.Many2one('zenlenet.flow', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    stage = fields.Selection(TASK_STAGES, string='阶段', required=True, default='deliver')
    name = fields.Char(string='任务', required=True)
    user_id = fields.Many2one('res.users', string='负责人', domain=[('share', '=', False)])
    due_date = fields.Date(string='截止')
    done = fields.Boolean(string='完成')
    done_at = fields.Datetime(string='完成时间', readonly=True)
    note = fields.Char(string='说明')

    def write(self, vals):
        if 'done' in vals:
            vals['done_at'] = fields.Datetime.now() if vals['done'] else False
        return super().write(vals)


class ZenlenetFlowResource(models.Model):
    _name = 'zenlenet.flow.resource'
    _description = '流转资源'
    _order = 'id'

    flow_id = fields.Many2one('zenlenet.flow', required=True, ondelete='cascade')
    service_type = fields.Selection(SERVICE_TYPES, string='业务类型', required=True)
    order_id = fields.Many2one('sale.order', string='订单')
    order_line_id = fields.Many2one('sale.order.line', string='订单行', ondelete='set null')
    resource_ref = fields.Reference(
        selection=[('zenlenet.prefix', 'IP 地址段'), ('zenlenet.address', '单个 IP'), ('zenlenet.line', '线路')],
        string='交付资源', help='这项业务实际交付的资源：IP 地址段、单个 IP 或线路。',
    )
    partner_id = fields.Many2one(related='flow_id.partner_id', string='客户', store=True)
    flow_state = fields.Selection(related='flow_id.state', string='工单阶段', store=True)
    datacenter_id = fields.Many2one(related='flow_id.datacenter_id', string='期望数据中心', store=True)
    flow_user_id = fields.Many2one(related='flow_id.delivery_user_id', string='交付负责人')
    needs_resource = fields.Boolean(string='需要资源', compute='_compute_needs_resource', store=True)
    prefix_id = fields.Many2one('zenlenet.prefix', string='IP 地址段', compute='_compute_targets', store=True, readonly=False)
    address_id = fields.Many2one('zenlenet.address', string='单个 IP', compute='_compute_targets', store=True, readonly=False)
    line_id = fields.Many2one('zenlenet.line', string='线路', compute='_compute_targets', store=True, readonly=False)
    spec = fields.Char(string='规格 / 说明')

    @api.depends('service_type')
    def _compute_needs_resource(self):
        for record in self:
            record.needs_resource = record.service_type in ('ipt', 'pl', 'ip', 'ip_single', 'line')

    def _wanted_prefixlen(self):
        self.ensure_one()
        found = re.search(r'/(\d{1,3})', self.spec or '')
        if found:
            return int(found.group(1))
        return 24 if self.service_type in ('ipt', 'ip') else 0

    def action_suggest(self):
        """Pick the first free block (or circuit) that fits the request, preferring the wanted data center."""
        Prefix = self.env['zenlenet.prefix']
        Line = self.env['zenlenet.line']
        for record in self:
            if record.resource_ref:
                continue
            if record.service_type in ('pl', 'line'):
                domain = [('status', 'in', ('planned', 'provisioning', 'active')), ('partner_id', '=', False)]
                if record.datacenter_id:
                    domain.append(('datacenter_id', '=', record.datacenter_id.id))
                line = Line.search(domain, limit=1, order='datacenter_id, name')
                if not line:
                    raise UserError(f'{record.datacenter_id.name or "库里"}没有空闲线路，请先采购或录入。')
                record.resource_ref = line
                continue
            wanted = record._wanted_prefixlen()
            base = [('status', 'in', ('active', 'reserved')), ('partner_id', '=', False), ('child_ids', '=', False)]
            if wanted:
                base.append(('prefixlen', '=', wanted))
            candidates = Prefix.search(base + ([('datacenter_id', '=', record.datacenter_id.id)] if record.datacenter_id else []), limit=1, order='prefix')
            if not candidates:
                candidates = Prefix.search(base, limit=1, order='prefix')
            if not candidates:
                raise UserError(f'没有空闲的 /{wanted or "任意"} 网段，请先切割或录入。')
            record.resource_ref = candidates
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

    @api.depends('resource_ref')
    def _compute_targets(self):
        for record in self:
            ref = record.resource_ref
            record.prefix_id = ref if ref and ref._name == 'zenlenet.prefix' else record.prefix_id if not ref else False
            record.address_id = ref if ref and ref._name == 'zenlenet.address' else record.address_id if not ref else False
            record.line_id = ref if ref and ref._name == 'zenlenet.line' else record.line_id if not ref else False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.flow_id._apply_resources()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'address_id', 'prefix_id', 'resource_ref', 'service_type'} & set(vals):
            self.flow_id._apply_resources()
        return result

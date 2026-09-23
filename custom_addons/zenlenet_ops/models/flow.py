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
        picked = self.resource_ids.filtered(lambda item: item.service_type in ('ip', 'ip_single')).mapped('address_id')
        blocks = self.resource_ids.filtered(lambda item: item.service_type == 'ip').mapped('prefix_id')
        return picked | blocks.mapped('address_ids') | self.address_ids

    def _has_allocation(self):
        self.ensure_one()
        if (self.resource_note or '').strip() or self.address_ids or self.line_ids:
            return True
        return any(
            item.order_id or item.address_id or item.prefix_id or item.line_id or (item.spec or '').strip()
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

    def _check_exit(self):
        self.ensure_one()
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
            blocks = record.resource_ids.filtered(lambda item: item.service_type == 'ip').mapped('prefix_id')
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

    def action_prev(self):
        for record in self:
            previous = prev_state(record.kind, record.state)
            if not previous or record.state in ('done', 'cancel'):
                continue
            record.state = previous
            record._post(f'退回{state_label(record.state)}')

    def action_reclaim(self):
        for record in self:
            if not can_reclaim(record.kind, record.state):
                raise UserError('只有测试单可以回收。')
            record.state = 'reclaim'
            record._post('进入回收')

    def action_to_business(self):
        for record in self:
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
    prefix_id = fields.Many2one('zenlenet.prefix', string='IP 地址段')
    address_id = fields.Many2one('zenlenet.address', string='单个 IP')
    line_id = fields.Many2one('zenlenet.line', string='线路')
    spec = fields.Char(string='规格')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.flow_id._apply_resources()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'address_id', 'prefix_id', 'service_type'} & set(vals):
            self.flow_id._apply_resources()
        return result

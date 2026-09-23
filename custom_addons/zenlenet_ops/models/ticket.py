from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.tickets import (
    KINDS,
    SLA_HOURS,
    PRIORITIES,
    STATES,
    due_at,
    is_overdue,
    next_state,
    prev_state,
    state_label,
)

from .settings import param_int

SLA_PARAMS = {'3': 'zenlenet.sla_urgent', '2': 'zenlenet.sla_high', '1': 'zenlenet.sla_normal', '0': 'zenlenet.sla_low'}


class ZenlenetTicket(models.Model):
    _name = 'zenlenet.ticket'
    _description = '工单'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, id desc'

    name = fields.Char(string='工单号', required=True, copy=False, default='/', tracking=True)
    subject = fields.Char(string='标题', required=True, tracking=True)
    kind = fields.Selection(KINDS, string='类型', default='fault', required=True, tracking=True)
    priority = fields.Selection(PRIORITIES, string='优先级', default='1', required=True, tracking=True)
    state = fields.Selection(
        STATES, string='状态', default='new', required=True, tracking=True, index=True,
        group_expand='_group_expand_states',
    )
    partner_id = fields.Many2one('res.partner', string='客户', tracking=True, domain=[('is_company', '=', True)])
    contact = fields.Char(string='客户联系人')
    channel = fields.Selection([
        ('email', '邮件'),
        ('im', '微信 / Telegram'),
        ('phone', '电话'),
        ('monitor', '监控告警'),
        ('internal', '内部'),
    ], string='来源', default='im')
    user_id = fields.Many2one(
        'res.users', string='处理人', tracking=True, domain=[('share', '=', False)],
    )
    team = fields.Selection([
        ('sales', '销售'),
        ('delivery', '交付'),
        ('service', '售后'),
    ], string='分组', default='service', required=True)
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='数据中心')
    address_ids = fields.Many2many('zenlenet.address', string='涉及IP')
    line_ids = fields.Many2many('zenlenet.line', string='涉及线路')
    flow_id = fields.Many2one('zenlenet.flow', string='关联业务流转')
    description = fields.Html(string='问题描述', sanitize=True)
    resolution = fields.Html(string='处理结果', sanitize=True)
    opened_at = fields.Datetime(string='受理时间', default=fields.Datetime.now, required=True)
    due_at = fields.Datetime(string='SLA 截止', compute='_compute_due', store=True)
    resolved_at = fields.Datetime(string='解决时间', readonly=True)
    closed_at = fields.Datetime(string='关闭时间', readonly=True)
    sla_hours = fields.Integer(string='SLA（小时）', compute='_compute_due', store=True)
    overdue = fields.Boolean(string='已超时', compute='_compute_overdue', search='_search_overdue')
    color = fields.Integer(compute='_compute_color')
    credit_ids = fields.One2many('zenlenet.credit', 'ticket_id', string='故障减免')
    credit_count = fields.Integer(compute='_compute_credit_count')

    @api.model
    def _group_expand_states(self, states, domain):
        return [key for key, _label in STATES if key != 'cancel']

    def _sla_table(self):
        return {
            key: param_int(self.env, SLA_PARAMS[key], SLA_HOURS[key])
            for key in SLA_PARAMS
        }

    @api.depends('opened_at', 'priority')
    def _compute_due(self):
        table = self._sla_table()
        for record in self:
            hours = table.get(record.priority, SLA_HOURS['1'])
            record.sla_hours = hours
            record.due_at = due_at(record.opened_at, record.priority, hours)

    def _compute_overdue(self):
        now = fields.Datetime.now()
        for record in self:
            record.overdue = is_overdue(record.state, record.due_at, now)

    def _search_overdue(self, operator, value):
        wanted = (operator == '=' and value) or (operator == '!=' and not value)
        domain = [('due_at', '<', fields.Datetime.now()), ('state', 'not in', ('resolved', 'closed', 'cancel'))]
        return domain if wanted else ['!'] + domain

    @api.depends('credit_ids')
    def _compute_credit_count(self):
        for record in self:
            record.credit_count = len(record.credit_ids)

    def action_open_credits(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_credits').read()[0]
        action['domain'] = [('ticket_id', '=', self.id)]
        action['context'] = {'default_ticket_id': self.id, 'default_partner_id': self.partner_id.id}
        return action

    @api.depends('priority', 'overdue')
    def _compute_color(self):
        palette = {'0': 0, '1': 4, '2': 2, '3': 1}
        for record in self:
            record.color = 1 if record.overdue else palette.get(record.priority, 0)

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('zenlenet.ticket') or '/'
            if vals.get('user_id') and vals.get('state', 'new') == 'new':
                vals['state'] = 'assigned'
        return super().create(vals_list)

    def write(self, vals):
        result = super().write(vals)
        if vals.get('user_id') and 'state' not in vals:
            self.filtered(lambda item: item.state == 'new').write({'state': 'assigned'})
        return result

    def _post(self, text):
        for record in self:
            record.message_post(body=text)

    def action_take(self):
        for record in self:
            record.write({'user_id': self.env.user.id, 'state': 'assigned' if record.state == 'new' else record.state})
            record._post(f'{self.env.user.name} 接单')

    def action_next(self):
        for record in self:
            if record.state in ('assigned', 'processing') and not record.user_id:
                raise UserError('请先指定处理人。')
            if record.state == 'processing' and not (record.resolution or '').strip():
                raise UserError('请先写处理结果，再标记为已解决。')
            nxt = next_state(record.state)
            if not nxt:
                continue
            values = {'state': nxt}
            if nxt == 'resolved':
                values['resolved_at'] = fields.Datetime.now()
            if nxt == 'closed':
                values['closed_at'] = fields.Datetime.now()
            record.write(values)
            record._post(f'进入{state_label(nxt)}')

    def action_prev(self):
        for record in self:
            previous = prev_state(record.state)
            if not previous or record.state in ('closed', 'cancel'):
                continue
            record.state = previous
            record._post(f'退回{state_label(previous)}')

    def action_wait(self):
        for record in self:
            if record.state not in ('assigned', 'processing'):
                continue
            record.state = 'waiting'
            record._post('等待客户反馈')

    def action_cancel(self):
        for record in self:
            if record.state in ('closed', 'cancel'):
                continue
            record.state = 'cancel'
            record._post('已取消')

    def action_request_credit(self):
        self.ensure_one()
        order = self.flow_id.order_id
        if not order:
            order = self.env['sale.order'].search([('partner_id', '=', self.partner_id.id), ('state', '=', 'sale'), ('zenlenet_stage', '=', 'active')], limit=1)
        return {
            'type': 'ir.actions.act_window',
            'name': '申请故障减免',
            'res_model': 'zenlenet.credit',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_ticket_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_order_id': order.id,
                'default_outage_start': self.opened_at,
                'default_outage_end': self.resolved_at or fields.Datetime.now(),
                'default_reason': self.subject,
            },
        }

    def action_open_flow(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'zenlenet.flow',
            'res_id': self.flow_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.flow import (
    STATES,
    can_convert,
    can_reclaim,
    next_state,
    prev_state,
    state_label,
    transition_allowed,
)


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
        'res.users', string='负责人', required=True, tracking=True,
        default=lambda self: self.env.user, domain=[('share', '=', False)],
    )
    partner_id = fields.Many2one('res.partner', string='公司', tracking=True, domain=[('is_company', '=', True)])
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

    @api.model
    def _group_expand_states(self, states, domain):
        return [key for key, _label in STATES if key != 'cancel']

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('zenlenet.flow') or '/'
            vals['state'] = 'company'
        return super().create(vals_list)

    def write(self, vals):
        if 'state' in vals or 'kind' in vals:
            for record in self:
                new_state = vals.get('state', record.state)
                new_kind = vals.get('kind', record.kind)
                if not transition_allowed(record.kind, record.state, new_kind, new_state):
                    raise UserError('请按顺序推进，不能跳步。')
        result = super().write(vals)
        if {'state', 'kind', 'address_ids', 'partner_id'} & set(vals):
            self._apply_resources()
        return result

    def _check_exit(self):
        self.ensure_one()
        if self.state == 'company' and not self.partner_id:
            raise UserError('请先录入公司，再进入下一步。')
        if self.state == 'allocate' and not self.address_ids and not self.line_ids and not (self.resource_note or '').strip():
            raise UserError('请先分配IP、线路，或写上资源说明。')

    def _apply_resources(self):
        for record in self:
            addresses = record.address_ids
            if not addresses:
                continue
            partner = record.partner_id.id or False
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

"""Outage credits: an SLA breach on a service becomes money off the next bill or a credit note."""

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.billing import credit_amount, outage_hours

from .settings import param_int


class ZenlenetCredit(models.Model):
    _name = 'zenlenet.credit'
    _description = '故障减免'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='编号', default='/', copy=False, readonly=True)
    partner_id = fields.Many2one('res.partner', string='客户', required=True, index=True, domain=[('is_company', '=', True)])
    order_id = fields.Many2one('sale.order', string='受影响服务', required=True, domain="[('partner_id', '=', partner_id), ('state', '=', 'sale')]")
    ticket_id = fields.Many2one('zenlenet.ticket', string='故障工单', domain="[('partner_id', '=', partner_id)]")
    contract_id = fields.Many2one('zenlenet.contract', string='合同', compute='_compute_contract', store=True)
    currency_id = fields.Many2one(related='order_id.currency_id')
    monthly_fee = fields.Monetary(string='该服务月费', compute='_compute_amount', store=True)
    outage_start = fields.Datetime(string='故障开始', required=True)
    outage_end = fields.Datetime(string='故障恢复', required=True)
    hours = fields.Float(string='故障时长（小时）', compute='_compute_amount', store=True)
    method = fields.Selection([
        ('hours', '按故障小时：每小时减免月费的 X%'),
        ('percent', '按月费比例：减免月费的 X%'),
        ('amount', '固定金额'),
    ], string='减免方式', default='hours', required=True)
    rate = fields.Float(string='比例 %', default=lambda self: param_int(self.env, 'zenlenet.credit_rate', 5))
    fixed_amount = fields.Monetary(string='固定金额')
    cap_percent = fields.Float(string='上限（月费 %）', default=lambda self: param_int(self.env, 'zenlenet.credit_cap', 100))
    amount = fields.Monetary(string='减免金额', compute='_compute_amount', store=True)
    reason = fields.Text(string='故障说明与依据')
    apply_mode = fields.Selection([
        ('next_invoice', '下期账单抵扣'),
        ('credit_note', '开红字账单（退款 / 冲减）'),
    ], string='处理方式', default='next_invoice', required=True)
    state = fields.Selection([
        ('draft', '待审批'),
        ('approved', '已批准'),
        ('applied', '已抵扣'),
        ('rejected', '已驳回'),
    ], string='状态', default='draft', required=True, tracking=True, index=True)
    approver_id = fields.Many2one('res.users', string='审批人', readonly=True)
    approved_at = fields.Datetime(string='审批时间', readonly=True)
    invoice_id = fields.Many2one('account.move', string='抵扣所在账单', readonly=True)
    requested_by = fields.Many2one('res.users', string='申请人', default=lambda self: self.env.user, readonly=True)

    @api.depends('order_id')
    def _compute_contract(self):
        Contract = self.env['zenlenet.contract']
        for record in self:
            record.contract_id = Contract.search([('order_ids', 'in', record.order_id.id), ('state', 'in', ('active', 'expiring'))], limit=1) if record.order_id else False

    @api.depends('order_id.amount_untaxed', 'outage_start', 'outage_end', 'method', 'rate', 'fixed_amount', 'cap_percent')
    def _compute_amount(self):
        for record in self:
            record.monthly_fee = record.order_id.amount_untaxed if record.order_id else 0.0
            record.hours = outage_hours(record.outage_start, record.outage_end)
            record.amount = credit_amount(
                record.monthly_fee, record.method, hours=record.hours, rate=record.rate,
                amount=record.fixed_amount, cap_ratio=(record.cap_percent or 100.0) / 100.0,
            )

    @api.onchange('ticket_id')
    def _onchange_ticket(self):
        for record in self:
            ticket = record.ticket_id
            if not ticket:
                continue
            record.partner_id = ticket.partner_id or record.partner_id
            if ticket.opened_at:
                record.outage_start = ticket.opened_at
            if ticket.resolved_at:
                record.outage_end = ticket.resolved_at
            if ticket.flow_id.order_id:
                record.order_id = ticket.flow_id.order_id
            if not record.reason:
                record.reason = ticket.subject

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('zenlenet.credit') or '/'
        return super().create(vals_list)

    def action_approve(self):
        for record in self:
            if record.amount <= 0:
                raise UserError('减免金额为 0，请检查故障时长和比例。')
            record.write({'state': 'approved', 'approver_id': self.env.user.id, 'approved_at': fields.Datetime.now()})
            record.message_post(body=f'已批准减免 {record.amount:.2f}，{dict(record._fields["apply_mode"].selection)[record.apply_mode]}')
            if record.apply_mode == 'credit_note':
                record._issue_credit_note()

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_reset(self):
        self.write({'state': 'draft', 'approver_id': False, 'approved_at': False})

    def _invoice_line_vals(self):
        self.ensure_one()
        label = f'故障减免 {self.name}：{self.order_id.name} 中断 {self.hours:g} 小时'
        if self.ticket_id:
            label += f'（工单 {self.ticket_id.name}）'
        return {
            'name': label,
            'quantity': 1.0,
            'price_unit': -self.amount,
            'tax_ids': [(6, 0, [])],
        }

    def _issue_credit_note(self):
        self.ensure_one()
        note = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'invoice_date': fields.Date.context_today(self),
            'ref': self.name,
            'invoice_origin': self.ticket_id.name or self.order_id.name,
            'zenlenet_contract_id': self.contract_id.id,
            'narration': self.reason or '',
            'invoice_line_ids': [(0, 0, dict(self._invoice_line_vals(), price_unit=self.amount))],
        })
        self.write({'state': 'applied', 'invoice_id': note.id})
        return note

    def action_open_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'view_id': self.env.ref('zenlenet_ops.view_invoice_form').id,
            'target': 'current',
        }

    @api.model
    def pending_for(self, partner, orders):
        return self.search([
            ('partner_id', '=', partner.id), ('order_id', 'in', orders.ids),
            ('state', '=', 'approved'), ('apply_mode', '=', 'next_invoice'),
        ])

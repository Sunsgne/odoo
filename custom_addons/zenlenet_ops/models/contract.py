import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.billing import (
    bills_this_period,
    clean_label,
    contract_end,
    contract_status,
    cycle_amount,
    period_bounds,
    period_label,
    period_ref,
)

from .settings import param_int

_logger = logging.getLogger(__name__)

CYCLES = [
    ('monthly', '按月'),
    ('quarterly', '按季'),
    ('yearly', '按年'),
]
STATES = [
    ('draft', '草稿'),
    ('active', '执行中'),
    ('expiring', '即将到期'),
    ('expired', '已到期'),
    ('terminated', '已终止'),
]


class ZenlenetContract(models.Model):
    _name = 'zenlenet.contract'
    _description = '合同'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='合同编号', required=True, copy=False, default='/', tracking=True)
    title = fields.Char(string='合同名称', default='网络服务协议')
    partner_id = fields.Many2one(
        'res.partner', string='客户', required=True, tracking=True, domain=[('is_company', '=', True)],
    )
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one('res.currency', string='币种', compute='_compute_currency', store=True)
    order_ids = fields.Many2many(
        'sale.order', string='包含订单', domain="[('partner_id', '=', partner_id)]",
    )
    start_date = fields.Date(string='开始日期', default=fields.Date.context_today, required=True, tracking=True)
    term_months = fields.Integer(
        string='期限（月）', required=True,
        default=lambda self: param_int(self.env, 'zenlenet.contract_term', 12),
    )
    end_date = fields.Date(string='结束日期', compute='_compute_end_date', store=True, readonly=False, tracking=True)
    billing_cycle = fields.Selection(CYCLES, string='出账周期', default='monthly', required=True)
    auto_renew = fields.Boolean(
        string='到期自动续签',
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param('zenlenet.auto_renew', 'True') != 'False',
    )
    monthly_amount = fields.Monetary(string='月费', compute='_compute_amounts', store=True)
    cycle_amount = fields.Monetary(string='每期金额', compute='_compute_amounts', store=True)
    state = fields.Selection(STATES, string='状态', default='draft', required=True, tracking=True, index=True)
    signed_on = fields.Date(string='签署日期')
    sales_user_id = fields.Many2one(
        'res.users', string='销售', default=lambda self: self.env.user, domain=[('share', '=', False)],
    )
    terms = fields.Html(string='补充条款', sanitize=True)
    note = fields.Text(string='备注')
    invoice_ids = fields.One2many('account.move', 'zenlenet_contract_id', string='账单')
    invoice_count = fields.Integer(compute='_compute_invoice_count')
    days_left = fields.Integer(string='剩余天数', compute='_compute_days_left')

    @api.depends('partner_id', 'company_id')
    def _compute_currency(self):
        for record in self:
            pricelist = record.partner_id.property_product_pricelist
            record.currency_id = pricelist.currency_id or record.company_id.currency_id or self.env.company.currency_id

    @api.depends('start_date', 'term_months')
    def _compute_end_date(self):
        for record in self:
            record.end_date = contract_end(record.start_date, record.term_months)

    @api.depends('order_ids.amount_untaxed', 'billing_cycle')
    def _compute_amounts(self):
        for record in self:
            monthly = sum(record.order_ids.mapped('amount_untaxed'))
            record.monthly_amount = monthly
            record.cycle_amount = cycle_amount(monthly, record.billing_cycle)

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        for record in self:
            record.invoice_count = len(record.invoice_ids)

    @api.depends('end_date')
    def _compute_days_left(self):
        today = fields.Date.context_today(self)
        for record in self:
            record.days_left = (record.end_date - today).days if record.end_date else 0

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('zenlenet.contract') or '/'
        return super().create(vals_list)

    def action_activate(self):
        for record in self:
            if not record.order_ids:
                raise UserError('请先把这个客户的订单加进合同。')
            if not record.signed_on:
                record.signed_on = fields.Date.context_today(self)
            record.state = contract_status('active', record.end_date, fields.Date.context_today(self))
            record.message_post(body='合同开始执行')

    def action_terminate(self):
        for record in self:
            record.state = 'terminated'
            record.message_post(body='合同终止')

    def action_renew(self):
        for record in self:
            if not record.end_date:
                continue
            record.write({
                'start_date': fields.Date.add(record.end_date, days=1),
                'state': 'active',
            })
            record.message_post(body=f'续签到 {record.end_date}')

    def action_reset(self):
        self.write({'state': 'draft'})

    def action_open_invoices(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_invoices').read()[0]
        action['domain'] = [('zenlenet_contract_id', '=', self.id)]
        action['context'] = {'default_zenlenet_contract_id': self.id}
        return action

    def action_bill_now(self):
        today = fields.Date.context_today(self)
        created = self.env['account.move']
        for record in self:
            invoice = record._create_period_invoice(today, force=True)
            if invoice:
                created |= invoice
        if not created:
            raise UserError('本期账单已经出过了。')
        if len(created) == 1:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': created.id,
                'view_mode': 'form',
                'view_id': self.env.ref('zenlenet_ops.view_invoice_form').id,
                'target': 'current',
            }
        return self.action_open_invoices()

    def _create_period_invoice(self, day, force=False):
        self.ensure_one()
        if self.state not in ('active', 'expiring'):
            return self.env['account.move']
        if not force and not bills_this_period(self.billing_cycle, day, self.start_date):
            return self.env['account.move']
        ref = period_ref(self.partner_id.id, day)
        Move = self.env['account.move']
        if Move.search_count([('ref', '=', ref), ('zenlenet_contract_id', '=', self.id), ('state', '!=', 'cancel')]):
            return Move
        first, last = period_bounds(day)
        footer = self.env['ir.config_parameter'].sudo().get_param('zenlenet.invoice_footer', '')
        lines = []
        for order in self.order_ids:
            for line in order.order_line.filtered(lambda item: not item.display_type):
                lines.append((0, 0, {
                    'product_id': line.product_id.id,
                    'name': f'{clean_label(line.name) or line.product_id.name}（{period_label(day)}）',
                    'quantity': line.product_uom_qty,
                    'price_unit': line.price_unit,
                    'tax_ids': [(6, 0, [])],
                    'sale_line_ids': [(4, line.id)],
                }))
        if not lines:
            return Move
        invoice = Move.create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'invoice_date': day,
            'invoice_date_due': fields.Date.add(day, days=param_int(self.env, 'zenlenet.due_days', 30)),
            'ref': ref,
            'zenlenet_contract_id': self.id,
            'invoice_origin': self.name,
            'narration': '\n'.join(part for part in (f'{self.title or "服务"} 账期 {first} 至 {last}', footer) if part),
            'invoice_line_ids': lines,
        })
        self.message_post(body=f'已生成 {period_label(day)} 账单 {invoice.name or ""}'.strip())
        return invoice

    @api.model
    def _cron_daily(self):
        today = fields.Date.context_today(self)
        notice_days = param_int(self.env, 'zenlenet.notice_days', 30)
        for record in self.search([('state', 'in', ('active', 'expiring', 'expired'))]):
            wanted = contract_status(record.state, record.end_date, today, notice_days)
            if wanted == 'expired' and record.auto_renew:
                record.action_renew()
                continue
            if wanted != record.state:
                record.state = wanted
                if wanted == 'expiring' and record.sales_user_id:
                    record.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=record.sales_user_id.id,
                        summary=f'合同 {record.name} 将于 {record.end_date} 到期，请跟进续签',
                    )

    @api.model
    def _cron_monthly_billing(self):
        today = fields.Date.context_today(self)
        if today.day < param_int(self.env, 'zenlenet.billing_day', 1):
            return 0
        count = 0
        for record in self.search([('state', 'in', ('active', 'expiring'))]):
            if record._create_period_invoice(today):
                count += 1
        _logger.info('zenlenet monthly billing created %s invoices for %s', count, period_label(today))
        return count

    @api.model
    def action_bill_period(self):
        """Header button: bill every running contract for this month."""
        count = self._cron_monthly_billing()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '出账完成',
                'message': f'本月新生成 {count} 张账单。已经出过的不会重复。',
                'type': 'success' if count else 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class AccountMove(models.Model):
    _inherit = 'account.move'

    zenlenet_contract_id = fields.Many2one('zenlenet.contract', string='合同', index=True, ondelete='set null')

    @api.model
    def action_zenlenet_bill_period(self):
        return self.env['zenlenet.contract'].action_bill_period()


class SaleOrderQuote(models.Model):
    _inherit = 'sale.order'

    zenlenet_contract_ids = fields.Many2many('zenlenet.contract', string='合同')

    def action_print_quote(self):
        return self.env.ref('zenlenet_ops.report_quotation').report_action(self)

    def action_make_contract(self):
        self.ensure_one()
        contract = self.env['zenlenet.contract'].create({
            'partner_id': self.partner_id.id,
            'order_ids': [(6, 0, self.ids)],
            'sales_user_id': self.user_id.id or self.env.user.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'zenlenet.contract',
            'res_id': contract.id,
            'view_mode': 'form',
            'target': 'current',
        }

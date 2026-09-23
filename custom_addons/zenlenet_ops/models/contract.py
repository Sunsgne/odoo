import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.billing import (
    CYCLE_MONTHS,
    bandwidth_lines,
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
    _inherit = ['mail.thread', 'mail.activity.mixin', 'zenlenet.deletable']
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
    item_ids = fields.One2many('zenlenet.contract.item', 'contract_id', string='费用条款', copy=True)
    monthly_amount = fields.Monetary(string='月费', compute='_compute_amounts', store=True,
                                     help='所有周期性费用折算到每月的合计，未税。')
    cycle_amount = fields.Monetary(string='每期金额', compute='_compute_amounts', store=True)
    one_time_total = fields.Monetary(string='一次性费用', compute='_compute_amounts', store=True)
    one_time_billed = fields.Monetary(string='一次性已出账', compute='_compute_amounts', store=True)
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

    def _delete_snapshot(self):
        return {'state': self.state, 'invoice_count': len(self.invoice_ids)}

    @api.depends('partner_id', 'company_id')
    def _compute_currency(self):
        for record in self:
            pricelist = record.partner_id.property_product_pricelist
            record.currency_id = pricelist.currency_id or record.company_id.currency_id or self.env.company.currency_id

    @api.depends('start_date', 'term_months')
    def _compute_end_date(self):
        for record in self:
            record.end_date = contract_end(record.start_date, record.term_months)

    @api.depends('item_ids.amount', 'item_ids.kind', 'item_ids.cycle', 'item_ids.billed', 'billing_cycle')
    def _compute_amounts(self):
        for record in self:
            recurring = record.item_ids.filtered(lambda item: item.kind == 'recurring')
            monthly = sum(item.amount / CYCLE_MONTHS.get(item.cycle, 1) for item in recurring)
            record.monthly_amount = monthly
            record.cycle_amount = cycle_amount(monthly, record.billing_cycle)
            one_time = record.item_ids.filtered(lambda item: item.kind == 'one_time')
            record.one_time_total = sum(one_time.mapped('amount'))
            record.one_time_billed = sum(one_time.filtered('billed').mapped('amount'))

    def action_load_items(self):
        """Build the fee schedule from the linked orders: a recurring item per service line, a one-time item per setup fee."""
        Item = self.env['zenlenet.contract.item']
        for record in self:
            existing = Item.search([('contract_id', '=', record.id), ('order_line_id', '!=', False)])
            have = {(item.order_line_id.id, item.kind) for item in existing}
            for order in record.order_ids:
                for line in order.order_line.filtered(lambda item: not item.display_type):
                    if (line.id, 'recurring') in have:
                        continue
                    have.add((line.id, 'recurring'))
                    name = clean_label(line.name) or line.product_id.name
                    Item.create({
                        'contract_id': record.id,
                        'kind': 'recurring',
                        'cycle': record.billing_cycle or 'monthly',
                        'name': name,
                        'product_id': line.product_id.id,
                        'order_line_id': line.id,
                        'quantity': line.product_uom_qty,
                        'price_unit': line.price_unit * (1 - (line.discount or 0.0) / 100.0),
                        'p95': order.zenlenet_bill_mode == 'p95' and line == order._zenlenet_bandwidth_line(),
                        'start_date': record.start_date,
                    })
                    if line.zenlenet_setup_fee and (line.id, 'one_time') not in have:
                        have.add((line.id, 'one_time'))
                        Item.create({
                            'contract_id': record.id,
                            'kind': 'one_time',
                            'name': f'{name} 一次性费用',
                            'product_id': line.product_id.id,
                            'order_line_id': line.id,
                            'quantity': 1.0,
                            'price_unit': line.zenlenet_setup_fee,
                            'start_date': record.start_date,
                        })
        return True

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
        records = super().create(vals_list)
        records.filtered(lambda record: record.order_ids and not record.item_ids).action_load_items()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'order_ids' in vals:
            self.action_load_items()
        return result

    def action_activate(self):
        for record in self:
            if not record.item_ids:
                raise UserError('请先填写费用条款（或加入订单后点「从订单带入费用」）。')
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
        ref = period_ref(self.partner_id.id, day)
        Move = self.env['account.move']
        if Move.search_count([('ref', '=', ref), ('zenlenet_contract_id', '=', self.id), ('state', '!=', 'cancel')]):
            return Move
        first, last = period_bounds(day)
        footer = self.env['ir.config_parameter'].sudo().get_param('zenlenet.invoice_footer', '')
        lines = []
        Usage = self.env['zenlenet.usage']
        label = period_label(day)
        billed_one_time = self.env['zenlenet.contract.item']
        for item in self.item_ids.sorted('sequence'):
            if item.kind == 'one_time':
                if item.billed or (item.start_date and item.start_date > day):
                    continue
                lines.append((0, 0, {
                    'product_id': item.product_id.id,
                    'name': f'{item.name}（一次性）',
                    'quantity': item.quantity,
                    'price_unit': item.price_unit,
                    'tax_ids': [(6, 0, [])],
                    'sale_line_ids': [(4, item.order_line_id.id)] if item.order_line_id else False,
                }))
                billed_one_time |= item
                continue
            if item.end_date and item.end_date < first:
                continue
            if item.start_date and item.start_date > last:
                continue
            if not bills_this_period(item.cycle, day, item.start_date or self.start_date):
                continue
            cycle_label = dict(CYCLES).get(item.cycle, '')
            if item.p95 and item.order_line_id:
                order = item.order_line_id.order_id
                usage = Usage.for_order(order, day)
                commit = item.order_line_id._zenlenet_commit()
                p95 = usage.p95_mbps if usage else None
                for kind, mbps, price in bandwidth_lines(commit, p95, item.price_unit, item.order_line_id.zenlenet_overage_price):
                    if kind == 'commit':
                        detail = f'保底 {commit:g}M' + (f'，95 值 {p95:g}M' if p95 is not None else '，本期无 95 值按保底')
                    else:
                        detail = f'95 值 {p95:g}M 超出保底 {commit:g}M 的部分'
                    lines.append((0, 0, {
                        'product_id': item.product_id.id,
                        'name': f'{item.name}（{label} · {detail}）',
                        'quantity': mbps,
                        'price_unit': price,
                        'tax_ids': [(6, 0, [])],
                        'sale_line_ids': [(4, item.order_line_id.id)],
                    }))
                continue
            lines.append((0, 0, {
                'product_id': item.product_id.id,
                'name': f'{item.name}（{label} · {cycle_label}）',
                'quantity': item.quantity,
                'price_unit': item.price_unit,
                'tax_ids': [(6, 0, [])],
                'sale_line_ids': [(4, item.order_line_id.id)] if item.order_line_id else False,
            }))
        credits = self.env['zenlenet.credit'].pending_for(self.partner_id, self.order_ids)
        for credit in credits:
            lines.append((0, 0, credit._invoice_line_vals()))
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
        if billed_one_time:
            billed_one_time.write({'billed': True, 'invoice_id': invoice.id})
        if credits:
            credits.write({'state': 'applied', 'invoice_id': invoice.id})
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

    def action_bill_period(self):
        """List header button: bill every running contract for this month.

        Header buttons receive the selected ids as ``self``; the selection is irrelevant here.
        """
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


class ZenlenetContractItem(models.Model):
    """One fee line of a contract: charged once, or every month / quarter / year."""

    _name = 'zenlenet.contract.item'
    _description = '合同费用条款'
    _inherit = ['zenlenet.deletable']
    _order = 'contract_id, kind desc, sequence, id'

    contract_id = fields.Many2one('zenlenet.contract', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    kind = fields.Selection([('recurring', '周期费用'), ('one_time', '一次性费用')], string='类型', required=True, default='recurring')
    cycle = fields.Selection(CYCLES, string='周期', default='monthly')
    name = fields.Char(string='费用项目', required=True)
    product_id = fields.Many2one('product.product', string='业务 / SKU', domain=[('sale_ok', '=', True)])
    order_line_id = fields.Many2one('sale.order.line', string='来源订单行', ondelete='set null')
    quantity = fields.Float(string='数量', default=1.0)
    price_unit = fields.Monetary(string='单价', currency_field='currency_id')
    amount = fields.Monetary(string='金额', compute='_compute_amount', store=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='contract_id.currency_id')
    p95 = fields.Boolean(string='按 95 值', help='出账时按该订单行的保底和 95 值拆行。')
    start_date = fields.Date(string='开始计费')
    end_date = fields.Date(string='停止计费')
    billed = fields.Boolean(string='已出账', help='一次性费用出过账后打勾，不再重复。')
    invoice_id = fields.Many2one('account.move', string='所在账单', readonly=True)

    def _delete_snapshot(self):
        return {'contract_state': self.contract_id.state}

    @api.depends('quantity', 'price_unit')
    def _compute_amount(self):
        for item in self:
            item.amount = (item.quantity or 0.0) * (item.price_unit or 0.0)

    @api.onchange('product_id')
    def _onchange_product(self):
        for item in self:
            if item.product_id and not item.name:
                item.name = item.product_id.name
            if item.product_id and not item.price_unit:
                item.price_unit = item.product_id.lst_price


class AccountMove(models.Model):
    _inherit = 'account.move'

    zenlenet_contract_id = fields.Many2one('zenlenet.contract', string='合同', index=True, ondelete='set null')

    def action_zenlenet_bill_period(self):
        return self.env['zenlenet.contract'].action_bill_period()


class SaleOrderQuote(models.Model):
    _inherit = 'sale.order'

    zenlenet_contract_ids = fields.Many2many('zenlenet.contract', string='关联合同')

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

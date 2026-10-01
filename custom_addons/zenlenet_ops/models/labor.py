from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.labor import clock_hours, labor_amount

from .settings import param_int

METHODS = [
    ('onsite', '现场'),
    ('remote', '远程'),
]
OPERATIONS = [
    ('wire', '接线'),
    ('spare', '放置备件'),
    ('rack', '上架'),
    ('unrack', '下架'),
    ('replace', '更换'),
    ('inspect', '巡检'),
    ('other', '其他'),
]
UNITS = [
    ('hour', '小时'),
    ('half_day', '半人天'),
    ('day', '人天'),
]
RESULTS = [
    ('done', '已完成'),
    ('partial', '部分完成'),
    ('failed', '未完成'),
]
STATES = [
    ('draft', '登记'),
    ('confirmed', '已确认'),
    ('billed', '已出账'),
    ('cancel', '已取消'),
]


class ZenlenetLabor(models.Model):
    _name = 'zenlenet.labor'
    _description = '人力'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'zenlenet.deletable']
    _order = 'service_date desc, id desc'
    _rec_names_search = ['name', 'ref', 'engineer', 'place']

    name = fields.Char(string='编号', required=True, copy=False, default='/', readonly=True)
    ref = fields.Char(string='工单号', tracking=True)
    service_date = fields.Date(string='服务日期', required=True, default=fields.Date.context_today, index=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='客户', required=True, index=True, tracking=True)
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='机房', index=True)
    place = fields.Char(string='机房位置')
    method = fields.Selection(METHODS, string='服务方式', required=True, default='onsite')
    operation = fields.Selection(OPERATIONS, string='操作类型', required=True)
    target = fields.Text(string='设备/机柜/端口')
    detail = fields.Text(string='操作内容')
    engineer = fields.Char(string='工程师')
    arrived = fields.Char(string='到场/开始时间')
    left = fields.Char(string='离场/结束时间')
    hours = fields.Float(string='服务工时')
    rate_unit = fields.Selection(UNITS, string='计费单位', required=True, default='half_day')
    quantity = fields.Float(string='数量', default=1.0, required=True)
    currency_id = fields.Many2one(
        'res.currency', string='币种', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    price_unit = fields.Monetary(string='单价', currency_field='currency_id')
    amount = fields.Monetary(string='费用', compute='_compute_amount', store=True, currency_field='currency_id')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    company_currency_id = fields.Many2one(related='company_id.currency_id')
    amount_company = fields.Monetary(
        string='折合', compute='_compute_amount_company', currency_field='company_currency_id',
    )
    applicant = fields.Char(string='申请人', default=lambda self: self.env.user.name)
    approver = fields.Char(string='授权人')
    result = fields.Selection(RESULTS, string='执行结果')
    issue = fields.Text(string='异常及遗留问题')
    confirmed_by = fields.Char(string='客户确认人')
    confirmed_on = fields.Date(string='确认时间')
    state = fields.Selection(STATES, string='状态', default='draft', required=True, tracking=True, index=True)
    product_id = fields.Many2one('product.product', string='产品', default=lambda self: self._default_product())
    invoice_id = fields.Many2one('account.move', string='账单', readonly=True, copy=False)

    @api.model
    def _default_product(self):
        product = self.env.ref('zenlenet_ops.product_labor', raise_if_not_found=False)
        return product.id if product else False

    def _delete_snapshot(self):
        return {'state': self.state, 'invoice': bool(self.invoice_id)}

    @api.depends('quantity', 'price_unit')
    def _compute_amount(self):
        for record in self:
            record.amount = labor_amount(record.quantity, record.price_unit)

    @api.depends('amount', 'currency_id', 'company_id', 'service_date')
    def _compute_amount_company(self):
        for record in self:
            company_currency = record.company_currency_id
            if not record.amount or not record.currency_id or not company_currency:
                record.amount_company = 0.0
            elif record.currency_id == company_currency:
                record.amount_company = record.amount
            else:
                record.amount_company = record.currency_id._convert(
                    record.amount,
                    company_currency,
                    record.company_id,
                    record.service_date or fields.Date.context_today(record),
                )

    @api.onchange('datacenter_id')
    def _onchange_datacenter(self):
        for record in self:
            site = record.datacenter_id
            if site and not record.place:
                record.place = site.city or site.region or site.name or ''

    @api.onchange('arrived', 'left', 'rate_unit', 'hours')
    def _onchange_hours(self):
        for record in self:
            span = clock_hours(record.arrived, record.left)
            if span and not record.hours:
                record.hours = span
            if record.rate_unit == 'hour':
                record.quantity = record.hours or 0.0
            elif not record.quantity:
                record.quantity = 1.0

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('zenlenet.labor') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('zenlenet_labor_bill'):
            if any(record.state == 'billed' for record in self):
                raise UserError('已经出过账。')
            if any(record.state == 'confirmed' for record in self) and set(vals) - {'state', 'invoice_id'}:
                raise UserError('已确认的记录要改，先改回登记。')
        return super().write(vals)

    def action_confirm(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.state != 'draft':
                raise UserError('已经确认过。')
            if not record.partner_id:
                raise UserError('请填写客户。')
            if record.result != 'done':
                raise UserError('执行结果还不是已完成。')
            if not record.approver:
                raise UserError('请填写授权人。')
            if not record.confirmed_by:
                raise UserError('请填写客户确认人。')
            if record.amount <= 0:
                raise UserError('费用为 0。')
            record.write({
                'state': 'confirmed',
                'confirmed_on': record.confirmed_on or today,
            })
        return True

    def action_reset(self):
        locked = self.filtered(lambda record: record.state != 'confirmed')
        if locked:
            raise UserError('只有已确认、还没出账的记录可以改回登记。')
        self.write({'state': 'draft'})
        return True

    def action_cancel(self):
        if any(record.state == 'billed' for record in self):
            raise UserError('已经出过账。')
        self.filtered(lambda record: record.state in ('draft', 'confirmed')).write({'state': 'cancel'})
        return True

    def _income_account(self):
        self.ensure_one()
        product = self.product_id
        if product:
            accounts = product.product_tmpl_id.with_company(self.company_id).get_product_accounts()
            income = accounts.get('income')
            if income:
                return income
        return self.env['account.account'].with_company(self.company_id).search([
            ('account_type', '=', 'income'),
        ], limit=1)

    def _invoice_line_vals(self):
        self.ensure_one()
        operation = dict(OPERATIONS).get(self.operation, '')
        method = dict(METHODS).get(self.method, '')
        unit = dict(UNITS).get(self.rate_unit, '')
        bits = [
            '人力',
            str(self.service_date or ''),
            self.datacenter_id.name or '',
            self.place or '',
            method,
            operation,
            unit,
        ]
        if self.ref:
            bits.append(self.ref)
        account = self._income_account()
        if not account:
            raise UserError('没有收入科目。')
        vals = {
            'name': ' '.join(bit for bit in bits if bit),
            'quantity': self.quantity,
            'price_unit': self.price_unit,
            'account_id': account.id,
            'tax_ids': [(6, 0, [])],
        }
        if self.product_id:
            vals['product_id'] = self.product_id.id
        return vals

    def action_bill(self):
        if not (
            self.env.user.has_group('zenlenet_ops.group_finance')
            or self.env.user.has_group('zenlenet_ops.group_manager')
        ):
            raise UserError('只有财务可以出账。')
        records = self
        if not records:
            raise UserError('请先勾选已确认的人力。')
        if any(record.state != 'confirmed' for record in records):
            raise UserError('客户还没确认。')
        groups = {}
        for record in records:
            key = (record.partner_id.id, record.currency_id.id, record.company_id.id)
            groups.setdefault(key, self.env['zenlenet.labor'])
            groups[key] |= record
        invoices = self.env['account.move']
        due_days = param_int(self.env, 'zenlenet.due_days', 30)
        for batch in groups.values():
            day = max(batch.mapped('service_date'))
            sample = batch[0]
            invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': sample.partner_id.id,
                'currency_id': sample.currency_id.id,
                'company_id': sample.company_id.id,
                'invoice_date': day,
                'invoice_date_due': fields.Date.add(day, days=due_days),
                'invoice_origin': ', '.join(batch.mapped('name')),
                'ref': ', '.join(name for name in batch.mapped('ref') if name) or False,
                'invoice_line_ids': [(0, 0, record._invoice_line_vals()) for record in batch.sorted('service_date')],
            })
            batch.with_context(zenlenet_labor_bill=True).write({
                'state': 'billed',
                'invoice_id': invoice.id,
            })
            invoices |= invoice
        if len(invoices) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': '账单',
                'res_model': 'account.move',
                'res_id': invoices.id,
                'view_mode': 'form',
                'view_id': self.env.ref('zenlenet_ops.view_invoice_form').id,
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': '账单',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
            'target': 'current',
        }

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

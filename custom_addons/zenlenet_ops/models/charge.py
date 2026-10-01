from odoo import api, fields, models
from odoo.exceptions import UserError

from .settings import param_int

KINDS = [
    ('nrc', '一次性'),
    ('recurring', '周期费'),
    ('p95', '95 带宽'),
    ('labor', '人力'),
    ('manual', '手工'),
]


class ZenlenetCharge(models.Model):
    _name = 'zenlenet.charge'
    _description = '收费项'
    _inherit = ['zenlenet.deletable']
    _order = 'period desc, id desc'

    name = fields.Char(string='说明', required=True)
    business_key = fields.Char(string='业务键', required=True, index=True, copy=False)
    kind = fields.Selection(KINDS, string='种类', required=True, default='manual')
    partner_id = fields.Many2one('res.partner', string='客户', required=True, index=True)
    order_id = fields.Many2one('sale.order', string='服务订单', index=True)
    contract_id = fields.Many2one('zenlenet.contract', string='合同', index=True)
    labor_id = fields.Many2one('zenlenet.labor', string='人力', index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='币种', required=True, default=lambda self: self.env.company.currency_id)
    period = fields.Char(string='账期', index=True)
    quantity = fields.Float(string='数量', default=1.0, required=True)
    price_unit = fields.Monetary(string='单价')
    amount = fields.Monetary(string='金额', compute='_compute_amount', store=True)
    invoice_id = fields.Many2one('account.move', string='账单', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', '草稿'),
        ('invoiced', '已出账'),
    ], string='状态', default='draft', required=True, index=True)

    _business_key_unique = models.Constraint('unique(business_key)', '这个收费项已经存在。')

    def _delete_snapshot(self):
        return {'state': self.state, 'invoice': bool(self.invoice_id)}

    @api.depends('quantity', 'price_unit')
    def _compute_amount(self):
        for record in self:
            record.amount = round((record.quantity or 0.0) * (record.price_unit or 0.0), 2)

    @api.model
    def register(self, key, values):
        """Same key and same money returns the existing row. A different amount is rejected."""
        key = (key or '').strip()
        if not key:
            raise UserError('收费项没有业务键。')
        found = self.search([('business_key', '=', key)], limit=1)
        if found:
            incoming = round(float(values.get('quantity') or found.quantity) * float(values.get('price_unit') or found.price_unit), 2)
            if abs(found.amount - incoming) > 0.009:
                raise UserError('同一收费项已经存在，金额不一致。')
            return found
        payload = dict(values)
        payload['business_key'] = key
        return self.create(payload)

    def _income_account(self):
        self.ensure_one()
        return self.env['account.account'].with_company(self.company_id).search([
            ('account_type', '=', 'income'),
        ], limit=1)

    def write(self, vals):
        if any(record.state == 'invoiced' for record in self) and not self.env.context.get('zenlenet_charge_post'):
            raise UserError('已经出过账。')
        return super().write(vals)

    def action_invoice(self):
        if not (
            self.env.user.has_group('zenlenet_ops.group_finance')
            or self.env.user.has_group('zenlenet_ops.group_manager')
        ):
            raise UserError('只有财务可以出账。')
        records = self.filtered(lambda row: row.state == 'draft')
        if not records:
            raise UserError('没有未出账的收费项。')
        groups = {}
        for record in records:
            key = (record.partner_id.id, record.currency_id.id, record.company_id.id)
            groups.setdefault(key, self.env['zenlenet.charge'])
            groups[key] |= record
        invoices = self.env['account.move']
        due_days = param_int(self.env, 'zenlenet.due_days', 30)
        today = fields.Date.context_today(self)
        for batch in groups.values():
            sample = batch[0]
            account = sample._income_account()
            if not account:
                raise UserError('没有收入科目。')
            lines = []
            for record in batch:
                lines.append((0, 0, {
                    'name': record.name,
                    'quantity': record.quantity,
                    'price_unit': record.price_unit,
                    'account_id': account.id,
                    'tax_ids': [(6, 0, [])],
                }))
            invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': sample.partner_id.id,
                'currency_id': sample.currency_id.id,
                'company_id': sample.company_id.id,
                'invoice_date': today,
                'invoice_date_due': fields.Date.add(today, days=due_days),
                'invoice_origin': ', '.join(batch.mapped('business_key')),
                'invoice_line_ids': lines,
            })
            batch.with_context(zenlenet_charge_post=True).write({'state': 'invoiced', 'invoice_id': invoice.id})
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
        }

"""Suppliers are partners with supplier_rank; every free-text supplier column now points at one."""

from odoo import api, fields, models


class ResPartnerSupplier(models.Model):
    _inherit = 'res.partner'

    zenlenet_supplier_kind = fields.Selection([
        ('carrier', '运营商 / 带宽'),
        ('idc', '机房 / IDC'),
        ('cloud', '云服务'),
        ('hardware', '设备'),
        ('other', '其他'),
    ], string='供应商类型')
    zenlenet_line_count = fields.Integer(compute='_compute_supplier_counts')
    zenlenet_purchase_count = fields.Integer(compute='_compute_supplier_counts')
    zenlenet_bill_count = fields.Integer(compute='_compute_supplier_counts')
    zenlenet_payable_amount = fields.Monetary(compute='_compute_supplier_counts', currency_field='zenlenet_currency_id')
    zenlenet_supplied_line_ids = fields.One2many('zenlenet.line', 'supplier_id', string='线路')
    zenlenet_purchase_ids = fields.One2many('zenlenet.purchase', 'supplier_id', string='采购')
    zenlenet_bill_ids = fields.One2many(
        'account.move', 'partner_id', string='供应商账单',
        domain=[('move_type', '=', 'in_invoice'), ('state', '!=', 'cancel')],
    )
    zenlenet_datacenter_ids = fields.One2many('zenlenet.datacenter', 'supplier_id', string='机房')
    zenlenet_supplied_address_ids = fields.One2many('zenlenet.address', 'supplier_id', string='地址')
    zenlenet_return_ids = fields.One2many('zenlenet.supplier.return', 'supplier_id', string='退资源')

    def _compute_supplier_counts(self):
        ids = self.ids

        def grouped(model, domain, aggregate='__count'):
            if not ids:
                return {}
            rows = self.env[model].sudo()._read_group([('partner_id', 'in', ids)] + domain, ['partner_id'], [aggregate])
            return {record.id: value for record, value in rows}

        lines = {}
        if ids:
            for record, count in self.env['zenlenet.line'].sudo()._read_group(
                [('supplier_id', 'in', ids)], ['supplier_id'], ['__count'],
            ):
                lines[record.id] = count
        purchases = {}
        if ids:
            for record, count in self.env['zenlenet.purchase'].sudo()._read_group(
                [('supplier_id', 'in', ids), ('state', '!=', 'returned')], ['supplier_id'], ['__count'],
            ):
                purchases[record.id] = count
        bills = grouped('account.move', [('move_type', '=', 'in_invoice')])
        payable = grouped('account.move', [
            ('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ], aggregate='amount_residual:sum')
        for record in self:
            record.zenlenet_line_count = lines.get(record.id, 0)
            record.zenlenet_purchase_count = purchases.get(record.id, 0)
            record.zenlenet_bill_count = bills.get(record.id, 0)
            record.zenlenet_payable_amount = payable.get(record.id, 0.0) or 0.0

    @api.model
    def zenlenet_supplier_by_name(self, name, kind=None):
        name = (name or '').strip()
        if not name:
            return self.browse()
        supplier = self.sudo().search([('name', '=', name), ('supplier_rank', '>', 0)], limit=1)
        if supplier:
            return supplier
        existing = self.sudo().search([('name', '=', name), ('is_company', '=', True)], limit=1)
        if existing:
            existing.write({'supplier_rank': 1, 'zenlenet_supplier_kind': kind or existing.zenlenet_supplier_kind})
            return existing
        return self.sudo().create({
            'name': name, 'is_company': True, 'company_type': 'company', 'supplier_rank': 1,
            'zenlenet_supplier_kind': kind or 'other',
        })

    def action_open_supplier_lines(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_lines').read()[0]
        action['domain'] = [('supplier_id', '=', self.id)]
        action['context'] = {'default_supplier_id': self.id, 'search_default_running': 1}
        return action

    def action_open_supplier_purchases(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_purchases').read()[0]
        action['domain'] = [('supplier_id', '=', self.id)]
        action['context'] = {'default_supplier_id': self.id}
        return action

    def action_open_supplier_bills(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_vendor_bills').read()[0]
        action['domain'] = [('partner_id', '=', self.id), ('move_type', '=', 'in_invoice')]
        action['context'] = {'default_partner_id': self.id, 'default_move_type': 'in_invoice'}
        return action

    @api.model
    def _zenlenet_migrate_suppliers(self):
        """Turn free-text supplier names on lines, purchases, addresses, and returns into supplier partners."""
        for model, field in (('zenlenet.line', 'supplier'), ('zenlenet.purchase', 'supplier'),
                             ('zenlenet.address', 'supplier'), ('zenlenet.supplier.return', 'supplier'),
                             ('zenlenet.datacenter', 'supplier')):
            Model = self.env[model].sudo()
            if 'supplier_id' not in Model._fields:
                continue
            for name, in Model._read_group([('supplier_id', '=', False), (field, '!=', False)], [field]):
                if not (name or '').strip() or name == '未填写':
                    continue
                kind = 'idc' if model == 'zenlenet.datacenter' else ('carrier' if model in ('zenlenet.line', 'zenlenet.address') else None)
                supplier = self.zenlenet_supplier_by_name(name, kind)
                Model.search([('supplier_id', '=', False), (field, '=', name)]).with_context(netbox_skip_push=True).write({'supplier_id': supplier.id})

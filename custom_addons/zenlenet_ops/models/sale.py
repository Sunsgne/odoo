from odoo import api, fields, models

BANDWIDTH_CODES = ('ipt', 'pl')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    zenlenet_key = fields.Char(index=True, copy=False)
    zenlenet_stage = fields.Selection([
        ('testing', '测试'),
        ('active', '在网'),
        ('terminated', '已退租'),
    ], string='状态', index=True)
    zenlenet_graph_ref = fields.Char(string='Cacti 图 ID', help='Cacti 里这条服务的流量图编号，95 值按它对上。')
    zenlenet_bill_mode = fields.Selection([
        ('flat', '固定带宽'),
        ('p95', '95 值计费'),
    ], string='计费方式', default='flat', required=True)
    zenlenet_usage_ids = fields.One2many('zenlenet.usage', 'order_id', string='95 值')

    def _zenlenet_bandwidth_line(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: not line.display_type and (line.product_id.default_code or '') in BANDWIDTH_CODES
        )[:1]

    def action_mark_active(self):
        for order in self:
            if order.state == 'cancel':
                order.action_draft()
            if order.state in ('draft', 'sent'):
                order.action_confirm()
            order.zenlenet_stage = 'active'

    def action_mark_testing(self):
        for order in self:
            if order.state == 'sale':
                order._action_cancel()
            if order.state == 'cancel':
                order.action_draft()
            order.zenlenet_stage = 'testing'

    def action_mark_terminated(self):
        for order in self:
            if order.state != 'cancel':
                order._action_cancel()
            order.zenlenet_stage = 'terminated'


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    zenlenet_commit_mbps = fields.Float(string='保底 (Mbps)', help='留空时按数量作为保底带宽。')
    zenlenet_overage_price = fields.Float(string='超量单价 / Mbps', help='95 值超过保底的部分按这个单价；留空则整体按单价。')
    zenlenet_sku = fields.Char(related='product_id.default_code', string='SKU')

    def _zenlenet_commit(self):
        self.ensure_one()
        return self.zenlenet_commit_mbps or self.product_uom_qty or 0.0


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.depends('name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.name or ''


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.depends('name', 'product_template_attribute_value_ids')
    def _compute_display_name(self):
        for record in self:
            variant = record.product_template_attribute_value_ids._get_combination_name()
            record.display_name = f'{record.name} ({variant})' if variant else (record.name or '')

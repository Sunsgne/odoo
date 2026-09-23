from odoo import api, fields, models
from odoo.exceptions import UserError

BANDWIDTH_CODES = ('ipt', 'pl')
SERVICE_BY_CODE = {'ipt': 'ipt', 'pl': 'pl', 'vm': 'vm', 'colo': 'colo', 'resale': 'resale'}


class SaleOrder(models.Model):
    """A quotation that becomes a service order, a draft contract, and a delivery ticket in one click."""

    _inherit = 'sale.order'

    zenlenet_key = fields.Char(index=True, copy=False)
    zenlenet_stage = fields.Selection([
        ('testing', '测试'),
        ('active', '在网'),
        ('terminated', '已退租'),
    ], string='服务状态', index=True, copy=False)
    zenlenet_graph_ref = fields.Char(string='Cacti 图 ID', help='Cacti 里这条服务的流量图编号，95 值按它对上。')
    zenlenet_bill_mode = fields.Selection([
        ('flat', '固定带宽'),
        ('p95', '95 值计费'),
    ], string='计费方式', default='flat', required=True)
    zenlenet_usage_ids = fields.One2many('zenlenet.usage', 'order_id', string='95 值')
    zenlenet_term_months = fields.Integer(string='合约期（月）', default=12, help='报价按这个期限算合约总额，确认后带入合同。')
    zenlenet_version = fields.Integer(string='版本', default=1, copy=False)
    zenlenet_parent_id = fields.Many2one('sale.order', string='上一版本', copy=False, readonly=True)
    zenlenet_setup_total = fields.Monetary(string='一次性费用合计', compute='_compute_zenlenet_totals', store=True)
    zenlenet_contract_total = fields.Monetary(string='合约期总额', compute='_compute_zenlenet_totals', store=True,
                                              help='月费 × 合约期 + 一次性费用，未税。')
    zenlenet_setup_billed = fields.Boolean(string='一次性费用已出账', copy=False)
    zenlenet_flow_ids = fields.One2many('zenlenet.flow', 'order_id', string='交付工单')
    zenlenet_flow_count = fields.Integer(compute='_compute_zenlenet_links')
    zenlenet_contract_id = fields.Many2one('zenlenet.contract', string='合同', compute='_compute_zenlenet_links')

    @api.depends('order_line.zenlenet_setup_fee', 'amount_untaxed', 'zenlenet_term_months')
    def _compute_zenlenet_totals(self):
        for order in self:
            setup = sum(order.order_line.mapped('zenlenet_setup_fee'))
            order.zenlenet_setup_total = setup
            order.zenlenet_contract_total = order.amount_untaxed * max(order.zenlenet_term_months or 0, 0) + setup

    def _compute_zenlenet_links(self):
        Contract = self.env['zenlenet.contract']
        for order in self:
            order.zenlenet_flow_count = len(order.zenlenet_flow_ids)
            order.zenlenet_contract_id = Contract.search([('order_ids', 'in', order.id)], limit=1)

    def _zenlenet_bandwidth_line(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: not line.display_type and (line.product_id.default_code or '') in BANDWIDTH_CODES
        )[:1]

    # ------------------------------------------------------------------ quote
    def action_new_version(self):
        self.ensure_one()
        copy = self.copy({
            'zenlenet_version': self.zenlenet_version + 1,
            'zenlenet_parent_id': self.id,
            'origin': self.origin,
        })
        if self.state in ('draft', 'sent'):
            self._action_cancel()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': copy.id,
            'view_mode': 'form',
            'view_id': self.env.ref('zenlenet_ops.view_quote_form').id,
            'target': 'current',
        }

    def action_print_quote(self):
        return self.env.ref('zenlenet_ops.report_quotation').report_action(self)

    def action_confirm(self):
        for order in self:
            if not order.order_line.filtered(lambda line: not line.display_type):
                raise UserError('报价里还没有业务明细。')
            if not order.user_id:
                raise UserError('请先填写客户经理。')
        result = super().action_confirm()
        for order in self:
            order._zenlenet_after_confirm()
        return result

    def _zenlenet_after_confirm(self):
        """Confirming a quote opens the delivery ticket and drafts the contract."""
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        if partner.zenlenet_status == 'lead':
            partner.zenlenet_status = 'testing'
        if not partner.zenlenet_manager_id:
            partner.zenlenet_manager_id = self.user_id
        Contract = self.env['zenlenet.contract']
        contract = Contract.search([('partner_id', '=', partner.id), ('state', '=', 'draft')], limit=1)
        if contract:
            contract.order_ids = [(4, self.id)]
        else:
            contract = Contract.create({
                'partner_id': partner.id,
                'order_ids': [(6, 0, self.ids)],
                'term_months': self.zenlenet_term_months or 12,
                'sales_user_id': self.user_id.id,
                'title': f'{partner.name} 网络服务协议',
            })
        Flow = self.env['zenlenet.flow']
        if not Flow.search_count([('order_id', '=', self.id), ('state', 'not in', ('done', 'cancel'))]):
            flow = Flow.create({
                'kind': 'business',
                'partner_id': partner.id,
                'order_id': self.id,
                'sales_user_id': self.user_id.id,
            })
            flow.action_load_order()
        self.message_post(body=f'已确认。合同 {contract.name}（草稿）和交付工单已创建。')

    def action_open_flows(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_flow').read()[0]
        action['domain'] = [('order_id', '=', self.id)]
        action['context'] = {'default_order_id': self.id, 'default_partner_id': self.partner_id.id}
        return action

    def action_open_contract(self):
        self.ensure_one()
        if not self.zenlenet_contract_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'zenlenet.contract',
            'res_id': self.zenlenet_contract_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_make_contract(self):
        self.ensure_one()
        if self.zenlenet_contract_id:
            return self.action_open_contract()
        contract = self.env['zenlenet.contract'].create({
            'partner_id': self.partner_id.commercial_partner_id.id,
            'order_ids': [(6, 0, self.ids)],
            'term_months': self.zenlenet_term_months or 12,
            'sales_user_id': self.user_id.id or self.env.user.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'zenlenet.contract',
            'res_id': contract.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------ stage
    def action_mark_active(self):
        for order in self:
            if order.state == 'cancel':
                order.action_draft()
            if order.state in ('draft', 'sent'):
                order.action_confirm()
            order.zenlenet_stage = 'active'
            order.partner_id.commercial_partner_id.zenlenet_status = 'active'

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

    zenlenet_sku = fields.Char(related='product_id.default_code', string='SKU')
    zenlenet_setup_fee = fields.Monetary(string='一次性费用', help='接入费、安装费等，只在第一期账单收。')
    zenlenet_commit_mbps = fields.Float(string='保底 (Mbps)', help='留空时按数量作为保底带宽。')
    zenlenet_overage_price = fields.Float(string='超量单价 / Mbps', help='95 值超过保底的部分按这个单价；留空则整体按单价。')
    zenlenet_unit = fields.Char(string='单位', compute='_compute_zenlenet_unit')

    @api.depends('product_id')
    def _compute_zenlenet_unit(self):
        units = {'ipt': 'Mbps', 'pl': 'Mbps', 'vm': '台', 'colo': '台 / U', 'resale': '项'}
        for line in self:
            line.zenlenet_unit = units.get(line.product_id.default_code or '', '项')

    def _zenlenet_commit(self):
        self.ensure_one()
        return self.zenlenet_commit_mbps or self.product_uom_qty or 0.0

    def _zenlenet_service_type(self):
        self.ensure_one()
        return SERVICE_BY_CODE.get(self.product_id.default_code or '', 'resale')


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

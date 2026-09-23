from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    zenlenet_status = fields.Selection([
        ('active', '在网'),
        ('testing', '测试'),
        ('churned', '已退租'),
    ], string='业务状态', default='active')
    zenlenet_order_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_contract_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_invoice_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_unpaid_amount = fields.Monetary(compute='_compute_zenlenet_counts', currency_field='currency_id')
    zenlenet_ticket_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_flow_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_address_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_line_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_mrr = fields.Monetary(string='月费合计', compute='_compute_zenlenet_counts', currency_field='currency_id')
    zenlenet_since = fields.Date(string='首次开通', compute='_compute_zenlenet_counts')
    zenlenet_manager_id = fields.Many2one('res.users', string='客户经理', domain=[('share', '=', False)])

    def _compute_zenlenet_counts(self):
        Order = self.env['sale.order'].sudo()
        Move = self.env['account.move'].sudo()
        for record in self:
            orders = Order.search([('partner_id', 'child_of', record.id), ('state', '=', 'sale')])
            active = orders.filtered(lambda order: order.zenlenet_stage == 'active')
            record.zenlenet_order_count = Order.search_count([('partner_id', 'child_of', record.id)])
            record.zenlenet_mrr = sum(active.mapped('amount_untaxed'))
            record.zenlenet_since = min(orders.mapped('date_order')).date() if orders else False
            record.zenlenet_contract_count = self.env['zenlenet.contract'].sudo().search_count([
                ('partner_id', '=', record.id),
            ])
            invoices = Move.search([('partner_id', 'child_of', record.id), ('move_type', '=', 'out_invoice')])
            record.zenlenet_invoice_count = len(invoices)
            record.zenlenet_unpaid_amount = sum(invoices.filtered(
                lambda move: move.state == 'posted' and move.payment_state in ('not_paid', 'partial'),
            ).mapped('amount_residual'))
            record.zenlenet_ticket_count = self.env['zenlenet.ticket'].sudo().search_count([
                ('partner_id', '=', record.id), ('state', 'not in', ('closed', 'cancel')),
            ])
            record.zenlenet_flow_count = self.env['zenlenet.flow'].sudo().search_count([
                ('partner_id', '=', record.id), ('state', 'not in', ('done', 'cancel')),
            ])
            record.zenlenet_address_count = self.env['zenlenet.address'].sudo().search_count([
                ('partner_id', '=', record.id),
            ])
            record.zenlenet_line_count = self.env['zenlenet.line'].sudo().search_count([
                ('partner_id', '=', record.id), ('stopped', '=', False),
            ])

    def _zenlenet_action(self, xmlid, domain, context=None, name=None):
        self.ensure_one()
        action = self.env.ref(xmlid).read()[0]
        action['domain'] = domain
        action['context'] = {'default_partner_id': self.id, **(context or {})}
        if name:
            action['display_name'] = f'{self.name} · {name}'
        return action

    def action_open_resources(self):
        return self._zenlenet_action('zenlenet_ops.action_addresses', [('partner_id', '=', self.id)], name='IP资源')

    def action_open_lines(self):
        return self._zenlenet_action('zenlenet_ops.action_lines', [('partner_id', '=', self.id)], name='线路')

    def action_open_orders(self):
        return self._zenlenet_action(
            'zenlenet_ops.action_orders', [('partner_id', 'child_of', self.id)], name='服务订单',
        )

    def action_open_quote(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '新报价',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_partner_id': self.id},
        }

    def action_open_contracts(self):
        return self._zenlenet_action('zenlenet_ops.action_contracts', [('partner_id', '=', self.id)], name='合同')

    def action_open_invoices(self):
        return self._zenlenet_action(
            'zenlenet_ops.action_invoices',
            [('partner_id', 'child_of', self.id), ('move_type', '=', 'out_invoice'), ('state', '!=', 'cancel')],
            name='账单',
        )

    def action_open_tickets(self):
        return self._zenlenet_action('zenlenet_ops.action_tickets', [('partner_id', '=', self.id)], name='工单')

    def action_open_flows(self):
        return self._zenlenet_action('zenlenet_ops.action_flow', [('partner_id', '=', self.id)], name='开通交付')

    @api.model
    def _zenlenet_refresh_status(self):
        """Derive 在网 / 测试 / 已退租 from the customer's live orders."""
        Order = self.env['sale.order'].sudo()
        for partner in self.sudo().search([('is_company', '=', True), ('customer_rank', '>', 0)]):
            stages = set(Order.search([('partner_id', 'child_of', partner.id)]).mapped('zenlenet_stage'))
            if 'active' in stages:
                wanted = 'active'
            elif 'testing' in stages:
                wanted = 'testing'
            elif 'terminated' in stages:
                wanted = 'churned'
            else:
                continue
            if partner.zenlenet_status != wanted:
                partner.zenlenet_status = wanted

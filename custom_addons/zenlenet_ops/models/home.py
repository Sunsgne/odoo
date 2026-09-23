from odoo import api, fields, models


class ZenlenetHome(models.Model):
    _name = 'zenlenet.home'
    _description = '首页'

    name = fields.Char(default='尊领运营')
    customers_active = fields.Integer(compute='_compute_kpis')
    customers_total = fields.Integer(compute='_compute_kpis')
    services_active = fields.Integer(compute='_compute_kpis')
    services_testing = fields.Integer(compute='_compute_kpis')
    mrr = fields.Monetary(compute='_compute_kpis', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', compute='_compute_kpis')
    quotes_open = fields.Integer(compute='_compute_kpis')
    contracts_running = fields.Integer(compute='_compute_kpis')
    contracts_expiring = fields.Integer(compute='_compute_kpis')
    invoices_draft = fields.Integer(compute='_compute_kpis')
    unpaid_count = fields.Integer(compute='_compute_kpis')
    unpaid_amount = fields.Monetary(compute='_compute_kpis', currency_field='currency_id')
    flows_open = fields.Integer(compute='_compute_kpis')
    flows_mine = fields.Integer(compute='_compute_kpis')
    allocations_pending = fields.Integer(compute='_compute_kpis')
    tickets_open = fields.Integer(compute='_compute_kpis')
    tickets_overdue = fields.Integer(compute='_compute_kpis')
    tickets_new = fields.Integer(compute='_compute_kpis')
    maintenance_open = fields.Integer(compute='_compute_kpis')
    datacenters = fields.Integer(compute='_compute_kpis')
    ip_total = fields.Integer(compute='_compute_kpis')
    ip_free = fields.Integer(compute='_compute_kpis')
    ip_usage = fields.Float(compute='_compute_kpis')
    lines_active = fields.Integer(compute='_compute_kpis')
    assets_in_use = fields.Integer(compute='_compute_kpis')
    purchases_open = fields.Integer(compute='_compute_kpis')
    users_count = fields.Integer(compute='_compute_kpis')

    def _compute_kpis(self):
        env = self.env
        Partner = env['res.partner'].sudo()
        Order = env['sale.order'].sudo()
        Move = env['account.move'].sudo()
        Address = env['zenlenet.address'].sudo()
        customer_domain = [('is_company', '=', True), ('customer_rank', '>', 0)]
        active_orders = Order.search([('zenlenet_stage', '=', 'active'), ('state', '=', 'sale')])
        unpaid = Move.search([
            ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ])
        ip_total = Address.search_count([])
        ip_free = Address.search_count([('status', '=', 'free')])
        for record in self:
            record.currency_id = env.company.currency_id
            record.customers_total = Partner.search_count(customer_domain)
            record.customers_active = Partner.search_count(customer_domain + [('zenlenet_status', '=', 'active')])
            record.services_active = len(active_orders)
            record.services_testing = Order.search_count([('zenlenet_stage', '=', 'testing')])
            record.mrr = sum(active_orders.mapped('amount_untaxed'))
            record.quotes_open = Order.search_count([('state', 'in', ('draft', 'sent')), ('zenlenet_stage', '=', False)])
            record.contracts_running = env['zenlenet.contract'].sudo().search_count([
                ('state', 'in', ('active', 'expiring')),
            ])
            record.contracts_expiring = env['zenlenet.contract'].sudo().search_count([
                ('state', 'in', ('expiring', 'expired')),
            ])
            record.invoices_draft = Move.search_count([('move_type', '=', 'out_invoice'), ('state', '=', 'draft')])
            record.unpaid_count = len(unpaid)
            record.unpaid_amount = sum(unpaid.mapped('amount_residual'))
            record.flows_open = env['zenlenet.flow'].sudo().search_count([('state', 'not in', ('done', 'cancel'))])
            record.flows_mine = env['zenlenet.flow'].sudo().search_count([
                ('state', 'not in', ('done', 'cancel')), ('user_id', '=', env.user.id),
            ])
            record.allocations_pending = env['zenlenet.flow.resource'].sudo().search_count([
                ('flow_state', '=', 'allocate'), ('needs_resource', '=', True), ('resource_ref', '=', False),
            ])
            record.tickets_open = env['zenlenet.ticket'].sudo().search_count([
                ('state', 'not in', ('closed', 'cancel')),
            ])
            record.tickets_overdue = env['zenlenet.ticket'].sudo().search_count([('overdue', '=', True)])
            record.tickets_new = env['zenlenet.ticket'].sudo().search_count([('state', '=', 'new')])
            record.maintenance_open = env['zenlenet.maintenance'].sudo().search_count([
                ('state', 'not in', ('done', 'cancel')),
            ])
            record.datacenters = env['zenlenet.datacenter'].sudo().search_count([('state', '=', 'active')])
            record.ip_total = ip_total
            record.ip_free = ip_free
            record.ip_usage = round((ip_total - ip_free) * 100.0 / ip_total, 1) if ip_total else 0.0
            record.lines_active = env['zenlenet.line'].sudo().search_count([('stopped', '=', False)])
            record.assets_in_use = env['zenlenet.asset'].sudo().search_count([('state', '=', 'in_use')])
            record.purchases_open = env['zenlenet.purchase'].sudo().search_count([('state', 'in', ('draft', 'ordered'))])
            record.users_count = env['res.users'].sudo().search_count([('share', '=', False)])

    @api.model
    def action_open(self):
        record = self.sudo().search([], limit=1) or self.sudo().create({})
        return {
            'type': 'ir.actions.act_window',
            'name': '首页',
            'res_model': self._name,
            'res_id': record.id,
            'view_mode': 'form',
            'view_id': self.env.ref('zenlenet_ops.view_home_form').id,
            'target': 'current',
        }

    def action_open_allocation(self):
        return self.env.ref('zenlenet_ops.action_allocation_queue').read()[0]

    def action_open_unpaid(self):
        action = self.env.ref('zenlenet_ops.action_invoices').read()[0]
        action['domain'] = [
            ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ]
        return action

    def action_open_overdue_tickets(self):
        action = self.env.ref('zenlenet_ops.action_tickets').read()[0]
        action['context'] = {'search_default_overdue': 1}
        return action

    def action_open_expiring(self):
        action = self.env.ref('zenlenet_ops.action_contracts').read()[0]
        action['context'] = {'search_default_expiring': 1}
        return action

    def action_open_my_flows(self):
        action = self.env.ref('zenlenet_ops.action_flow').read()[0]
        action['context'] = {'search_default_mine': 1, 'search_default_open': 1}
        return action

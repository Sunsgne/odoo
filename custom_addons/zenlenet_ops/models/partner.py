from odoo import api, fields, models
from odoo.exceptions import UserError

LEVELS = [('a', 'A 级 · 战略客户'), ('b', 'B 级 · 重点客户'), ('c', 'C 级 · 普通客户')]
SOURCES = [
    ('referral', '转介绍'),
    ('direct', '直客'),
    ('agent', '代理商'),
    ('inbound', '官网 / 咨询'),
    ('event', '展会 / 活动'),
    ('other', '其他'),
]
INDUSTRIES = [
    ('isp', '运营商 / ISP'),
    ('cloud', '云 / IDC'),
    ('game', '游戏'),
    ('fintech', '金融 / 支付'),
    ('media', '媒体 / 直播'),
    ('enterprise', '企业'),
    ('other', '其他'),
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    zenlenet_code = fields.Char(string='客户编号', copy=False, index=True, readonly=True)
    zenlenet_status = fields.Selection([
        ('lead', '潜在'),
        ('active', '在网'),
        ('testing', '测试'),
        ('churned', '已退租'),
    ], string='业务状态', default='lead', index=True, tracking=True)
    zenlenet_manager_id = fields.Many2one(
        'res.users', string='客户经理', domain=[('share', '=', False)], index=True, tracking=True,
    )
    zenlenet_level = fields.Selection(LEVELS, string='客户等级', default='c')
    zenlenet_source = fields.Selection(SOURCES, string='客户来源')
    zenlenet_industry = fields.Selection(INDUSTRIES, string='行业')
    zenlenet_payment_days = fields.Integer(string='账期（天）', default=30)
    zenlenet_commercial_contact = fields.Char(string='商务对接人')
    zenlenet_noc_email = fields.Char(string='NOC 邮箱')
    zenlenet_noc_phone = fields.Char(string='NOC 电话')
    zenlenet_currency_id = fields.Many2one(
        'res.currency', string='结算币种', compute='_compute_currency', inverse='_inverse_currency',
    )
    zenlenet_price_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_order_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_contract_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_invoice_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_unpaid_amount = fields.Monetary(compute='_compute_zenlenet_counts', currency_field='zenlenet_currency_id')
    zenlenet_ticket_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_flow_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_address_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_line_count = fields.Integer(compute='_compute_zenlenet_counts')
    zenlenet_mrr = fields.Monetary(string='月费合计', compute='_compute_zenlenet_counts', currency_field='zenlenet_currency_id')
    zenlenet_since = fields.Date(string='首次开通', compute='_compute_zenlenet_counts')
    zenlenet_contract_ids = fields.One2many('zenlenet.contract', 'partner_id', string='合同')
    zenlenet_ticket_ids = fields.One2many('zenlenet.ticket', 'partner_id', string='服务工单')
    zenlenet_prefix_ids = fields.One2many('zenlenet.prefix', 'partner_id', string='地址段')
    zenlenet_address_ids = fields.One2many('zenlenet.address', 'partner_id', string='IP 地址')
    zenlenet_flow_ids = fields.One2many('zenlenet.flow', 'partner_id', string='交付工单')
    zenlenet_line_ids = fields.One2many('zenlenet.line', 'partner_id', string='线路')
    zenlenet_vm_ids = fields.One2many('zenlenet.vm', 'partner_id', string='云主机')
    zenlenet_invoice_ids = fields.One2many('account.move', 'partner_id', string='账单', domain=[('move_type', '=', 'out_invoice'), ('state', '!=', 'cancel')])
    zenlenet_price_item_ids = fields.Many2many(
        'product.pricelist.item', compute='_compute_price_items', string='专属价格',
    )


    # ------------------------------------------------------------------ pricing
    @api.depends('property_product_pricelist')
    def _compute_currency(self):
        for record in self:
            record.zenlenet_currency_id = record.property_product_pricelist.currency_id or self.env.company.currency_id

    def _inverse_currency(self):
        for record in self:
            if record.zenlenet_currency_id:
                record._ensure_pricelist(record.zenlenet_currency_id)

    def _ensure_pricelist(self, currency=None):
        """Each customer owns one pricelist. Its currency is the customer's settlement currency."""
        self.ensure_one()
        Pricelist = self.env['product.pricelist'].sudo()
        current = self.property_product_pricelist
        currency = currency or current.currency_id or self.env.company.currency_id
        name = f'{self.name} · 专属价目'
        own = current if (current and current.name == name) else Pricelist.search([('name', '=', name)], limit=1)
        if own:
            if own.currency_id != currency:
                own.currency_id = currency
        else:
            own = Pricelist.create({'name': name, 'currency_id': currency.id, 'company_id': False})
        if self.property_product_pricelist != own:
            self.property_product_pricelist = own
        return own

    def action_open_prices(self):
        self.ensure_one()
        pricelist = self._ensure_pricelist()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} · 专属价格',
            'res_model': 'product.pricelist.item',
            'view_mode': 'list',
            'views': [(self.env.ref('zenlenet_ops.view_price_item_list').id, 'list')],
            'domain': [('pricelist_id', '=', pricelist.id)],
            'context': {
                'default_pricelist_id': pricelist.id,
                'default_applied_on': '1_product',
                'default_compute_price': 'fixed',
            },
            'target': 'current',
        }

    # ------------------------------------------------------------------- counts
    def _compute_zenlenet_counts(self):
        ids = self.ids
        Order = self.env['sale.order'].sudo()
        Move = self.env['account.move'].sudo()

        def grouped(model, domain, field='partner_id', aggregate='__count'):
            if not ids:
                return {}
            rows = self.env[model].sudo()._read_group([(field, 'in', ids)] + domain, [field], [aggregate])
            return {record.id: value for record, value in rows}

        orders = grouped('sale.order', [])
        contracts = grouped('zenlenet.contract', [])
        invoices = grouped('account.move', [('move_type', '=', 'out_invoice')])
        unpaid = grouped('account.move', [
            ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ], aggregate='amount_residual:sum')
        tickets = grouped('zenlenet.ticket', [('state', 'not in', ('closed', 'cancel'))])
        flows = grouped('zenlenet.flow', [('state', 'not in', ('done', 'cancel'))])
        addresses = grouped('zenlenet.address', [])
        lines = grouped('zenlenet.line', [('stopped', '=', False)])
        mrr = grouped('sale.order', [('state', '=', 'sale'), ('zenlenet_stage', '=', 'active')], aggregate='amount_untaxed:sum')
        since = grouped('sale.order', [('state', '=', 'sale')], aggregate='date_order:min')
        prices = {}
        if ids:
            for pricelist, count in self.env['product.pricelist.item'].sudo()._read_group(
                [('pricelist_id', 'in', self.mapped('property_product_pricelist').ids)], ['pricelist_id'], ['__count'],
            ):
                prices[pricelist.id] = count
        for record in self:
            record.zenlenet_order_count = orders.get(record.id, 0)
            record.zenlenet_contract_count = contracts.get(record.id, 0)
            record.zenlenet_invoice_count = invoices.get(record.id, 0)
            record.zenlenet_unpaid_amount = unpaid.get(record.id, 0.0) or 0.0
            record.zenlenet_ticket_count = tickets.get(record.id, 0)
            record.zenlenet_flow_count = flows.get(record.id, 0)
            record.zenlenet_address_count = addresses.get(record.id, 0)
            record.zenlenet_line_count = lines.get(record.id, 0)
            record.zenlenet_mrr = mrr.get(record.id, 0.0) or 0.0
            first = since.get(record.id)
            record.zenlenet_since = first.date() if first else False
            record.zenlenet_price_count = prices.get(record.property_product_pricelist.id, 0)

    # -------------------------------------------------------------------- crud
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda partner: partner.is_company and partner.customer_rank > 0)._assign_codes()
        return records

    @api.depends('name', 'property_product_pricelist')
    def _compute_price_items(self):
        Pricelist = self.env['product.pricelist'].sudo()
        empty = self.env['product.pricelist.item']
        for record in self:
            name = f'{record.name} · 专属价目' if record.name else ''
            current = record.property_product_pricelist
            own = current if name and current and current.name == name else Pricelist.browse()
            if name and not own:
                own = Pricelist.search([('name', '=', name)], limit=1)
            record.zenlenet_price_item_ids = own.item_ids if own else empty

    def _assign_codes(self):
        sequence = self.env['ir.sequence'].sudo()
        for record in self.filtered(lambda partner: not partner.zenlenet_code):
            record.zenlenet_code = sequence.next_by_code('zenlenet.customer') or '/'

    # ----------------------------------------------------------------- actions
    def _zenlenet_action(self, xmlid, domain, context=None, name=None):
        self.ensure_one()
        action = self.env.ref(xmlid).read()[0]
        action['domain'] = domain
        action['context'] = {'default_partner_id': self.id, **(context or {})}
        if name:
            action['display_name'] = f'{self.name} · {name}'
        return action

    def action_open_resources(self):
        return self._zenlenet_action('zenlenet_ops.action_addresses', [('partner_id', '=', self.id)], name='IP 地址')

    def action_open_lines(self):
        return self._zenlenet_action('zenlenet_ops.action_lines', [('partner_id', '=', self.id)], name='线路')

    def action_open_orders(self):
        return self._zenlenet_action(
            'zenlenet_ops.action_orders', [('partner_id', 'child_of', self.id)], name='服务订单',
        )

    def action_open_quote(self):
        self.ensure_one()
        if not self.zenlenet_manager_id:
            raise UserError('请先给这家客户指定客户经理，报价会归到这个人名下。')
        self._ensure_pricelist()
        return {
            'type': 'ir.actions.act_window',
            'name': '新报价',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'view_id': self.env.ref('zenlenet_ops.view_quote_form').id,
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
                'default_user_id': self.zenlenet_manager_id.id,
                'default_pricelist_id': self.property_product_pricelist.id,
            },
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
        return self._zenlenet_action('zenlenet_ops.action_tickets', [('partner_id', '=', self.id)], name='服务工单')

    def action_open_flows(self):
        return self._zenlenet_action('zenlenet_ops.action_flow', [('partner_id', '=', self.id)], name='交付工单')

    @api.model
    def _zenlenet_refresh_status(self):
        """Derive 在网 / 测试 / 已退租 from live orders; assign codes to legacy customers."""
        partners = self.sudo().search([('is_company', '=', True), ('customer_rank', '>', 0)])
        partners._assign_codes()
        stages = {}
        for partner, stage_list in self.env['sale.order'].sudo()._read_group(
            [('partner_id', 'in', partners.ids)], ['partner_id'], ['zenlenet_stage:array_agg'],
        ):
            stages[partner.id] = set(stage_list or [])
        for partner in partners:
            found = stages.get(partner.id, set())
            if 'active' in found:
                wanted = 'active'
            elif 'testing' in found:
                wanted = 'testing'
            elif 'terminated' in found:
                wanted = 'churned'
            else:
                wanted = partner.zenlenet_status or 'lead'
            if partner.zenlenet_status != wanted:
                partner.zenlenet_status = wanted

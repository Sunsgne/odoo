from odoo import api, fields, models

PARAMS = {
    'billing_day': ('zenlenet.billing_day', 1),
    'due_days': ('zenlenet.due_days', 30),
    'contract_term': ('zenlenet.contract_term', 12),
    'notice_days': ('zenlenet.notice_days', 30),
    'sla_urgent': ('zenlenet.sla_urgent', 4),
    'sla_high': ('zenlenet.sla_high', 8),
    'sla_normal': ('zenlenet.sla_normal', 24),
    'sla_low': ('zenlenet.sla_low', 72),
}


def param_int(env, key, default):
    raw = env['ir.config_parameter'].sudo().get_param(key)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    zenlenet_brand = fields.Char(string='系统名称', config_parameter='zenlenet.brand')
    zenlenet_usage_token = fields.Char(string='95 值接口 Token', config_parameter='zenlenet.usage_token')
    zenlenet_company_name = fields.Char(related='company_id.name', readonly=False, string='公司名称')
    zenlenet_company_vat = fields.Char(related='company_id.vat', readonly=False, string='UEN / 税号')
    zenlenet_company_street = fields.Char(related='company_id.street', readonly=False, string='地址')
    zenlenet_company_email = fields.Char(related='company_id.email', readonly=False, string='账务邮箱')
    zenlenet_company_phone = fields.Char(related='company_id.phone', readonly=False, string='电话')
    zenlenet_company_logo = fields.Binary(related='company_id.logo', readonly=False, string='Logo')
    zenlenet_currency_id = fields.Many2one(related='company_id.currency_id', string='币种')

    zenlenet_billing_day = fields.Integer(
        string='每月出账日', config_parameter='zenlenet.billing_day', default=1,
    )
    zenlenet_due_days = fields.Integer(string='付款期限（天）', config_parameter='zenlenet.due_days', default=30)
    zenlenet_auto_billing = fields.Boolean(string='自动出账')
    zenlenet_invoice_footer = fields.Char(
        string='账单备注', config_parameter='zenlenet.invoice_footer',
    )

    zenlenet_credit_rate = fields.Integer(string='每小时减免月费 %', config_parameter='zenlenet.credit_rate', default=5)
    zenlenet_credit_cap = fields.Integer(string='单次减免上限（月费 %）', config_parameter='zenlenet.credit_cap', default=100)
    zenlenet_contract_term = fields.Integer(string='默认期限（月）', config_parameter='zenlenet.contract_term', default=12)
    zenlenet_notice_days = fields.Integer(string='到期提前提醒（天）', config_parameter='zenlenet.notice_days', default=30)
    zenlenet_auto_renew = fields.Boolean(string='默认自动续签', config_parameter='zenlenet.auto_renew', default=True)

    zenlenet_sla_urgent = fields.Integer(string='紧急（小时）', config_parameter='zenlenet.sla_urgent', default=4)
    zenlenet_sla_high = fields.Integer(string='高（小时）', config_parameter='zenlenet.sla_high', default=8)
    zenlenet_sla_normal = fields.Integer(string='普通（小时）', config_parameter='zenlenet.sla_normal', default=24)
    zenlenet_sla_low = fields.Integer(string='低（小时）', config_parameter='zenlenet.sla_low', default=72)

    zenlenet_ping0_key = fields.Char(string='Ping0 Key', config_parameter='zenlenet.ping0_key')
    zenlenet_ping0_last = fields.Char(string='上次查询', compute='_compute_counts')
    zenlenet_netbox_url = fields.Char(string='NetBox 网址', config_parameter='zenlenet.netbox_url')
    zenlenet_netbox_api_url = fields.Char(string='API 地址', config_parameter='zenlenet.netbox_api_url')
    zenlenet_netbox_host = fields.Char(string='Host 头', config_parameter='zenlenet.netbox_host')
    zenlenet_netbox_token = fields.Char(string='API Token', config_parameter='zenlenet.netbox_token')
    zenlenet_netbox_sync = fields.Boolean(string='自动同步', config_parameter='zenlenet.netbox_sync')
    zenlenet_netbox_last_sync = fields.Char(string='上次同步', compute='_compute_counts')
    zenlenet_netbox_last_stats = fields.Char(compute='_compute_counts')
    zenlenet_netbox_ready = fields.Boolean(compute='_compute_counts')
    zenlenet_currency_ids = fields.Many2many(
        'res.currency', string='可用币种', compute='_compute_currencies', inverse='_inverse_currencies',
    )
    zenlenet_rate_pulled = fields.Char(string='上次拉取', compute='_compute_counts')
    zenlenet_sso_enabled = fields.Boolean(string='启用 Office 365 登录')
    zenlenet_sso_client_id = fields.Char(string='Azure 应用 ID（Client ID）')
    zenlenet_sso_tenant = fields.Char(string='Azure 租户 ID', config_parameter='zenlenet.azure_tenant')
    zenlenet_sso_ready = fields.Boolean(compute='_compute_counts')

    zenlenet_user_count = fields.Integer(compute='_compute_counts')
    zenlenet_product_count = fields.Integer(compute='_compute_counts')
    zenlenet_template_count = fields.Integer(compute='_compute_counts')
    zenlenet_datacenter_count = fields.Integer(compute='_compute_counts')

    def _oauth_provider(self):
        return self.env['auth.oauth.provider'].sudo().with_context(active_test=False).search(
            [('name', 'ilike', 'Office 365')], limit=1,
        ) or self.env['auth.oauth.provider'].sudo().with_context(active_test=False).search(
            [('auth_endpoint', 'ilike', 'microsoftonline')], limit=1,
        )

    def _compute_counts(self):
        for record in self:
            record.zenlenet_user_count = self.env['res.users'].sudo().search_count([('share', '=', False)])
            record.zenlenet_product_count = self.env['product.template'].sudo().search_count([('sale_ok', '=', True)])
            record.zenlenet_template_count = self.env['zenlenet.notice.template'].sudo().search_count([])
            record.zenlenet_datacenter_count = self.env['zenlenet.datacenter'].sudo().search_count([])
            provider = record._oauth_provider()
            record.zenlenet_sso_ready = bool(provider and provider.client_id)
            icp = self.env['ir.config_parameter'].sudo()
            record.zenlenet_netbox_last_sync = icp.get_param('zenlenet.netbox_last_sync') or '还没同步过'
            record.zenlenet_netbox_last_stats = icp.get_param('zenlenet.netbox_last_stats') or ''
            record.zenlenet_netbox_ready = self.env['zenlenet.netbox'].is_configured()
            last = self.env['zenlenet.ip.probe'].sudo().search(
                [('checked_at', '!=', False)], order='checked_at desc', limit=1,
            )
            record.zenlenet_ping0_last = fields.Datetime.to_string(last.checked_at) if last else ''
            record.zenlenet_rate_pulled = icp.get_param('zenlenet.rate_pulled') or ''

    def _compute_currencies(self):
        active = self.env['res.currency'].search([('active', '=', True)])
        for record in self:
            record.zenlenet_currency_ids = active

    def _inverse_currencies(self):
        Currency = self.env['res.currency'].sudo().with_context(active_test=False)
        company_currency = self.env.company.currency_id
        for record in self:
            wanted = record.zenlenet_currency_ids | company_currency
            Currency.search([('active', '=', True), ('id', 'not in', wanted.ids)]).write({'active': False})
            wanted.filtered(lambda currency: not currency.active).write({'active': True})

    def action_netbox_sync(self):
        return self.env['zenlenet.netbox'].action_sync()

    def action_open_currencies(self):
        return {
            'type': 'ir.actions.act_window',
            'name': '币种与汇率',
            'res_model': 'res.currency',
            'view_mode': 'list,form',
            'domain': [('active', '=', True)],
        }

    def action_pull_rates(self):
        self.env['res.currency'].zenlenet_pull_rates()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def get_values(self):
        values = super().get_values()
        cron = self.env.ref('zenlenet_ops.cron_contract_billing', raise_if_not_found=False)
        provider = self._oauth_provider()
        values.update({
            'zenlenet_auto_billing': bool(cron and cron.sudo().active),
            'zenlenet_sso_enabled': bool(provider and provider.enabled),
            'zenlenet_sso_client_id': provider.client_id if provider else False,
        })
        return values

    def set_values(self):
        super().set_values()
        brand = (self.zenlenet_brand or '').strip()
        if brand:
            root = self.env.ref('zenlenet_ops.menu_root', raise_if_not_found=False)
            if root and root.name != brand:
                root.sudo().name = brand
        cron = self.env.ref('zenlenet_ops.cron_contract_billing', raise_if_not_found=False)
        if cron:
            cron.sudo().active = bool(self.zenlenet_auto_billing)
        provider = self._oauth_provider()
        if provider:
            client_id = (self.zenlenet_sso_client_id or '').strip()
            provider.write({
                'client_id': client_id or False,
                'enabled': bool(self.zenlenet_sso_enabled and client_id),
            })

    def action_open_users(self):
        return self.env.ref('zenlenet_ops.action_users').read()[0]

    def action_open_products(self):
        return self.env.ref('zenlenet_ops.action_products').read()[0]

    def action_open_templates(self):
        return self.env.ref('zenlenet_ops.action_templates').read()[0]

    def action_open_datacenters(self):
        return self.env.ref('zenlenet_ops.action_datacenter_board').read()[0]

    def action_open_crons(self):
        return {
            'type': 'ir.actions.act_window',
            'name': '定时任务',
            'res_model': 'ir.cron',
            'view_mode': 'list,form',
            'domain': [('name', 'ilike', '尊领')],
        }

    def action_open_groups(self):
        return {
            'type': 'ir.actions.act_window',
            'name': '管理员',
            'res_model': 'res.users',
            'view_mode': 'list,form',
            'domain': [('all_group_ids', 'in', self.env.ref('zenlenet_ops.group_manager').id), ('share', '=', False)],
            'views': [
                (self.env.ref('zenlenet_ops.view_ops_user_list').id, 'list'),
                (self.env.ref('zenlenet_ops.view_ops_user_form').id, 'form'),
            ],
        }

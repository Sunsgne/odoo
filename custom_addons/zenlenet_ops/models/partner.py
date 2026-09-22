from urllib.parse import quote

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    zenlenet_status = fields.Selection([
        ('active', '在网'),
        ('testing', '测试'),
        ('churned', '已退租'),
    ], string='业务状态', default='active')

    def action_open_netbox(self):
        self.ensure_one()
        base = self.env['ir.config_parameter'].sudo().get_param(
            'zenlenet.netbox_url', 'https://netbox.zenlenet.com'
        ).rstrip('/')
        return {
            'type': 'ir.actions.act_url',
            'url': f'{base}/tenancy/tenants/?q={quote(self.name or "")}',
            'target': 'new',
        }

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ZenlenetShell(models.AbstractModel):
    _name = 'zenlenet.shell'
    _description = '尊领菜单'

    @api.model
    def apply(self):
        root = self.env.ref('zenlenet_ops.menu_root', raise_if_not_found=False)
        if root:
            menus = self.env['ir.ui.menu'].sudo().search([('parent_id', '=', False), ('id', '!=', root.id)])
            menus.write({'active': False})
            root.active = True
        self.env['zenlenet.notice.template'].sudo().load_workbook_templates()
        self.env['zenlenet.loader'].sudo().load_operational()
        self.env['zenlenet.flow'].sudo().migrate_resources()
        self.env['zenlenet.flow'].sudo().search([]).sudo()._ensure_default_tasks()
        self.env['zenlenet.datacenter'].sudo().migrate_places()
        self.env['zenlenet.prefix'].sudo().link_addresses()
        self.env['res.partner']._zenlenet_migrate_suppliers()
        self.env['zenlenet.flow.resource'].sudo().search([('service_type', '=', 'ip'), ('address_id', '!=', False), ('prefix_id', '=', False)]).write({'service_type': 'ip_single'})
        brand = self.env['ir.config_parameter'].sudo().get_param('zenlenet.brand')
        if brand and root and root.name != brand:
            root.name = brand
        contracts = self.env['zenlenet.contract'].sudo().search([])
        contracts._compute_currency()
        contracts._compute_amounts()
        self.env['res.partner']._zenlenet_refresh_status()
        action = self.env.ref('zenlenet_ops.action_home_page', raise_if_not_found=False)
        users = self.env['res.users'].sudo().search([('share', '=', False)])
        if action and 'action_id' in users._fields:
            users.write({'action_id': action.id})
        _logger.info('zenlenet shell applied')

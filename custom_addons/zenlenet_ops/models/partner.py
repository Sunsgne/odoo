from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    zenlenet_status = fields.Selection([
        ('active', '在网'),
        ('testing', '测试'),
        ('churned', '已退租'),
    ], string='业务状态', default='active')

    def action_open_resources(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'IP资源',
            'res_model': 'zenlenet.address',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_open_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '订单',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('zenlenet_ops.view_order_list').id, 'list'),
                (False, 'form'),
            ],
            'domain': [('partner_id', 'child_of', self.id)],
            'context': {'default_partner_id': self.id},
        }

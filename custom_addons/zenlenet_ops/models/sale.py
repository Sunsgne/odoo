from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    zenlenet_key = fields.Char(index=True, copy=False)
    zenlenet_stage = fields.Selection([
        ('testing', '测试'),
        ('active', '在网'),
        ('terminated', '已退租'),
    ], string='状态', index=True)

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

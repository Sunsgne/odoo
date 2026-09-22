from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    zenlenet_key = fields.Char(index=True, copy=False)

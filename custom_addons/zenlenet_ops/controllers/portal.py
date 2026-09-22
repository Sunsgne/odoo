from odoo import http
from odoo.http import request


class ZenlenetPortal(http.Controller):
    @http.route('/zenlenet/partner', type='http', auth='user')
    def partner(self, name='', **kwargs):
        partner = request.env['res.partner'].sudo().search([
            ('name', '=', name),
            ('is_company', '=', True),
        ], limit=1)
        if not partner:
            return request.redirect('/odoo/contacts')
        return request.redirect(f'/odoo/contacts/{partner.id}')

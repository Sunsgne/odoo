import csv
import io

from odoo import http
from odoo.http import request


class ZenlenetPortal(http.Controller):
    @http.route('/zenlenet/prefixes.csv', type='http', auth='user')
    def prefixes(self, **kwargs):
        labels = dict(request.env['zenlenet.address']._fields['status'].selection)
        counts = {}
        for row in request.env['zenlenet.address'].search_read([], ['block', 'pop', 'status']):
            key = (row['block'] or '', row['pop'] or '', labels.get(row['status'], ''))
            counts[key] = counts.get(key, 0) + 1
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['IP段', '机房', '分配状态', '地址数量'])
        for key in sorted(counts):
            writer.writerow([*key, counts[key]])
        payload = buffer.getvalue().encode('utf-8-sig')
        return request.make_response(payload, headers=[
            ('Content-Type', 'text/csv; charset=utf-8'),
            ('Content-Disposition', 'attachment; filename=ip-prefixes.csv'),
        ])

    @http.route('/zenlenet/partner', type='http', auth='user')
    def partner(self, name='', **kwargs):
        partner = request.env['res.partner'].sudo().search([
            ('name', '=', name),
            ('is_company', '=', True),
        ], limit=1)
        if not partner:
            return request.redirect('/odoo/contacts')
        return request.redirect(f'/odoo/contacts/{partner.id}')

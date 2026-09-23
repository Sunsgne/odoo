import csv
import io
import json

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

    @http.route('/zenlenet/usage', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def usage(self, **kwargs):
        """Cacti pushes monthly 95th-percentile readings here."""
        try:
            payload = json.loads(request.httprequest.get_data(as_text=True) or '{}')
        except ValueError:
            return request.make_json_response({'error': 'invalid json'}, status=400)
        env = request.env(su=True)
        expected = (env['ir.config_parameter'].get_param('zenlenet.usage_token') or '').strip()
        if not expected or payload.get('token') != expected:
            return request.make_json_response({'error': 'unauthorized'}, status=401)
        period = (payload.get('period') or '').strip()
        if len(period) != 7:
            return request.make_json_response({'error': 'period must be YYYY-MM'}, status=400)
        Order = env['sale.order']
        done, missing = 0, []
        for item in payload.get('items') or []:
            key = str(item.get('order') or item.get('graph_id') or '').strip()
            order = Order.search(['|', ('name', '=', key), ('zenlenet_graph_ref', '=', key)], limit=1) if key else Order
            if not order or item.get('p95_mbps') is None:
                missing.append(key)
                continue
            env['zenlenet.usage'].upsert(
                order, period, float(item['p95_mbps']), item.get('max_mbps'), item.get('avg_mbps'),
                source='cacti', graph_ref=str(item.get('graph_id') or '') or None,
            )
            done += 1
        return request.make_json_response({'imported': done, 'missing': missing})

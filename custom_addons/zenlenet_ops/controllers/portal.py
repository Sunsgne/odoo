import csv
import io
import json

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request


class ZenlenetPortal(http.Controller):
    @http.route('/zenlenet/prefixes.csv', type='http', auth='user')
    def prefixes(self, **kwargs):
        from odoo.addons.zenlenet_ops.remain import inventory_export_allowed
        user = request.env.user
        if not inventory_export_allowed(
            user.has_group('zenlenet_ops.group_finance'),
            user.has_group('zenlenet_ops.group_manager'),
        ):
            return request.make_json_response({'error': 'forbidden'}, status=403)
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

    @http.route('/zenlenet/inbox', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def inbox(self, **kwargs):
        from odoo.addons.zenlenet_ops.loop import payload_hash
        raw = request.httprequest.get_data(as_text=True) or ''
        env = request.env(su=True)
        secret = (env['ir.config_parameter'].get_param('zenlenet.webhook_secret') or '').strip()
        given = request.httprequest.headers.get('X-Zenlenet-Signature') or ''
        if not secret or given != secret:
            return request.make_json_response({'error': 'unauthorized'}, status=401)
        try:
            payload = json.loads(raw or '{}')
        except ValueError:
            return request.make_json_response({'error': 'invalid json'}, status=400)
        event_key = str(payload.get('event_key') or '').strip()
        if not event_key:
            return request.make_json_response({'error': 'event_key'}, status=400)
        try:
            row = env['zenlenet.inbox'].receive(event_key, payload_hash(raw), payload.get('version') or 0, raw)
        except UserError:
            return request.make_json_response({'error': 'conflict'}, status=409)
        return request.make_json_response({'id': row.id, 'state': row.state})

    @http.route('/zenlenet/mine', type='http', auth='user')
    def mine(self, **kwargs):
        from odoo.addons.zenlenet_ops.remain import portal_partner_id
        user = request.env.user
        partner_id = portal_partner_id(not user.share, user.partner_id.commercial_partner_id.id)
        if not partner_id:
            return request.redirect('/odoo')
        orders = request.env['sale.order'].search([
            ('partner_id', 'child_of', partner_id),
            ('state', '=', 'sale'),
        ])
        invoices = request.env['account.move'].search([
            ('partner_id', 'child_of', partner_id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
        ])
        body = ['<h1>服务</h1><ul>']
        body.extend(f'<li>{order.name}</li>' for order in orders)
        body.append('</ul><h1>账单</h1><ul>')
        body.extend(f'<li>{invoice.name}</li>' for invoice in invoices)
        body.append('</ul>')
        return request.make_response(''.join(body), headers=[('Content-Type', 'text/html; charset=utf-8')])

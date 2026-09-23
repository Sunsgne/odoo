import base64
import logging
import os
import sqlite3

from odoo import models

from odoo.addons.zenlenet_ops.blocks import prefix_block

_logger = logging.getLogger(__name__)

PRODUCTS = (
    ('ipt', 'IPT / RMIPT 带宽', 6.0),
    ('pl', '专线带宽', 5.0),
    ('sdwan', 'SD-WAN 接入', 5.0),
    ('vm', '云主机', 80.0),
    ('colo', '托管', 150.0),
    ('resale', '转售', 0.0),
)
COMPANY = {
    'name': 'ZENLENET PTE. LTD.',
    'street': '60 Paya Lebar Road #11-53 Paya Lebar Square',
    'city': 'Singapore',
    'zip': '409051',
    'vat': '202326370G',
}


class ZenlenetLoader(models.AbstractModel):
    _name = 'zenlenet.loader'
    _description = 'ZENLENET snapshot loader'

    def sync_office365(self):
        client = os.environ.get('AZURE_CLIENT_ID', '').strip()
        tenant = os.environ.get('AZURE_TENANT_ID', '').strip() or 'common'
        provider = self.env.ref('zenlenet_ops.provider_microsoft', raise_if_not_found=False)
        if provider and client and client != 'pending':
            provider.write({
                'client_id': client,
                'enabled': True,
                'auth_endpoint': f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize',
            })
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('auth_oauth.authorization_header', 'True')
        params.set_param('auth_signup.invitation_scope', 'b2c')
        return bool(client and client != 'pending')

    def load(self, path):
        self._company()
        self._ensure_chart()
        self.sync_office365()
        products = self._products()
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        partners = self._partners(connection)
        orders = self._orders(connection, partners, products)
        self._invoices(orders)
        self._tickets(connection, partners)
        connection.close()
        return {
            'partners': len(partners),
            'orders': len(orders),
        }

    def _company(self):
        company = self.env.company.sudo()
        usd = self.env.ref('base.USD')
        country = self.env.ref('base.sg')
        values = dict(COMPANY)
        values['country_id'] = country.id
        if not self.env['account.move'].sudo().search_count([]):
            values['currency_id'] = usd.id
        layout = self.env.ref('web.external_layout_standard', raise_if_not_found=False)
        if layout and not company.external_report_layout_id:
            values['external_report_layout_id'] = layout.id
        paper = self.env.ref('zenlenet_ops.paperformat_zenlenet', raise_if_not_found=False)
        if paper:
            values['paperformat_id'] = paper.id
        if not company.logo or company.uses_default_logo:
            icon = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'description', 'icon.png')
            if os.path.isfile(icon):
                with open(icon, 'rb') as handle:
                    values['logo'] = base64.b64encode(handle.read())
        company.write(values)
        currencies = self.env['res.currency'].sudo().with_context(active_test=False).search([('name', 'in', ('USD', 'SGD', 'CNY', 'HKD'))])
        currencies.filtered(lambda currency: not currency.active).write({'active': True})
        icp = self.env['ir.config_parameter'].sudo()
        for key, value in (('zenlenet.netbox_api_url', 'https://172.18.0.1'), ('zenlenet.netbox_host', 'netbox.zenlenet.com')):
            if not icp.get_param(key):
                icp.set_param(key, value)
        lang = self.env['res.lang'].with_context(active_test=False).search([('code', '=', 'zh_CN')], limit=1)
        if lang and not lang.active:
            lang.active = True
        admin = self.env.ref('base.user_admin')
        if lang:
            admin.lang = 'zh_CN'
        password = os.environ.get('ODOO_ADMIN_PASSWORD', '').strip()
        if password:
            admin.password = password

    def _ensure_chart(self):
        company = self.env.company
        if company.chart_template:
            return
        try:
            self.env['account.chart.template'].try_loading('sg', company, install_demo=False)
        except Exception:
            _logger.exception('Singapore chart was not installed; invoices will be skipped')

    def _products(self):
        found = {}
        template = self.env['product.template'].sudo()
        for code, name, price in PRODUCTS:
            product = template.search([('default_code', '=', code)], limit=1)
            if product and code == 'pl' and 'SD-WAN' in (product.name or ''):
                product.name = name
            if not product:
                product = template.create({
                    'name': name,
                    'default_code': code,
                    'type': 'service',
                    'list_price': price,
                    'sale_ok': True,
                    'invoice_policy': 'order',
                })
            found[code] = product.product_variant_id
        return found

    def _partners(self, connection):
        found = {}
        Partner = self.env['res.partner'].sudo()
        for row in connection.execute('select * from customers'):
            name = (row['name'] or '').strip()
            if not name:
                continue
            partner = Partner.search([('name', '=', name), ('is_company', '=', True)], limit=1)
            values = {
                'name': name,
                'is_company': True,
                'company_type': 'company',
                'customer_rank': 1,
                'zenlenet_status': row['status'] if row['status'] in {'active', 'testing', 'churned'} else 'active',
                'comment': row['note'] or False,
            }
            if partner:
                partner.write(values)
            else:
                partner = Partner.create(values)
            found[row['id']] = partner
        return found

    def _orders(self, connection, partners, products):
        Order = self.env['sale.order'].sudo().with_context(tracking_disable=True, mail_notrack=True)
        created = Order.browse()
        for row in connection.execute('select * from service_orders'):
            partner = partners.get(row['customer_id'])
            if not partner:
                continue
            key = str(row['id'])
            if Order.search_count([('zenlenet_key', '=', key)]):
                continue
            code, qty, price = _price(row['product'], row['bw_mbps'])
            product = products[code]
            where = row['pop_code'] or row['country'] or ''
            order = Order.create({
                'partner_id': partner.id,
                'zenlenet_key': key,
                'origin': f"{row['product']} {where}"[:200],
                'client_order_ref': (row['circuit_no'] or row['source'] or '')[:40],
                'order_line': [(0, 0, {
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'price_unit': price,
                    'name': f"{where} {row['product']} {row['bandwidth_text'] or row['spec'] or ''}".strip()[:200],
                })],
            })
            status = row['status']
            stage = status if status in {'active', 'testing', 'terminated'} else 'active'
            order.zenlenet_stage = stage
            if status == 'active':
                order.action_confirm()
            elif status == 'terminated':
                order._action_cancel()
            created |= order
        return created

    def _invoices(self, orders):
        confirmed = orders.filtered(lambda order: order.state == 'sale' and order.amount_total)
        for partner in confirmed.partner_id:
            batch = confirmed.filtered(lambda order, partner=partner: order.partner_id == partner)
            try:
                with self.env.cr.savepoint():
                    batch.with_context(tracking_disable=True)._create_invoices(grouped=False)
            except Exception:
                _logger.exception('invoice skipped for %s', partner.name)

    def _tickets(self, connection, partners):
        Maintenance = self.env['zenlenet.maintenance'].sudo()
        for row in connection.execute('select * from tickets'):
            if Maintenance.search_count([('name', '=', row['key'])]):
                continue
            Maintenance.create({
                'name': row['key'],
                'kind': row['type_code'] if row['type_code'] in dict(Maintenance._fields['kind'].selection) else 'maintenance',
                'partner_id': partners.get(row['customer_id']).id if partners.get(row['customer_id']) else False,
                'place': row['pop'] or '未指定节点',
                'impact': row['impact'] or '',
                'reason': row['reason'] or '',
                'duration': row['duration'] or '30分钟',
                'subject': row['subject'] or '',
                'body': row['body'] or '',
                'state': 'review',
            })

    def load_operational(self):
        path = self._snapshot_path()
        self.env['zenlenet.notice.template'].sudo().load_workbook_templates()
        if not path:
            _logger.warning('ZENLENET snapshot was not found; menus were updated without new rows')
            return
        self.load(path)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        self._stages(connection)
        self._addresses(connection)
        self._lines(connection)
        self._returns(connection)
        connection.close()
        self._assets()
        _logger.info(
            'zenlenet rows addresses=%s lines=%s returns=%s orders=%s templates=%s assets=%s',
            self.env['zenlenet.address'].sudo().search_count([]),
            self.env['zenlenet.line'].sudo().search_count([]),
            self.env['zenlenet.supplier.return'].sudo().search_count([]),
            self.env['sale.order'].sudo().search_count([]),
            self.env['zenlenet.notice.template'].sudo().search_count([]),
            self.env['zenlenet.asset'].sudo().search_count([]),
        )

    def _snapshot_path(self):
        for candidate in (
            os.environ.get('ZENLENET_SNAPSHOT', ''),
            '/mnt/snapshot/zenlenet.db',
            '/import/zenlenet.db',
        ):
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    def _stages(self, connection):
        Order = self.env['sale.order'].sudo()
        grouped = {'active': [], 'testing': [], 'terminated': []}
        for row in connection.execute('select id, status from service_orders'):
            if row['status'] in grouped:
                grouped[row['status']].append(str(row['id']))
        for stage, keys in grouped.items():
            if keys:
                Order.search([
                    ('zenlenet_key', 'in', keys),
                    ('zenlenet_stage', '!=', stage),
                ]).write({'zenlenet_stage': stage})

    def _addresses(self, connection):
        Address = self.env['zenlenet.address'].sudo()
        existing = set(Address.search([]).mapped('snapshot_id'))
        partners = {
            partner.name: partner
            for partner in self.env['res.partner'].sudo().search([('is_company', '=', True)])
        }
        names = {
            row['id']: row['name']
            for row in connection.execute('select id, name from customers')
        }
        roles = {
            'idc': 'IDC',
            'local': '本地',
            'native': '原生',
            'home': '家庭',
            'bgp': 'BGP',
            'other': '其他',
        }
        statuses = {'allocated', 'free', 'reserved', 'testing', 'returning', 'internal', 'transferring'}
        batch = []
        for row in connection.execute('select * from ip_records'):
            if row['id'] in existing:
                continue
            partner = partners.get(names.get(row['customer_id']))
            net_attr = row['net_attr'] if row['net_attr'] in {'公网', '内网', 'FastFiber'} else '公网'
            dc_type = row['dc_type'] if row['dc_type'] in {
                '主营机房', '第三方', 'POP点', '公有云', '已退租', '不常用', '安畅云',
            } else False
            batch.append({
                'snapshot_id': row['id'],
                'address': f"{row['address']}/{row['prefixlen']}",
                'block': prefix_block(row['version'], row['address'], row['prefixlen']),
                'pop': row['pop'] or '',
                'supplier': row['supplier'] or '',
                'partner_id': partner.id if partner else False,
                'role': roles.get(row['role'], '其他'),
                'net_attr': net_attr,
                'dc_type': dc_type,
                'status': row['status'] if row['status'] in statuses else 'free',
                'usage': row['usage'] or '',
                'expires_on': row['expires_on'] or False,
                'remark': (row['remark'] or '')[:2000],
            })
            if len(batch) >= 500:
                Address.with_context(zenlenet_import=True).create(batch)
                batch = []
        if batch:
            Address.with_context(zenlenet_import=True).create(batch)

    def _lines(self, connection):
        Line = self.env['zenlenet.line'].sudo()
        existing = set(Line.search([]).mapped('snapshot_key'))
        batch = []
        for row in connection.execute('select * from circuits'):
            key = f"c{row['id']}"
            if key in existing:
                continue
            bandwidth = row['bandwidth_mbps'] or 0
            batch.append({
                'snapshot_key': key,
                'name': (row['circuit_no'] or f"{row['a_city']}-{row['z_city']}" or '专线')[:80],
                'kind': 'private',
                'a_end': ' '.join(part for part in (row['a_city'], row['a_vlan']) if part),
                'z_end': ' '.join(part for part in (row['z_city'], row['z_vlan']) if part),
                'bandwidth': f'{bandwidth:g}M' if bandwidth else '',
            })
        for row in connection.execute('select * from vxlan_links'):
            key = f"v{row['id']}"
            if key in existing:
                continue
            batch.append({
                'snapshot_key': key,
                'name': f"VNI-{row['vni'] or row['id']}"[:80],
                'kind': 'vxlan',
                'a_end': row['a_end'] or '',
                'z_end': row['z_end'] or '',
                'bandwidth': row['bandwidth'] or '',
                'partner_name': row['customer_name'] or '',
                'purpose': row['purpose'] or '',
                'stopped': '回收' in (row['stopped'] or '') or '终止' in (row['stopped'] or ''),
            })
        if batch:
            Line.with_context(zenlenet_import=True).create(batch)

    def _returns(self, connection):
        Return = self.env['zenlenet.supplier.return'].sudo()
        existing = set(Return.search([]).mapped('snapshot_id'))
        batch = []
        for row in connection.execute('select * from supplier_returns'):
            if row['id'] in existing:
                continue
            if not (row['supplier'] or row['resource']):
                continue
            batch.append({
                'snapshot_id': row['id'],
                'supplier': row['supplier'] or '未填写',
                'resource': row['resource'] or '未填写',
                'when_text': row['when_text'] or '',
                'note': row['note'] or '',
            })
        if batch:
            Return.create(batch)

    def _assets(self):
        Asset = self.env['zenlenet.asset'].sudo()
        existing = set(Asset.search([]).mapped('snapshot_key'))
        orders = self.env['sale.order'].sudo().search([
            ('zenlenet_key', '!=', False),
            ('order_line.product_id.default_code', '=', 'colo'),
        ])
        batch = []
        for order in orders:
            key = f'colo:{order.zenlenet_key}'
            if key in existing:
                continue
            existing.add(key)
            line = order.order_line[:1]
            label = ((line.name if line else '') or '托管').strip() or '托管'
            batch.append({
                'snapshot_key': key,
                'name': label[:200],
                'partner_id': order.partner_id.id,
                'pop': (order.origin or '')[:120],
                'state': 'idle' if order.zenlenet_stage == 'terminated' else 'in_use',
            })
        if not batch:
            return
        try:
            Asset.create(batch)
        except Exception as error:
            _logger.warning('colo assets were not loaded: %s', type(error).__name__)


def _price(product, bandwidth):
    qty = float(bandwidth or 0) or 1.0
    if product in {'IPT', 'RMIPT'}:
        return 'ipt', qty, 6.0
    if product == 'PL':
        return 'pl', qty, 5.0
    if product == 'SDWAN':
        return 'sdwan', qty, 5.0
    if product == 'VM':
        return 'vm', 1.0, 80.0
    if product == '托管':
        return 'colo', 1.0, 150.0
    return 'resale', 1.0, 0.0

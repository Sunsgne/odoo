import logging
import os
import sqlite3

from odoo import models

_logger = logging.getLogger(__name__)

PRODUCTS = (
    ('ipt', 'IPT / RMIPT 带宽', 6.0),
    ('pl', '专线 / SD-WAN 带宽', 5.0),
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
        company.write(values)
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
            key = f"{row['customer_id']}:{row['product']}:{row['pop_code']}:{row['bandwidth_text']}:{row['status']}:{row['started_on']}"
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
            if status == 'active':
                order.action_confirm()
            elif status == 'terminated':
                order._action_cancel()
            created |= order
        return created

    def _invoices(self, orders):
        confirmed = orders.filtered(lambda order: order.state == 'sale')
        for partner in confirmed.partner_id:
            batch = confirmed.filtered(lambda order, partner=partner: order.partner_id == partner)
            try:
                with self.env.cr.savepoint():
                    batch.with_context(tracking_disable=True)._create_invoices(grouped=True)
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


def _price(product, bandwidth):
    qty = float(bandwidth or 0) or 1.0
    if product in {'IPT', 'RMIPT'}:
        return 'ipt', qty, 6.0
    if product in {'PL', 'SDWAN'}:
        return 'pl', qty, 5.0
    if product == 'VM':
        return 'vm', 1.0, 80.0
    if product == '托管':
        return 'colo', 1.0, 150.0
    return 'resale', 1.0, 0.0

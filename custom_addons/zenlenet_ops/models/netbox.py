"""NetBox is the source of truth for sites, prefixes, IP addresses, and circuits.

The console mirrors those objects so operators work in one place, and every
allocation made here is written back to NetBox through its REST API.
"""

import ipaddress
import logging
import re

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SITE_STATUS = {'active': 'active', 'planned': 'planning', 'staging': 'planning',
               'decommissioning': 'closed', 'retired': 'closed'}
SITE_STATUS_OUT = {'active': 'active', 'planning': 'planned', 'closed': 'retired'}
PREFIX_STATUS = {'container': 'container', 'active': 'active', 'reserved': 'reserved', 'deprecated': 'deprecated'}
IP_STATUS_OUT = {
    'allocated': 'active', 'testing': 'active', 'internal': 'active', 'free': 'active',
    'reserved': 'reserved', 'transferring': 'reserved', 'returning': 'deprecated',
}
CIRCUIT_TYPE = {'vxlan': 'vxlan'}
PAGE = 500


class ZenlenetNetbox(models.AbstractModel):
    _name = 'zenlenet.netbox'
    _description = 'NetBox 连接'

    # ------------------------------------------------------------------ client
    @api.model
    def _params(self):
        icp = self.env['ir.config_parameter'].sudo()
        return {
            'api': (icp.get_param('zenlenet.netbox_api_url') or '').rstrip('/'),
            'host': (icp.get_param('zenlenet.netbox_host') or '').strip(),
            'public': (icp.get_param('zenlenet.netbox_url') or '').rstrip('/'),
            'token': (icp.get_param('zenlenet.netbox_token') or '').strip(),
            'enabled': icp.get_param('zenlenet.netbox_sync', 'False') == 'True',
        }

    @api.model
    def is_configured(self):
        cfg = self._params()
        return bool(cfg['api'] and cfg['token'])

    @api.model
    def public_link(self, path):
        cfg = self._params()
        base = cfg['public'] or cfg['api']
        return f'{base}{path}' if base else False

    def _session(self):
        cfg = self._params()
        if not cfg['api'] or not cfg['token']:
            raise UserError('请先在「设置 → NetBox」里填写 API 地址和 Token。')
        session = requests.Session()
        session.headers.update({
            'Authorization': f"Token {cfg['token']}",
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })
        if cfg['host']:
            session.headers['Host'] = cfg['host']
        # A private address in the API URL means we talk to nginx on the docker gateway with the public hostname.
        session.verify = not re.match(r'https://(\d+\.\d+\.\d+\.\d+|localhost)', cfg['api'])
        return session, cfg['api']

    def _iterate(self, session, base, path, params=None):
        url = f'{base}/api{path}'
        query = dict(params or {}, limit=PAGE, offset=0)
        while url:
            response = session.get(url, params=query if query is not None else None, timeout=60)
            if response.status_code != 200:
                raise UserError(f'NetBox 返回 {response.status_code}：{response.text[:200]}')
            payload = response.json()
            yield from payload.get('results', [])
            url = payload.get('next')
            query = None
            if url and base.startswith('https://') and url.startswith('http://'):
                url = 'https://' + url[len('http://'):]
            if url:
                # Keep talking to the configured endpoint even when NetBox echoes its public hostname.
                url = re.sub(r'^https?://[^/]+', base, url)

    def _write(self, session, base, method, path, payload):
        response = session.request(method, f'{base}/api{path}', json=payload, timeout=60)
        if response.status_code >= 300:
            raise UserError(f'NetBox 写入失败 {response.status_code}：{response.text[:300]}')
        return response.json() if response.text else {}

    # -------------------------------------------------------------------- sync
    @api.model
    def action_sync(self):
        stats = self.sync_all()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'NetBox 同步完成',
                'message': '数据中心 {sites}，地址段 {prefixes}，IP {ips}，线路 {circuits}。'.format(**stats),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _cron_sync(self):
        if not self._params()['enabled'] or not self.is_configured():
            return
        try:
            self.sync_all()
        except Exception:
            _logger.exception('NetBox sync failed')

    @api.model
    def sync_all(self):
        session, base = self._session()
        stats = {
            'sites': self._sync_sites(session, base),
            'prefixes': self._sync_prefixes(session, base),
            'ips': self._sync_ips(session, base),
            'circuits': self._sync_circuits(session, base),
        }
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('zenlenet.netbox_last_sync', fields.Datetime.to_string(fields.Datetime.now()))
        icp.set_param('zenlenet.netbox_last_stats', '数据中心 {sites} · 地址段 {prefixes} · IP {ips} · 线路 {circuits}'.format(**stats))
        _logger.info('zenlenet netbox sync %s', stats)
        return stats

    def _partner_by_tenant(self, tenant):
        if not tenant:
            return False
        name = (tenant.get('name') or '').strip()
        if not name:
            return False
        Partner = self.env['res.partner'].sudo()
        partner = Partner.search([('name', '=', name), ('is_company', '=', True)], limit=1)
        if not partner:
            partner = Partner.create({'name': name, 'is_company': True, 'company_type': 'company', 'customer_rank': 1})
        return partner.id

    def _sync_sites(self, session, base):
        DC = self.env['zenlenet.datacenter'].sudo()
        existing = {record.netbox_id: record for record in DC.search([('netbox_id', '!=', 0)])}
        by_name = {record.name: record for record in DC.search([])}
        count = 0
        for site in self._iterate(session, base, '/dcim/sites/'):
            status = (site.get('status') or {}).get('value', 'active')
            values = {
                'netbox_id': site['id'],
                'name': site['name'],
                'code': site.get('slug') or '',
                'state': SITE_STATUS.get(status, 'active'),
                'address': site.get('physical_address') or '',
                'note': site.get('description') or '',
                'facility': site.get('facility') or '',
                'netbox_synced': fields.Datetime.now(),
            }
            record = existing.get(site['id']) or by_name.get(site['name'])
            if record:
                record.write({key: value for key, value in values.items() if value or key in ('netbox_id', 'state')})
            else:
                record = DC.create(values)
                by_name[record.name] = record
            count += 1
        return count

    def _sync_prefixes(self, session, base):
        Prefix = self.env['zenlenet.prefix'].sudo()
        DC = self.env['zenlenet.datacenter'].sudo()
        sites = {record.netbox_id: record.id for record in DC.search([('netbox_id', '!=', 0)])}
        existing = {record.prefix: record for record in Prefix.search([])}
        count = 0
        for item in self._iterate(session, base, '/ipam/prefixes/'):
            scope = item.get('scope') or {}
            site_id = sites.get(scope.get('id')) if (item.get('scope_type') or '') == 'dcim.site' else False
            values = {
                'netbox_id': item['id'],
                'prefix': item['prefix'],
                'status': PREFIX_STATUS.get((item.get('status') or {}).get('value'), 'active'),
                'datacenter_id': site_id,
                'partner_id': self._partner_by_tenant(item.get('tenant')),
                'role': (item.get('role') or {}).get('name') or '',
                'vlan': (item.get('vlan') or {}).get('display') or '',
                'description': item.get('description') or '',
                'is_pool': bool(item.get('is_pool')),
                'netbox_synced': fields.Datetime.now(),
            }
            record = existing.get(item['prefix'])
            if record:
                record.write(values)
            else:
                existing[item['prefix']] = Prefix.create(values)
            count += 1
        return count

    def _sync_ips(self, session, base):
        Address = self.env['zenlenet.address'].sudo()
        existing = {record.address: record for record in Address.search([])}
        count = 0
        batch = []
        for item in self._iterate(session, base, '/ipam/ip-addresses/'):
            custom = {
                key: (value.get('value') if isinstance(value, dict) else value)
                for key, value in (item.get('custom_fields') or {}).items()
            }
            status = (item.get('status') or {}).get('value')
            partner_id = self._partner_by_tenant(item.get('tenant'))
            values = {
                'netbox_id': item['id'],
                'partner_id': partner_id,
                'netbox_synced': fields.Datetime.now(),
            }
            if custom.get('dc_type'):
                values['dc_type'] = custom['dc_type']
            if custom.get('net_attr'):
                values['net_attr'] = custom['net_attr']
            if custom.get('usage'):
                values['usage'] = custom['usage']
            if custom.get('expires_on'):
                values['expires_on'] = custom['expires_on']
            record = existing.get(item['address'])
            if record:
                # NetBox decides tenant and hard states; the console keeps its finer allocation states.
                if status == 'reserved' and record.status not in ('reserved', 'transferring'):
                    values['status'] = 'reserved'
                elif status == 'deprecated' and record.status != 'returning':
                    values['status'] = 'returning'
                elif status == 'active' and partner_id and record.status == 'free':
                    values['status'] = 'allocated'
                elif status == 'active' and not partner_id and record.status in ('allocated', 'testing'):
                    values['status'] = 'free'
                record.with_context(netbox_skip_push=True).write(values)
            else:
                values.update({
                    'address': item['address'],
                    'block': self._block_of(item['address']),
                    'status': 'allocated' if (status == 'active' and partner_id) else (
                        'reserved' if status == 'reserved' else ('returning' if status == 'deprecated' else 'free')),
                    'remark': item.get('description') or '',
                })
                batch.append(values)
                if len(batch) >= 500:
                    Address.with_context(netbox_skip_push=True).create(batch)
                    batch = []
            count += 1
        if batch:
            Address.with_context(netbox_skip_push=True).create(batch)
        return count

    @staticmethod
    def _block_of(cidr):
        try:
            network = ipaddress.ip_interface(cidr).network
        except ValueError:
            return ''
        if network.version == 4:
            return str(ipaddress.ip_network(f'{network.network_address}/24', strict=False)) if network.prefixlen > 24 else str(network)
        return str(ipaddress.ip_network(f'{network.network_address}/64', strict=False)) if network.prefixlen > 64 else str(network)

    def _sync_circuits(self, session, base):
        Line = self.env['zenlenet.line'].sudo()
        DC = self.env['zenlenet.datacenter'].sudo()
        sites = {record.netbox_id: record for record in DC.search([('netbox_id', '!=', 0)])}
        existing = {record.name: record for record in Line.search([])}
        count = 0
        for item in self._iterate(session, base, '/circuits/circuits/'):
            kind_name = ((item.get('type') or {}).get('name') or '').lower()
            a_end = self._termination_label(item.get('termination_a'))
            z_end = self._termination_label(item.get('termination_z'))
            a_site = self._termination_site(item.get('termination_a'), sites)
            rate = item.get('commit_rate') or 0
            values = {
                'netbox_id': item['id'],
                'name': item['cid'],
                'kind': CIRCUIT_TYPE.get(kind_name, 'private'),
                'status': (item.get('status') or {}).get('value') or 'active',
                'supplier': (item.get('provider') or {}).get('name') or '',
                'supplier_id': self.env['res.partner'].zenlenet_supplier_by_name((item.get('provider') or {}).get('name'), 'carrier').id or False,
                'commit_rate': int(rate / 1000) if rate else 0,
                'start_date': item.get('install_date') or False,
                'end_date': item.get('termination_date') or False,
                'purpose': item.get('description') or '',
                'partner_id': self._partner_by_tenant(item.get('tenant')),
                'netbox_synced': fields.Datetime.now(),
            }
            if a_end:
                values['a_end'] = a_end
            if z_end:
                values['z_end'] = z_end
            if a_site:
                values['datacenter_id'] = a_site.id
            if rate and not (existing.get(item['cid']) and existing[item['cid']].bandwidth):
                values['bandwidth'] = f'{int(rate / 1000)}M' if rate >= 1000 else f'{rate}K'
            record = existing.get(item['cid'])
            if record:
                record.write(values)
            else:
                existing[item['cid']] = Line.create(values)
            count += 1
        return count

    @staticmethod
    def _termination_label(termination):
        if not termination:
            return ''
        inner = termination.get('termination') or {}
        return inner.get('name') or inner.get('display') or termination.get('display') or ''

    @staticmethod
    def _termination_site(termination, sites):
        if not termination:
            return None
        if (termination.get('termination_type') or '') == 'dcim.site':
            return sites.get((termination.get('termination') or {}).get('id'))
        return None

    # -------------------------------------------------------------------- push
    def _tenant_for(self, session, base, partner):
        if not partner:
            return None
        found = list(self._iterate(session, base, '/tenancy/tenants/', {'name': partner.name}))
        if found:
            return found[0]['id']
        created = self._write(session, base, 'POST', '/tenancy/tenants/', {
            'name': partner.name,
            'slug': f'kh-{partner.id}',
        })
        return created.get('id')

    @api.model
    def push_addresses(self, addresses):
        cfg = self._params()
        if not cfg['enabled'] or not self.is_configured():
            return
        session, base = self._session()
        for address in addresses.filtered('netbox_id'):
            payload = {
                'status': IP_STATUS_OUT.get(address.status, 'active'),
                'tenant': self._tenant_for(session, base, address.partner_id) if address.partner_id else None,
                'description': (address.usage or address.remark or '')[:200],
                'custom_fields': {
                    'dc_type': address.dc_type or None,
                    'net_attr': address.net_attr or None,
                    'usage': address.usage or None,
                    'expires_on': fields.Date.to_string(address.expires_on) if address.expires_on else None,
                },
            }
            self._write(session, base, 'PATCH', f'/ipam/ip-addresses/{address.netbox_id}/', payload)
            address.with_context(netbox_skip_push=True).write({'netbox_synced': fields.Datetime.now()})

    @api.model
    def create_prefixes(self, prefixes):
        cfg = self._params()
        if not cfg['enabled'] or not self.is_configured():
            return
        session, base = self._session()
        for prefix in prefixes.filtered(lambda record: not record.netbox_id):
            payload = {
                'prefix': prefix.prefix,
                'status': prefix.status if prefix.status in ('container', 'active', 'reserved', 'deprecated') else 'active',
                'description': (prefix.description or '')[:200],
            }
            if prefix.datacenter_id.netbox_id:
                payload.update({'scope_type': 'dcim.site', 'scope_id': prefix.datacenter_id.netbox_id})
            if prefix.partner_id:
                payload['tenant'] = self._tenant_for(session, base, prefix.partner_id)
            created = self._write(session, base, 'POST', '/ipam/prefixes/', payload)
            prefix.with_context(netbox_skip_push=True).write({'netbox_id': created.get('id'), 'netbox_synced': fields.Datetime.now()})

    @api.model
    def push_prefixes(self, prefixes):
        cfg = self._params()
        if not cfg['enabled'] or not self.is_configured():
            return
        session, base = self._session()
        status_out = {'container': 'container', 'active': 'active', 'reserved': 'reserved', 'deprecated': 'deprecated'}
        for prefix in prefixes.filtered('netbox_id'):
            payload = {
                'status': status_out.get(prefix.status, 'active'),
                'tenant': self._tenant_for(session, base, prefix.partner_id) if prefix.partner_id else None,
                'description': (prefix.description or '')[:200],
            }
            self._write(session, base, 'PATCH', f'/ipam/prefixes/{prefix.netbox_id}/', payload)
            prefix.with_context(netbox_skip_push=True).write({'netbox_synced': fields.Datetime.now()})

    @api.model
    def push_site(self, datacenter):
        cfg = self._params()
        if not cfg['enabled'] or not self.is_configured():
            return
        session, base = self._session()
        payload = {
            'name': datacenter.name,
            'status': SITE_STATUS_OUT.get(datacenter.state, 'active'),
            'facility': datacenter.facility or '',
            'physical_address': datacenter.address or '',
            'description': (datacenter.note or '')[:200],
        }
        if datacenter.netbox_id:
            self._write(session, base, 'PATCH', f'/dcim/sites/{datacenter.netbox_id}/', payload)
        else:
            slug = re.sub(r'[^a-z0-9-]+', '-', (datacenter.code or datacenter.name).lower()).strip('-') or f'dc-{datacenter.id}'
            created = self._write(session, base, 'POST', '/dcim/sites/', dict(payload, slug=slug))
            datacenter.with_context(netbox_skip_push=True).write({'netbox_id': created.get('id')})

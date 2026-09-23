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

from odoo.addons.zenlenet_ops.resource_bindings import circuit_kind, end_facts, kbps, vlan_vid

_logger = logging.getLogger(__name__)

SITE_STATUS = {'active': 'active', 'planned': 'planning', 'staging': 'planning',
               'decommissioning': 'closed', 'retired': 'closed'}
SITE_STATUS_OUT = {'active': 'active', 'planning': 'planned', 'closed': 'retired'}
PREFIX_STATUS = {'container': 'container', 'active': 'active', 'reserved': 'reserved', 'deprecated': 'deprecated'}
IP_STATUS_OUT = {
    'allocated': 'active', 'testing': 'active', 'internal': 'active', 'free': 'active',
    'reserved': 'reserved', 'transferring': 'reserved', 'returning': 'deprecated',
}
PAGE = 500
DEVICE_STATUS_IN = {'active': 'active', 'planned': 'planned', 'staged': 'planned', 'offline': 'offline',
                    'failed': 'offline', 'decommissioning': 'decommissioning', 'inventory': 'planned'}
DEVICE_STATUS_OUT = {'active': 'active', 'planned': 'planned', 'offline': 'offline', 'decommissioning': 'decommissioning'}
VM_STATUS_IN = {'active': 'active', 'planned': 'planned', 'staged': 'planned', 'offline': 'offline',
                'failed': 'offline', 'decommissioning': 'offline'}
VM_STATUS_OUT = {'active': 'active', 'planned': 'planned', 'offline': 'offline'}


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
        if not session.verify:
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
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
                'message': '数据中心 {sites}，物理机 {devices}，地址段 {prefixes}，IP {ips}，线路 {circuits}，云主机 {vms}。'.format(**stats),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _cron_push(self):
        """Every minute: write back addresses and prefixes changed in the console."""
        if not self._params()['enabled'] or not self.is_configured():
            return
        Address = self.env['zenlenet.address'].sudo()
        Prefix = self.env['zenlenet.prefix'].sudo()
        try:
            pending = Address.search([('netbox_pending', '=', True)], limit=200)
            self.create_addresses(pending.filtered(lambda record: not record.netbox_id))
            self.push_addresses(pending.filtered('netbox_id'))
            pending.with_context(netbox_skip_push=True).write({'netbox_pending': False})
            prefixes = Prefix.search([('netbox_pending', '=', True)], limit=100)
            self.create_prefixes(prefixes.filtered(lambda record: not record.netbox_id))
            self.push_prefixes(prefixes.filtered('netbox_id'))
            prefixes.with_context(netbox_skip_push=True).write({'netbox_pending': False})
        except Exception:
            _logger.exception('NetBox push failed')

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
            'devices': self._sync_devices(session, base),
            'prefixes': self._sync_prefixes(session, base),
            'ips': self._sync_ips(session, base),
            'circuits': self._sync_circuits(session, base),
            'vms': self._sync_vms(session, base),
        }
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('zenlenet.netbox_last_sync', fields.Datetime.to_string(fields.Datetime.now()))
        icp.set_param(
            'zenlenet.netbox_last_stats',
            '数据中心 {sites} · 物理机 {devices} · 地址段 {prefixes} · IP {ips} · 线路 {circuits} · 云主机 {vms}'.format(**stats),
        )
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
                record.with_context(netbox_skip_push=True).write({key: value for key, value in values.items() if value or key in ('netbox_id', 'state')})
            else:
                record = DC.with_context(netbox_skip_push=True).create(values)
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
                record.with_context(netbox_skip_push=True).write(values)
            else:
                existing[item['prefix']] = Prefix.with_context(netbox_skip_push=True).create(values)
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

    def _sync_devices(self, session, base):
        Device = self.env['zenlenet.device'].sudo()
        sites = {record.netbox_id: record.id for record in self.env['zenlenet.datacenter'].sudo().search([('netbox_id', '!=', 0)])}
        existing = {record.netbox_id: record for record in Device.search([('netbox_id', '!=', 0)])}
        count = 0
        for item in self._iterate(session, base, '/dcim/devices/'):
            status = (item.get('status') or {}).get('value') or 'active'
            values = {
                'netbox_id': item['id'],
                'name': item['name'],
                'datacenter_id': sites.get((item.get('site') or {}).get('id')) or False,
                'role': (item.get('role') or {}).get('name') or '',
                'status': DEVICE_STATUS_IN.get(status, 'active'),
                'serial': item.get('serial') or '',
                'netbox_synced': fields.Datetime.now(),
            }
            record = existing.get(item['id'])
            if record:
                record.with_context(netbox_skip_push=True).write(values)
            else:
                existing[item['id']] = Device.with_context(netbox_skip_push=True).create(values)
            count += 1
        return count

    def _sync_vms(self, session, base):
        Vm = self.env['zenlenet.vm'].sudo()
        sites = {record.netbox_id: record.id for record in self.env['zenlenet.datacenter'].sudo().search([('netbox_id', '!=', 0)])}
        devices = {record.netbox_id: record.id for record in self.env['zenlenet.device'].sudo().search([('netbox_id', '!=', 0)])}
        addresses = {record.address: record.id for record in self.env['zenlenet.address'].sudo().search([])}
        existing = {record.netbox_id: record for record in Vm.search([('netbox_id', '!=', 0)])}
        count = 0
        for item in self._iterate(session, base, '/virtualization/virtual-machines/'):
            status = (item.get('status') or {}).get('value') or 'active'
            primary = item.get('primary_ip4') or item.get('primary_ip') or {}
            ip_text = primary.get('address') or ''
            custom = item.get('custom_fields') or {}
            bandwidth = custom.get('bandwidth_mbps') or 0
            if isinstance(bandwidth, dict):
                bandwidth = bandwidth.get('value') or 0
            values = {
                'netbox_id': item['id'],
                'name': item['name'],
                'datacenter_id': sites.get((item.get('site') or {}).get('id')) or False,
                'device_id': devices.get((item.get('device') or {}).get('id')) or False,
                'address_id': addresses.get(ip_text) or False,
                'ip_text': ip_text,
                'bandwidth_mbps': int(bandwidth or 0),
                'status': VM_STATUS_IN.get(status, 'active'),
                'vcpus': item.get('vcpus') or 0,
                'memory': item.get('memory') or 0,
                'partner_id': self._partner_by_tenant(item.get('tenant')),
                'netbox_synced': fields.Datetime.now(),
            }
            if not values['datacenter_id']:
                continue
            record = existing.get(item['id'])
            if record:
                record.with_context(netbox_skip_push=True).write(values)
            else:
                existing[item['id']] = Vm.with_context(netbox_skip_push=True).create(values)
            count += 1
        return count

    def _sync_circuits(self, session, base):
        Line = self.env['zenlenet.line'].sudo()
        DC = self.env['zenlenet.datacenter'].sudo()
        Device = self.env['zenlenet.device'].sudo()
        sites = {record.netbox_id: record for record in DC.search([('netbox_id', '!=', 0)])}
        devices = {record.netbox_id: record for record in Device.search([('netbox_id', '!=', 0)])}
        ends = {}
        for term in self._iterate(session, base, '/circuits/circuit-terminations/'):
            circuit = term.get('circuit') or {}
            side = (term.get('term_side') or '').upper()
            if circuit.get('id') and side in ('A', 'Z'):
                ends.setdefault(circuit['id'], {})[side] = self._termination_with_vlan(session, base, term)
        existing = {record.name: record for record in Line.search([])}
        count = 0
        for item in self._iterate(session, base, '/circuits/circuits/'):
            kind_name = (item.get('type') or {}).get('name') or ''
            rate = item.get('commit_rate') or 0
            values = {
                'netbox_id': item['id'],
                'name': item['cid'],
                'kind': circuit_kind(kind_name),
                'status': (item.get('status') or {}).get('value') or 'active',
                'supplier': (item.get('provider') or {}).get('name') or '',
                'supplier_id': self.env['res.partner'].zenlenet_supplier_by_name((item.get('provider') or {}).get('name'), 'carrier').id or False,
                'start_date': item.get('install_date') or False,
                'end_date': item.get('termination_date') or False,
                'purpose': item.get('description') or '',
                'partner_id': self._partner_by_tenant(item.get('tenant')),
                'netbox_synced': fields.Datetime.now(),
            }
            self._apply_end(values, 'a', ends.get(item['id'], {}).get('A'), sites, devices)
            self._apply_end(values, 'z', ends.get(item['id'], {}).get('Z'), sites, devices)
            if values.get('a_site_id') and not values.get('datacenter_id'):
                values['datacenter_id'] = values['a_site_id']
            if rate:
                values['commit_rate'] = int(rate / 1000)
            if rate and not (existing.get(item['cid']) and existing[item['cid']].bandwidth):
                values['bandwidth'] = f'{int(rate / 1000)}M' if rate >= 1000 else f'{rate}K'
            record = existing.get(item['cid'])
            if record:
                record.with_context(netbox_skip_push=True).write(values)
            else:
                existing[item['cid']] = Line.with_context(netbox_skip_push=True).create(values)
            count += 1
        return count

    def _termination_with_vlan(self, session, base, term):
        """Brief cable peers omit the VLAN. Read the interface when a port is cabled."""
        peers = term.get('link_peers') or []
        if peers and peers[0].get('id') and not (peers[0].get('untagged_vlan') or {}).get('vid'):
            response = session.get(f"{base}/api/dcim/interfaces/{peers[0]['id']}/", timeout=60)
            if response.status_code == 200:
                term = dict(term, link_peers=[response.json()])
        return term

    def _apply_end(self, values, side, term, sites, devices):
        facts = end_facts(term)
        if not facts:
            label = self._termination_label(term)
            if label:
                values[f'{side}_end'] = label
            return
        if facts.get('term_netbox_id'):
            values[f'{side}_term_netbox_id'] = facts['term_netbox_id']
        site = sites.get(facts.get('site_netbox_id'))
        if site:
            values[f'{side}_site_id'] = site.id
            if side == 'a':
                values['datacenter_id'] = site.id
        if facts.get('region'):
            values['region'] = facts['region']
            values['region_netbox_id'] = facts.get('region_netbox_id') or 0
        device = devices.get(facts.get('device_netbox_id'))
        if device:
            values[f'{side}_device_id'] = device.id
        elif facts.get('device_netbox_id') and facts.get('device_name') and site:
            created = self.env['zenlenet.device'].sudo().with_context(netbox_skip_push=True).create({
                'name': facts['device_name'],
                'netbox_id': facts['device_netbox_id'],
                'datacenter_id': site.id,
                'netbox_synced': fields.Datetime.now(),
            })
            devices[facts['device_netbox_id']] = created
            values[f'{side}_device_id'] = created.id
        if facts.get('port'):
            values[f'{side}_port'] = facts['port']
        if facts.get('vlan'):
            values[f'{side}_vlan'] = facts['vlan']
        if facts.get('iface_netbox_id'):
            values[f'{side}_iface_netbox_id'] = facts['iface_netbox_id']
        label = ' '.join(bit for bit in (facts.get('site_name'), facts.get('device_name'), facts.get('port')) if bit)
        if label:
            values[f'{side}_end'] = label

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
    def create_addresses(self, addresses):
        cfg = self._params()
        if not cfg['enabled'] or not self.is_configured():
            return
        session, base = self._session()
        for address in addresses.filtered(lambda record: not record.netbox_id):
            payload = {
                'address': address.address,
                'status': IP_STATUS_OUT.get(address.status, 'active'),
                'description': (address.usage or '')[:200],
                'custom_fields': {'dc_type': address.dc_type or None, 'net_attr': address.net_attr or None, 'usage': address.usage or None},
            }
            if address.partner_id:
                payload['tenant'] = self._tenant_for(session, base, address.partner_id)
            created = self._write(session, base, 'POST', '/ipam/ip-addresses/', payload)
            address.with_context(netbox_skip_push=True).write({'netbox_id': created.get('id'), 'netbox_synced': fields.Datetime.now()})

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
    def delete_remote(self, path, netbox_ids):
        """Remove mirrored objects from NetBox so the hourly sync does not resurrect them.

        Runs inside the caller's transaction: a failure raises and rolls the console delete back.
        """
        cfg = self._params()
        if not netbox_ids or self.env.context.get('netbox_skip_push') or not cfg['enabled'] or not self.is_configured():
            return
        session, base = self._session()
        for netbox_id in netbox_ids:
            response = session.delete(f'{base}/api{path}{netbox_id}/', timeout=60)
            if response.status_code >= 300 and response.status_code != 404:
                raise UserError(f'NetBox 删除失败 {response.status_code}：{response.text[:300]}。控制台的删除已撤销。')

    def _slug(self, text, fallback):
        slug = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')
        return (slug or fallback)[:50]

    def _first(self, session, base, path, params):
        found = list(self._iterate(session, base, path, params))
        return found[0] if found else None

    def _generic_role(self, session, base):
        icp = self.env['ir.config_parameter'].sudo()
        cached = icp.get_param('zenlenet.netbox_device_role_id')
        if cached:
            return int(cached)
        found = self._first(session, base, '/dcim/device-roles/', {'slug': 'zenlenet-host'})
        role_id = found['id'] if found else self._write(session, base, 'POST', '/dcim/device-roles/', {
            'name': '主机', 'slug': 'zenlenet-host', 'color': '607d8b',
        })['id']
        icp.set_param('zenlenet.netbox_device_role_id', str(role_id))
        return role_id

    def _generic_type(self, session, base):
        icp = self.env['ir.config_parameter'].sudo()
        cached = icp.get_param('zenlenet.netbox_device_type_id')
        if cached:
            return int(cached)
        maker = self._first(session, base, '/dcim/manufacturers/', {'slug': 'zenlenet'})
        maker_id = maker['id'] if maker else self._write(session, base, 'POST', '/dcim/manufacturers/', {
            'name': 'ZENLENET', 'slug': 'zenlenet',
        })['id']
        found = self._first(session, base, '/dcim/device-types/', {'slug': 'zenlenet-host'})
        type_id = found['id'] if found else self._write(session, base, 'POST', '/dcim/device-types/', {
            'manufacturer': maker_id, 'model': '主机', 'slug': 'zenlenet-host',
        })['id']
        icp.set_param('zenlenet.netbox_device_type_id', str(type_id))
        return type_id

    def _circuit_type_id(self, session, base, kind):
        names = {'pl': '专线', 'sdwan': 'SD-WAN', 'vxlan': 'VXLAN', 'private': '供应商专线'}
        name = names.get(kind, '专线')
        slug = {'pl': 'pl', 'sdwan': 'sd-wan', 'vxlan': 'vxlan', 'private': 'private'}[kind if kind in names else 'pl']
        found = self._first(session, base, '/circuits/circuit-types/', {'slug': slug})
        if found:
            return found['id']
        return self._write(session, base, 'POST', '/circuits/circuit-types/', {'name': name, 'slug': slug})['id']

    @api.model
    def push_device(self, device):
        cfg = self._params()
        if not cfg['enabled'] or not self.is_configured() or not device.datacenter_id.netbox_id:
            return
        session, base = self._session()
        payload = {
            'name': device.name,
            'site': device.datacenter_id.netbox_id,
            'role': self._generic_role(session, base),
            'device_type': self._generic_type(session, base),
            'status': DEVICE_STATUS_OUT.get(device.status, 'active'),
            'serial': device.serial or '',
        }
        if device.netbox_id:
            self._write(session, base, 'PATCH', f'/dcim/devices/{device.netbox_id}/', payload)
        else:
            created = self._write(session, base, 'POST', '/dcim/devices/', payload)
            device.with_context(netbox_skip_push=True).write({
                'netbox_id': created.get('id'), 'netbox_synced': fields.Datetime.now(),
            })

    @api.model
    def push_vm(self, vm):
        cfg = self._params()
        if not cfg['enabled'] or not self.is_configured() or not vm.datacenter_id.netbox_id:
            return
        session, base = self._session()
        self._ensure_bandwidth_field(session, base)
        if vm.device_id and not vm.device_id.netbox_id:
            self.push_device(vm.device_id)
        payload = {
            'name': vm.name,
            'site': vm.datacenter_id.netbox_id,
            'status': VM_STATUS_OUT.get(vm.status, 'active'),
            'custom_fields': {'bandwidth_mbps': vm.bandwidth_mbps or None},
        }
        if vm.vcpus:
            payload['vcpus'] = vm.vcpus
        if vm.memory:
            payload['memory'] = vm.memory
        if vm.device_id.netbox_id:
            payload['device'] = vm.device_id.netbox_id
        if vm.partner_id:
            payload['tenant'] = self._tenant_for(session, base, vm.partner_id)
        if vm.netbox_id:
            self._write(session, base, 'PATCH', f'/virtualization/virtual-machines/{vm.netbox_id}/', payload)
        else:
            created = self._write(session, base, 'POST', '/virtualization/virtual-machines/', payload)
            vm.with_context(netbox_skip_push=True).write({
                'netbox_id': created.get('id'), 'netbox_synced': fields.Datetime.now(),
            })
        if vm.address_id.netbox_id:
            self._bind_vm_ip(session, base, vm)

    def _ensure_bandwidth_field(self, session, base):
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param('zenlenet.netbox_vm_bandwidth_field') == '1':
            return
        found = self._first(session, base, '/extras/custom-fields/', {'name': 'bandwidth_mbps'})
        if not found:
            self._write(session, base, 'POST', '/extras/custom-fields/', {
                'name': 'bandwidth_mbps',
                'label': '带宽 (Mbps)',
                'type': 'integer',
                'object_types': ['virtualization.virtualmachine'],
            })
        else:
            types = list(found.get('object_types') or [])
            if 'virtualization.virtualmachine' not in types:
                types.append('virtualization.virtualmachine')
                self._write(session, base, 'PATCH', f"/extras/custom-fields/{found['id']}/", {'object_types': types})
        icp.set_param('zenlenet.netbox_vm_bandwidth_field', '1')

    def _bind_vm_ip(self, session, base, vm):
        """Primary IP has to sit on an interface of this VM before NetBox will accept it."""
        iface_id = vm.iface_netbox_id
        if not iface_id:
            found = self._first(session, base, '/virtualization/interfaces/', {
                'virtual_machine_id': vm.netbox_id, 'name': 'eth0',
            })
            iface_id = found['id'] if found else self._write(session, base, 'POST', '/virtualization/interfaces/', {
                'virtual_machine': vm.netbox_id, 'name': 'eth0',
            })['id']
            vm.with_context(netbox_skip_push=True).write({'iface_netbox_id': iface_id})
        self._write(session, base, 'PATCH', f'/ipam/ip-addresses/{vm.address_id.netbox_id}/', {
            'assigned_object_type': 'virtualization.vminterface',
            'assigned_object_id': iface_id,
        })
        address = vm.address_id.address or vm.ip_text or ''
        primary = 'primary_ip6' if ':' in address else 'primary_ip4'
        self._write(session, base, 'PATCH', f'/virtualization/virtual-machines/{vm.netbox_id}/', {
            primary: vm.address_id.netbox_id,
        })

    @api.model
    def push_line(self, line):
        cfg = self._params()
        if not cfg['enabled'] or not self.is_configured():
            return
        session, base = self._session()
        if not line.netbox_id:
            self._create_remote_line(session, base, line)
        if not line.netbox_id:
            return
        rate = kbps(line.commit_rate)
        if rate:
            self._write(session, base, 'PATCH', f'/circuits/circuits/{line.netbox_id}/', {'commit_rate': rate})
        if line.kind == 'sdwan' and line.region:
            self._push_region_end(session, base, line)
            return
        if line.kind in ('pl', 'vxlan', 'private'):
            self._push_device_end(session, base, line, 'a')
            self._push_device_end(session, base, line, 'z')

    def _create_remote_line(self, session, base, line):
        provider_name = line.supplier_id.name or line.supplier or ''
        if not provider_name:
            return
        provider = self._first(session, base, '/circuits/providers/', {'name': provider_name})
        if not provider:
            return
        created = self._write(session, base, 'POST', '/circuits/circuits/', {
            'cid': line.name,
            'provider': provider['id'],
            'type': self._circuit_type_id(session, base, line.kind),
            'status': 'active',
            'commit_rate': kbps(line.commit_rate),
            'description': (line.purpose or '')[:200],
        })
        line.with_context(netbox_skip_push=True).write({
            'netbox_id': created.get('id'), 'netbox_synced': fields.Datetime.now(),
        })

    def _push_region_end(self, session, base, line):
        slug = self._slug(line.region, f'region-{line.id}')
        found = self._first(session, base, '/dcim/regions/', {'name': line.region})
        region_id = found['id'] if found else self._write(session, base, 'POST', '/dcim/regions/', {
            'name': line.region, 'slug': slug,
        })['id']
        line.with_context(netbox_skip_push=True).write({'region_netbox_id': region_id})
        self._upsert_termination(session, base, line, 'A', 'dcim.region', region_id, line.a_term_netbox_id, 'a_term_netbox_id')

    def _push_device_end(self, session, base, line, side):
        site = line[f'{side}_site_id']
        device = line[f'{side}_device_id']
        port = (line[f'{side}_port'] or '').strip()
        if not (site and site.netbox_id and device and port):
            return
        if not device.netbox_id:
            self.push_device(device)
        if not device.netbox_id:
            return
        vid = vlan_vid(line[f'{side}_vlan'])
        vlan_id = self._ensure_vlan(session, base, site.netbox_id, vid) if vid else None
        iface_id = self._ensure_interface(session, base, device.netbox_id, port, vlan_id)
        line.with_context(netbox_skip_push=True).write({f'{side}_iface_netbox_id': iface_id})
        term_id = self._upsert_termination(
            session, base, line, side.upper(), 'dcim.site', site.netbox_id,
            line[f'{side}_term_netbox_id'], f'{side}_term_netbox_id',
        )
        self._cable_end(session, base, term_id, iface_id)

    def _ensure_vlan(self, session, base, site_id, vid):
        found = self._first(session, base, '/ipam/vlans/', {'vid': vid, 'site_id': site_id})
        if found:
            return found['id']
        return self._write(session, base, 'POST', '/ipam/vlans/', {
            'vid': vid, 'name': f'VLAN{vid}', 'site': site_id, 'status': 'active',
        })['id']

    def _ensure_interface(self, session, base, device_id, port, vlan_id):
        found = self._first(session, base, '/dcim/interfaces/', {'device_id': device_id, 'name': port})
        payload = {'mode': 'access'}
        if vlan_id:
            payload['untagged_vlan'] = vlan_id
        if found:
            if vlan_id:
                self._write(session, base, 'PATCH', f"/dcim/interfaces/{found['id']}/", payload)
            return found['id']
        payload.update({'device': device_id, 'name': port, 'type': 'other'})
        return self._write(session, base, 'POST', '/dcim/interfaces/', payload)['id']

    def _upsert_termination(self, session, base, line, side, termination_type, termination_id, current_id, store_field):
        payload = {
            'termination_type': termination_type,
            'termination_id': termination_id,
            'port_speed': kbps(line.commit_rate),
        }
        if current_id:
            self._write(session, base, 'PATCH', f'/circuits/circuit-terminations/{current_id}/', payload)
            return current_id
        found = self._first(session, base, '/circuits/circuit-terminations/', {
            'circuit_id': line.netbox_id, 'term_side': side,
        })
        if found:
            self._write(session, base, 'PATCH', f"/circuits/circuit-terminations/{found['id']}/", payload)
            line.with_context(netbox_skip_push=True).write({store_field: found['id']})
            return found['id']
        created = self._write(session, base, 'POST', '/circuits/circuit-terminations/', dict(payload, circuit=line.netbox_id, term_side=side))
        line.with_context(netbox_skip_push=True).write({store_field: created['id']})
        return created['id']

    def _cable_end(self, session, base, term_id, iface_id):
        response = session.get(f'{base}/api/circuits/circuit-terminations/{term_id}/', timeout=60)
        if response.status_code != 200 or response.json().get('cable'):
            return
        self._write(session, base, 'POST', '/dcim/cables/', {
            'a_terminations': [{'object_type': 'circuits.circuittermination', 'object_id': term_id}],
            'b_terminations': [{'object_type': 'dcim.interface', 'object_id': iface_id}],
        })

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

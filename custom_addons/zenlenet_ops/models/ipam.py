"""RPC entry points for the one-page IPAM screen (tree on the left, address grid in the middle, facts on the right)."""

import ipaddress
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.blocks import parse_prefix

_logger = logging.getLogger(__name__)

STATUS_LABELS = {
    'free': '未分配', 'allocated': '已分配', 'reserved': '预分配', 'transferring': '调库中',
    'returning': '出库中', 'testing': '测试', 'internal': '自用',
}
MAX_GRID_BLOCKS = 16


class ZenlenetPrefixIpam(models.Model):
    _inherit = 'zenlenet.prefix'

    @api.model
    def ipam_tree(self, search=''):
        domain = []
        if search:
            domain = ['|', '|', ('prefix', 'ilike', search), ('description', 'ilike', search), ('partner_id.name', 'ilike', search)]
        rows = self.search_read(domain, [
            'prefix', 'parent_id', 'status', 'partner_id', 'datacenter_id', 'utilization', 'child_count',
            'family', 'prefixlen', 'description',
        ], order='family, prefix')
        wanted = {row['id'] for row in rows}
        if search:
            # keep ancestors so matches stay attached to their branch
            ancestors = self.browse([row['parent_id'][0] for row in rows if row['parent_id']])
            while ancestors:
                extra = ancestors.filtered(lambda record: record.id not in wanted)
                if not extra:
                    break
                rows += extra.read(['prefix', 'parent_id', 'status', 'partner_id', 'datacenter_id', 'utilization',
                                    'child_count', 'family', 'prefixlen', 'description'])
                wanted |= set(extra.ids)
                ancestors = extra.mapped('parent_id')
        return [{
            'id': row['id'],
            'prefix': row['prefix'],
            'parent_id': row['parent_id'][0] if row['parent_id'] else False,
            'status': row['status'],
            'partner': row['partner_id'][1] if row['partner_id'] else '',
            'datacenter': row['datacenter_id'][1] if row['datacenter_id'] else '',
            'utilization': row['utilization'],
            'child_count': row['child_count'],
            'family': row['family'],
            'prefixlen': row['prefixlen'],
            'description': row['description'] or '',
        } for row in rows]

    def _ipam_addresses(self, network):
        Address = self.env['zenlenet.address']
        blocks = [str(subnet) for subnet in network.subnets(new_prefix=24)] if network.version == 4 and network.prefixlen <= 24 else [str(network)]
        rows = Address.search_read(
            ['|', ('prefix_id', 'in', (self | self.child_ids).ids), ('block', 'in', blocks[:512])],
            ['address', 'status', 'partner_id', 'usage', 'net_attr', 'netbox_id'],
        )
        found = {}
        for row in rows:
            try:
                host = ipaddress.ip_interface(row['address']).ip
            except ValueError:
                continue
            if host in network:
                found[str(host)] = row
        return found

    def ipam_detail(self):
        self.ensure_one()
        try:
            network = ipaddress.ip_network(parse_prefix(self.prefix), strict=False)
        except ValueError as error:
            raise UserError('网段格式不对。') from error
        found = self._ipam_addresses(network)
        blocks, truncated = [], False
        if network.version == 4 and network.prefixlen >= 16:
            subnets = list(network.subnets(new_prefix=max(24, network.prefixlen)))
            if len(subnets) > MAX_GRID_BLOCKS:
                subnets, truncated = subnets[:MAX_GRID_BLOCKS], True
            for subnet in subnets:
                cells = []
                for host in subnet:
                    key = str(host)
                    row = found.get(key)
                    special = ''
                    if network.prefixlen < 31:
                        if host == network.network_address:
                            special = 'network'
                        elif host == network.broadcast_address:
                            special = 'broadcast'
                    cells.append({
                        'ip': key,
                        'last': int(host) & 0xFF,
                        'status': row['status'] if row else ('special' if special else 'none'),
                        'partner': row['partner_id'][1] if row and row['partner_id'] else '',
                        'usage': row['usage'] if row else '',
                        'id': row['id'] if row else False,
                        'special': special,
                    })
                blocks.append({
                    'label': f'{subnet.network_address} - {subnet.broadcast_address}',
                    'prefix': str(subnet),
                    'cells': cells,
                    'used': sum(1 for cell in cells if cell['status'] not in ('none', 'free', 'special')),
                })
        counts = {}
        for row in found.values():
            counts[row['status']] = counts.get(row['status'], 0) + 1
        children = self.child_ids.read(['prefix', 'status', 'partner_id', 'size_display', 'allocated_count', 'free_count', 'utilization', 'description'])
        return {
            'id': self.id,
            'prefix': self.prefix,
            'status': self.status,
            'status_label': dict(self._fields['status'].selection).get(self.status, ''),
            'family': self.family,
            'netmask': self.netmask,
            'first_ip': self.first_ip,
            'last_ip': self.last_ip,
            'size': self.size,
            'size_display': self.size_display,
            'used': sum(count for status, count in counts.items() if status != 'free'),
            'counts': {STATUS_LABELS.get(key, key): value for key, value in counts.items()},
            'partner': self.partner_id.name or '',
            'partner_id': self.partner_id.id,
            'datacenter': self.datacenter_id.name or '',
            'datacenter_id': self.datacenter_id.id,
            'parent': self.parent_id.prefix or '',
            'parent_id': self.parent_id.id,
            'role': self.role or '',
            'vlan': self.vlan or '',
            'description': self.description or '',
            'netbox_id': self.netbox_id,
            'netbox_url': self.env['zenlenet.netbox'].public_link(f'/ipam/prefixes/{self.netbox_id}/') if self.netbox_id else '',
            'netbox_synced': fields.Datetime.to_string(self.netbox_synced) if self.netbox_synced else '',
            'create_date': fields.Datetime.to_string(self.create_date) if self.create_date else '',
            'blocks': blocks,
            'truncated': truncated,
            'children': [{
                'id': child['id'], 'prefix': child['prefix'], 'status': child['status'],
                'partner': child['partner_id'][1] if child['partner_id'] else '',
                'size': child['size_display'], 'allocated': child['allocated_count'], 'free': child['free_count'],
                'utilization': child['utilization'], 'description': child['description'] or '',
            } for child in children],
            'can_write': self.has_access('write'),
        }

    def ipam_set_address(self, ip, values):
        """Create or update one host inside this prefix from the grid popover."""
        self.ensure_one()
        try:
            network = ipaddress.ip_network(parse_prefix(self.prefix), strict=False)
            host = ipaddress.ip_address(ip)
        except ValueError as error:
            raise UserError('地址格式不对。') from error
        if host not in network:
            raise UserError('这个地址不在当前网段里。')
        Address = self.env['zenlenet.address']
        record = Address.search([('address', '=like', f'{ip}/%')], limit=1)
        payload = {}
        if 'status' in values and values['status'] in STATUS_LABELS:
            payload['status'] = values['status']
        if 'partner_id' in values:
            payload['partner_id'] = values['partner_id'] or False
        if 'usage' in values:
            payload['usage'] = values['usage'] or ''
        if record:
            record.write(payload)
        else:
            record = Address.create(dict(payload, **{
                'address': f'{ip}/{network.max_prefixlen}',
                'block': str(network) if network.prefixlen >= 24 else str(ipaddress.ip_network(f'{ip}/24', strict=False)),
                'prefix_id': self.id,
                'datacenter_id': self.datacenter_id.id,
                'pop': self.datacenter_id.name or '',
                'dc_type': self.datacenter_id.kind or False,
                'status': payload.get('status', 'allocated'),
            }))
        return {'id': record.id, 'status': record.status, 'partner': record.partner_id.name or '', 'usage': record.usage or ''}

    @api.model
    def ipam_pending_flows(self):
        """Delivery tickets waiting for resources, for the grid's assign panel."""
        flows = self.env['zenlenet.flow'].search([('state', '=', 'allocate')], order='id desc', limit=50)
        return [{
            'id': flow.id, 'name': flow.name, 'partner_id': flow.partner_id.id, 'partner': flow.partner_id.name or '',
            'datacenter': flow.datacenter_id.name or '', 'pending': flow.pending_count,
            'order': flow.order_id.name or '',
        } for flow in flows]

    def ipam_bulk_assign(self, ips, partner_id=None, flow_id=None, usage=''):
        """Allocate the selected hosts to a customer, optionally through a delivery ticket."""
        self.ensure_one()
        flow = self.env['zenlenet.flow'].browse(flow_id) if flow_id else self.env['zenlenet.flow']
        if flow and not partner_id:
            partner_id = flow.partner_id.id
        if not partner_id:
            raise UserError('请选择客户或交付工单。')
        Resource = self.env['zenlenet.flow.resource']
        records = self.env['zenlenet.address']
        for ip in ips:
            info = self.ipam_set_address(ip, {'status': 'allocated', 'partner_id': partner_id, 'usage': usage or (f'交付工单 {flow.name}' if flow else '')})
            records |= records.browse(info['id'])
        if flow:
            have = set(flow.resource_ids.mapped('address_id').ids)
            for address in records:
                if address.id in have:
                    continue
                Resource.create({
                    'flow_id': flow.id,
                    'service_type': 'ip_single',
                    'resource_ref': f'zenlenet.address,{address.id}',
                    'spec': f'{address.address} 由地址管理分配',
                })
        return {'count': len(records), 'flow': flow.name if flow else ''}

    def ipam_bulk_status(self, ips, status):
        self.ensure_one()
        if status not in STATUS_LABELS:
            raise UserError('状态不对。')
        for ip in ips:
            self.ipam_set_address(ip, {'status': status, **({'partner_id': self.partner_id.id} if status in ('allocated', 'testing') and self.partner_id else {})})
        return True

    def ipam_assign(self, partner_id):
        self.ensure_one()
        self.partner_id = partner_id or False
        if partner_id:
            self.action_allocate()
        else:
            self.action_release()
        return True

    @api.model
    def ipam_customers(self, search=''):
        return self.env['res.partner'].search_read(
            [('is_company', '=', True), ('customer_rank', '>', 0), ('name', 'ilike', search or '')],
            ['name'], limit=20, order='name',
        )

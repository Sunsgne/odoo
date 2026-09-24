"""RPC entry points for the one-page IPAM screen (tree on the left, address grid in the middle, facts on the right)."""

import ipaddress
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.blocks import edge_label, parse_prefix

_logger = logging.getLogger(__name__)

STATUS_LABELS = {
    'free': '未分配', 'allocated': '已分配', 'reserved': '预分配', 'transferring': '调库中',
    'returning': '出库中', 'testing': '测试', 'internal': '自用',
}
MAX_GRID_BLOCKS = 16


class ZenlenetIpamDomain(models.Model):
    _name = 'zenlenet.ipam.domain'
    _description = '管理域'
    _order = 'name'

    name = fields.Char(string='管理域', required=True)
    prefix_ids = fields.One2many('zenlenet.prefix', 'domain_id', string='地址段')
    prefix_count = fields.Integer(string='地址段', compute='_compute_prefix_count')

    _name_unique = models.Constraint('unique(name)', '这个管理域已经存在。')

    @api.depends('prefix_ids')
    def _compute_prefix_count(self):
        for record in self:
            record.prefix_count = len(record.prefix_ids)


class ZenlenetPrefixIpam(models.Model):
    _inherit = 'zenlenet.prefix'

    domain_id = fields.Many2one('zenlenet.ipam.domain', string='管理域', index=True, ondelete='set null')

    @api.model
    def ipam_domains(self):
        rows = self.env['zenlenet.ipam.domain'].search_read([], ['name', 'prefix_count'], order='name')
        return [{'id': row['id'], 'name': row['name'], 'count': row['prefix_count']} for row in rows]

    @api.model
    def ipam_lookup(self, address='', obj='', domain_id=False):
        """Find the tightest prefix for an address, range or CIDR, or for a customer, host or device."""
        Prefix = self
        scope = [('domain_id', '=', int(domain_id))] if domain_id else []
        prefix_id = False
        hit_ip = ''
        text = (address or '').strip()
        if text:
            start = text.split('-', 1)[0].strip()
            try:
                if '/' in start:
                    network = ipaddress.ip_network(parse_prefix(start), strict=False)
                else:
                    host = ipaddress.ip_address(start)
                    network = ipaddress.ip_network(f'{host}/{32 if host.version == 4 else 128}', strict=False)
                    hit_ip = str(host)
            except ValueError as error:
                raise UserError('地址格式不对。') from error
            best = None
            for record in Prefix.search(scope):
                try:
                    current = ipaddress.ip_network(parse_prefix(record.prefix), strict=False)
                except ValueError:
                    continue
                if network.version == current.version and (network.subnet_of(current) or network == current):
                    if best is None or current.prefixlen > best[0]:
                        best = (current.prefixlen, record.id)
            prefix_id = best[1] if best else False
        query = (obj or '').strip()
        if query:
            address_row = self.env['zenlenet.address'].search([
                '|', '|', '|',
                ('address', 'ilike', query),
                ('usage', 'ilike', query),
                ('partner_id.name', 'ilike', query),
                ('remark', 'ilike', query),
            ], limit=1)
            if address_row.prefix_id and (not domain_id or address_row.prefix_id.domain_id.id == int(domain_id)):
                prefix_id = address_row.prefix_id.id
                hit_ip = address_row.address.split('/')[0]
            elif not prefix_id:
                found = Prefix.search(scope + [
                    '|', '|', '|',
                    ('description', 'ilike', query),
                    ('role', 'ilike', query),
                    ('partner_id.name', 'ilike', query),
                    ('prefix', 'ilike', query),
                ], limit=1)
                prefix_id = found.id or False
            if not prefix_id:
                device = self.env['zenlenet.device'].search([('name', 'ilike', query)], limit=1)
                if device.datacenter_id:
                    found = Prefix.search(scope + [('datacenter_id', '=', device.datacenter_id.id)], limit=1)
                    prefix_id = found.id or False
        return {'prefix_id': prefix_id, 'ip': hit_ip}

    @api.model
    def ipam_tree(self, search='', domain_id=False):
        domain = []
        if domain_id:
            domain.append(('domain_id', '=', int(domain_id)))
        if search:
            domain += ['|', '|', ('prefix', 'ilike', search), ('description', 'ilike', search), ('partner_id.name', 'ilike', search)]
        fields_list = ['prefix', 'parent_id', 'status', 'partner_id', 'datacenter_id', 'utilization', 'child_count',
                       'family', 'prefixlen', 'description', 'region', 'asn', 'domain_id']
        rows = self.search_read(domain, fields_list, order='family, prefix')
        wanted = {row['id'] for row in rows}
        if search or domain_id:
            # keep ancestors so matches stay attached to their branch
            ancestors = self.browse([row['parent_id'][0] for row in rows if row['parent_id']])
            while ancestors:
                extra = ancestors.filtered(lambda record: record.id not in wanted)
                if not extra:
                    break
                rows += extra.read(fields_list)
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
            'region': row['region'] or '未分地区',
            'asn': row['asn'] or 0,
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
                    # Ends stay selectable. They read as free when empty, and cannot be given to a customer.
                    label = edge_label(self.prefix, key)
                    cells.append({
                        'ip': key,
                        'last': int(host) & 0xFF,
                        'status': row['status'] if row else ('free' if label else 'none'),
                        'partner': row['partner_id'][1] if row and row['partner_id'] else '',
                        'partner_id': row['partner_id'][0] if row and row['partner_id'] else False,
                        'usage': row['usage'] if row else '',
                        'id': row['id'] if row else False,
                        'special': '',
                        'edge': bool(label),
                        'edge_label': label,
                    })
                blocks.append({
                    'label': f'{subnet.network_address} - {subnet.broadcast_address}',
                    'prefix': str(subnet),
                    'cells': cells,
                    'used': sum(1 for cell in cells if cell['status'] not in ('none', 'free')),
                })
        counts = {}
        reserved_for = {}
        for row in found.values():
            counts[row['status']] = counts.get(row['status'], 0) + 1
            if row['status'] == 'reserved':
                name = row['partner_id'][1] if row['partner_id'] else '未指定客户'
                reserved_for[name] = reserved_for.get(name, 0) + 1
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
            'reserved_for': [
                {'partner': name, 'count': count}
                for name, count in sorted(reserved_for.items(), key=lambda item: (-item[1], item[0]))
            ],
            'datacenter': self.datacenter_id.name or '',
            'datacenter_id': self.datacenter_id.id,
            'parent': self.parent_id.prefix or '',
            'parent_id': self.parent_id.id,
            'region': self.region or '',
            'asn': self.asn or 0,
            'top': self.top_id.prefix or self.prefix,
            'top_id': self.top_id.id or self.id,
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

    def _reject_edge_allocation(self, ips):
        """Network and broadcast addresses can be selected, but not given to a customer."""
        self.ensure_one()
        for ip in ips or []:
            if edge_label(self.prefix, ip):
                raise UserError('网络位和广播位不能分配。')

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
        if payload.get('status') in ('free', 'internal'):
            payload['partner_id'] = False
        elif 'partner_id' in values:
            payload['partner_id'] = values['partner_id'] or False
        if 'usage' in values:
            payload['usage'] = values['usage'] or ''
        status = payload.get('status') or (record.status if record else 'allocated')
        partner = payload['partner_id'] if 'partner_id' in payload else (record.partner_id.id if record else False)
        if status == 'reserved' and not partner:
            raise UserError('预分配要先选定客户。')
        if edge_label(str(network), str(host)) and status in ('allocated', 'reserved'):
            raise UserError('网络位和广播位不能分配。')
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
        flows = self.env['zenlenet.flow'].search([
            ('state', '=', 'allocate'), ('move', '=', 'out'),
        ], order='id desc', limit=50)
        return [{
            'id': flow.id, 'name': flow.name, 'partner_id': flow.partner_id.id, 'partner': flow.partner_id.name or '',
            'datacenter': flow.datacenter_id.name or '', 'pending': flow.pending_count,
            'order': flow.order_id.name or '',
        } for flow in flows]

    def ipam_bulk_assign(self, ips, partner_id=None, flow_id=None, usage=''):
        """Hang the selected hosts on an open 开通 ticket. The ticket marks them allocated."""
        self.ensure_one()
        flow = self.env['zenlenet.flow'].browse(flow_id).exists() if flow_id else self.env['zenlenet.flow']
        if not flow or flow.move != 'out' or flow.state != 'allocate':
            raise UserError('分配给客户要挂在一张处于「分配资源」的开通工单上。没有的话先开一张。')
        if not ips:
            raise UserError('请先选地址。')
        self._reject_edge_allocation(ips)
        Address = self.env['zenlenet.address']
        Resource = self.env['zenlenet.flow.resource']
        have = set(flow.resource_ids.mapped('address_id').ids)
        count = 0
        for ip in ips:
            existing = Address.search([('address', '=like', f'{ip}/%')], limit=1)
            if not existing:
                existing = Address.with_context(zenlenet_flow_apply=True).create({
                    'address': f'{ip}/32',
                    'prefix_id': self.id,
                    'block': self.prefix,
                    'datacenter_id': self.datacenter_id.id,
                    'status': 'free',
                })
            if existing.id in have:
                continue
            Resource.create({
                'flow_id': flow.id,
                'service_type': 'ip_single',
                'address_id': existing.id,
                'spec': usage or f'{ip} 由地址管理分配',
            })
            count += 1
        return {'count': count, 'flow': flow.name}

    def ipam_bulk_reserve(self, ips, partner_id):
        """Hold the selected hosts for a customer. No delivery ticket."""
        self.ensure_one()
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner or not partner.is_company:
            raise UserError('请选择要预分配的客户。')
        if not ips:
            raise UserError('请先选地址。')
        self._reject_edge_allocation(ips)
        Address = self.env['zenlenet.address']
        Resource = self.env['zenlenet.flow.resource']
        for ip in ips:
            existing = Address.search([('address', '=like', f'{ip}/%')], limit=1)
            if existing and existing.status in ('allocated', 'testing', 'returning', 'transferring'):
                who = existing.partner_id.name or '未填客户'
                raise UserError(f'{ip} 已经分给 {who}，不能改成预分配。要改的话先释放。')
            if existing and Resource.search_count([
                ('address_id', '=', existing.id),
                ('flow_id.state', 'not in', ('cancel', 'done')),
            ]):
                raise UserError(f'{ip} 还挂在交付工单上，不能改成预分配。')
            values = {'status': 'reserved', 'partner_id': partner.id}
            if not existing or not existing.usage:
                values['usage'] = '预分配'
            self.ipam_set_address(ip, values)
        return {'count': len(ips), 'partner': partner.name}

    def ipam_bulk_status(self, ips, status):
        self.ensure_one()
        if status not in STATUS_LABELS:
            raise UserError('状态不对。')
        if status == 'reserved':
            raise UserError('预分配要指定客户。')
        if status in ('allocated', 'testing', 'returning', 'transferring'):
            raise UserError('分配、测试、出库和调库要走资源工单。')
        Address = self.env['zenlenet.address']
        for ip in ips:
            existing = Address.search([('address', '=like', f'{ip}/%')], limit=1)
            if status == 'free' and existing and existing.status in ('allocated', 'testing', 'returning', 'transferring'):
                raise UserError(f'{ip} 已在用，退回请开「退：退回」工单。')
            values = {'status': status}
            if status in ('free', 'internal'):
                values['partner_id'] = False
            self.ipam_set_address(ip, values)
        return True

    def ipam_open_ticket(self, ips, move):
        """Start a resource ticket for the selected hosts and open it here."""
        self.ensure_one()
        if move not in ('out', 'in', 'back', 'cutover'):
            raise UserError('工单类型不对。')
        if not ips:
            raise UserError('请先选地址。')
        if move == 'out':
            self._reject_edge_allocation(ips)
        Address = self.env['zenlenet.address']
        addresses = Address
        for ip in ips:
            found = Address.search([('address', '=like', f'{ip}/%')], limit=1)
            if not found:
                raise UserError(f'{ip} 还没登记，不能开工单。')
            addresses |= found
        partners = addresses.mapped('partner_id')
        flow = self.env['zenlenet.flow'].create({
            'move': move,
            'kind': 'business',
            'partner_id': partners.id if len(partners) == 1 and move in ('out', 'back', 'cutover') else False,
            'datacenter_id': self.datacenter_id.id,
            'return_to': 'stock' if move == 'back' else False,
        })
        Resource = self.env['zenlenet.flow.resource']
        for address in addresses:
            values = {'flow_id': flow.id, 'service_type': 'ip_single', 'spec': address.address}
            if move == 'cutover':
                values['from_address_id'] = address.id
            else:
                values['address_id'] = address.id
            Resource.create(values)
        return {
            'type': 'ir.actions.act_window',
            'name': flow.name,
            'res_model': 'zenlenet.flow',
            'res_id': flow.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def ipam_open_prefix_ticket(self, move):
        self.ensure_one()
        return self._open_move(move)

    def ipam_assign(self, partner_id):
        self.ensure_one()
        return self._open_move('out' if partner_id else 'back')

    @api.model
    def ipam_customers(self, search=''):
        return self.env['res.partner'].search_read(
            [('is_company', '=', True), ('customer_rank', '>', 0), ('name', 'ilike', search or '')],
            ['name'], limit=20, order='name',
        )

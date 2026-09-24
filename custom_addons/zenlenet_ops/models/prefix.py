import ipaddress

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.blocks import parse_prefix

PREFIX_STATUSES = [
    ('container', '容器'),
    ('active', '在用'),
    ('reserved', '预留'),
    ('deprecated', '已弃用'),
]


class ZenlenetPrefix(models.Model):
    """An IP prefix, mirroring NetBox's ipam.Prefix. Addresses inside it are the console's IP rows."""

    _name = 'zenlenet.prefix'
    _description = '地址段'
    _inherit = ['zenlenet.deletable']
    _order = 'prefix'
    _rec_name = 'prefix'
    _rec_names_search = ['prefix', 'description', 'role']

    netbox_id = fields.Integer(string='NetBox ID', index=True, copy=False)
    netbox_synced = fields.Datetime(string='上次同步')
    netbox_pending = fields.Boolean(string='待写回 NetBox', default=False, index=True)
    prefix = fields.Char(string='地址段', required=True, index=True)
    family = fields.Selection([('4', 'IPv4'), ('6', 'IPv6')], string='协议', compute='_compute_size', store=True)
    status = fields.Selection(PREFIX_STATUSES, string='状态', default='active', required=True, index=True)
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='数据中心', index=True, ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='客户', index=True, domain=[('is_company', '=', True)])
    supplier_ids = fields.Many2many(
        'res.partner', 'zenlenet_prefix_supplier_rel', 'prefix_id', 'supplier_id',
        string='供应商', domain=[('supplier_rank', '>', 0)],
    )
    role = fields.Char(string='用途角色')
    vlan = fields.Char(string='VLAN')
    description = fields.Char(string='说明')
    is_pool = fields.Boolean(string='地址池')
    region = fields.Char(string='地区', index=True, compute='_compute_inherited', store=True, readonly=False, recursive=True)
    asn = fields.Integer(string='AS 号', index=True, compute='_compute_inherited', store=True, readonly=False, recursive=True)
    asn_display = fields.Char(string='AS', compute='_compute_asn_display')
    top_id = fields.Many2one('zenlenet.prefix', string='IP 段（顶级）', compute='_compute_top', store=True, index=True, recursive=True)
    parent_id = fields.Many2one('zenlenet.prefix', string='上级网段', compute='_compute_parent', store=True, index=True)
    child_ids = fields.One2many('zenlenet.prefix', 'parent_id', string='下级网段')
    child_count = fields.Integer(compute='_compute_children')
    netmask = fields.Char(string='掩码', compute='_compute_size', store=True)
    first_ip = fields.Char(string='起始 IP', compute='_compute_size', store=True)
    last_ip = fields.Char(string='结束 IP', compute='_compute_size', store=True)
    prefixlen = fields.Integer(string='前缀长度', compute='_compute_size', store=True)
    size = fields.Integer(string='可用地址数', compute='_compute_size', store=True)
    size_display = fields.Char(string='容量', compute='_compute_size', store=True)
    address_ids = fields.One2many('zenlenet.address', 'prefix_id', string='地址')
    allocation_ids = fields.One2many('zenlenet.flow.resource', 'prefix_id', string='交付记录')
    address_count = fields.Integer(string='已登记', compute='_compute_usage')
    allocated_count = fields.Integer(string='已分配', compute='_compute_usage')
    free_count = fields.Integer(string='未分配', compute='_compute_usage')
    utilization = fields.Float(string='使用率', compute='_compute_usage')

    _prefix_unique = models.Constraint('unique(prefix)', '这个地址段已经存在。')

    def _delete_snapshot(self):
        used = self.env['zenlenet.address'].search_count([('prefix_id', '=', self.id), ('status', '!=', 'free')])
        return {
            'status': self.status,
            'child_count': len(self.child_ids),
            'used_addresses': used,
            'partner': bool(self.partner_id),
        }

    def unlink(self):
        remote = self.filtered('netbox_id').mapped('netbox_id')
        result = super().unlink()
        self.env['zenlenet.netbox'].delete_remote('/ipam/prefixes/', remote)
        return result

    @api.depends('prefix', 'is_pool')
    def _compute_size(self):
        for record in self:
            try:
                network = ipaddress.ip_network(parse_prefix(record.prefix or ''), strict=False)
            except ValueError:
                record.size = 0
                record.size_display = ''
                record.family = False
                record.netmask = record.first_ip = record.last_ip = ''
                record.prefixlen = 0
                continue
            record.family = str(network.version)
            record.prefixlen = network.prefixlen
            record.netmask = str(network.netmask) if network.version == 4 else f'/{network.prefixlen}'
            record.first_ip = str(network.network_address)
            record.last_ip = str(network.broadcast_address)
            usable = network.num_addresses
            if network.version == 4 and network.prefixlen < 31 and not record.is_pool:
                usable = max(usable - 2, 0)
            record.size = min(usable, 2_147_483_647)
            record.size_display = f'2^{network.max_prefixlen - network.prefixlen}' if network.version == 6 else f'{usable:,}'

    @api.depends('parent_id', 'parent_id.region', 'parent_id.asn', 'datacenter_id', 'datacenter_id.region', 'datacenter_id.asn')
    def _compute_inherited(self):
        for record in self:
            if not record.region:
                record.region = record.parent_id.region or record.datacenter_id.region or record.datacenter_id.city or record.datacenter_id.name or False
            if not record.asn:
                record.asn = record.parent_id.asn or record.datacenter_id.asn or 0

    @api.depends('asn')
    def _compute_asn_display(self):
        for record in self:
            record.asn_display = f'AS{record.asn}' if record.asn else ''

    @api.depends('parent_id', 'parent_id.top_id')
    def _compute_top(self):
        for record in self:
            node = record
            seen = set()
            while node.parent_id and node.id not in seen:
                seen.add(node.id)
                node = node.parent_id
            record.top_id = node if node != record else False

    @api.depends('prefix')
    def _compute_parent(self):
        for record in self:
            record.parent_id = record._find_parent()

    def _find_parent(self):
        self.ensure_one()
        try:
            network = ipaddress.ip_network(parse_prefix(self.prefix or ''), strict=False)
        except ValueError:
            return False
        best = False
        for candidate in self.search([('family', '=', str(network.version)), ('prefixlen', '<', network.prefixlen), ('id', '!=', self.id)]):
            try:
                other = ipaddress.ip_network(candidate.prefix, strict=False)
            except ValueError:
                continue
            if network.subnet_of(other) and (not best or other.prefixlen > best[0]):
                best = (other.prefixlen, candidate)
        return best[1] if best else False

    def _compute_children(self):
        counts = {
            parent.id: count
            for parent, count in self._read_group([('parent_id', 'in', self.ids)], ['parent_id'], ['__count'])
        } if self.ids else {}
        for record in self:
            record.child_count = counts.get(record.id, 0)

    @api.model
    def relink_hierarchy(self):
        for record in self.sudo().search([]):
            parent = record._find_parent()
            if record.parent_id != parent:
                record.parent_id = parent

    def action_add_child(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'在 {self.prefix} 下新增网段',
            'res_model': 'zenlenet.prefix.add',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_parent_id': self.id, 'default_datacenter_id': self.datacenter_id.id,
                        'default_net_attr': False},
        }

    def action_open_ipam(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'zenlenet_ipam',
            'name': '地址管理',
            'context': {'ipam_prefix_id': self.id},
        }

    def action_open_children(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_prefixes').read()[0]
        action['domain'] = [('parent_id', '=', self.id)]
        action['context'] = {'default_parent_id': self.id, 'default_datacenter_id': self.datacenter_id.id}
        action['display_name'] = f'{self.prefix} · 下级网段'
        return action

    def _compute_usage(self):
        Address = self.env['zenlenet.address']
        if not self.ids:
            for record in self:
                record.address_count = record.allocated_count = record.free_count = 0
                record.utilization = 0.0
            return
        totals = {
            prefix.id: count
            for prefix, count in Address._read_group([('prefix_id', 'in', self.ids)], ['prefix_id'], ['__count'])
        }
        allocated = {
            prefix.id: count
            for prefix, count in Address._read_group(
                [('prefix_id', 'in', self.ids), ('status', 'in', ('allocated', 'testing', 'internal'))],
                ['prefix_id'], ['__count'],
            )
        }
        free = {
            prefix.id: count
            for prefix, count in Address._read_group(
                [('prefix_id', 'in', self.ids), ('status', '=', 'free')], ['prefix_id'], ['__count'],
            )
        }
        for record in self:
            record.address_count = totals.get(record.id, 0)
            record.allocated_count = allocated.get(record.id, 0)
            record.free_count = free.get(record.id, 0)
            base = record.size or record.address_count
            record.utilization = round(record.allocated_count * 100.0 / base, 1) if base else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        cleaned = []
        for vals in vals_list:
            vals = dict(vals)
            if vals.get('prefix'):
                try:
                    vals['prefix'] = parse_prefix(vals['prefix'])
                except ValueError as error:
                    raise UserError('网段格式不对。') from error
            cleaned.append(vals)
        return super().create(cleaned)

    @api.model
    def zenlenet_link_suppliers(self):
        """Hang each block on the suppliers already written on the addresses inside it."""
        rows = self.env['zenlenet.address'].sudo()._read_group(
            [('supplier_id', '!=', False), ('prefix_id', '!=', False)],
            ['prefix_id', 'supplier_id'],
            ['__count'],
        )
        wanted = {}
        for prefix, supplier, _count in rows:
            if prefix and supplier:
                wanted.setdefault(prefix.id, set()).add(supplier.id)
        for prefix in self.sudo().browse(list(wanted)):
            missing = wanted[prefix.id] - set(prefix.supplier_ids.ids)
            if missing:
                prefix.with_context(netbox_skip_push=True).write({
                    'supplier_ids': [(4, supplier_id) for supplier_id in missing],
                })

    def write(self, vals):
        if (
            'partner_id' in vals
            and not any(self.env.context.get(key) for key in ('zenlenet_flow_apply', 'netbox_skip_push', 'zenlenet_import'))
        ):
            for record in self:
                if (vals.get('partner_id') or False) != (record.partner_id.id or False):
                    raise UserError(f'{record.prefix} 整段分给客户或收回，要走资源工单。')
        if not self.env.context.get('netbox_skip_push') and {'partner_id', 'status', 'description'} & set(vals):
            vals = dict(vals, netbox_pending=True)
        return super().write(vals)

    def _open_move(self, move):
        self.ensure_one()
        flow = self.env['zenlenet.flow'].create({
            'move': move,
            'kind': 'business',
            'partner_id': self.partner_id.id if move in ('out', 'back', 'cutover') else False,
            'datacenter_id': self.datacenter_id.id,
            'return_to': 'stock',
        })
        values = {'flow_id': flow.id, 'service_type': 'ip', 'spec': self.prefix}
        if move == 'cutover':
            values['from_prefix_id'] = self.id
        else:
            values['prefix_id'] = self.id
        self.env['zenlenet.flow.resource'].create(values)
        return {
            'type': 'ir.actions.act_window',
            'name': flow.name,
            'res_model': 'zenlenet.flow',
            'res_id': flow.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_allocate(self):
        self.ensure_one()
        return self._open_move('out')

    def action_release(self):
        self.ensure_one()
        return self._open_move('back')

    def action_open_addresses(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_addresses').read()[0]
        action['domain'] = [('prefix_id', '=', self.id)]
        action['context'] = {'default_prefix_id': self.id, 'default_block': self.prefix,
                             'default_datacenter_id': self.datacenter_id.id}
        action['display_name'] = f'{self.prefix} · 地址'
        return action

    def action_open_netbox(self):
        self.ensure_one()
        link = self.env['zenlenet.netbox'].public_link(f'/ipam/prefixes/{self.netbox_id}/')
        if not (self.netbox_id and link):
            return False
        return {'type': 'ir.actions.act_url', 'url': link, 'target': 'new'}

    @api.model
    def link_addresses(self):
        """Attach addresses to their prefix by matching the block string; create prefixes for unknown blocks."""
        Address = self.env['zenlenet.address'].sudo()
        known = {record.prefix: record for record in self.sudo().search([])}
        for block, in Address._read_group([('prefix_id', '=', False), ('block', '!=', False)], ['block']):
            if not block:
                continue
            prefix = known.get(block)
            if not prefix:
                sample = Address.search([('block', '=', block)], limit=1)
                prefix = self.sudo().create({
                    'prefix': block,
                    'datacenter_id': sample.datacenter_id.id,
                    'partner_id': sample.partner_id.id if Address.search_count([('block', '=', block), ('partner_id', '!=', sample.partner_id.id)]) == 0 else False,
                })
                known[block] = prefix
            Address.search([('prefix_id', '=', False), ('block', '=', block)]).write({'prefix_id': prefix.id})

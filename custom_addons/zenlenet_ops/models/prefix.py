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
    _order = 'prefix'
    _rec_name = 'prefix'
    _rec_names_search = ['prefix', 'description', 'role']

    netbox_id = fields.Integer(string='NetBox ID', index=True, copy=False)
    netbox_synced = fields.Datetime(string='上次同步')
    prefix = fields.Char(string='地址段', required=True, index=True)
    family = fields.Selection([('4', 'IPv4'), ('6', 'IPv6')], string='协议', compute='_compute_size', store=True)
    status = fields.Selection(PREFIX_STATUSES, string='状态', default='active', required=True, index=True)
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='数据中心', index=True, ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='客户', index=True, domain=[('is_company', '=', True)])
    role = fields.Char(string='用途角色')
    vlan = fields.Char(string='VLAN')
    description = fields.Char(string='说明')
    is_pool = fields.Boolean(string='地址池', help='整段作为地址池分配，网络地址和广播地址也可用。')
    parent_id = fields.Many2one('zenlenet.prefix', string='上级网段', compute='_compute_parent', store=True, index=True)
    child_ids = fields.One2many('zenlenet.prefix', 'parent_id', string='下级网段')
    child_count = fields.Integer(compute='_compute_children')
    netmask = fields.Char(string='掩码', compute='_compute_size', store=True)
    first_ip = fields.Char(string='起始 IP', compute='_compute_size', store=True)
    last_ip = fields.Char(string='结束 IP', compute='_compute_size', store=True)
    prefixlen = fields.Integer(string='前缀长度', compute='_compute_size', store=True)
    size = fields.Integer(string='可用地址数', compute='_compute_size', store=True, help='IPv6 段按 2^31 上限记录，实际容量见协议列。')
    size_display = fields.Char(string='容量', compute='_compute_size', store=True)
    address_ids = fields.One2many('zenlenet.address', 'prefix_id', string='地址')
    address_count = fields.Integer(string='已登记', compute='_compute_usage')
    allocated_count = fields.Integer(string='已分配', compute='_compute_usage')
    free_count = fields.Integer(string='未分配', compute='_compute_usage')
    utilization = fields.Float(string='使用率', compute='_compute_usage')

    _prefix_unique = models.Constraint('unique(prefix)', '这个地址段已经存在。')

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

    def action_split(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'切割 {self.prefix}',
            'res_model': 'zenlenet.prefix.split',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_prefix_id': self.id, 'default_new_prefixlen': min((self.prefixlen or 0) + 1, 32 if self.family == '4' else 64)},
        }

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

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('netbox_skip_push') and {'partner_id', 'status', 'description'} & set(vals):
            try:
                self.env['zenlenet.netbox'].push_prefixes(self)
            except Exception as error:  # noqa: BLE001 - never block an operator on the mirror
                import logging
                logging.getLogger(__name__).warning('NetBox prefix push skipped: %s', type(error).__name__)
        return result

    def action_allocate(self):
        """Mark the whole block and every address in it as allocated to the block's customer."""
        for record in self:
            if not record.partner_id:
                raise UserError('请先选择客户，再整段分配。')
            record.address_ids.write({'status': 'allocated', 'partner_id': record.partner_id.id})
            record.status = 'active'

    def action_release(self):
        for record in self:
            record.address_ids.write({'status': 'free', 'partner_id': False})
            record.write({'partner_id': False, 'status': 'active'})

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


class ZenlenetPrefixSplit(models.TransientModel):
    _name = 'zenlenet.prefix.split'
    _description = '切割网段'

    prefix_id = fields.Many2one('zenlenet.prefix', required=True)
    current = fields.Char(related='prefix_id.prefix', string='当前网段')
    new_prefixlen = fields.Integer(string='切成 /', required=True)
    count = fields.Integer(string='将生成', compute='_compute_count')
    keep_remaining = fields.Boolean(string='只切前面几段', help='勾上后只按下面的数量生成，剩下的保留在原网段里。')
    limit = fields.Integer(string='生成数量', default=4)

    @api.depends('new_prefixlen', 'prefix_id')
    def _compute_count(self):
        for wizard in self:
            current = wizard.prefix_id.prefixlen or 0
            wizard.count = 2 ** (wizard.new_prefixlen - current) if wizard.new_prefixlen > current else 0

    def action_split(self):
        self.ensure_one()
        parent = self.prefix_id
        try:
            network = ipaddress.ip_network(parse_prefix(parent.prefix), strict=False)
        except ValueError as error:
            raise UserError('网段格式不对。') from error
        if self.new_prefixlen <= network.prefixlen:
            raise UserError('新前缀长度要比当前的大，例如 /22 切成 /24。')
        if self.new_prefixlen - network.prefixlen > 8 and not self.keep_remaining:
            raise UserError('一次最多切 256 段（前缀长度相差不超过 8），或勾选「只切前面几段」。')
        Prefix = self.env['zenlenet.prefix']
        existing = set(Prefix.search([('family', '=', parent.family)]).mapped('prefix'))
        created = Prefix
        for index, subnet in enumerate(network.subnets(new_prefix=self.new_prefixlen)):
            if self.keep_remaining and index >= max(self.limit, 1):
                break
            cidr = str(subnet)
            if cidr in existing:
                continue
            created |= Prefix.create({
                'prefix': cidr,
                'datacenter_id': parent.datacenter_id.id,
                'status': 'active',
                'role': parent.role,
                'vlan': parent.vlan,
                'description': f'由 {parent.prefix} 切出',
            })
        if parent.status != 'container':
            parent.status = 'container'
        try:
            self.env['zenlenet.netbox'].create_prefixes(created)
        except Exception as error:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning('NetBox prefix create skipped: %s', type(error).__name__)
        return parent.action_open_children()

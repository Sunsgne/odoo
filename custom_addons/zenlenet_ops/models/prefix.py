import ipaddress

from odoo import api, fields, models

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
    size = fields.Integer(string='地址总数', compute='_compute_size', store=True)
    address_ids = fields.One2many('zenlenet.address', 'prefix_id', string='地址')
    address_count = fields.Integer(string='已登记', compute='_compute_usage')
    allocated_count = fields.Integer(string='已分配', compute='_compute_usage')
    free_count = fields.Integer(string='未分配', compute='_compute_usage')
    utilization = fields.Float(string='使用率', compute='_compute_usage')

    _prefix_unique = models.Constraint('unique(prefix)', '这个地址段已经存在。')

    @api.depends('prefix')
    def _compute_size(self):
        for record in self:
            try:
                network = ipaddress.ip_network(parse_prefix(record.prefix or ''), strict=False)
            except ValueError:
                record.size = 0
                record.family = False
                continue
            record.family = str(network.version)
            usable = network.num_addresses
            if network.version == 4 and network.prefixlen < 31 and not record.is_pool:
                usable = max(usable - 2, 0)
            record.size = usable

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

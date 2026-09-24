import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.resource_bindings import binding_text, mbps_of, site_line_domain, split_end

from .records import DC_TYPES

LINE_PUSH_FIELDS = {
    'kind', 'region', 'commit_rate', 'bandwidth', 'datacenter_id',
    'a_site_id', 'z_site_id', 'a_device_id', 'z_device_id', 'a_port', 'z_port', 'a_vlan', 'z_vlan',
}

_logger = logging.getLogger(__name__)

LINE_STATUSES = [
    ('planned', '规划中'),
    ('provisioning', '开通中'),
    ('active', '在用'),
    ('offline', '离线'),
    ('deprovisioning', '拆除中'),
    ('decommissioned', '已终止'),
]


class ZenlenetDatacenter(models.Model):
    _name = 'zenlenet.datacenter'
    _description = '数据中心'
    _inherit = ['zenlenet.deletable']
    _order = 'sequence, name'

    name = fields.Char(string='名称', required=True, index=True)
    code = fields.Char(string='简称 / Slug')
    netbox_id = fields.Integer(string='NetBox ID', index=True, copy=False)
    netbox_synced = fields.Datetime(string='上次同步')
    facility = fields.Char(string='机房设施', help='运营商机房的正式名称或楼栋编号，对应 NetBox 的 Facility。')
    region = fields.Char(string='地区', index=True, help='香港 / 新加坡 / 东京 / 洛杉矶……这个机房下的网段默认归到这个地区。')
    asn = fields.Integer(string='AS 号', help='这个机房默认宣告的 AS，新增网段时带入。')
    supplier_id = fields.Many2one('res.partner', string='机房供应商', domain=[('supplier_rank', '>', 0)], index=True)
    prefix_ids = fields.One2many('zenlenet.prefix', 'datacenter_id', string='地址段')
    prefix_count = fields.Integer(string='地址段数', compute='_compute_counts')
    sequence = fields.Integer(default=10)
    kind = fields.Selection(DC_TYPES, string='类型', default='主营机房', index=True)
    city = fields.Char(string='城市')
    country_id = fields.Many2one('res.country', string='国家')
    address = fields.Char(string='地址')
    supplier = fields.Char(string='供应商')
    contact = fields.Char(string='机房联系人')
    phone = fields.Char(string='联系电话')
    state = fields.Selection([
        ('active', '在用'),
        ('planning', '规划中'),
        ('closed', '已退租'),
    ], string='状态', default='active', required=True, index=True)
    note = fields.Text(string='备注')
    address_ids = fields.One2many('zenlenet.address', 'datacenter_id', string='IP资源')
    line_ids = fields.One2many('zenlenet.line', 'datacenter_id', string='线路')
    site_line_ids = fields.Many2many('zenlenet.line', compute='_compute_site_lines', string='线路')
    device_ids = fields.One2many('zenlenet.device', 'datacenter_id', string='物理机')
    vm_ids = fields.One2many('zenlenet.vm', 'datacenter_id', string='云主机')
    asset_ids = fields.One2many('zenlenet.asset', 'datacenter_id', string='固定资产')
    address_count = fields.Integer(string='地址数', compute='_compute_counts')
    allocated_count = fields.Integer(string='已分配', compute='_compute_counts')
    free_count = fields.Integer(string='未分配', compute='_compute_counts')
    line_count = fields.Integer(string='线路数', compute='_compute_counts')
    asset_count = fields.Integer(string='设备数', compute='_compute_counts')
    usage_percent = fields.Float(string='使用率', compute='_compute_counts')

    _name_unique = models.Constraint('unique(name)', '这个数据中心已经存在。')

    def _delete_snapshot(self):
        counts = {}
        for key, model in (('prefix_count', 'zenlenet.prefix'), ('address_count', 'zenlenet.address'),
                           ('line_count', 'zenlenet.line'), ('asset_count', 'zenlenet.asset')):
            counts[key] = self.env[model].search_count([('datacenter_id', '=', self.id)])
        return counts

    @api.depends('region')
    def _compute_site_lines(self):
        Line = self.env['zenlenet.line']
        for record in self:
            record.site_line_ids = Line.search(site_line_domain(record.id, record.region))

    def _grouped(self, model, domain):
        return {
            record.id: count
            for record, count in self.env[model]._read_group(
                [('datacenter_id', 'in', self.ids)] + domain, ['datacenter_id'], ['__count'],
            )
        }

    @api.depends('address_ids.status', 'line_ids.stopped', 'asset_ids', 'prefix_ids')
    def _compute_counts(self):
        totals = self._grouped('zenlenet.address', [])
        allocated = self._grouped('zenlenet.address', [('status', 'in', ('allocated', 'testing', 'internal'))])
        free = self._grouped('zenlenet.address', [('status', '=', 'free')])
        lines = self._grouped('zenlenet.line', [('stopped', '=', False)])
        assets = self._grouped('zenlenet.asset', [])
        prefixes = self._grouped('zenlenet.prefix', [])
        for record in self:
            total = totals.get(record.id, 0)
            used = allocated.get(record.id, 0)
            record.address_count = total
            record.allocated_count = used
            record.free_count = free.get(record.id, 0)
            record.line_count = lines.get(record.id, 0)
            record.asset_count = assets.get(record.id, 0)
            record.prefix_count = prefixes.get(record.id, 0)
            record.usage_percent = round(used * 100.0 / total, 1) if total else 0.0

    def dc_tree(self, search=''):
        """Sites grouped the way NetBox groups them: region, then site."""
        domain = []
        if search:
            domain = ['|', '|', '|', ('name', 'ilike', search), ('region', 'ilike', search),
                      ('city', 'ilike', search), ('facility', 'ilike', search)]
        sites = self.search(domain, order='region, sequence, name')
        Prefix = self.env['zenlenet.prefix']
        Line = self.env['zenlenet.line']
        sellable_prefix = {
            record.id: count
            for record, count in Prefix._read_group(
                [('datacenter_id', 'in', sites.ids), ('status', 'in', ('active', 'reserved')),
                 ('partner_id', '=', False), ('child_ids', '=', False)],
                ['datacenter_id'], ['__count'],
            )
        }
        sellable_line = {
            record.id: count
            for record, count in Line._read_group(
                [('datacenter_id', 'in', sites.ids), ('partner_id', '=', False),
                 ('status', 'in', ('planned', 'provisioning', 'active'))],
                ['datacenter_id'], ['__count'],
            )
        }
        Vm = self.env['zenlenet.vm']
        sellable_vm = {
            record.id: count
            for record, count in Vm._read_group(
                [('datacenter_id', 'in', sites.ids), ('partner_id', '=', False), ('status', '=', 'active')],
                ['datacenter_id'], ['__count'],
            )
        }
        return [{
            'id': site.id,
            'name': site.name,
            'region': site.region or site.city or '未分地区',
            'state': site.state,
            'facility': site.facility or '',
            'sellable_prefixes': sellable_prefix.get(site.id, 0),
            'sellable_lines': sellable_line.get(site.id, 0),
            'sellable_vms': sellable_vm.get(site.id, 0),
        } for site in sites]

    def dc_site(self):
        """One site, the way a salesperson reads a NetBox site: what can still be sold here."""
        self.ensure_one()
        prefix_rows = self.prefix_ids.read([
            'prefix', 'status', 'partner_id', 'size_display', 'allocated_count', 'free_count',
            'utilization', 'description', 'parent_id', 'prefixlen',
        ])
        parents = {row['parent_id'][0] for row in prefix_rows if row['parent_id']}
        prefixes = []
        for row in prefix_rows:
            partner = row['partner_id'][1] if row['partner_id'] else ''
            sellable = not partner and row['status'] in ('active', 'reserved') and row['id'] not in parents
            prefixes.append({
                'id': row['id'],
                'prefix': row['prefix'],
                'status': row['status'],
                'partner': partner,
                'size': row['size_display'] or '',
                'used': row['allocated_count'] or 0,
                'free': row['free_count'] or 0,
                'utilization': row['utilization'] or 0,
                'description': row['description'] or '',
                'parent_id': row['parent_id'][0] if row['parent_id'] else False,
                'parent': row['parent_id'][1] if row['parent_id'] else '',
                'prefixlen': row['prefixlen'] or 0,
                'sellable': sellable,
            })
        domain = site_line_domain(self.id, self.region)
        lines = self._line_rows(self.env['zenlenet.line'].search(domain, order='kind, name'))
        device_status = dict(self.env['zenlenet.device']._fields['status'].selection)
        devices = [{
            'id': device.id,
            'name': device.name,
            'role': device.role or '',
            'status': device.status,
            'status_label': device_status.get(device.status, ''),
            'vms': len(device.vm_ids),
        } for device in self.env['zenlenet.device'].search([('datacenter_id', '=', self.id)], order='name')]
        vm_status = dict(self.env['zenlenet.vm']._fields['status'].selection)
        vms = []
        for vm in self.env['zenlenet.vm'].search([('datacenter_id', '=', self.id)], order='name'):
            partner = vm.partner_id.name or ''
            vms.append({
                'id': vm.id,
                'name': vm.name,
                'device': vm.device_id.name or '',
                'device_id': vm.device_id.id or False,
                'ip': vm.address_id.address or vm.ip_text or '',
                'bandwidth': f'{vm.bandwidth_mbps}M' if vm.bandwidth_mbps else '',
                'partner': partner,
                'status': vm.status,
                'status_label': vm_status.get(vm.status, ''),
                'sellable': not partner and vm.status == 'active',
            })
        return {
            'id': self.id,
            'name': self.name,
            'state': self.state,
            'state_label': dict(self._fields['state'].selection).get(self.state, ''),
            'region': self.region or self.city or '',
            'region_name': self.region or '',
            'facility': self.facility or '',
            'asn': self.asn or 0,
            'city': self.city or '',
            'address': self.address or '',
            'supplier': self.supplier_id.name or self.supplier or '',
            'contact': self.contact or '',
            'phone': self.phone or '',
            'note': self.note or '',
            'netbox_url': (
                self.env['zenlenet.netbox'].public_link(f'/dcim/sites/{self.netbox_id}/') if self.netbox_id else ''
            ),
            'can_write': self.has_access('write'),
            'prefixes': prefixes,
            'lines': lines,
            'devices': devices,
            'vms': vms,
            'sellable_prefixes': sum(1 for row in prefixes if row['sellable']),
            'sellable_lines': sum(1 for row in lines if row['sellable']),
            'sellable_vms': sum(1 for row in vms if row['sellable']),
            'loose': False,
        }

    def _line_rows(self, lines):
        kind_label = dict(self.env['zenlenet.line']._fields['kind'].selection)
        status_label = dict(LINE_STATUSES)
        rows = []
        for line in lines:
            partner = line.partner_id.name or ''
            rate = mbps_of(line.bandwidth, line.commit_rate)
            rows.append({
                'id': line.id,
                'name': line.name,
                'kind': line.kind,
                'kind_label': kind_label.get(line.kind, line.kind or ''),
                'status': line.status,
                'status_label': status_label.get(line.status, ''),
                'partner': partner,
                'bandwidth': f'{rate}M' if rate else (line.bandwidth or ''),
                'region': line.region or '',
                'a_end': binding_text(line.a_site_id.name, line.a_device_id.name, line.a_port, line.a_vlan) or line.a_end or '',
                'z_end': binding_text(line.z_site_id.name, line.z_device_id.name, line.z_port, line.z_vlan) or line.z_end or '',
                'a_site': line.a_site_id.name or '',
                'z_site': line.z_site_id.name or '',
                'a_device': line.a_device_id.name or '',
                'z_device': line.z_device_id.name or '',
                'a_port': line.a_port or '',
                'z_port': line.z_port or '',
                'a_vlan': line.a_vlan or '',
                'z_vlan': line.z_vlan or '',
                'supplier': line.supplier_id.name or '',
                'purpose': line.purpose or '',
                'sellable': not partner and line.status in ('planned', 'provisioning', 'active'),
            })
        return rows

    @api.model
    def _loose_domain(self):
        return [
            ('datacenter_id', '=', False),
            ('a_site_id', '=', False),
            ('z_site_id', '=', False),
        ]

    @api.model
    def dc_loose_count(self):
        return self.env['zenlenet.line'].search_count(self._loose_domain())

    @api.model
    def dc_loose(self):
        """Lines whose imported place name did not match a site. Still editable here."""
        lines = self._line_rows(self.env['zenlenet.line'].search(self._loose_domain(), order='kind, name'))
        return {
            'id': 0,
            'name': '未挂机房',
            'state': 'planning',
            'state_label': '待归位',
            'region': '',
            'region_name': '',
            'facility': '',
            'asn': 0,
            'city': '',
            'address': '',
            'supplier': '',
            'contact': '',
            'phone': '',
            'note': '这些线路的机房名对不上现有机房。点开后补上 A/Z 端机房，设备和端口可以后补。',
            'netbox_url': '',
            'can_write': self.env['zenlenet.line'].has_access('write'),
            'prefixes': [],
            'lines': lines,
            'devices': [],
            'vms': [],
            'sellable_prefixes': 0,
            'sellable_lines': sum(1 for row in lines if row['sellable']),
            'sellable_vms': 0,
            'loose': True,
        }

    def dc_open_ticket(self, move='in'):
        """Open an inbound, return or cutover ticket for this site, on the same page."""
        self.ensure_one()
        if move not in ('in', 'back', 'cutover', 'out'):
            raise UserError('工单类型不对。')
        flow = self.env['zenlenet.flow'].create({
            'move': move,
            'kind': 'business',
            'datacenter_id': self.id,
            'place': self.name,
            'supplier_id': self.supplier_id.id if move == 'in' else False,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': flow.name,
            'res_model': 'zenlenet.flow',
            'res_id': flow.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('netbox_skip_push') and {'name', 'state', 'address', 'facility', 'note'} & set(vals):
            for record in self:
                try:
                    self.env['zenlenet.netbox'].push_site(record)
                except Exception as error:
                    _logger.warning('NetBox site push skipped for %s: %s', record.name, type(error).__name__)
        return result

    def action_open_netbox(self):
        self.ensure_one()
        link = self.env['zenlenet.netbox'].public_link(f'/dcim/sites/{self.netbox_id}/')
        if not (self.netbox_id and link):
            return False
        return {'type': 'ir.actions.act_url', 'url': link, 'target': 'new'}

    def action_open_prefixes(self):
        self.ensure_one()
        action = self.env.ref('zenlenet_ops.action_prefixes').read()[0]
        action['domain'] = [('datacenter_id', '=', self.id)]
        action['context'] = {'default_datacenter_id': self.id}
        action['display_name'] = f'{self.name} · 地址段'
        return action

    def _open(self, name, model, extra_domain=None, context=None):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} · {name}',
            'res_model': model,
            'view_mode': 'list,form',
            'domain': [('datacenter_id', '=', self.id)] + (extra_domain or []),
            'context': {'default_datacenter_id': self.id, **(context or {})},
        }

    def action_open_addresses(self):
        return self._open('IP资源', 'zenlenet.address')

    def action_open_lines(self):
        return self._open('线路', 'zenlenet.line')

    def action_open_assets(self):
        return self._open('固定资产', 'zenlenet.asset')

    def action_open_maintenance(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} · 割接维护',
            'res_model': 'zenlenet.maintenance',
            'view_mode': 'kanban,list,form',
            'domain': [('datacenter_id', '=', self.id)],
            'context': {'default_datacenter_id': self.id, 'default_place': self.name},
        }

    @api.model
    def ensure_from_names(self, names, kinds=None):
        """Create missing data centers for the given place names and return {name: record}."""
        kinds = kinds or {}
        wanted = {(name or '').strip() for name in names if (name or '').strip()}
        found = {record.name: record for record in self.search([('name', 'in', list(wanted))])}
        missing = sorted(wanted - set(found))
        if missing:
            created = self.create([
                {
                    'name': name,
                    'kind': kinds.get(name) or '主营机房',
                    'state': 'closed' if kinds.get(name) == '已退租' else 'active',
                }
                for name in missing
            ])
            found.update({record.name: record for record in created})
        return found

    @api.model
    def migrate_places(self):
        """Attach imported rows that only carry a place name to a data center record."""
        Address = self.env['zenlenet.address'].sudo()
        Line = self.env['zenlenet.line'].sudo()
        Asset = self.env['zenlenet.asset'].sudo()
        Maintenance = self.env['zenlenet.maintenance'].sudo()
        kinds = {}
        for pop, dc_type in Address._read_group(
            [('pop', '!=', False), ('dc_type', '!=', False)], groupby=['pop', 'dc_type'],
        ):
            kinds.setdefault(pop, dc_type)
        names = set(Address.search([('datacenter_id', '=', False), ('pop', '!=', False)]).mapped('pop'))
        names |= set(Asset.search([('datacenter_id', '=', False), ('pop', '!=', False)]).mapped('pop'))
        names |= set(Maintenance.search([('datacenter_id', '=', False), ('place', '!=', False)]).mapped('place'))
        centers = self.ensure_from_names(names, kinds)
        for name, center in centers.items():
            Address.search([('datacenter_id', '=', False), ('pop', '=', name)]).write({'datacenter_id': center.id})
            Asset.search([('datacenter_id', '=', False), ('pop', '=', name)]).write({'datacenter_id': center.id})
            Maintenance.search([('datacenter_id', '=', False), ('place', '=', name)]).write({
                'datacenter_id': center.id,
            })
        for line in Line.search([('datacenter_id', '=', False), ('a_end', '!=', False)]):
            head = (line.a_end or '').split(' ')[0].strip()
            if head in centers:
                line.datacenter_id = centers[head]
        partners = {
            partner.name: partner.id
            for partner in self.env['res.partner'].sudo().search([('is_company', '=', True)])
        }
        for line in Line.search([('partner_id', '=', False), ('partner_name', '!=', False)]):
            partner_id = partners.get((line.partner_name or '').strip())
            if partner_id:
                line.with_context(zenlenet_import=True).partner_id = partner_id


class ZenlenetAddress(models.Model):
    _inherit = 'zenlenet.address'

    datacenter_id = fields.Many2one('zenlenet.datacenter', string='数据中心', index=True, ondelete='set null')
    prefix_id = fields.Many2one('zenlenet.prefix', string='地址段', index=True, ondelete='set null')
    supplier_id = fields.Many2one('res.partner', string='供应商', domain=[('supplier_rank', '>', 0)], index=True)
    netbox_id = fields.Integer(string='NetBox ID', index=True, copy=False)
    netbox_synced = fields.Datetime(string='上次同步')
    netbox_pending = fields.Boolean(string='待写回 NetBox', default=False, index=True)

    @api.onchange('prefix_id')
    def _onchange_prefix(self):
        for record in self:
            if record.prefix_id:
                record.block = record.prefix_id.prefix
                if record.prefix_id.datacenter_id:
                    record.datacenter_id = record.prefix_id.datacenter_id

    def write(self, vals):
        if not self.env.context.get('netbox_skip_push') and {'status', 'partner_id', 'usage', 'dc_type', 'net_attr', 'expires_on'} & set(vals):
            vals = dict(vals, netbox_pending=True)
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('netbox_skip_push'):
            vals_list = [dict(vals, netbox_pending=True) for vals in vals_list]
        return super().create(vals_list)

    def unlink(self):
        remote = self.filtered('netbox_id').mapped('netbox_id')
        result = super().unlink()
        self.env['zenlenet.netbox'].delete_remote('/ipam/ip-addresses/', remote)
        return result

    def action_open_netbox(self):
        self.ensure_one()
        link = self.env['zenlenet.netbox'].public_link(f'/ipam/ip-addresses/{self.netbox_id}/')
        if not (self.netbox_id and link):
            return False
        return {'type': 'ir.actions.act_url', 'url': link, 'target': 'new'}

    @api.onchange('datacenter_id')
    def _onchange_datacenter(self):
        for record in self:
            if record.datacenter_id:
                record.pop = record.datacenter_id.name
                if record.datacenter_id.kind:
                    record.dc_type = record.datacenter_id.kind


class ZenlenetLine(models.Model):
    _inherit = 'zenlenet.line'

    datacenter_id = fields.Many2one('zenlenet.datacenter', string='数据中心', index=True, ondelete='set null')
    netbox_id = fields.Integer(string='NetBox ID', index=True, copy=False)
    netbox_synced = fields.Datetime(string='上次同步')
    status = fields.Selection(LINE_STATUSES, string='状态', default='active', required=True, index=True)
    commit_rate = fields.Integer(string='带宽 (Mbps)')
    region = fields.Char(string='地区', index=True, help='SD-WAN 挂在这个地区上，对应 NetBox 的 Region。')
    region_netbox_id = fields.Integer(string='NetBox 地区', copy=False)
    a_site_id = fields.Many2one('zenlenet.datacenter', string='A 端机房', index=True, ondelete='set null')
    z_site_id = fields.Many2one('zenlenet.datacenter', string='Z 端机房', index=True, ondelete='set null')
    a_device_id = fields.Many2one('zenlenet.device', string='A 端设备', index=True, ondelete='set null')
    z_device_id = fields.Many2one('zenlenet.device', string='Z 端设备', index=True, ondelete='set null')
    a_port = fields.Char(string='A 端端口')
    z_port = fields.Char(string='Z 端端口')
    a_vlan = fields.Char(string='A 端 VLAN')
    z_vlan = fields.Char(string='Z 端 VLAN')
    a_term_netbox_id = fields.Integer(copy=False)
    z_term_netbox_id = fields.Integer(copy=False)
    a_iface_netbox_id = fields.Integer(copy=False)
    z_iface_netbox_id = fields.Integer(copy=False)
    partner_id = fields.Many2one('res.partner', string='客户', index=True, domain=[('is_company', '=', True)])
    supplier = fields.Char(string='供应商（旧）')
    supplier_id = fields.Many2one('res.partner', string='供应商', domain=[('supplier_rank', '>', 0)], index=True)
    monthly_cost = fields.Monetary(string='月成本', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    start_date = fields.Date(string='开通日期')
    end_date = fields.Date(string='到期日期')

    def _delete_snapshot(self):
        return {'status': self.status, 'partner': bool(self.partner_id)}

    @api.onchange('partner_id')
    def _onchange_partner(self):
        for record in self:
            if record.partner_id:
                record.partner_name = record.partner_id.name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('stopped') and not vals.get('status'):
                vals['status'] = 'decommissioned'
            if vals.get('status') in ('decommissioned', 'deprovisioning', 'offline'):
                vals['stopped'] = True
        records = super().create(vals_list)
        if not any(self.env.context.get(key) for key in ('zenlenet_flow_apply', 'netbox_skip_push', 'zenlenet_import')):
            for record in records:
                try:
                    self.env['zenlenet.netbox'].push_line(record)
                except Exception as error:
                    _logger.warning('NetBox line push skipped for %s: %s', record.id, type(error).__name__)
        return records

    def write(self, vals):
        if 'status' in vals and 'stopped' not in vals:
            vals['stopped'] = vals['status'] in ('decommissioned', 'deprovisioning', 'offline')
        elif 'stopped' in vals and 'status' not in vals and vals['stopped']:
            vals['status'] = 'decommissioned'
        skipped = any(self.env.context.get(key) for key in ('zenlenet_flow_apply', 'netbox_skip_push', 'zenlenet_import'))
        if not skipped and ({'partner_id', 'status'} & set(vals)):
            for record in self:
                new_partner = vals.get('partner_id', record.partner_id.id) or False
                if 'partner_id' in vals and new_partner != (record.partner_id.id or False):
                    raise UserError('线路交给客户或收回，要走资源工单。')
                new_status = vals.get('status', record.status)
                if 'status' in vals and record.status == 'active' and new_status in ('deprovisioning', 'decommissioned', 'offline'):
                    raise UserError('线路拆除或退回要走资源工单。')
        result = super().write(vals)
        if not skipped and LINE_PUSH_FIELDS & set(vals):
            for record in self:
                try:
                    self.env['zenlenet.netbox'].push_line(record)
                except Exception as error:
                    _logger.warning('NetBox line push skipped for %s: %s', record.id, type(error).__name__)
        return result

    @api.model
    def _backfill_bindings(self):
        """Turn imported 'place vlan' text into the site and VLAN a private line actually has."""
        sites = {record.name: record.id for record in self.env['zenlenet.datacenter'].sudo().search([])}
        for line in self.sudo().search([]):
            vals = {}
            if line.kind == 'private' and (line.snapshot_key or '').startswith('c'):
                vals['kind'] = 'pl'
            if not line.commit_rate:
                rate = mbps_of(line.bandwidth, 0)
                if rate:
                    vals['commit_rate'] = rate
            for side in ('a', 'z'):
                if line[f'{side}_vlan'] or line[f'{side}_site_id']:
                    continue
                place, vid = split_end(line[f'{side}_end'])
                if vid:
                    vals[f'{side}_vlan'] = str(vid)
                site_id = sites.get(place) or sites.get((place or '').split(' ')[0])
                if site_id:
                    vals[f'{side}_site_id'] = site_id
            if not line.a_site_id and not vals.get('a_site_id') and line.datacenter_id:
                vals['a_site_id'] = line.datacenter_id.id
            if vals:
                line.with_context(netbox_skip_push=True, zenlenet_import=True).write(vals)
        return True

    def action_open_netbox(self):
        self.ensure_one()
        link = self.env['zenlenet.netbox'].public_link(f'/circuits/circuits/{self.netbox_id}/')
        if not (self.netbox_id and link):
            return False
        return {'type': 'ir.actions.act_url', 'url': link, 'target': 'new'}


class ZenlenetAsset(models.Model):
    _inherit = 'zenlenet.asset'

    datacenter_id = fields.Many2one('zenlenet.datacenter', string='数据中心', index=True, ondelete='set null')
    model = fields.Char(string='型号')
    purchased_on = fields.Date(string='购入日期')


class ZenlenetMaintenance(models.Model):
    _inherit = 'zenlenet.maintenance'

    datacenter_id = fields.Many2one('zenlenet.datacenter', string='数据中心', index=True, ondelete='set null')

    @api.onchange('datacenter_id')
    def _onchange_datacenter(self):
        for record in self:
            if record.datacenter_id and not record.place:
                record.place = record.datacenter_id.name

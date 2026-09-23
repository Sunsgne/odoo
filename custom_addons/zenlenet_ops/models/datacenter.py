import logging

from odoo import api, fields, models

from .records import DC_TYPES

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
    _order = 'sequence, name'

    name = fields.Char(string='名称', required=True, index=True)
    code = fields.Char(string='简称 / Slug')
    netbox_id = fields.Integer(string='NetBox ID', index=True, copy=False)
    netbox_synced = fields.Datetime(string='上次同步')
    facility = fields.Char(string='机房设施', help='运营商机房的正式名称或楼栋编号，对应 NetBox 的 Facility。')
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
    asset_ids = fields.One2many('zenlenet.asset', 'datacenter_id', string='固定资产')
    address_count = fields.Integer(string='地址数', compute='_compute_counts')
    allocated_count = fields.Integer(string='已分配', compute='_compute_counts')
    free_count = fields.Integer(string='未分配', compute='_compute_counts')
    line_count = fields.Integer(string='线路数', compute='_compute_counts')
    asset_count = fields.Integer(string='设备数', compute='_compute_counts')
    usage_percent = fields.Float(string='使用率', compute='_compute_counts')

    _name_unique = models.Constraint('unique(name)', '这个数据中心已经存在。')

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
                line.partner_id = partner_id


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
    commit_rate = fields.Integer(string='签约速率 (Mbps)')
    partner_id = fields.Many2one('res.partner', string='客户', index=True, domain=[('is_company', '=', True)])
    supplier = fields.Char(string='供应商（旧）')
    supplier_id = fields.Many2one('res.partner', string='供应商', domain=[('supplier_rank', '>', 0)], index=True)
    monthly_cost = fields.Monetary(string='月成本', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    start_date = fields.Date(string='开通日期')
    end_date = fields.Date(string='到期日期')

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
        return super().create(vals_list)

    def write(self, vals):
        if 'status' in vals and 'stopped' not in vals:
            vals['stopped'] = vals['status'] in ('decommissioned', 'deprovisioning', 'offline')
        elif 'stopped' in vals and 'status' not in vals and vals['stopped']:
            vals['status'] = 'decommissioned'
        return super().write(vals)

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

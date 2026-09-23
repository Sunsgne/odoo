from odoo import api, fields, models

from .records import DC_TYPES


class ZenlenetDatacenter(models.Model):
    _name = 'zenlenet.datacenter'
    _description = '数据中心'
    _order = 'sequence, name'

    name = fields.Char(string='名称', required=True, index=True)
    code = fields.Char(string='简称')
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

    @api.depends('address_ids.status', 'line_ids.stopped', 'asset_ids')
    def _compute_counts(self):
        Address = self.env['zenlenet.address']
        for record in self:
            total = Address.search_count([('datacenter_id', '=', record.id)])
            allocated = Address.search_count([
                ('datacenter_id', '=', record.id),
                ('status', 'in', ('allocated', 'testing', 'internal')),
            ])
            record.address_count = total
            record.allocated_count = allocated
            record.free_count = Address.search_count([('datacenter_id', '=', record.id), ('status', '=', 'free')])
            record.line_count = self.env['zenlenet.line'].search_count([
                ('datacenter_id', '=', record.id), ('stopped', '=', False),
            ])
            record.asset_count = self.env['zenlenet.asset'].search_count([('datacenter_id', '=', record.id)])
            record.usage_percent = round(allocated * 100.0 / total, 1) if total else 0.0

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
    partner_id = fields.Many2one('res.partner', string='客户', index=True, domain=[('is_company', '=', True)])
    supplier = fields.Char(string='供应商')
    monthly_cost = fields.Monetary(string='月成本', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    start_date = fields.Date(string='开通日期')
    end_date = fields.Date(string='到期日期')

    @api.onchange('partner_id')
    def _onchange_partner(self):
        for record in self:
            if record.partner_id:
                record.partner_name = record.partner_id.name


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

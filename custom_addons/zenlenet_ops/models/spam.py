"""Device purchase in four queues: plan, inbound, sign-off, acceptance."""

from odoo import api, fields, models

from .itam import ASSET_CATEGORIES


class ZenlenetPurchaseSpam(models.Model):
    _inherit = 'zenlenet.purchase'

    contract_code = fields.Char(string='合同号', index=True)
    device_ids = fields.One2many('zenlenet.purchase.device', 'purchase_id', string='设备')
    device_count = fields.Integer(string='设备数', compute='_compute_device_count')

    @api.depends('device_ids')
    def _compute_device_count(self):
        for record in self:
            record.device_count = len(record.device_ids)


class ZenlenetPurchaseDevice(models.Model):
    _name = 'zenlenet.purchase.device'
    _description = '采购设备'
    _inherit = ['zenlenet.deletable']
    _order = 'id desc'
    _rec_name = 'asset_sn'

    purchase_id = fields.Many2one('zenlenet.purchase', string='采购计划', required=True, ondelete='cascade', index=True)
    asset_sn = fields.Char(string='资产序列号', copy=False, readonly=True)
    category = fields.Selection(ASSET_CATEGORIES, string='类型', default='host', required=True)
    manufacturer = fields.Char(string='厂商')
    manufacturer_sn = fields.Char(string='厂商序列号', index=True)
    model_name = fields.Char(string='型号')
    box_no = fields.Char(string='物流箱号')
    state = fields.Selection([
        ('expected', '待入库'),
        ('inbound', '待签收'),
        ('signed', '待验收'),
        ('accepted', '已验收'),
    ], string='状态', default='expected', required=True, index=True)
    asset_id = fields.Many2one('zenlenet.asset', string='资产', readonly=True, copy=False)
    signed_on = fields.Datetime(string='签收时间', readonly=True)
    accepted_on = fields.Datetime(string='验收时间', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('asset_sn'):
                vals['asset_sn'] = sequence.next_by_code('zenlenet.purchase.device') or '/'
        return super().create(vals_list)

    def action_inbound(self):
        self.filtered(lambda line: line.state == 'expected').write({'state': 'inbound'})
        return True

    def action_sign(self):
        self.filtered(lambda line: line.state == 'inbound').write({
            'state': 'signed',
            'signed_on': fields.Datetime.now(),
        })
        return True

    def action_accept(self):
        Asset = self.env['zenlenet.asset']
        for line in self.filtered(lambda item: item.state == 'signed' and not item.asset_id):
            plan = line.purchase_id
            asset = Asset.create({
                'name': line.model_name or line.manufacturer_sn or line.asset_sn,
                'code': line.asset_sn,
                'category': line.category,
                'manufacturer': line.manufacturer,
                'serial': line.manufacturer_sn,
                'model': line.model_name,
                'datacenter_id': plan.datacenter_id.id,
                'supplier_id': plan.supplier_id.id,
                'purchase_id': plan.id,
                'city': plan.datacenter_id.city or '',
                'ownership': 'owned',
                'availability': 'stock',
                'state': 'idle',
                'purchased_on': fields.Date.context_today(self),
            })
            line.write({
                'state': 'accepted',
                'asset_id': asset.id,
                'accepted_on': fields.Datetime.now(),
            })
        return True

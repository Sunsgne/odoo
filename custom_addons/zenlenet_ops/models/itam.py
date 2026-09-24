"""Asset ledger in the shape of an ITAM board: category, ownership, rack position, and the task that moves it."""

from odoo import api, fields, models

ASSET_CATEGORIES = [
    ('host', '主机'),
    ('network', '网络设备'),
    ('gpu', 'GPU'),
    ('memory', '内存'),
    ('disk', '硬盘'),
    ('ib', 'IB 卡'),
    ('nic', '网卡'),
    ('raid', 'RAID 卡'),
    ('hba', 'HBA 卡'),
    ('optical', '光模块'),
    ('switch_board', '交换板卡'),
    ('cabinet', '机柜主机'),
    ('cdu', 'CDU'),
    ('sidecar', 'Sidecar'),
    ('spare', '其他备件'),
]
OWNERSHIP = [
    ('owned', '自有'),
    ('trial', '试用'),
    ('rental', '租赁'),
    ('hosting', '客户托管'),
]
AVAILABILITY = [
    ('in_rack', '在架'),
    ('stock', '在库'),
    ('loan', '外借'),
    ('repair', '维修中'),
]
TASK_KINDS = [
    ('entry', '入库'),
    ('inventory', '盘点'),
    ('repair', '维修'),
    ('scrap', '报废'),
    ('move', '搬迁'),
    ('loan', '外借'),
    ('giveback', '归还'),
]


class ZenlenetAssetItam(models.Model):
    _inherit = 'zenlenet.asset'

    code = fields.Char(string='资产编码', copy=False, index=True)
    category = fields.Selection(ASSET_CATEGORIES, string='类别', index=True)
    manufacturer = fields.Char(string='厂商')
    warranty_end = fields.Date(string='保修到期')
    city = fields.Char(string='城市')
    ownership = fields.Selection(OWNERSHIP, string='归属', default='owned', required=True, index=True)
    availability = fields.Selection(AVAILABILITY, string='在架状态', default='stock', required=True, index=True)
    repair_state = fields.Selection([
        ('ok', '正常'),
        ('repairing', '维修中'),
    ], string='维修', default='ok', required=True)
    plan_state = fields.Selection([
        ('none', '无'),
        ('planned', '规划中'),
    ], string='规划', default='none', required=True)
    role = fields.Char(string='角色')
    u_start = fields.Integer(string='起始 U')
    u_end = fields.Integer(string='结束 U')
    supplier_id = fields.Many2one('res.partner', string='供应商', domain=[('supplier_rank', '>', 0)])
    purchase_id = fields.Many2one('zenlenet.purchase', string='采购计划', index=True)
    task_ids = fields.One2many('zenlenet.asset.task', 'asset_id', string='任务')

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = sequence.next_by_code('zenlenet.asset') or '/'
        return super().create(vals_list)

    @api.model
    def itam_board(self):
        labels = dict(self._fields['category'].selection)
        counts = {key: 0 for key in labels}
        unset = 0
        for category, count in self._read_group([], ['category'], ['__count']):
            key = category[0] if isinstance(category, tuple) else category
            if key in counts:
                counts[key] = count
            else:
                unset += count
        owned = self.search_count([('ownership', '=', 'owned')])
        total = self.search_count([])
        return {
            'total': total,
            'owned': owned,
            'other': total - owned,
            'in_rack': self.search_count([('availability', '=', 'in_rack')]),
            'repairing': self.search_count([('repair_state', '=', 'repairing')]),
            'unset': unset,
            'categories': [{'key': key, 'label': label, 'count': counts[key]} for key, label in labels.items()],
        }


class ZenlenetAssetTask(models.Model):
    _name = 'zenlenet.asset.task'
    _description = '资产任务'
    _inherit = ['zenlenet.deletable']
    _order = 'id desc'

    name = fields.Char(string='单号', default='/', copy=False, readonly=True)
    kind = fields.Selection(TASK_KINDS, string='类型', required=True, default='entry', index=True)
    asset_id = fields.Many2one('zenlenet.asset', string='资产', index=True)
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='目标机房')
    category = fields.Selection(ASSET_CATEGORIES, string='类别')
    manufacturer = fields.Char(string='厂商')
    serial = fields.Char(string='厂商序列号')
    model_name = fields.Char(string='型号')
    quantity = fields.Integer(string='数量', default=1)
    user_id = fields.Many2one('res.users', string='经办人', default=lambda self: self.env.user)
    state = fields.Selection([
        ('open', '进行中'),
        ('done', '完成'),
    ], string='状态', default='open', required=True, index=True)
    done_on = fields.Datetime(string='完成时间', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('zenlenet.asset.task') or '/'
        records = super().create(vals_list)
        for task in records.filtered(lambda item: item.kind == 'repair' and item.asset_id):
            task.asset_id.write({'repair_state': 'repairing', 'availability': 'repair'})
        return records

    def action_done(self):
        Asset = self.env['zenlenet.asset']
        for task in self.filtered(lambda item: item.state == 'open'):
            asset = task.asset_id
            if task.kind == 'entry' and not asset:
                asset = Asset.create({
                    'name': task.model_name or task.serial or task.name,
                    'category': task.category,
                    'manufacturer': task.manufacturer,
                    'serial': task.serial,
                    'model': task.model_name,
                    'datacenter_id': task.datacenter_id.id,
                    'availability': 'stock',
                    'state': 'idle',
                })
                task.asset_id = asset
            elif task.kind == 'repair' and asset:
                asset.write({'repair_state': 'ok', 'availability': 'in_rack' if asset.datacenter_id else 'stock'})
            elif task.kind == 'scrap' and asset:
                asset.write({'state': 'scrap', 'availability': 'stock'})
            elif task.kind == 'loan' and asset:
                asset.availability = 'loan'
            elif task.kind == 'giveback' and asset:
                asset.write({
                    'availability': 'in_rack' if asset.datacenter_id else 'stock',
                    'state': 'in_use',
                })
            elif task.kind == 'move' and asset and task.datacenter_id:
                asset.write({'datacenter_id': task.datacenter_id.id, 'availability': 'in_rack', 'city': task.datacenter_id.city or asset.city})
            task.write({'state': 'done', 'done_on': fields.Datetime.now()})
        return True

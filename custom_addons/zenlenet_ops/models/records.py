from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.blocks import parse_prefix

from .notices import NOTICES

NET_ATTRS = [
    ('FastFiber', 'FastFiber'),
    ('公网', '公网'),
    ('内网', '内网'),
]
DC_TYPES = [
    ('已退租', '已退租'),
    ('不常用', '不常用'),
    ('主营机房', '主营机房'),
    ('安畅云', '安畅云'),
    ('第三方', '第三方'),
    ('POP点', 'POP点'),
    ('公有云', '公有云'),
]
STATUSES = [
    ('allocated', '已分配'),
    ('free', '未分配'),
    ('reserved', '预分配'),
    ('transferring', '调库中'),
    ('returning', '出库中'),
    ('testing', '测试'),
    ('internal', '自用'),
]


class ZenlenetAddress(models.Model):
    _name = 'zenlenet.address'
    _description = 'IP资源'
    _order = 'pop, address'
    _rec_name = 'address'
    _rec_names_search = ['address', 'block', 'pop']

    snapshot_id = fields.Integer(index=True, copy=False)
    address = fields.Char(string='地址', required=True, index=True)
    block = fields.Char(string='IP段', index=True)
    pop = fields.Char(string='机房', index=True)
    supplier = fields.Char(string='供应商')
    partner_id = fields.Many2one('res.partner', string='客户', index=True)
    role = fields.Char(string='资源属性')
    net_attr = fields.Selection(NET_ATTRS, string='网络属性', default='公网', index=True)
    dc_type = fields.Selection(DC_TYPES, string='数据中心类型', index=True)
    status = fields.Selection(STATUSES, string='分配状态', default='free', index=True)
    usage = fields.Char(string='用途')
    expires_on = fields.Date(string='到期日')
    remark = fields.Text(string='备注')

    _address_snapshot_unique = models.Constraint(
        'unique(snapshot_id)',
        '这条地址已经导入过。',
    )

    def action_export_prefixes(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/zenlenet/prefixes.csv',
            'target': 'new',
        }

    def action_merge(self):
        if len(self) < 2:
            raise UserError('请先勾选同一个IP段里的至少两条地址。')
        blocks = {(record.block or '').strip() for record in self}
        if len(blocks) != 1 or not next(iter(blocks)):
            raise UserError('只能合并同一个IP段里的地址。')
        block = next(iter(blocks))
        sample = self[0]
        found = self.env['zenlenet.ipset'].search([('name', '=', block)], limit=1)
        if found:
            found.write({'address_ids': [(4, record.id) for record in self]})
        else:
            found = self.env['zenlenet.ipset'].create({
                'name': block,
                'pop': sample.pop,
                'net_attr': sample.net_attr,
                'dc_type': sample.dc_type,
                'address_ids': [(6, 0, self.ids)],
            })
        return {
            'type': 'ir.actions.act_window',
            'name': 'IP集',
            'res_model': 'zenlenet.ipset',
            'res_id': found.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_add_prefix(self):
        return {
            'type': 'ir.actions.act_window',
            'name': '添加IP段',
            'res_model': 'zenlenet.prefix.add',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_add_ipset(self):
        return {
            'type': 'ir.actions.act_window',
            'name': '添加IP集',
            'res_model': 'zenlenet.ipset',
            'view_mode': 'form',
            'target': 'current',
        }


class ZenlenetLine(models.Model):
    _name = 'zenlenet.line'
    _description = '线路'
    _order = 'kind, name'

    snapshot_key = fields.Char(index=True, copy=False)
    name = fields.Char(string='编号', required=True)
    kind = fields.Selection([
        ('private', '供应商专线'),
        ('vxlan', 'VXLAN'),
    ], string='类型', required=True, index=True)
    a_end = fields.Char(string='A端')
    z_end = fields.Char(string='Z端')
    bandwidth = fields.Char(string='带宽')
    partner_name = fields.Char(string='客户')
    purpose = fields.Char(string='用途')
    stopped = fields.Boolean(string='已终止')

    _snapshot_key_unique = models.Constraint(
        'unique(snapshot_key)',
        '这条线路已经导入过。',
    )


class ZenlenetSupplierReturn(models.Model):
    _name = 'zenlenet.supplier.return'
    _description = '退资源'
    _order = 'id desc'

    snapshot_id = fields.Integer(index=True, copy=False)
    supplier = fields.Char(string='供应商', required=True)
    resource = fields.Char(string='IP / 资源', required=True)
    when_text = fields.Char(string='时间')
    note = fields.Text(string='备注')

    _return_snapshot_unique = models.Constraint(
        'unique(snapshot_id)',
        '这条退资源记录已经导入过。',
    )


class ZenlenetNoticeTemplate(models.Model):
    _name = 'zenlenet.notice.template'
    _description = '通知模板'
    _order = 'code'

    code = fields.Char(string='编号', required=True)
    kind = fields.Selection([
        ('maintenance', '常规维护'),
        ('cutover', '割接迁移'),
        ('risk', '上游风险提示'),
        ('emergency', '紧急维护'),
        ('sdwan', '接入点 / SD-WAN'),
    ], string='类型', required=True)
    name = fields.Char(string='名称', required=True)
    scene = fields.Char(string='适用场景')
    subject = fields.Char(string='邮件主题')
    body = fields.Text(string='邮件正文')

    def load_workbook_templates(self):
        for kind, item in NOTICES.items():
            found = self.search([('kind', '=', kind)], limit=1)
            values = {
                'code': item['code'],
                'kind': kind,
                'name': item['name'],
                'scene': item['scene'],
                'subject': item['subject'],
                'body': item['body'],
            }
            if found:
                found.write(values)
            else:
                self.create(values)


class ZenlenetDesk(models.Model):
    _name = 'zenlenet.desk'
    _description = '尊领'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    hint = fields.Char(string='说明')
    sequence = fields.Integer(default=10)
    action_ref = fields.Char()

    def action_open(self):
        self.ensure_one()
        action = self.env.ref(self.action_ref).read()[0]
        return action


class ZenlenetIpset(models.Model):
    _name = 'zenlenet.ipset'
    _description = 'IP集'
    _order = 'name'

    name = fields.Char(string='名称', required=True)
    pop = fields.Char(string='机房')
    net_attr = fields.Selection(NET_ATTRS, string='网络属性')
    dc_type = fields.Selection(DC_TYPES, string='数据中心类型')
    address_ids = fields.Many2many('zenlenet.address', string='地址')
    note = fields.Text(string='备注')


class ZenlenetPrefixAdd(models.TransientModel):
    _name = 'zenlenet.prefix.add'
    _description = '添加IP段'

    cidr = fields.Char(string='IP段', required=True)
    pop = fields.Char(string='机房')
    supplier = fields.Char(string='供应商')
    net_attr = fields.Selection(NET_ATTRS, string='网络属性', default='公网')
    dc_type = fields.Selection(DC_TYPES, string='数据中心类型')
    status = fields.Selection(STATUSES, string='分配状态', default='free')

    def action_create(self):
        self.ensure_one()
        try:
            cidr = parse_prefix(self.cidr)
        except ValueError as error:
            raise UserError('IP段格式不对，请写成 192.0.2.0/24 这样。') from error
        address = self.env['zenlenet.address'].create({
            'address': cidr,
            'block': cidr,
            'pop': self.pop,
            'supplier': self.supplier,
            'net_attr': self.net_attr,
            'dc_type': self.dc_type,
            'status': self.status or 'free',
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'IP资源',
            'res_model': 'zenlenet.address',
            'res_id': address.id,
            'view_mode': 'form',
            'target': 'current',
        }


class ZenlenetPurchase(models.Model):
    _name = 'zenlenet.purchase'
    _description = '采购'
    _order = 'id desc'
    _rec_name = 'supplier'

    supplier = fields.Char(string='供应商', required=True)
    resource = fields.Char(string='资源', required=True)
    pop = fields.Char(string='机房')
    user_id = fields.Many2one(
        'res.users', string='负责人', default=lambda self: self.env.user, domain=[('share', '=', False)],
    )
    state = fields.Selection([
        ('draft', '待采购'),
        ('ordered', '已下单'),
        ('received', '已到货'),
        ('returned', '已退'),
    ], string='状态', default='draft', required=True)
    note = fields.Text(string='备注')


class ZenlenetAsset(models.Model):
    _name = 'zenlenet.asset'
    _description = '固定资产'
    _order = 'id desc'

    snapshot_key = fields.Char(index=True, copy=False)
    name = fields.Char(string='名称', required=True)
    partner_id = fields.Many2one('res.partner', string='客户')
    pop = fields.Char(string='机房')
    serial = fields.Char(string='序列号')
    state = fields.Selection([
        ('in_use', '在用'),
        ('idle', '闲置'),
        ('scrap', '报废'),
    ], string='状态', default='in_use', required=True)

    _asset_snapshot_unique = models.Constraint(
        'unique(snapshot_key)',
        '这台设备已经导入过。',
    )

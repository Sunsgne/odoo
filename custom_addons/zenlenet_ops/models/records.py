from odoo import fields, models

from .notices import NOTICES


class ZenlenetAddress(models.Model):
    _name = 'zenlenet.address'
    _description = 'IP资源'
    _order = 'pop, address'

    snapshot_id = fields.Integer(index=True, copy=False)
    address = fields.Char(string='地址', required=True, index=True)
    block = fields.Char(string='IP段', index=True)
    pop = fields.Char(string='机房', index=True)
    supplier = fields.Char(string='供应商')
    partner_id = fields.Many2one('res.partner', string='客户', index=True)
    role = fields.Char(string='资源属性')
    net_attr = fields.Selection([
        ('公网', '公网'),
        ('内网', '内网'),
    ], string='网络属性', default='公网')
    dc_type = fields.Selection([
        ('主营机房', '主营机房'),
        ('第三方', '第三方'),
        ('POP点', 'POP点'),
        ('公有云', '公有云'),
    ], string='数据中心类型')
    status = fields.Selection([
        ('allocated', '已分配'),
        ('free', '未分配'),
        ('reserved', '预分配'),
        ('testing', '测试'),
        ('returning', '出库中'),
        ('internal', '自用'),
    ], string='分配状态', default='free', index=True)
    usage = fields.Char(string='用途')
    expires_on = fields.Date(string='到期日')
    remark = fields.Text(string='备注')

    _address_snapshot_unique = models.Constraint(
        'unique(snapshot_id)',
        '这条地址已经导入过。',
    )


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

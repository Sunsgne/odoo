from odoo import api, fields, models
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
    _inherit = ['zenlenet.deletable']
    _order = 'pop, address'
    _rec_name = 'address'
    _rec_names_search = ['address', 'block', 'pop']

    snapshot_id = fields.Integer(index=True, copy=False)
    address = fields.Char(string='地址', required=True, index=True)
    block = fields.Char(string='IP段', index=True)
    pop = fields.Char(string='机房', index=True)
    supplier = fields.Char(string='供应商（旧）')
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
    _inherit = ['zenlenet.deletable']
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
    partner_name = fields.Char(string='客户（导入名）')
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
    supplier = fields.Char(string='供应商（旧）')
    supplier_id = fields.Many2one('res.partner', string='供应商', domain=[('supplier_rank', '>', 0)], index=True)
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
    _description = '新增网段'

    cidr = fields.Char(string='网段 (CIDR)', required=True)
    parent_id = fields.Many2one('zenlenet.prefix', string='上级网段')
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='数据中心')
    partner_id = fields.Many2one('res.partner', string='分配给客户', domain=[('is_company', '=', True), ('customer_rank', '>', 0)])
    supplier_id = fields.Many2one('res.partner', string='供应商', domain=[('supplier_rank', '>', 0)])
    status = fields.Selection([('container', '容器'), ('active', '在用'), ('reserved', '预留')], string='状态', default='active', required=True)
    region = fields.Char(string='地区')
    asn = fields.Integer(string='AS 号')
    role = fields.Char(string='用途角色')
    description = fields.Char(string='说明')
    pop = fields.Char(string='机房（旧）')
    supplier = fields.Char(string='供应商（旧）')
    net_attr = fields.Selection(NET_ATTRS, string='网络属性')
    dc_type = fields.Selection(DC_TYPES, string='数据中心类型')

    def action_create(self):
        self.ensure_one()
        try:
            cidr = parse_prefix(self.cidr)
        except ValueError as error:
            raise UserError('网段格式不对，请写成 192.0.2.0/24 这样。') from error
        Prefix = self.env['zenlenet.prefix']
        if Prefix.search_count([('prefix', '=', cidr)]):
            raise UserError('这个网段已经存在。')
        prefix = Prefix.create({
            'prefix': cidr,
            'datacenter_id': self.datacenter_id.id or self.parent_id.datacenter_id.id,
            'partner_id': self.partner_id.id,
            'status': self.status,
            'role': self.role or self.parent_id.role,
            'description': self.description or '',
            'region': self.region or self.parent_id.region or False,
            'asn': self.asn or self.parent_id.asn or 0,
        })
        try:
            self.env['zenlenet.netbox'].create_prefixes(prefix)
        except Exception as error:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning('NetBox prefix create skipped: %s', type(error).__name__)
        return {
            'type': 'ir.actions.act_window',
            'name': '网段',
            'res_model': 'zenlenet.prefix',
            'res_id': prefix.id,
            'view_mode': 'form',
            'target': 'current',
        }


class ZenlenetPurchase(models.Model):
    _name = 'zenlenet.purchase'
    _description = '采购'
    _inherit = ['zenlenet.deletable']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='采购单号', default='/', copy=False, readonly=True)
    category = fields.Selection([
        ('ip', 'IP 地址段'),
        ('transit', '带宽 / IP Transit'),
        ('circuit', '专线 / 波分'),
        ('colo', '机柜 / 电力'),
        ('device', '设备'),
        ('cloud', '云资源'),
        ('other', '其他'),
    ], string='采购类别', required=True, default='transit', index=True)
    supplier = fields.Char(string='供应商（旧）')
    supplier_id = fields.Many2one('res.partner', string='供应商', domain=[('supplier_rank', '>', 0)], index=True)
    resource = fields.Char(string='采购内容', required=True)
    bill_id = fields.Many2one('account.move', string='供应商账单', readonly=True, copy=False)
    datacenter_id = fields.Many2one('zenlenet.datacenter', string='数据中心', index=True)
    pop = fields.Char(string='机房（旧）')
    quantity = fields.Float(string='数量', default=1.0)
    unit = fields.Char(string='单位', default='项')
    currency_id = fields.Many2one('res.currency', string='币种', default=lambda self: self.env.company.currency_id)
    unit_cost = fields.Monetary(string='单价 / 月', currency_field='currency_id')
    monthly_cost = fields.Monetary(string='月成本', compute='_compute_cost', store=True, currency_field='currency_id')
    one_time_cost = fields.Monetary(string='一次性费用', currency_field='currency_id')
    term_months = fields.Integer(string='合约期（月）', default=12)
    ordered_on = fields.Date(string='下单日期')
    expected_on = fields.Date(string='预计到货')
    received_on = fields.Date(string='到货日期')
    end_on = fields.Date(string='到期日期')
    user_id = fields.Many2one(
        'res.users', string='负责人', default=lambda self: self.env.user, domain=[('share', '=', False)],
    )
    state = fields.Selection([
        ('draft', '待采购'),
        ('ordered', '已下单'),
        ('received', '已到货'),
        ('returned', '已退回'),
    ], string='状态', default='draft', required=True, index=True)
    note = fields.Text(string='备注')

    def _delete_snapshot(self):
        return {'state': self.state, 'bill_count': 1 if self.bill_id else 0}

    @api.depends('quantity', 'unit_cost')
    def _compute_cost(self):
        for record in self:
            record.monthly_cost = (record.quantity or 0.0) * (record.unit_cost or 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('zenlenet.purchase') or '/'
        return super().create(vals_list)

    def action_order(self):
        self.write({'state': 'ordered', 'ordered_on': fields.Date.context_today(self)})

    def action_receive(self):
        self.write({'state': 'received', 'received_on': fields.Date.context_today(self)})

    def action_return(self):
        self.write({'state': 'returned'})

    def action_make_bill(self):
        Move = self.env['account.move']
        created = Move
        for record in self:
            if record.bill_id or not record.supplier_id:
                continue
            bill = Move.create({
                'move_type': 'in_invoice',
                'partner_id': record.supplier_id.id,
                'currency_id': record.currency_id.id,
                'invoice_date': fields.Date.context_today(self),
                'ref': record.name,
                'invoice_origin': record.name,
                'invoice_line_ids': [(0, 0, {
                    'name': f'{record.resource}（{dict(record._fields["category"].selection).get(record.category, "")}）',
                    'quantity': record.quantity or 1.0,
                    'price_unit': record.unit_cost,
                    'tax_ids': [(6, 0, [])],
                })] + ([(0, 0, {
                    'name': f'{record.resource} 一次性费用',
                    'quantity': 1.0,
                    'price_unit': record.one_time_cost,
                    'tax_ids': [(6, 0, [])],
                })] if record.one_time_cost else []),
            })
            record.bill_id = bill
            created |= bill
        if not created:
            raise UserError('请先选择供应商；已经生成过账单的采购不会重复生成。')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': created[0].id,
            'view_mode': 'form',
            'view_id': self.env.ref('zenlenet_ops.view_vendor_bill_form').id,
            'target': 'current',
        }


class ZenlenetAsset(models.Model):
    _name = 'zenlenet.asset'
    _description = '固定资产'
    _inherit = ['zenlenet.deletable']
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

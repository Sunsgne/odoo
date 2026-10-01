from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.loop import can_rebind, capacity_ready, hold_allows, operation_result, payload_hash

SOURCES = [('netbox', 'NetBox'), ('monitor', '监控'), ('obss', '运营')]
HOLD_OBJECTS = [('prefix', '地址段'), ('address', '地址'), ('line', '线路')]
HOLD_STATES = [('draft', '草稿'), ('held', '预留中'), ('unknown', '结果未知'), ('released', '已释放')]
CHANGE_STATES = [('draft', '草稿'), ('approved', '已批准'), ('done', '已完成'), ('cancel', '已取消')]
EXIT_KINDS = [
    ('commercial', '商业终止'),
    ('technical', '技术停用'),
    ('metering', '计量截止'),
    ('capacity', '资源释放'),
    ('supplier', '供应商终止'),
]
OP_STATES = [('queued', '待执行'), ('unknown', '结果未知'), ('done', '已完成'), ('failed', '失败')]


class ZenlenetBinding(models.Model):
    _name = 'zenlenet.binding'
    _description = '外部绑定'
    _order = 'id desc'

    source = fields.Selection(SOURCES, string='来源', required=True, default='netbox')
    object_type = fields.Char(string='对象类型', required=True)
    external_id = fields.Char(string='外部编号', required=True)
    obss_model = fields.Char(string='本系统模型')
    res_ref = fields.Integer(string='本系统编号')
    tombstoned = fields.Boolean(string='已删除', default=False, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    _binding_key = models.Constraint(
        'unique(source, object_type, external_id)',
        '这个外部对象已经登记过。',
    )

    @api.model
    def register(self, source, object_type, external_id, obss_model=None, res_ref=None):
        found = self.search([
            ('source', '=', source),
            ('object_type', '=', object_type),
            ('external_id', '=', external_id),
        ], limit=1)
        if found:
            if not can_rebind(found.tombstoned):
                raise UserError('这个外部对象已经删除，不能按原编号重新绑定。')
            return found
        return self.create({
            'source': source,
            'object_type': object_type,
            'external_id': external_id,
            'obss_model': obss_model,
            'res_ref': res_ref or 0,
        })

    def action_tombstone(self):
        self.write({'tombstoned': True, 'res_ref': 0})
        return True


class ZenlenetOperation(models.Model):
    _name = 'zenlenet.operation'
    _description = '操作'
    _order = 'id desc'

    name = fields.Char(string='业务键', required=True, index=True)
    payload = fields.Char(string='内容')
    payload_digest = fields.Char(string='摘要', required=True)
    state = fields.Selection(OP_STATES, string='状态', default='queued', required=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    _operation_key = models.Constraint('unique(name)', '这个操作已经登记过。')

    @api.model
    def register(self, key, payload):
        digest = payload_hash(payload)
        found = self.search([('name', '=', key)], limit=1)
        if found:
            result = operation_result(found.payload_digest, digest)
            if result == 'conflict':
                raise UserError('同一操作键的内容不一致。')
            return found
        return self.create({'name': key, 'payload': payload, 'payload_digest': digest})

    def action_unknown(self):
        self.filtered(lambda row: row.state == 'queued').write({'state': 'unknown'})
        return True

    def action_done(self):
        pending = self.filtered(lambda row: row.state in ('queued', 'unknown'))
        pending.write({'state': 'done'})
        return True

    def action_fail(self):
        pending = self.filtered(lambda row: row.state in ('queued', 'unknown'))
        pending.write({'state': 'failed'})
        return True


class ZenlenetHold(models.Model):
    _name = 'zenlenet.hold'
    _description = '资源预留'
    _order = 'id desc'

    order_id = fields.Many2one('sale.order', string='服务订单', index=True)
    object_type = fields.Selection(HOLD_OBJECTS, string='资源', required=True)
    res_ref = fields.Integer(string='资源编号', required=True)
    slot = fields.Char(compute='_compute_slot', store=True, index=True)
    state = fields.Selection(HOLD_STATES, string='状态', default='draft', required=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    @api.depends('object_type', 'res_ref')
    def _compute_slot(self):
        for record in self:
            record.slot = f'{record.object_type}:{record.res_ref or 0}'

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS zenlenet_hold_one_active
            ON zenlenet_hold (slot)
            WHERE state = 'held'
        """)

    def action_hold(self):
        self.env.flush_all()
        for record in self:
            if record.state == 'held':
                continue
            if record.state not in ('draft', 'unknown'):
                raise UserError('这个预留不能再占用。')
            self.env.cr.execute(
                "SELECT id FROM zenlenet_hold WHERE slot = %s AND state = 'held' FOR UPDATE",
                [record.slot],
            )
            taken = self.env.cr.fetchone()
            if taken and taken[0] != record.id:
                raise UserError('这个资源已经有预留。')
            record.state = 'held'
        return True

    def action_unknown(self):
        self.filtered(lambda row: row.state == 'draft').write({'state': 'unknown'})
        return True

    def action_release(self):
        self.filtered(lambda row: row.state in ('held', 'unknown')).write({'state': 'released'})
        return True

    @api.model
    def allocation_blocked(self, object_type, res_id, order_id):
        if not res_id:
            return False
        hold = self.search([
            ('state', '=', 'held'),
            ('object_type', '=', object_type),
            ('res_ref', '=', res_id),
        ], limit=1)
        if not hold:
            return False
        return not hold_allows(hold.order_id.id or 0, order_id or 0)

    @api.model
    def blocked_ids(self, object_type, order_id):
        holds = self.search([('state', '=', 'held'), ('object_type', '=', object_type)])
        return [
            hold.res_ref for hold in holds
            if hold.res_ref and not hold_allows(hold.order_id.id or 0, order_id or 0)
        ]


class ZenlenetChange(models.Model):
    _name = 'zenlenet.change'
    _description = '变更'
    _order = 'id desc'

    order_id = fields.Many2one('sale.order', string='服务订单', required=True, index=True)
    summary = fields.Char(string='变更内容', required=True)
    state = fields.Selection(CHANGE_STATES, string='状态', default='draft', required=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS zenlenet_change_one_open
            ON zenlenet_change (order_id)
            WHERE state IN ('draft', 'approved')
        """)

    def action_approve(self):
        for record in self:
            if record.state != 'draft':
                raise UserError('只有草稿可以批准。')
            others = self.search_count([
                ('order_id', '=', record.order_id.id),
                ('state', '=', 'approved'),
                ('id', '!=', record.id),
            ])
            if others:
                raise UserError('这张服务订单已经有一张批准中的变更。')
            record.state = 'approved'
        return True

    def action_done(self):
        self.filtered(lambda row: row.state == 'approved').write({'state': 'done'})
        return True

    def action_cancel(self):
        self.filtered(lambda row: row.state in ('draft', 'approved')).write({'state': 'cancel'})
        return True


class ZenlenetExitStep(models.Model):
    _name = 'zenlenet.exit.step'
    _description = '退订'
    _order = 'order_id, id'

    order_id = fields.Many2one('sale.order', string='服务订单', required=True, index=True, ondelete='cascade')
    partner_id = fields.Many2one(related='order_id.partner_id', string='客户', store=True)
    kind = fields.Selection(EXIT_KINDS, string='事项', required=True)
    state = fields.Selection([('open', '未完成'), ('done', '已完成')], default='open', required=True, index=True)
    done_on = fields.Date(string='完成日期')
    company_id = fields.Many2one(related='order_id.company_id', store=True)

    _exit_kind = models.Constraint('unique(order_id, kind)', '这张订单的这项退订已经有了。')

    def action_done(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.state == 'done':
                continue
            if record.kind == 'capacity':
                done = self.search([
                    ('order_id', '=', record.order_id.id),
                    ('state', '=', 'done'),
                ]).mapped('kind')
                if not capacity_ready(done):
                    raise UserError('技术停用和计量截止还没完成。')
                record.order_id.zenlenet_capacity_released = today
            elif record.kind == 'technical':
                record.order_id.zenlenet_technical_disabled = today
            elif record.kind == 'metering':
                record.order_id.zenlenet_metering_cutoff = today
            elif record.kind == 'supplier':
                record.order_id.zenlenet_supplier_ceased = today
            record.write({'state': 'done', 'done_on': today})
        return True


class SaleOrderExit(models.Model):
    _inherit = 'sale.order'

    def _ensure_exit(self):
        Step = self.env['zenlenet.exit.step']
        for order in self:
            existing = set(Step.search([('order_id', '=', order.id)]).mapped('kind'))
            for kind, _label in EXIT_KINDS:
                if kind not in existing:
                    Step.create({'order_id': order.id, 'kind': kind})
        return True

    def action_open_exit(self):
        self.ensure_one()
        self._ensure_exit()
        return {
            'type': 'ir.actions.act_window',
            'name': '退订',
            'res_model': 'zenlenet.exit.step',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }

    def action_mark_terminated(self):
        result = super().action_mark_terminated()
        self._ensure_exit()
        return result

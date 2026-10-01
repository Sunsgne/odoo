from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.remain import (
    can_resell,
    next_job,
    next_rollout,
    power_ok,
    shadow_delta,
    should_apply,
)

JOB_KINDS = [
    ('ipt', 'IP Transit'),
    ('l2', '专线'),
    ('cloud', '云连接'),
    ('install', '装机'),
    ('wipe', '擦除'),
]
JOB_STATES = [
    ('draft', '草稿'),
    ('planned', '已计划'),
    ('unknown', '结果未知'),
    ('verified', '已核对'),
    ('failed', '失败'),
]


class ZenlenetInbox(models.Model):
    _name = 'zenlenet.inbox'
    _description = '收件箱'
    _order = 'id desc'

    event_key = fields.Char(string='事件键', required=True, index=True)
    payload_digest = fields.Char(string='摘要', required=True)
    version = fields.Integer(string='版本', required=True, default=0)
    payload = fields.Text(string='内容')
    state = fields.Selection([('new', '未处理'), ('applied', '已处理'), ('stale', '过期')], default='new', required=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    _event_key = models.Constraint('unique(event_key)', '这个事件已经收过。')

    @api.model
    def receive(self, event_key, digest, version, payload):
        found = self.sudo().search([('event_key', '=', event_key)], limit=1)
        if found:
            if found.payload_digest != digest:
                raise UserError('同一事件键的内容不一致。')
            return found
        return self.sudo().create({
            'event_key': event_key,
            'payload_digest': digest,
            'version': int(version or 0),
            'payload': payload or '',
        })

    def action_apply(self):
        for record in self:
            latest = self.search([
                ('event_key', '=', record.event_key),
                ('state', '=', 'applied'),
            ], order='version desc', limit=1)
            current = latest.version if latest else None
            if not should_apply(current, record.version):
                record.state = 'stale'
                continue
            record.state = 'applied'
        return True


class ZenlenetJob(models.Model):
    _name = 'zenlenet.job'
    _description = '执行'
    _order = 'id desc'

    name = fields.Char(string='说明', required=True)
    kind = fields.Selection(JOB_KINDS, string='种类', required=True, default='ipt')
    order_id = fields.Many2one('sale.order', string='服务订单')
    device_id = fields.Many2one('zenlenet.device', string='物理机')
    image = fields.Char(string='镜像')
    evidence = fields.Text(string='证据')
    state = fields.Selection(JOB_STATES, string='状态', default='draft', required=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    def _step(self, target):
        for record in self:
            nxt = next_job(record.state, bool((record.evidence or '').strip()))
            if nxt != target:
                raise UserError('这一步还不能做。')
            if target == 'verified' and record.kind == 'wipe' and not can_resell(record.evidence):
                raise UserError('擦除没有证据，不能再售。')
            if target == 'verified' and record.kind == 'install' and not record.image:
                raise UserError('装机没有镜像。')
            record.state = target
            if (
                target == 'verified'
                and record.kind == 'wipe'
                and record.device_id
                and record.device_id.status in ('offline', 'decommissioning')
            ):
                record.device_id.status = 'planned'
        return True

    def action_plan(self):
        return self._step('planned')

    def action_execute(self):
        """Simulator only. Execution is unknown until evidence is checked."""
        return self._step('unknown')

    def action_verify(self):
        return self._step('verified')

    def action_fail(self):
        self.filtered(lambda row: row.state in ('planned', 'unknown')).write({'state': 'failed'})
        return True


class ZenlenetCloud(models.Model):
    _name = 'zenlenet.cloud'
    _description = '云连接'
    _order = 'id desc'

    order_id = fields.Many2one('sale.order', string='服务订单', required=True)
    provider = fields.Selection([
        ('aws', 'AWS'),
        ('azure', 'Azure'),
        ('gcp', 'GCP'),
        ('aliyun', '阿里云'),
        ('tencent', '腾讯云'),
        ('other', '其他'),
    ], string='云', required=True, default='aws')
    vlan = fields.Char(string='VLAN')
    bandwidth = fields.Char(string='带宽')
    state = fields.Selection([
        ('draft', '草稿'),
        ('waiting', '等待对方'),
        ('accepted', '已接受'),
        ('failed', '失败'),
    ], string='状态', default='draft', required=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    def action_wait(self):
        self.filtered(lambda row: row.state == 'draft').write({'state': 'waiting'})
        return True

    def action_accept(self):
        self.filtered(lambda row: row.state == 'waiting').write({'state': 'accepted'})
        return True

    def action_fail(self):
        self.filtered(lambda row: row.state in ('draft', 'waiting')).write({'state': 'failed'})
        return True


class ZenlenetShadow(models.Model):
    _name = 'zenlenet.shadow'
    _description = '影子计费'
    _order = 'period desc, id desc'

    period = fields.Char(string='账期', required=True, index=True)
    partner_id = fields.Many2one('res.partner', string='客户', required=True)
    contract_amount = fields.Float(string='合同金额')
    charge_amount = fields.Float(string='收费项金额')
    delta = fields.Float(string='差额', compute='_compute_delta', store=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    _shadow_key = models.Constraint('unique(company_id, period, partner_id)', '这个客户这个账期已经对过。')

    @api.depends('contract_amount', 'charge_amount')
    def _compute_delta(self):
        for record in self:
            record.delta = shadow_delta(record.contract_amount, record.charge_amount)

    @api.model
    def build_period(self, period):
        """Compare contract fees and charges. Does not post an invoice."""
        if not (
            self.env.user.has_group('zenlenet_ops.group_finance')
            or self.env.user.has_group('zenlenet_ops.group_manager')
        ):
            raise UserError('只有财务可以做影子计费。')
        period = (period or '').strip()
        contracts = self.env['zenlenet.contract'].search([('state', 'in', ('active', 'expiring'))])
        charges = self.env['zenlenet.charge'].search([('period', '=', period)])
        partners = contracts.mapped('partner_id') | charges.mapped('partner_id')
        created = self.env['zenlenet.shadow']
        for partner in partners:
            contract_amount = sum(contracts.filtered(lambda row: row.partner_id == partner).mapped('monthly_amount'))
            charge_amount = sum(charges.filtered(lambda row: row.partner_id == partner).mapped('amount'))
            found = self.search([('period', '=', period), ('partner_id', '=', partner.id)], limit=1)
            values = {'contract_amount': contract_amount, 'charge_amount': charge_amount}
            if found:
                found.write(values)
                created |= found
            else:
                created |= self.create(dict(values, period=period, partner_id=partner.id))
        return created

    @api.model
    def action_build_current(self):
        from odoo.addons.zenlenet_ops.billing import period_label
        period = period_label(fields.Date.context_today(self))
        rows = self.build_period(period)
        return {
            'type': 'ir.actions.act_window',
            'name': '影子计费',
            'res_model': 'zenlenet.shadow',
            'view_mode': 'list,form',
            'domain': [('id', 'in', rows.ids)],
        }


class ZenlenetRollout(models.Model):
    _name = 'zenlenet.rollout'
    _description = '灰度'
    _order = 'id desc'

    datacenter_id = fields.Many2one('zenlenet.datacenter', string='机房', required=True)
    product = fields.Selection([
        ('ipt', 'IP Transit'),
        ('l2', '专线'),
        ('cloud', '云连接'),
        ('colo', '托管'),
        ('metal', '裸金属'),
        ('labor', '现场'),
    ], string='产品', required=True)
    state = fields.Selection([
        ('shadow', '影子'),
        ('hold', '预留'),
        ('change', '变更'),
        ('bill', '计费'),
    ], string='阶段', default='shadow', required=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    def action_advance(self):
        for record in self:
            nxt = next_rollout(record.state)
            if not nxt:
                raise UserError('已经是最后一阶段。')
            record.state = nxt
        return True


class ZenlenetDispute(models.Model):
    _name = 'zenlenet.dispute'
    _description = '账单争议'
    _order = 'id desc'

    invoice_id = fields.Many2one('account.move', string='账单', required=True)
    partner_id = fields.Many2one(related='invoice_id.partner_id', store=True)
    amount = fields.Monetary(string='争议金额', required=True)
    currency_id = fields.Many2one(related='invoice_id.currency_id')
    reason = fields.Char(string='原因', required=True)
    state = fields.Selection([
        ('draft', '草稿'),
        ('accepted', '已接受'),
        ('rejected', '已驳回'),
    ], default='draft', required=True)
    charge_id = fields.Many2one('zenlenet.charge', string='收费项', readonly=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    def action_accept(self):
        """A dispute becomes a draft charge. It does not edit a posted invoice."""
        for record in self:
            if record.state != 'draft':
                raise UserError('已经处理过。')
            if record.amount <= 0:
                raise UserError('争议金额要大于 0。')
            charge = self.env['zenlenet.charge'].register(f'dispute:{record.id}', {
                'name': record.reason,
                'kind': 'manual',
                'partner_id': record.partner_id.id,
                'company_id': record.company_id.id,
                'currency_id': record.currency_id.id,
                'quantity': 1.0,
                'price_unit': -record.amount,
            })
            record.write({'state': 'accepted', 'charge_id': charge.id})
        return True

    def action_reject(self):
        self.filtered(lambda row: row.state == 'draft').write({'state': 'rejected'})
        return True


class ZenlenetHook(models.Model):
    _name = 'zenlenet.hook'
    _description = '客户订阅'
    _order = 'id desc'

    partner_id = fields.Many2one('res.partner', string='客户', required=True)
    url = fields.Char(string='地址', required=True)
    event = fields.Selection([
        ('invoice', '账单'),
        ('ticket', '工单'),
        ('maintenance', '维护'),
    ], string='事件', required=True, default='invoice')
    active_hook = fields.Boolean(string='启用', default=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    def action_queue(self):
        """Record the intent. Delivery stays off until the subscription is enabled."""
        for record in self:
            if not record.active_hook:
                raise UserError('订阅还没启用。')
        return True


class ZenlenetLineProtect(models.Model):
    _inherit = 'zenlenet.line'

    protect_id = fields.Many2one('zenlenet.line', string='保护线路', index=True)


class ZenlenetDatacenterPower(models.Model):
    _inherit = 'zenlenet.datacenter'

    def action_check_power(self):
        for record in self:
            if not power_ok(record.power_used_kw, record.power_kw):
                raise UserError('已用电力超过容量。')
        return True

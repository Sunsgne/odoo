from datetime import timedelta

from odoo import api, fields, models

from .notices import NOTICES

STATES = [
    ('draft', '草稿'),
    ('review', '方案评审'),
    ('notify', '待通知'),
    ('notified', '已通知客户'),
    ('executing', '执行中'),
    ('verify', '业务验证'),
    ('done', '已完成'),
    ('cancel', '已取消'),
]
FLOW = [key for key, _label in STATES if key != 'cancel']
KINDS = [
    ('maintenance', '常规维护'),
    ('cutover', '割接迁移'),
    ('risk', '上游风险提示'),
    ('emergency', '紧急维护'),
    ('sdwan', '接入点 / SD-WAN'),
]


class ZenlenetMaintenance(models.Model):
    _name = 'zenlenet.maintenance'
    _description = '割接与维护'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, copy=False, default='/', tracking=True)
    kind = fields.Selection(KINDS, required=True, default='maintenance', tracking=True)
    partner_id = fields.Many2one('res.partner', string='客户', tracking=True)
    place = fields.Char(string='地区 / 节点', required=True, tracking=True)
    impact = fields.Text(string='影响范围')
    reason = fields.Char(string='事由')
    duration = fields.Char(string='预计影响', default='30分钟')
    window_start = fields.Datetime(string='开始（北京时间）')
    window_end = fields.Datetime(string='结束（北京时间）')
    subject = fields.Char(string='邮件主题')
    body = fields.Text(string='通知正文')
    state = fields.Selection(STATES, default='draft', required=True, tracking=True, group_expand='_group_expand_states')

    @api.model
    def _group_expand_states(self, states, domain):
        return [key for key, _label in STATES]

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('zenlenet.maintenance') or '/'
        records = super().create(vals_list)
        for record in records:
            if not record.subject or not record.body:
                record._fill_notice()
        return records

    def _fill_notice(self):
        subject, body = self._render_notice()
        self.write({'subject': subject, 'body': body})

    def _render_notice(self):
        self.ensure_one()
        start = self.window_start
        end = self.window_end
        values = {
            'place': self.place or '',
            'impact': self.impact or self.place or '',
            'reason': self.reason or '',
            'duration': self.duration or '30分钟',
            'start': fields.Datetime.to_string(start) if start else '',
            'end': fields.Datetime.to_string(end) if end else '',
            'utc_start': fields.Datetime.to_string(start - timedelta(hours=8)) if start else '',
            'utc_end': fields.Datetime.to_string(end - timedelta(hours=8)) if end else '',
        }
        stored = self.env['zenlenet.notice.template'].search([('kind', '=', self.kind)], limit=1)
        if stored:
            subject, body = stored.subject or '', stored.body or ''
        else:
            template = NOTICES.get(self.kind, NOTICES['maintenance'])
            subject, body = template['subject'], template['body']
        try:
            return subject.format(**values), body.format(**values)
        except (KeyError, IndexError, ValueError):
            return subject, body

    def action_refresh_notice(self):
        for record in self:
            record._fill_notice()

    def action_next(self):
        labels = dict(STATES)
        for record in self:
            if record.state not in FLOW:
                continue
            index = FLOW.index(record.state)
            if index >= len(FLOW) - 1:
                continue
            record.state = FLOW[index + 1]
            if record.state == 'notify':
                record._fill_notice()
            record.message_post(body=f'进入{labels[record.state]}')

    def action_prev(self):
        labels = dict(STATES)
        for record in self:
            if record.state not in FLOW:
                continue
            index = FLOW.index(record.state)
            if index == 0:
                continue
            record.state = FLOW[index - 1]
            record.message_post(body=f'退回{labels[record.state]}')

    def action_cancel(self):
        self.write({'state': 'cancel'})

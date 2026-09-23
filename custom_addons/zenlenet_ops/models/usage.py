"""Monthly bandwidth readings from Cacti, used for 95th-percentile billing."""

import base64
import csv
import io

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.billing import p95_billable, period_label


class ZenlenetUsage(models.Model):
    _name = 'zenlenet.usage'
    _description = '带宽用量（95 值）'
    _order = 'period desc, id desc'
    _rec_name = 'display_label'

    order_id = fields.Many2one('sale.order', string='服务订单', required=True, index=True, ondelete='cascade')
    partner_id = fields.Many2one(related='order_id.partner_id', string='客户', store=True, index=True)
    period = fields.Char(string='账期', required=True, index=True, help='格式 2026-09')
    p95_mbps = fields.Float(string='95 值 (Mbps)', required=True)
    max_mbps = fields.Float(string='峰值 (Mbps)')
    avg_mbps = fields.Float(string='均值 (Mbps)')
    commit_mbps = fields.Float(string='保底 (Mbps)', compute='_compute_billable', store=True)
    billable_mbps = fields.Float(string='计费 (Mbps)', compute='_compute_billable', store=True)
    overage_mbps = fields.Float(string='超量 (Mbps)', compute='_compute_billable', store=True)
    source = fields.Selection([('cacti', 'Cacti'), ('csv', 'CSV 导入'), ('manual', '手工')], default='manual', required=True)
    graph_ref = fields.Char(string='Cacti 图 ID')
    imported_at = fields.Datetime(string='采集时间', default=fields.Datetime.now)
    display_label = fields.Char(compute='_compute_label')

    _order_period_unique = models.Constraint('unique(order_id, period)', '同一订单同一账期只能有一条 95 值。')

    @api.depends('order_id', 'period', 'p95_mbps')
    def _compute_label(self):
        for record in self:
            record.display_label = f'{record.order_id.name or ""} {record.period or ""} · {record.p95_mbps:g}M'

    @api.depends('order_id.order_line.zenlenet_commit_mbps', 'order_id.order_line.product_uom_qty', 'p95_mbps')
    def _compute_billable(self):
        for record in self:
            line = record.order_id._zenlenet_bandwidth_line() if record.order_id else None
            commit = line._zenlenet_commit() if line else 0.0
            record.commit_mbps = commit
            record.billable_mbps = p95_billable(commit, record.p95_mbps)
            record.overage_mbps = max(record.billable_mbps - commit, 0.0)

    @api.model
    def upsert(self, order, period, p95, maximum=None, average=None, source='cacti', graph_ref=None):
        record = self.search([('order_id', '=', order.id), ('period', '=', period)], limit=1)
        values = {
            'p95_mbps': p95,
            'max_mbps': maximum if maximum is not None else (record.max_mbps if record else 0.0),
            'avg_mbps': average if average is not None else (record.avg_mbps if record else 0.0),
            'source': source,
            'graph_ref': graph_ref or (record.graph_ref if record else False),
            'imported_at': fields.Datetime.now(),
        }
        if record:
            record.write(values)
            return record
        return self.create(dict(values, order_id=order.id, period=period))

    @api.model
    def for_order(self, order, day):
        return self.search([('order_id', '=', order.id), ('period', '=', period_label(day))], limit=1)


class ZenlenetUsageImport(models.TransientModel):
    _name = 'zenlenet.usage.import'
    _description = '导入 95 值'

    period = fields.Char(string='账期', required=True, default=lambda self: period_label(fields.Date.context_today(self)))
    file = fields.Binary(string='CSV 文件', required=True)
    filename = fields.Char()
    note = fields.Char(readonly=True, default='列：订单号,95值Mbps,峰值Mbps,均值Mbps,图ID。订单号也可以填 Cacti 图 ID（先在订单上登记）。')

    def action_import(self):
        self.ensure_one()
        try:
            text = base64.b64decode(self.file or b'').decode('utf-8-sig')
        except UnicodeDecodeError as error:
            raise UserError('文件请用 UTF-8 编码保存。') from error
        Order = self.env['sale.order']
        Usage = self.env['zenlenet.usage']
        done, missing = 0, []
        for row in csv.reader(io.StringIO(text)):
            if not row or not row[0].strip() or row[0].strip().startswith('#'):
                continue
            key = row[0].strip()
            if key in ('订单号', 'order', 'order_id'):
                continue
            order = Order.search(['|', ('name', '=', key), ('zenlenet_graph_ref', '=', key)], limit=1)
            if not order:
                missing.append(key)
                continue

            def number(index):
                try:
                    return float(row[index]) if len(row) > index and row[index].strip() else None
                except ValueError:
                    return None

            p95 = number(1)
            if p95 is None:
                missing.append(key)
                continue
            Usage.upsert(order, self.period.strip(), p95, number(2), number(3), source='csv',
                         graph_ref=row[4].strip() if len(row) > 4 else None)
            done += 1
        message = f'导入 {done} 条。'
        if missing:
            message += f' 没匹配到订单：{"、".join(missing[:10])}{" …" if len(missing) > 10 else ""}'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': '95 值导入', 'message': message, 'type': 'success' if done else 'warning',
                       'sticky': bool(missing), 'next': {'type': 'ir.actions.act_window_close'}},
        }

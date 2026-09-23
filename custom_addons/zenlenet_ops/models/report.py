"""Report values for the console PDFs.

Every printout goes through one of these AbstractModels so the templates only
render prepared, human-readable rows. Codes and technical keys are stripped
before they reach paper.
"""

from odoo import api, fields, models

from odoo.addons.zenlenet_ops.billing import clean_label

SERVICE_LABELS = {
    'ipt': 'IPT / RMIPT 带宽',
    'pl': '专线',
    'sdwan': 'SD-WAN',
    'vm': '云主机',
    'colo': '托管',
    'resale': '转售',
    'ip': 'IP地址',
    'line': '线路',
}
STATUS_LABELS = {
    'allocated': ('已分配', 'ok'),
    'free': ('未分配', 'muted'),
    'reserved': ('预分配', 'info'),
    'transferring': ('调库中', 'warn'),
    'returning': ('出库中', 'warn'),
    'testing': ('测试', 'info'),
    'internal': ('自用', 'muted'),
}
PAYMENT_LABELS = {
    'not_paid': ('未收款', 'warn'),
    'partial': ('部分收款', 'warn'),
    'paid': ('已收款', 'ok'),
    'in_payment': ('收款中', 'info'),
    'reversed': ('已冲销', 'muted'),
    'blocked': ('已锁定', 'muted'),
    'invoicing_legacy': ('历史', 'muted'),
}


def _label(selection, value):
    return dict(selection).get(value, value or '')


class ReportBase(models.AbstractModel):
    _name = 'zenlenet.report.base'
    _description = '打印基础'

    def _company_block(self):
        company = self.env.company
        return {
            'name': company.name,
            'address': ' '.join(part for part in (company.street, company.street2, company.city, company.zip) if part),
            'country': company.country_id.name or '',
            'vat': company.vat or '',
            'email': company.email or '',
            'phone': company.phone or '',
            'website': company.website or '',
            'logo': company.logo,
        }

    def _order_rows(self, orders):
        rows = []
        for order in orders:
            for line in order.order_line.filtered(lambda item: not item.display_type):
                product = line.product_id
                code = product.default_code or ''
                rows.append({
                    'order': order.name,
                    'kind': SERVICE_LABELS.get(code, product.name or ''),
                    'name': clean_label(line.name) or product.name,
                    'qty': line.product_uom_qty,
                    'unit': 'Mbps' if code in ('ipt', 'pl', 'sdwan') else ('台' if code in ('vm', 'colo') else '项'),
                    'price': line.price_unit,
                    'subtotal': line.price_subtotal,
                    'stage': _label(order._fields['zenlenet_stage'].selection, order.zenlenet_stage),
                })
        return rows

    def _address_rows(self, addresses):
        rows = []
        for address in addresses:
            label, tone = STATUS_LABELS.get(address.status, (address.status, 'muted'))
            rows.append({
                'address': address.address,
                'block': address.block or '',
                'datacenter': address.datacenter_id.name or address.pop or '',
                'net_attr': address.net_attr or '',
                'status': label,
                'tone': tone,
                'usage': address.usage or '',
            })
        return rows

    def _line_rows(self, lines):
        return [{
            'name': line.name,
            'kind': _label(line._fields['kind'].selection, line.kind),
            'a_end': line.a_end or '',
            'z_end': line.z_end or '',
            'bandwidth': line.bandwidth or '',
            'datacenter': line.datacenter_id.name or '',
            'stopped': line.stopped,
        } for line in lines]

    def _base_values(self, docids, model, title, code):
        docs = self.env[model].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': model,
            'docs': docs,
            'company': self._company_block(),
            'title': title,
            'doc_code': code,
            'today': fields.Date.context_today(self),
            'currency': self.env.company.currency_id,
        }


class ReportQuotation(models.AbstractModel):
    _name = 'report.zenlenet_ops.report_quotation_document'
    _inherit = 'zenlenet.report.base'
    _description = '报价单'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = self._base_values(docids, 'sale.order', '服务报价单', 'QUOTE')
        values['rows_by_doc'] = {doc.id: self._order_rows(doc) for doc in values['docs']}
        values['validity'] = {
            doc.id: doc.validity_date or fields.Date.add(doc.date_order.date(), days=30)
            for doc in values['docs']
        }
        return values


class ReportContract(models.AbstractModel):
    _name = 'report.zenlenet_ops.report_contract_document'
    _inherit = 'zenlenet.report.base'
    _description = '合同'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = self._base_values(docids, 'zenlenet.contract', '网络服务协议', 'CONTRACT')
        Address = self.env['zenlenet.address'].sudo()
        Line = self.env['zenlenet.line'].sudo()
        rows, addresses, lines = {}, {}, {}
        for doc in values['docs']:
            rows[doc.id] = self._order_rows(doc.order_ids)
            addresses[doc.id] = self._address_rows(Address.search([
                ('partner_id', '=', doc.partner_id.id),
                ('status', 'in', ('allocated', 'testing')),
            ], order='datacenter_id, address', limit=200))
            lines[doc.id] = self._line_rows(Line.search([
                ('partner_id', '=', doc.partner_id.id), ('stopped', '=', False),
            ], limit=100))
        items = {}
        for doc in values['docs']:
            items[doc.id] = [{
                'kind': '一次性' if item.kind == 'one_time' else dict(item._fields['cycle'].selection).get(item.cycle, ''),
                'one_time': item.kind == 'one_time',
                'name': item.name,
                'qty': item.quantity,
                'price': item.price_unit,
                'amount': item.amount,
            } for item in doc.item_ids.sorted(lambda item: (item.kind != 'recurring', item.sequence, item.id))]
        values.update({
            'items_by_doc': items,
            'rows_by_doc': rows,
            'addresses_by_doc': addresses,
            'lines_by_doc': lines,
            'cycle_label': lambda doc: _label(doc._fields['billing_cycle'].selection, doc.billing_cycle),
        })
        return values


class ReportInvoice(models.AbstractModel):
    _name = 'report.zenlenet_ops.report_invoice_document'
    _inherit = 'zenlenet.report.base'
    _description = '账单'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = self._base_values(docids, 'account.move', '服务账单', 'INVOICE')
        footer = self.env['ir.config_parameter'].sudo().get_param('zenlenet.invoice_footer', '')
        rows, payment = {}, {}
        for doc in values['docs']:
            rows[doc.id] = [{
                'name': clean_label(line.name) or line.product_id.name or '',
                'kind': SERVICE_LABELS.get(line.product_id.default_code or '', ''),
                'qty': line.quantity,
                'price': line.price_unit,
                'subtotal': line.price_subtotal,
            } for line in doc.invoice_line_ids.filtered(lambda item: item.display_type == 'product')]
            payment[doc.id] = PAYMENT_LABELS.get(doc.payment_state, (doc.payment_state or '', 'muted'))
        values.update({'rows_by_doc': rows, 'payment_by_doc': payment, 'footer_note': footer})
        return values


class ReportDelivery(models.AbstractModel):
    _name = 'report.zenlenet_ops.report_delivery_document'
    _inherit = 'zenlenet.report.base'
    _description = '交付验收单'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = self._base_values(docids, 'zenlenet.flow', '交付验收单', 'DELIVERY')
        resources, tasks = {}, {}
        for doc in values['docs']:
            items = []
            for item in doc.resource_ids:
                detail, extra = '', ''
                if item.order_id:
                    detail = item.order_id.name
                    extra = '；'.join(
                        f'{clean_label(line.name) or line.product_id.name} × {line.product_uom_qty:g}'
                        for line in item.order_id.order_line.filtered(lambda line: not line.display_type)
                    )
                elif item.address_id:
                    detail = item.address_id.address
                    label, _tone = STATUS_LABELS.get(item.address_id.status, (item.address_id.status, ''))
                    extra = ' · '.join(part for part in (
                        item.address_id.datacenter_id.name or item.address_id.pop, item.address_id.net_attr, label,
                    ) if part)
                elif item.line_id:
                    detail = item.line_id.name
                    extra = ' → '.join(part for part in (item.line_id.a_end, item.line_id.z_end) if part)
                    if item.line_id.bandwidth:
                        extra = f'{extra} · {item.line_id.bandwidth}' if extra else item.line_id.bandwidth
                items.append({
                    'kind': SERVICE_LABELS.get(item.service_type, item.service_type),
                    'detail': detail,
                    'extra': extra,
                    'spec': item.spec or '',
                })
            for address in doc.address_ids:
                if not any(item['detail'] == address.address for item in items):
                    items.append({'kind': 'IP地址', 'detail': address.address, 'extra': address.pop or '', 'spec': ''})
            resources[doc.id] = items
            tasks[doc.id] = [{
                'stage': _label(task._fields['stage'].selection, task.stage),
                'name': task.name,
                'user': task.user_id.name or '',
                'done': task.done,
                'done_at': task.done_at,
            } for task in doc.task_ids]
        values.update({
            'resources_by_doc': resources,
            'tasks_by_doc': tasks,
            'state_label': lambda doc: _label(doc._fields['state'].selection, doc.state),
            'kind_label': lambda doc: _label(doc._fields['kind'].selection, doc.kind),
        })
        return values


class ReportNotice(models.AbstractModel):
    _name = 'report.zenlenet_ops.report_notice_document'
    _inherit = 'zenlenet.report.base'
    _description = '维护通知'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = self._base_values(docids, 'zenlenet.maintenance', '维护通知', 'NOTICE')
        values['kind_label'] = lambda doc: _label(doc._fields['kind'].selection, doc.kind)
        values['state_label'] = lambda doc: _label(doc._fields['state'].selection, doc.state)
        return values

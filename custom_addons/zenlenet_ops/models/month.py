"""Natural-month billing board: one row per customer, quote → contract → bill → resources."""

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang

from odoo.addons.zenlenet_ops.billing import (
    CYCLE_WORD,
    STATUS_LABEL,
    STATUS_RANK,
    bandwidth_lines,
    billing_anchor,
    customer_month_status,
    fee_applies,
    next_due_month,
    parse_period,
    period_bounds,
    period_label,
    period_ref,
    period_title,
    refine_month_status,
    shift_month,
    state_for_month,
    worst_status,
)

from .settings import param_int

CONTRACT_STATE = {
    'draft': '草稿',
    'active': '执行中',
    'expiring': '即将到期',
    'expired': '已到期',
    'terminated': '已终止',
}
QUOTE_STATE = {'draft': '报价草稿', 'sent': '已发给客户'}
ORDER_STAGE = {'testing': '测试', 'active': '在网', 'terminated': '已退租'}
PAYMENT = {
    'not_paid': '未收款',
    'partial': '部分收款',
    'paid': '已收款',
    'in_payment': '收款中',
    'reversed': '已红冲',
}
PREFIX_STATUS = {'container': '容器', 'active': '在用', 'reserved': '预留', 'deprecated': '已弃用'}
LINE_STATUS = {
    'planned': '规划中', 'provisioning': '开通中', 'active': '在用',
    'offline': '离线', 'deprovisioning': '拆除中', 'decommissioned': '已终止',
}
ADDRESS_STATUS = {
    'allocated': '已分配', 'reserved': '预分配', 'transferring': '调库中',
    'returning': '出库中', 'testing': '测试',
}
OPEN_VIEWS = {
    'quote': ('sale.order', 'zenlenet_ops.view_quote_form', '报价'),
    'order': ('sale.order', 'zenlenet_ops.view_quote_form', '订单'),
    'contract': ('zenlenet.contract', 'zenlenet_ops.view_contract_form', '合同'),
    'invoice': ('account.move', 'zenlenet_ops.view_invoice_form', '账单'),
}
RESOURCE_CAP = 8


class _Bucket:
    def __init__(self):
        self.due = 0.0
        self.invoiced = 0.0
        self.residual = 0.0
        self.drafts = 0
        self.posted = 0


class ZenlenetMonth(models.Model):
    _inherit = 'zenlenet.contract'

    # ------------------------------------------------------------------ board
    @api.model
    def month_board(self, period=None, shift=0, include_holders=False):
        payload = self._month_payload(period, shift, include_holders=bool(include_holders))
        payload.update(self._month_access())
        return payload

    @api.model
    def month_customer(self, partner_id, period=None):
        detail = self._month_detail(int(partner_id), period)
        detail.update(self._month_access())
        return detail

    @api.model
    def month_bill(self, partner_id=None, period=None):
        if not self.env.user.has_group('zenlenet_ops.group_finance'):
            raise UserError('只有财务可以出账。')
        ctx = self._period_context(period, 0)
        domain = [('state', 'in', ('active', 'expiring', 'expired'))]
        company = None
        if partner_id:
            partner = self.env['res.partner'].browse(int(partner_id)).exists()
            if not partner:
                raise UserError('没有这个客户。')
            company = partner.commercial_partner_id
            domain.append(('partner_id', 'child_of', company.id))
        created = already = skipped = 0
        Move = self.env['account.move']
        for contract in self.search(domain):
            if state_for_month(contract.state, contract.end_date, ctx['first']) != 'active':
                continue
            ref = period_ref(contract.partner_id.id, ctx['anchor'])
            if Move.search_count([
                ('ref', '=', ref), ('zenlenet_contract_id', '=', contract.id), ('state', '!=', 'cancel'),
            ]):
                already += 1
                continue
            if contract._create_period_invoice(ctx['anchor']):
                created += 1
            else:
                skipped += 1
        who = '这个客户' if company else '全部客户'
        message = f'{ctx["title"]} · {who}：新出 {created} 张，已有 {already} 张，{skipped} 份合同这个月没有要收的费用。'
        return {'created': created, 'already': already, 'skipped': skipped, 'message': message}

    @api.model
    def month_post(self, invoice_id):
        if not self.env.user.has_group('zenlenet_ops.group_finance'):
            raise UserError('只有财务可以确认账单。')
        invoice = self.env['account.move'].browse(int(invoice_id)).exists()
        if not invoice or invoice.move_type not in ('out_invoice', 'out_refund'):
            raise UserError('没有这张账单。')
        if invoice.state == 'draft':
            invoice.action_post()
        return True

    @api.model
    def month_open(self, kind, res_id):
        if kind not in OPEN_VIEWS:
            raise UserError('打不开这个记录。')
        if kind in ('quote', 'order') and not self.env.user.has_group('zenlenet_ops.group_sales'):
            raise UserError('只有销售可以打开报价和订单。')
        if kind == 'invoice' and not self.env.user.has_group('zenlenet_ops.group_finance'):
            raise UserError('只有财务可以打开账单。')
        model, view, name = OPEN_VIEWS[kind]
        record = self.env[model].browse(int(res_id)).exists()
        if not record:
            raise UserError('记录已经不在了。')
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'res_id': record.id,
            'view_mode': 'form',
            'views': [(self.env.ref(view).id, 'form')],
            'target': 'new',
        }

    @api.model
    def month_new_quote(self, partner_id=None):
        if not self.env.user.has_group('zenlenet_ops.group_sales'):
            raise UserError('只有销售可以新建报价。')
        context = {'default_state': 'draft'}
        if partner_id:
            partner = self.env['res.partner'].browse(int(partner_id)).exists()
            if partner:
                context['default_partner_id'] = partner.commercial_partner_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': '新建报价',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'views': [(self.env.ref('zenlenet_ops.view_quote_form').id, 'form')],
            'target': 'new',
            'context': context,
        }

    # ----------------------------------------------------------------- internals
    def _month_access(self):
        user = self.env.user
        return {
            'can_bill': user.has_group('zenlenet_ops.group_finance'),
            'can_quote': user.has_group('zenlenet_ops.group_sales'),
        }

    def _period_context(self, period, shift):
        today = fields.Date.context_today(self)
        day = shift_month(parse_period(period, today), shift)
        first, last = period_bounds(day)
        return {
            'day': day,
            'today': today,
            'first': first,
            'last': last,
            'label': period_label(day),
            'title': period_title(day),
            'anchor': billing_anchor(day, param_int(self.env, 'zenlenet.billing_day', 1), today),
        }

    def _money(self, amount, currency):
        amount = round(float(amount or 0.0), 2)
        if not currency:
            currency = self.env.company.currency_id
        return amount, formatLang(self.env, amount, currency_obj=currency)

    def _company(self, partner):
        if not partner:
            return self.env['res.partner']
        return partner.commercial_partner_id or partner

    def _ensure(self, found, partner):
        company = self._company(partner)
        if not company:
            return None
        row = found.get(company.id)
        if row:
            return row
        currency = company.zenlenet_currency_id or self.env.company.currency_id
        row = {
            'partner': company,
            'currency': currency,
            'contracts': self.env['zenlenet.contract'],
            'quotes': self.env['sale.order'],
            'invoices': self.env['account.move'],
            'buckets': {},
            'cycles': set(),
            'next_period': None,
            'item_count': 0,
            'running': 0,
            'draft_contracts': 0,
            'resources': 0,
        }
        found[company.id] = row
        return row

    def _bucket(self, row, currency):
        currency = currency or row['currency']
        bucket = row['buckets'].get(currency.id)
        if not bucket:
            bucket = _Bucket()
            row['buckets'][currency.id] = bucket
        return bucket, currency

    def _month_index(self, ctx):
        day, today, first, last, label = ctx['day'], ctx['today'], ctx['first'], ctx['last'], ctx['label']
        current = label == period_label(today)
        found = {}

        contracts = self.env['zenlenet.contract'].sudo().search([
            ('state', '!=', 'terminated'),
            ('start_date', '<=', last),
            '|', ('end_date', '=', False), ('end_date', '>=', first),
        ])
        contracts.mapped('item_ids.order_line_id')
        order_ids = contracts.mapped('item_ids.order_line_id.order_id').ids
        usages = {
            usage.order_id.id: usage
            for usage in self.env['zenlenet.usage'].sudo().search([
                ('order_id', 'in', order_ids), ('period', '=', label),
            ])
        }
        for contract in contracts:
            row = self._ensure(found, contract.partner_id)
            if not row:
                continue
            row['contracts'] |= contract
            logical = state_for_month(contract.state, contract.end_date, first)
            if logical == 'draft':
                row['draft_contracts'] += 1
            if logical == 'active':
                row['running'] += 1
                if contract.billing_cycle:
                    row['cycles'].add(contract.billing_cycle)
            for item in contract.item_ids:
                applies = self._item_applies(item, logical, day, first, last)
                if logical == 'active':
                    row['item_count'] += 1
                    if item.kind == 'recurring' and item.cycle:
                        row['cycles'].add(item.cycle)
                    if not applies and item.kind == 'recurring':
                        nxt = next_due_month(item.cycle, item.start_date or contract.start_date, day)
                        if nxt != label and (not row['next_period'] or nxt < row['next_period']):
                            row['next_period'] = nxt
                if not applies:
                    continue
                amount, _estimate = self._fee_amount(item, usages)
                bucket, _currency = self._bucket(row, contract.currency_id)
                bucket.due += amount

        ref_like = f'ZL-{label.replace("-", "")}-%'
        moves = self.env['account.move'].sudo().search([
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '!=', 'cancel'),
            '|',
            '&', ('invoice_date', '>=', first), ('invoice_date', '<=', last),
            '&', ('invoice_date', '=', False), ('ref', '=like', ref_like),
        ])
        for move in moves:
            row = self._ensure(found, move.partner_id)
            if not row:
                continue
            row['invoices'] |= move
            sign = -1 if move.move_type == 'out_refund' else 1
            bucket, _currency = self._bucket(row, move.currency_id)
            bucket.invoiced += sign * (move.amount_total or 0.0)
            if move.state == 'draft' and move.move_type == 'out_invoice':
                bucket.drafts += 1
            elif move.state == 'posted':
                bucket.posted += 1
                bucket.residual += sign * (move.amount_residual or 0.0)

        quotes = self.env['sale.order'].sudo().search([
            ('state', 'in', ('draft', 'sent')), ('zenlenet_stage', '=', False),
        ])
        for quote in quotes:
            local = fields.Datetime.context_timestamp(self, quote.date_order).date() if quote.date_order else None
            if not current and not (local and first <= local <= last):
                continue
            row = self._ensure(found, quote.partner_id)
            if row:
                row['quotes'] |= quote

        naked_count = 0
        if current:
            naked_ids = [partner_id for partner_id in self._holder_ids() if partner_id not in found]
            naked_count = len(naked_ids)
            if ctx.get('include_holders'):
                Partner = self.env['res.partner'].sudo()
                for partner_id in naked_ids:
                    self._ensure(found, Partner.browse(partner_id))

        self._apply_credits(found, moves, ctx)
        counts = self._resource_maps(list(found))
        for partner_id, row in found.items():
            prefix_count, address_count, line_count = counts.get(partner_id, (0, 0, 0))
            row['prefix_count'] = prefix_count
            row['address_count'] = address_count
            row['line_count'] = line_count
            row['resources'] = prefix_count + address_count + line_count
            self._finish_row(row, label)
        return found, naked_count

    def _item_applies(self, item, logical, day, first, last):
        """Rules for a new bill, plus a one-time fee already sitting on this month's invoice."""
        if fee_applies(logical, item.kind, item.cycle, day, item.start_date, item.end_date, item.billed):
            return True
        invoice = item.invoice_id
        if logical != 'active' or item.kind != 'one_time' or not item.billed or not invoice or invoice.state == 'cancel':
            return False
        return bool(invoice.invoice_date and first <= invoice.invoice_date <= last)

    def _fee_amount(self, item, usages):
        if not (item.p95 and item.order_line_id):
            return item.amount or 0.0, False
        line = item.order_line_id
        usage = usages.get(line.order_id.id)
        p95 = usage.p95_mbps if usage else None
        parts = bandwidth_lines(line._zenlenet_commit(), p95, item.price_unit, line.zenlenet_overage_price)
        return round(sum(mbps * price for _kind, mbps, price in parts), 2), p95 is None

    def _apply_credits(self, found, moves, ctx):
        if not found:
            return
        credits = self.env['zenlenet.credit'].sudo().search([
            ('partner_id', 'in', list(found)),
            ('state', 'in', ('approved', 'applied')),
            ('apply_mode', '=', 'next_invoice'),
        ])
        current = ctx['label'] == period_label(ctx['today'])
        move_ids = set(moves.ids)
        for credit in credits:
            row = found.get(credit.partner_id.commercial_partner_id.id)
            if not row or not credit.currency_id:
                continue
            take = False
            if credit.state == 'applied' and credit.invoice_id.id in move_ids:
                take = True
            elif credit.state == 'approved' and current:
                take = True
            if not take:
                continue
            bucket = row['buckets'].get(credit.currency_id.id)
            if not bucket:
                bucket, _currency = self._bucket(row, credit.currency_id)
            bucket.due -= credit.amount or 0.0

    def _finish_row(self, row, label):
        primary = row['currency']
        if primary.id not in row['buckets']:
            self._bucket(row, primary)
        quote_only = bool(row['quotes']) and not row['contracts'] and not row['invoices']
        statuses = []
        gaps = []
        for currency_id, bucket in row['buckets'].items():
            currency = self.env['res.currency'].browse(currency_id)
            status, gap = customer_month_status(
                bucket.due, bucket.invoiced, bucket.residual, bucket.drafts, bucket.posted,
                quote_only=quote_only and currency == primary,
            )
            statuses.append(status)
            if gap:
                _amount, text = self._money(abs(gap), currency)
                gaps.append(f'{currency.name} 规则比账单多 {text}' if gap > 0 else f'{currency.name} 账单比规则多 {text}')
        status = refine_month_status(
            worst_status(statuses), row['running'], row['draft_contracts'], bool(row['resources']), row['item_count'],
        )
        row['status'] = status
        row['gaps'] = gaps
        words = [CYCLE_WORD[key] for key in ('monthly', 'quarterly', 'yearly') if key in row['cycles']]
        rhythm = '、'.join(words)
        if row['next_period'] and row['next_period'] != label and row['status'] == 'skip':
            rhythm = f'{rhythm} · 下次 {row["next_period"]}' if rhythm else f'下次 {row["next_period"]}'
        if not rhythm:
            rhythm = '还没有合同' if not row['contracts'] else '未定周期'
        row['rhythm'] = rhythm

    def _holder_ids(self):
        ids = set()
        groups = (
            ('zenlenet.prefix', [('partner_id', '!=', False), ('status', '!=', 'deprecated')]),
            ('zenlenet.address', [('partner_id', '!=', False), ('status', 'not in', ('free', 'internal'))]),
            ('zenlenet.line', [('partner_id', '!=', False), ('status', '!=', 'decommissioned')]),
        )
        for model, domain in groups:
            for partner, in self.env[model].sudo()._read_group(domain, ['partner_id']):
                if partner:
                    ids.add(partner.commercial_partner_id.id)
        return ids

    def _resource_maps(self, partner_ids):
        """{partner_id: (prefixes, addresses, lines)} for the customers on this page."""
        if not partner_ids:
            return {}
        wanted = set(partner_ids)
        maps = {partner_id: [0, 0, 0] for partner_id in partner_ids}
        groups = (
            (0, 'zenlenet.prefix', [('status', '!=', 'deprecated')]),
            (1, 'zenlenet.address', [('status', 'not in', ('free', 'internal'))]),
            (2, 'zenlenet.line', [('status', '!=', 'decommissioned')]),
        )
        for index, model, domain in groups:
            grouped = self.env[model].sudo()._read_group(
                [('partner_id', '!=', False)] + domain, ['partner_id'], ['__count'],
            )
            for partner, count in grouped:
                if not partner:
                    continue
                key = partner.commercial_partner_id.id
                if key in wanted:
                    maps[key][index] += count
        return {key: tuple(value) for key, value in maps.items()}

    def _sales_name(self, row):
        partner = row['partner']
        if partner.zenlenet_manager_id:
            return partner.zenlenet_manager_id.name
        for contract in row['contracts']:
            if contract.sales_user_id:
                return contract.sales_user_id.name
        for quote in row['quotes']:
            if quote.user_id:
                return quote.user_id.name
        return ''

    def _month_payload(self, period, shift, include_holders=False):
        ctx = self._period_context(period, shift)
        ctx['include_holders'] = bool(include_holders)
        found, naked_count = self._month_index(ctx)
        rows = [self._row_payload(row) for row in found.values()]
        rows.sort(key=lambda row: (STATUS_RANK.get(row['status'], 99), row['name'] or ''))
        totals = {}
        for row in found.values():
            for currency_id, bucket in row['buckets'].items():
                currency = self.env['res.currency'].browse(currency_id)
                slot = totals.setdefault(currency.id, {'currency': currency, 'due': 0.0, 'invoiced': 0.0, 'residual': 0.0})
                slot['due'] += bucket.due
                slot['invoiced'] += bucket.invoiced
                slot['residual'] += bucket.residual
        total_rows = []
        for slot in sorted(totals.values(), key=lambda item: item['currency'].name or ''):
            currency = slot['currency']
            _due, due_label = self._money(slot['due'], currency)
            _invoiced, invoiced_label = self._money(slot['invoiced'], currency)
            _residual, residual_label = self._money(slot['residual'], currency)
            total_rows.append({
                'currency': currency.name,
                'due_label': due_label,
                'invoiced_label': invoiced_label,
                'residual_label': residual_label,
            })
        return {
            'period': ctx['label'],
            'title': ctx['title'],
            'today_period': period_label(ctx['today']),
            'rows': rows,
            'totals': total_rows,
            'count': len(rows),
            'naked_count': naked_count,
        }

    def _row_payload(self, row):
        partner = row['partner']
        primary = row['currency']
        bucket = row['buckets'].get(primary.id) or _Bucket()
        _due, due_label = self._money(bucket.due, primary)
        _invoiced, invoiced_label = self._money(bucket.invoiced, primary)
        _residual, residual_label = self._money(bucket.residual, primary)
        extras = []
        for currency_id, other in row['buckets'].items():
            if currency_id == primary.id:
                continue
            currency = self.env['res.currency'].browse(currency_id)
            _amount, label = self._money(other.due, currency)
            extras.append(f'{currency.name} {label}')
        return {
            'id': partner.id,
            'name': partner.name or '',
            'code': partner.zenlenet_code or '',
            'sales': self._sales_name(row),
            'currency': primary.name or '',
            'due_label': due_label,
            'invoiced_label': invoiced_label,
            'residual_label': residual_label,
            'extra_label': ('另有 ' + '、'.join(extras)) if extras else '',
            'status': row['status'],
            'status_label': STATUS_LABEL.get(row['status'], ''),
            'bill_label': self._bill_label(row['status'], invoiced_label, residual_label),
            'gaps': row['gaps'],
            'rhythm': row['rhythm'],
            'quotes': len(row['quotes']),
            'contracts': len(row['contracts']),
            'resources': row['resources'],
            'resource_label': self._resource_label(
                row.get('prefix_count', 0), row.get('address_count', 0), row.get('line_count', 0),
            ),
        }

    def _bill_label(self, status, invoiced_label, residual_label):
        if status == 'draft':
            return f'草稿 {invoiced_label}'
        if status == 'mixed':
            return f'含草稿 · 未收 {residual_label}'
        if status in ('unpaid', 'partial'):
            return f'未收 {residual_label}'
        if status == 'paid':
            return '已收清'
        if status == 'missing':
            return '还没有账单'
        return '—'

    def _resource_label(self, prefixes, addresses, lines):
        parts = []
        if prefixes:
            parts.append(f'{prefixes} 段')
        if addresses:
            parts.append(f'{addresses} 个地址')
        if lines:
            parts.append(f'{lines} 条线路')
        return ' · '.join(parts) if parts else '未挂资源'

    def _month_detail(self, partner_id, period):
        ctx = self._period_context(period, 0)
        partner = self.env['res.partner'].sudo().browse(partner_id).exists()
        if not partner:
            raise UserError('没有这个客户。')
        company = partner.commercial_partner_id
        found, _naked_count = self._month_index(ctx)
        row = found.get(company.id)
        if not row:
            row = self._ensure(found, company)
            counts = self._resource_maps([company.id]).get(company.id, (0, 0, 0))
            row['prefix_count'], row['address_count'], row['line_count'] = counts
            row['resources'] = sum(counts)
            self._finish_row(row, ctx['label'])
        payload = self._row_payload(row)
        payload.update({
            'quotes': [self._quote_payload(quote) for quote in row['quotes'].sorted('id', reverse=True)],
            'contracts': [self._contract_payload(contract, ctx) for contract in row['contracts'].sorted('id')],
            'invoices': [self._invoice_payload(move) for move in row['invoices'].sorted('invoice_date')],
            'resources': self._resource_payload(company.id),
        })
        return payload

    def _quote_payload(self, quote):
        local = fields.Datetime.context_timestamp(self, quote.date_order).date() if quote.date_order else None
        _monthly, monthly = self._money(quote.amount_untaxed, quote.currency_id)
        _setup, setup = self._money(quote.zenlenet_setup_total, quote.currency_id)
        return {
            'id': quote.id,
            'name': quote.name or '报价',
            'date': local.isoformat() if local else '',
            'monthly_label': monthly,
            'setup_label': setup,
            'user': quote.user_id.name or '',
            'state_label': QUOTE_STATE.get(quote.state, quote.state or ''),
        }

    def _contract_payload(self, contract, ctx):
        logical = state_for_month(contract.state, contract.end_date, ctx['first'])
        usages = {
            usage.order_id.id: usage
            for usage in self.env['zenlenet.usage'].sudo().search([
                ('order_id', 'in', contract.item_ids.mapped('order_line_id.order_id').ids),
                ('period', '=', ctx['label']),
            ])
        }
        items = []
        due = 0.0
        for item in contract.item_ids.sorted('sequence'):
            applies = self._item_applies(item, logical, ctx['day'], ctx['first'], ctx['last'])
            amount = (self._fee_amount(item, usages)[0] if applies else item.amount) or 0.0
            if applies:
                due += amount
            _shown, label = self._money(amount, contract.currency_id)
            items.append({
                'name': item.name or '',
                'due': applies,
                'amount_label': label,
            })
        _due, due_label = self._money(due, contract.currency_id)
        orders = []
        for order in contract.order_ids:
            _amount, amount_label = self._money(order.amount_untaxed, order.currency_id)
            orders.append({
                'id': order.id,
                'name': order.name or '',
                'stage_label': ORDER_STAGE.get(order.zenlenet_stage, '已确认'),
                'amount_label': amount_label,
            })
        return {
            'id': contract.id,
            'name': contract.name or '',
            'title': contract.title or '',
            'state_label': CONTRACT_STATE.get(contract.state, ''),
            'cycle_label': CYCLE_WORD.get(contract.billing_cycle, ''),
            'start': contract.start_date.isoformat() if contract.start_date else '',
            'end': contract.end_date.isoformat() if contract.end_date else '',
            'due_label': due_label,
            'items': items,
            'orders': orders,
        }

    def _invoice_payload(self, move):
        _amount, amount_label = self._money(move.amount_total, move.currency_id)
        _residual, residual_label = self._money(move.amount_residual, move.currency_id)
        name = move.name if move.name and move.name != '/' else '草稿'
        return {
            'id': move.id,
            'name': name,
            'date': move.invoice_date.isoformat() if move.invoice_date else '',
            'amount_label': amount_label,
            'residual_label': residual_label,
            'state': move.state,
            'kind': '退款' if move.move_type == 'out_refund' else '账单',
            'payment': PAYMENT.get(move.payment_state, '') if move.state == 'posted' else '草稿',
            'contract': move.zenlenet_contract_id.name or '',
        }

    def _resource_payload(self, partner_id):
        Prefix = self.env['zenlenet.prefix'].sudo()
        Address = self.env['zenlenet.address'].sudo()
        Line = self.env['zenlenet.line'].sudo()
        prefix_domain = [('partner_id', 'child_of', partner_id), ('status', '!=', 'deprecated')]
        line_domain = [('partner_id', 'child_of', partner_id), ('status', '!=', 'decommissioned')]
        address_domain = [('partner_id', 'child_of', partner_id), ('status', 'not in', ('free', 'internal'))]
        prefixes = Prefix.search(prefix_domain, limit=RESOURCE_CAP, order='prefix')
        lines = Line.search(line_domain, limit=RESOURCE_CAP, order='name')
        addresses = []
        for status, count in Address._read_group(address_domain, ['status'], ['__count']):
            addresses.append({'label': ADDRESS_STATUS.get(status, status or ''), 'count': count})
        addresses.sort(key=lambda item: item['label'])
        return {
            'prefixes': [{
                'id': prefix.id,
                'name': prefix.prefix or '',
                'dc': prefix.datacenter_id.name or '',
                'status_label': PREFIX_STATUS.get(prefix.status, ''),
            } for prefix in prefixes],
            'prefix_more': max(Prefix.search_count(prefix_domain) - len(prefixes), 0),
            'lines': [{
                'id': line.id,
                'name': line.name or '',
                'bandwidth': line.bandwidth or (f'{line.commit_rate}M' if line.commit_rate else ''),
                'dc': line.datacenter_id.name or '',
                'status_label': LINE_STATUS.get(line.status, ''),
            } for line in lines],
            'line_more': max(Line.search_count(line_domain) - len(lines), 0),
            'addresses': addresses,
        }

"""Billing periods and contract terms. No Odoo imports."""

import calendar
from datetime import date, timedelta

NOTICE_DAYS = 30
CYCLE_MONTHS = {'monthly': 1, 'quarterly': 3, 'yearly': 12}


def clean_label(text):
    """Drop a leading "[code] " prefix and surrounding whitespace from a line description."""
    text = (text or '').strip()
    if text.startswith('[') and ']' in text:
        text = text.split(']', 1)[1].strip()
    return text


def add_months(day, months):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def period_label(day):
    return f'{day.year:04d}-{day.month:02d}'


def period_ref(partner_id, day):
    return f'ZL-{period_label(day).replace("-", "")}-{partner_id}'


def period_bounds(day):
    first = day.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return first, last


def period_title(day):
    return f'{day.year}年{day.month}月'


def parse_period(text, today):
    """YYYY-MM, or today when the text is empty or not a real month."""
    text = (text or '').strip()
    if len(text) >= 7 and text[4] == '-':
        try:
            year, month = int(text[:4]), int(text[5:7])
            return date(year, month, 1)
        except ValueError:
            pass
    return today.replace(day=1)


def shift_month(day, step):
    return add_months(day.replace(day=1), int(step or 0))


def billing_anchor(day, billing_day, today):
    """Invoice date inside this natural month.

    The configured billing day is clamped to the month. In the current month it
    never lands in the future.
    """
    first, last = period_bounds(day)
    number = min(max(int(billing_day or 1), 1), last.day)
    anchor = first.replace(day=number)
    if period_label(day) == period_label(today) and anchor > today:
        return today
    return anchor


CYCLE_WORD = {'monthly': '月结', 'quarterly': '季结', 'yearly': '年结'}

STATUS_LABEL = {
    'missing': '未出账',
    'naked': '有资源无合同',
    'no_items': '没有费用条款',
    'draft_contract': '合同未执行',
    'unpaid': '待收款',
    'partial': '部分收款',
    'draft': '账单草稿',
    'mixed': '还有草稿',
    'quote': '待确认报价',
    'skip': '本月不出',
    'paid': '已收清',
}

STATUS_HINT = {
    'missing': '这个自然月按合同该收，账单还没出。',
    'naked': '资源已经在客户名下，但没有执行中的合同，出不了账。',
    'no_items': '合同在执行，但没有费用条款，这个月出不了账。',
    'draft_contract': '合同还是草稿。开始执行以后才会按月出账。',
    'unpaid': '账单已确认，款还没收。',
    'partial': '收了一部分。',
    'draft': '账单还是草稿，确认后才能收款。',
    'mixed': '有的账单确认了，还有草稿没确认。',
    'quote': '报价还没确认。确认后才会生成合同草稿。',
    'skip': '合同在，但这个自然月不轮到出账。',
    'paid': '这个月的账单已经收清。',
}

STATUS_RANK = {
    'missing': 0,
    'naked': 1,
    'no_items': 2,
    'draft_contract': 3,
    'unpaid': 4,
    'partial': 5,
    'draft': 6,
    'mixed': 7,
    'quote': 8,
    'skip': 9,
    'paid': 10,
}


def state_for_month(state, end, month_first):
    """How a contract reads for one natural month.

    Draft and terminated stay as they are. A running contract, even one that
    has since expired, still bills a month that started on or before its end.
    """
    if state in ('draft', 'terminated'):
        return state
    if end and month_first > end:
        return 'expired'
    if state in ('active', 'expiring', 'expired'):
        return 'active'
    return state


def fee_due(kind, cycle, day, start, end, billed):
    """Whether a fee belongs on the natural month that contains day.

    Recurring fees bill on their anniversary and only while the fee window
    overlaps that month. A one-time fee bills on the first month that ends on
    or after its start, and never again once it has been billed.
    """
    first, last = period_bounds(day)
    if kind == 'one_time':
        if billed:
            return False
        if start and start > last:
            return False
        return True
    if end and end < first:
        return False
    if start and start > last:
        return False
    return bills_this_period(cycle or 'monthly', day, start)


def fee_applies(contract_state, kind, cycle, day, start, end, billed):
    if contract_state not in ('active', 'expiring'):
        return False
    return fee_due(kind, cycle, day, start, end, billed)


def next_due_month(cycle, start, day):
    """First YYYY-MM on or after day.month when this cycle bills."""
    months = CYCLE_MONTHS.get(cycle or 'monthly', 1)
    anchor = (start or day).replace(day=1)
    current = day.replace(day=1)
    if anchor > current:
        cursor = anchor
    else:
        elapsed = (current.year - anchor.year) * 12 + current.month - anchor.month
        cursor = add_months(current, (months - elapsed % months) % months)
    return period_label(cursor)


def fee_note(contract_state, kind, cycle, day, start, end, billed, due, p95=False, estimate=False):
    if contract_state == 'draft':
        return '合同还没开始执行，不出账'
    if contract_state in ('expired', 'terminated'):
        return '合同已结束'
    if due:
        if p95 and estimate:
            return '本月出 · 95 值还没导入，先按保底估'
        if p95:
            return '本月出 · 按 95 值'
        if kind == 'one_time':
            return '本月出 · 一次性，只收这一次'
        return f'本月出 · {CYCLE_WORD.get(cycle or "monthly", "月结")}'
    if kind == 'one_time' and billed:
        return '一次性已经出过'
    first, last = period_bounds(day)
    if start and start > last:
        return f'{period_label(start)} 才开始计费'
    if end and end < first:
        return '已停止计费'
    nxt = next_due_month(cycle, start, day)
    word = CYCLE_WORD.get(cycle or 'monthly', '月结')
    if nxt != period_label(day):
        return f'{word}，下次 {nxt}'
    return '本月不出'


def customer_month_status(due, invoiced, residual, drafts, posted, quote_only=False):
    """Money status for one customer in one currency. Gap is due minus invoiced."""
    due = round(float(due or 0), 2)
    invoiced = round(float(invoiced or 0), 2)
    residual = round(float(residual or 0), 2)
    drafts = int(drafts or 0)
    posted = int(posted or 0)
    if quote_only and not drafts and not posted:
        status = 'quote'
    elif posted and drafts:
        status = 'mixed'
    elif drafts:
        status = 'draft'
    elif posted and residual <= 0.009:
        status = 'paid'
    elif posted and abs(residual) + 0.009 < abs(invoiced):
        status = 'partial'
    elif posted:
        status = 'unpaid'
    elif abs(due) > 0.009:
        status = 'missing'
    else:
        status = 'skip'
    gap = round(due - invoiced, 2) if (drafts or posted) else 0.0
    if abs(gap) <= 0.009:
        gap = 0.0
    return status, gap


def worst_status(statuses):
    ranked = [status for status in statuses if status in STATUS_RANK]
    if not ranked:
        return 'skip'
    return min(ranked, key=lambda status: STATUS_RANK[status])


def refine_month_status(status, running, draft_contracts, resources, item_count):
    """A quiet month still says why, when the customer is not actually billing-ready."""
    if status == 'skip' and running and not item_count:
        return 'no_items'
    if status == 'skip' and not running and draft_contracts:
        return 'draft_contract'
    if status in ('skip', 'quote') and not running and resources:
        return 'naked'
    return status


def contract_end(start, term_months):
    if not start or not term_months or term_months <= 0:
        return None
    return add_months(start, term_months) - timedelta(days=1)


def contract_status(state, end, today, notice_days=NOTICE_DAYS):
    """Return the state a running contract should carry today."""
    if state not in ('active', 'expiring', 'expired'):
        return state
    if not end:
        return 'active'
    if today > end:
        return 'expired'
    if (end - today).days <= notice_days:
        return 'expiring'
    return 'active'


def cycle_amount(monthly, cycle):
    return round((monthly or 0.0) * CYCLE_MONTHS.get(cycle, 1), 2)


def bills_this_period(cycle, day, start):
    """A monthly contract bills every month; quarterly and yearly bill on anniversaries only."""
    months = CYCLE_MONTHS.get(cycle, 1)
    if months == 1 or not start:
        return True
    elapsed = (day.year - start.year) * 12 + day.month - start.month
    return elapsed >= 0 and elapsed % months == 0


def p95_billable(commit, p95):
    """Billable megabits for a burstable service: never below the commit."""
    return max(float(commit or 0), float(p95 or 0))


def bandwidth_lines(commit, p95, price, overage_price=None):
    """Split a burstable month into (kind, mbps, unit price) parts.

    kind is 'commit' for the guaranteed part and 'overage' for traffic above it.
    Without a 95th-percentile reading the commit is billed as usual.
    """
    commit = float(commit or 0)
    if p95 is None:
        return [('commit', commit, price)]
    p95 = float(p95)
    if p95 <= commit:
        return [('commit', commit, price)]
    if overage_price:
        return [('commit', commit, price), ('overage', round(p95 - commit, 2), overage_price)]
    return [('commit', round(p95, 2), price)]


def credit_amount(monthly_fee, method, hours=0.0, rate=0.0, amount=0.0, cap_ratio=1.0):
    """Service credit for an outage.

    method 'hours'   : hours × rate% of the monthly fee per hour
    method 'percent' : rate% of the monthly fee
    method 'amount'  : a fixed amount
    The result never exceeds cap_ratio × monthly fee.
    """
    fee = float(monthly_fee or 0.0)
    if method == 'hours':
        value = fee * float(rate or 0.0) / 100.0 * float(hours or 0.0)
    elif method == 'percent':
        value = fee * float(rate or 0.0) / 100.0
    else:
        value = float(amount or 0.0)
    cap = fee * float(cap_ratio if cap_ratio is not None else 1.0)
    return round(max(0.0, min(value, cap)) if cap > 0 else max(0.0, value), 2)


def outage_hours(start, end):
    if not start or not end or end <= start:
        return 0.0
    return round((end - start).total_seconds() / 3600.0, 2)

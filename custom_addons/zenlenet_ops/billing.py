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

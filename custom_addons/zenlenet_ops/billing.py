"""Billing periods and contract terms. No Odoo imports."""

import calendar
from datetime import date, timedelta

NOTICE_DAYS = 30
CYCLE_MONTHS = {'monthly': 1, 'quarterly': 3, 'yearly': 12}


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

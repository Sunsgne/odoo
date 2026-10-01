"""Billing measurements that do not depend on obss.

95th percentile is nearest-rank on the aggregated series. Missing samples stay
missing. A counter that goes backwards is a restart, not negative usage.
"""

import math
from datetime import date


def parse_samples(text):
    """Comma-separated samples. A blank slot is missing, not zero."""
    if text is None:
        return []
    slots = []
    for part in str(text).replace('，', ',').split(','):
        raw = part.strip()
        if not raw:
            slots.append(None)
            continue
        slots.append(float(raw))
    return slots


def nearest_rank_p95(values):
    """Ascending nearest-rank: the ceil(0.95 * N)-th valid sample, 1-based."""
    valid = [float(value) for value in values if value is not None]
    if not valid:
        return None
    ordered = sorted(valid)
    rank = math.ceil(0.95 * len(ordered))
    return ordered[rank - 1]


def aggregate_series(columns):
    """Sum aligned samples. A timestamp with no reading stays missing."""
    width = max((len(column) for column in columns), default=0)
    totals = []
    for index in range(width):
        present = []
        for column in columns:
            if index < len(column) and column[index] is not None:
                present.append(float(column[index]))
        totals.append(sum(present) if present else None)
    return totals


def counter_bps(delta_bytes, seconds):
    """Bits per second from a counter delta. A restart returns None."""
    if delta_bytes is None or seconds is None:
        return None
    delta = float(delta_bytes)
    window = float(seconds)
    if delta < 0 or window <= 0:
        return None
    return delta * 8.0 / window


def prorate(amount, active_start, period_start, period_end):
    """Day-count share of amount. period_end is exclusive."""
    if not isinstance(active_start, date) or not isinstance(period_start, date) or not isinstance(period_end, date):
        return 0.0
    total = (period_end - period_start).days
    start = active_start if active_start > period_start else period_start
    if total <= 0 or start >= period_end:
        return 0.0
    days = (period_end - start).days
    return round(float(amount or 0) * days / total, 2)


def commit_overage_amount(p95, commit, commit_price, overage_price):
    """Untaxed charge: commit stays billed, only the part above it uses the overage price."""
    measured = float(p95 or 0)
    floor = float(commit or 0)
    if measured <= floor:
        return round(floor * float(commit_price or 0), 2)
    overage = measured - floor
    return round(floor * float(commit_price or 0) + overage * float(overage_price or 0), 2)

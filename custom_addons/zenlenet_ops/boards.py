"""Layout numbers for the asset, campus, and purchase boards."""

from datetime import timedelta


def share(part, total):
    if not total:
        return 0
    return round(100 * part / total)


def place_bucket(availability, repair_state):
    if repair_state == 'repairing' or availability == 'repair':
        return 'repair'
    if availability == 'loan':
        return 'loan'
    if availability == 'in_rack':
        return 'in_rack'
    if availability == 'stock':
        return 'stock'
    return 'unknown'


def warranty_bucket(today, end):
    if not end:
        return 'unknown'
    if end < today - timedelta(days=365):
        return 'expired_year'
    if end < today:
        return 'expired'
    if end <= today + timedelta(days=365):
        return 'within_year'
    return 'over_year'


def power_ratio(used, capacity):
    used = used or 0
    capacity = capacity or 0
    if capacity <= 0:
        return {'percent': 0, 'over': used > 0}
    percent = round(100 * used / capacity)
    return {'percent': min(percent, 100), 'over': used > capacity}


def top_counts(pairs, limit=12):
    found = {}
    for key, count in pairs:
        label = (key or '').strip()
        if not label:
            continue
        found[label] = found.get(label, 0) + count
    rows = sorted(found.items(), key=lambda item: (-item[1], item[0]))
    return [{'label': label, 'count': count} for label, count in rows[:limit]]

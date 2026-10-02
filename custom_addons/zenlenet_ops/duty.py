"""Duty roster rules that do not depend on obss."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ('一', '二', '三', '四', '五', '六', '日')
TRANSITIONS = {
    ('draft', 'submit'): 'peer',
    ('peer', 'peer'): 'lead',
    ('lead', 'approve'): 'approved',
    ('peer', 'refuse'): 'refused',
    ('lead', 'refuse'): 'refused',
    ('peer', 'withdraw'): 'withdrawn',
    ('lead', 'withdraw'): 'withdrawn',
}


def parse_hhmm(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ':':
        return None
    hour, minute = value.split(':')
    if not (hour.isdigit() and minute.isdigit()):
        return None
    hour, minute = int(hour), int(minute)
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def overnight(start, end):
    start_m = parse_hhmm(start)
    end_m = parse_hhmm(end)
    if start_m is None or end_m is None:
        return False
    return end_m <= start_m


def week_start(day, starts_on):
    """Return the first day of the week. starts_on is 6 for Sunday, 0 for Monday."""
    delta = (day.weekday() - starts_on) % 7
    return day - timedelta(days=delta)


def week_days(day, starts_on='sun'):
    anchor = 6 if starts_on == 'sun' else 0
    start = week_start(day, anchor)
    return [start + timedelta(days=offset) for offset in range(7)]


def month_days(day, starts_on='sun'):
    first = day.replace(day=1)
    if day.month == 12:
        last = day.replace(year=day.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        last = day.replace(month=day.month + 1, day=1) - timedelta(days=1)
    start = week_start(first, 6 if starts_on == 'sun' else 0)
    days = []
    cursor = start
    while cursor <= last:
        days.append(cursor)
        cursor += timedelta(days=1)
    while len(days) % 7:
        days.append(days[-1] + timedelta(days=1))
    return days


def weekday_label(day):
    return WEEKDAYS[day.weekday()]


def offset_label(tz_name, day):
    try:
        zone = ZoneInfo(tz_name or 'UTC')
    except Exception:
        zone = ZoneInfo('UTC')
    moment = datetime.combine(day, time(12), zone)
    offset = moment.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = '+' if minutes >= 0 else '-'
    minutes = abs(minutes)
    return f'UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}'


def coverage(rows):
    need = sum(int(row.get('need') or 0) for row in rows)
    filled = sum(int(row.get('filled') or 0) for row in rows)
    rate = round(100 * filled / need) if need else 0
    return {'need': need, 'filled': filled, 'rate': rate}


def person_counts(rows):
    found = {}
    for row in rows:
        for person in row.get('people') or []:
            key = person.get('id')
            found[key] = found.get(key, 0) + 1
    return sorted(found.items(), key=lambda item: (-item[1], item[0] or 0))


def apply_swap(from_members, to_members, applicant, target):
    source = set(from_members)
    dest = set(to_members)
    if applicant not in source or target not in dest or applicant == target:
        return None
    source.discard(applicant)
    dest.discard(target)
    source.add(target)
    dest.add(applicant)
    return source, dest


def next_state(state, event):
    return TRANSITIONS.get((state, event))

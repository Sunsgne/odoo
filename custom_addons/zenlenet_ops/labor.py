"""Field-labor pricing. Clock time and the billed quantity are separate.

A one-hour visit can still be billed as one half-day. The fee is the billed
quantity times the unit price in the currency written on the record.
"""


def clock_hours(start, end):
    """Hours between two clock strings. Equal or unreadable clocks are zero."""
    begin = _clock(start)
    finish = _clock(end)
    if begin is None or finish is None or finish <= begin:
        return 0.0
    return round(finish - begin, 2)


def _clock(text):
    raw = (text or '').strip().replace('：', ':')
    if not raw or ':' not in raw:
        return None
    hour_text, minute_text = raw.split(':', 1)
    minute_text = minute_text.split(':', 1)[0]
    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None
    if hour < 0 or hour > 47 or minute < 0 or minute > 59:
        return None
    return hour + minute / 60.0


def labor_amount(quantity, price):
    return round(float(quantity or 0) * float(price or 0), 2)

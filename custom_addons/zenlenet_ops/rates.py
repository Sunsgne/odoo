import json
import re
import urllib.request
import xml.etree.ElementTree as ET

MAJORS = ('USD', 'EUR', 'GBP', 'HKD', 'JPY', 'AUD', 'CAD', 'SGD', 'CHF', 'CNY')

FRANKFURTER_URL = 'https://api.frankfurter.dev/v1/latest'
ECB_URL = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'

_DATE = re.compile(r'\d{4}-\d{2}-\d{2}$')


def rates_per_company(per_base, base, company):
    """Units of each currency per 1 unit of ``company``.

    ``per_base`` maps a currency code to units of that currency per 1 unit of
    ``base``. ``base`` itself is treated as 1 even when the map omits it.
    """
    table = {str(code): float(value) for code, value in per_base.items()}
    table[base] = float(table.get(base, 1.0))
    if company not in table:
        raise ValueError(company)
    pivot = table[company]
    if pivot <= 0:
        raise ValueError(company)
    converted = {code: value / pivot for code, value in table.items()}
    converted[company] = 1.0
    return converted


def _day(value):
    day = str(value or '')
    if not _DATE.fullmatch(day):
        raise ValueError(day)
    return day


def frankfurter_url(company, codes):
    targets = ','.join(code for code in codes if code != company)
    return f'{FRANKFURTER_URL}?from={company}&to={targets}'


def parse_frankfurter(payload, company):
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8')
    if isinstance(payload, str):
        payload = json.loads(payload)
    base = payload.get('base') or company
    rates = payload.get('rates') or {}
    if not rates:
        raise ValueError('empty')
    return rates_per_company(rates, base, company), _day(payload.get('date'))


def parse_ecb(payload, company):
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8')
    root = ET.fromstring(payload)
    day = None
    rates = {}
    for node in root.iter():
        if day is None and node.attrib.get('time'):
            day = node.attrib['time']
        code = node.attrib.get('currency')
        rate = node.attrib.get('rate')
        if code and rate:
            rates[code] = float(rate)
    if not rates:
        raise ValueError('empty')
    rates['EUR'] = 1.0
    return rates_per_company(rates, 'EUR', company), _day(day)


def fetch_bytes(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={'User-Agent': 'zenlenet-ops', 'Accept': 'application/json, application/xml, */*'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(1_000_000)


def pull(company):
    """Rates for the major currencies, as units of foreign currency per 1 ``company`` unit."""
    company = (company or '').upper()
    if not company:
        raise ValueError('company')
    targets = [code for code in MAJORS if code != company]
    frankfurter_error = None
    try:
        table, day = parse_frankfurter(fetch_bytes(frankfurter_url(company, targets)), company)
        missing = [code for code in targets if code not in table]
        if missing:
            raise ValueError('missing')
    except Exception as exc:
        frankfurter_error = exc
    else:
        return _keep(table, company), day
    try:
        table, day = parse_ecb(fetch_bytes(ECB_URL), company)
    except Exception as exc:
        raise exc from frankfurter_error
    if company not in table:
        raise ValueError(company) from frankfurter_error
    return _keep(table, company), day


def _keep(table, company):
    table[company] = 1.0
    keep = [code for code in MAJORS if code in table]
    if company not in keep:
        keep.append(company)
    return {code: table[code] for code in keep}

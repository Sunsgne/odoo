"""Turn a prefix into the /24s Ping0 should be asked about, and read its answer.

Ping0 classifies a segment, so one host stands for the whole /24.
No Odoo imports: the daily job and the tests both call these helpers.
"""

import ipaddress
from urllib.parse import quote

# A container bigger than this is not exploded into every /24. Child prefixes
# and addresses already recorded inside it are checked on their own.
MIN_PREFIXLEN = 16
FRESH_HOURS = 20
DAILY_LIMIT = 2000
BUTTON_LIMIT = 16


def slash24s(text):
    """/24 networks covered by this prefix. Empty for IPv6 and for blocks larger than /16."""
    try:
        network = ipaddress.ip_network(str(text or '').strip(), strict=False)
    except ValueError:
        return []
    if network.version != 4:
        return []
    if network.prefixlen > 24:
        return [ipaddress.ip_network(f'{network.network_address}/24', strict=False)]
    if network.prefixlen == 24:
        return [network]
    if network.prefixlen >= MIN_PREFIXLEN:
        return list(network.subnets(new_prefix=24))
    return []


def block24_of(address):
    text = str(address or '').split('/')[0].strip()
    try:
        host = ipaddress.ip_address(text)
    except ValueError:
        return ''
    if host.version != 4:
        return ''
    return str(ipaddress.ip_network(f'{host}/24', strict=False))


def sample_host(network):
    try:
        return str(next(network.hosts()))
    except StopIteration:
        return str(network.network_address)


def lookup_url(key, ip):
    return f'https://ping0.cc/apiloc/apikey({quote(str(key), safe="")})/ip({quote(str(ip), safe="")})'


def labels(payload):
    """Map Ping0's JSON onto the words the address page shows. None when the call failed."""
    if not isinstance(payload, dict) or payload.get('error'):
        return None
    isidc = payload.get('isidc')
    if isidc is True:
        ip_type = 'IDC机房 IP'
    elif isidc is False:
        ip_type = '家庭宽带 IP'
    else:
        ip_type = ''
    native = payload.get('isnative')
    if native is True:
        ip_native = '原生 IP'
    elif native is False:
        ip_native = '广播 IP'
    else:
        ip_native = ''
    risk = payload.get('iprisk')
    if risk is None or risk == '':
        risk_value = None
    else:
        try:
            risk_value = int(risk)
        except (TypeError, ValueError):
            risk_value = None
    return {
        'ip_type': ip_type,
        'ip_native': ip_native,
        'ip_risk': risk_value,
        'location': payload.get('location') or '',
        'asn': str(payload.get('asn') or ''),
    }


def auth_failed(status, payload):
    if status in (401, 403):
        return True
    if isinstance(payload, dict):
        message = str(payload.get('error') or '').lower()
        if message and any(word in message for word in ('token', 'apikey', 'api key', 'unauthorized')):
            return True
    return False

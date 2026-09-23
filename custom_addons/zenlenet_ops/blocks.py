"""IP block labels shared by the address import. No Odoo imports."""

import ipaddress


def prefix_block(version, address, prefixlen):
    text = f'{address}/{prefixlen}'
    try:
        network = ipaddress.ip_network(text, strict=False)
    except ValueError:
        return text
    if network.version == 4 and int(prefixlen or 32) == 32:
        return str(ipaddress.ip_network(f'{network.network_address}/24', strict=False))
    return str(network)


def parse_prefix(text):
    network = ipaddress.ip_network(str(text or '').strip(), strict=False)
    return str(network)

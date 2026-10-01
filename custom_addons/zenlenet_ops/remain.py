"""Rules for the work that still sits beside the live console.

Executors here are simulators. They do not log into machines, call cloud
APIs, or post invoices.
"""

ROLLOUT = ('shadow', 'hold', 'change', 'bill')


def should_apply(current_version, incoming_version):
    """An older event must not roll a newer version backwards."""
    if incoming_version is None:
        return False
    if current_version is None:
        return True
    return int(incoming_version) >= int(current_version)


def inventory_export_allowed(is_finance, is_manager):
    return bool(is_finance or is_manager)


def next_rollout(state):
    try:
        index = ROLLOUT.index(state)
    except ValueError:
        return None
    if index + 1 >= len(ROLLOUT):
        return None
    return ROLLOUT[index + 1]


def next_job(state, has_evidence):
    """Execute lands on unknown. Verified requires evidence."""
    if state == 'draft':
        return 'planned'
    if state == 'planned':
        return 'unknown'
    if state == 'unknown' and has_evidence:
        return 'verified'
    return None


def can_resell(evidenced):
    return bool(evidenced)


def shadow_delta(contract_amount, charge_amount):
    return round(float(contract_amount or 0) - float(charge_amount or 0), 2)


def power_ok(used, capacity):
    if not capacity:
        return True
    return float(used or 0) <= float(capacity)


def portal_partner_id(is_internal, commercial_partner_id):
    """Internal users stay in the backend. Portal users are scoped to their company."""
    if is_internal or not commercial_partner_id:
        return False
    return commercial_partner_id

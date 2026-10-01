"""Rules for bindings, operations, holds, changes, and exit checklists."""

EXIT_KINDS = ('commercial', 'technical', 'metering', 'capacity', 'supplier')


def operation_result(existing_hash, new_hash):
    """Same key: identical payload is a replay, a different payload is a conflict."""
    if not existing_hash or not new_hash:
        return 'missing'
    if existing_hash == new_hash:
        return 'same'
    return 'conflict'


def hold_allows(hold_order_id, allocating_order_id):
    """None means there is no hold. 0 means the hold names no order and blocks everyone."""
    if hold_order_id is None:
        return True
    if not hold_order_id:
        return False
    return hold_order_id == allocating_order_id


def can_rebind(tombstoned):
    return not tombstoned


def capacity_ready(done_kinds):
    done = set(done_kinds or [])
    return 'technical' in done and 'metering' in done


def pick_remote(by_external_id, name_owner, remote_id, remote_name, tombstoned_ids=()):
    """How a remote row attaches to a local one.

    ``name_owner`` maps a display name to the external id already stored on that
    row, or 0 when the row has never been linked. A tombstoned id is not attached
    to a different row by name. The same id coming back updates its own row.
    """
    tombstoned = set(tombstoned_ids or ())
    if remote_id in by_external_id:
        return 'id'
    if remote_id in tombstoned:
        return 'tombstone'
    owner = name_owner.get(remote_name)
    if owner is None:
        return 'new'
    if not owner:
        return 'first'
    if owner == remote_id:
        return 'id'
    return 'conflict'


def http_policy(status):
    """401 and 403 stop. 429 and 5xx can be retried. Other errors fail once."""
    code = int(status or 0)
    if code in (401, 403):
        return 'stop'
    if code == 429 or code >= 500:
        return 'retry'
    if code >= 300:
        return 'fail'
    return 'ok'


def payload_hash(text):
    import hashlib
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()

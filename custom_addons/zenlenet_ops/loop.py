"""Rules for bindings, operations, holds, changes, and exit checklists."""

EXIT_KINDS = ('commercial', 'technical', 'metering', 'capacity', 'supplier')


def operation_result(existing_hash, new_hash):
    """Same key: identical payload is a replay, a different payload is a conflict."""
    if not existing_hash or not new_hash:
        return 'missing'
    if existing_hash == new_hash:
        return 'same'
    return 'conflict'


def can_rebind(tombstoned):
    return not tombstoned


def capacity_ready(done_kinds):
    done = set(done_kinds or [])
    return 'technical' in done and 'metering' in done


def payload_hash(text):
    import hashlib
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()

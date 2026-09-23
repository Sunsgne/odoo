"""Person-assigned handoff. No Odoo imports."""

# Which concrete resource a demand line may hold. Anything else (云主机、托管、转售) needs no network resource.
RESOURCE_SLOT = {
    'ipt': 'prefix',
    'ip': 'prefix',
    'ip_single': 'address',
    'pl': 'line',
    'sdwan': 'line',
    'line': 'line',
}


def resource_slot(service_type):
    return RESOURCE_SLOT.get(service_type)


def normalize_assignment(service_type, prefix_id=None, address_id=None, line_id=None, resource_ref=None):
    """A demand line holds exactly one resource, and only the kind its business uses.

    ``resource_ref`` (``model,id``) is accepted so older callers keep working. Returns
    ``(prefix_id, address_id, line_id)`` with the unused slots cleared.
    """
    if resource_ref and not any((prefix_id, address_id, line_id)):
        model, _, raw = str(resource_ref).partition(',')
        try:
            rid = int(raw)
        except (TypeError, ValueError):
            rid = None
        if model == 'zenlenet.prefix':
            prefix_id = rid
        elif model == 'zenlenet.address':
            address_id = rid
        elif model == 'zenlenet.line':
            line_id = rid
    slot = resource_slot(service_type)
    if slot == 'prefix':
        return prefix_id or None, None, None
    if slot == 'address':
        return None, address_id or None, None
    if slot == 'line':
        return None, None, line_id or None
    return None, None, None


def resource_reference(prefix_id, address_id, line_id):
    if prefix_id:
        return f'zenlenet.prefix,{prefix_id}'
    if address_id:
        return f'zenlenet.address,{address_id}'
    if line_id:
        return f'zenlenet.line,{line_id}'
    return False


STATES = [
    ('company', '录入客户'),
    ('allocate', '分配资源'),
    ('deliver', '交付'),
    ('accept', '验收'),
    ('decide', '测试结论'),
    ('reclaim', '回收'),
    ('done', '完成'),
    ('cancel', '已取消'),
]

MOVES = ('out', 'in', 'back', 'cutover')
BUSINESS = ('company', 'allocate', 'deliver', 'accept', 'done')
TEST = ('company', 'allocate', 'deliver', 'accept', 'decide', 'reclaim', 'done')
INBOUND = ('company', 'allocate', 'deliver', 'done')
RETURN = ('company', 'reclaim', 'done')
CUTOVER = ('company', 'deliver', 'allocate', 'accept', 'done')
CONVERT_FROM = ('accept', 'decide', 'reclaim')
RECLAIM_FROM = ('accept', 'decide')
STEP_LABELS = {
    'out': dict(STATES),
    'in': {
        'company': '登记来源', 'allocate': '核对资源', 'deliver': '确认入库',
        'done': '完成', 'cancel': '已取消',
    },
    'back': {
        'company': '登记退回', 'reclaim': '回收资源', 'done': '完成', 'cancel': '已取消',
    },
    'cutover': {
        'company': '割接方案', 'deliver': '通知客户', 'allocate': '更换资源',
        'accept': '业务验证', 'done': '完成', 'cancel': '已取消',
    },
}


def path_for(move, kind):
    move = move or 'out'
    if move == 'in':
        return INBOUND
    if move == 'back':
        return RETURN
    if move == 'cutover':
        return CUTOVER
    return TEST if kind == 'test' else BUSINESS


def next_state(kind, state, move='out'):
    if (move or 'out') == 'out' and kind == 'test' and state in ('accept', 'decide'):
        return None
    path = path_for(move, kind)
    if state not in path:
        return None
    index = path.index(state)
    if index >= len(path) - 1:
        return None
    return path[index + 1]


def prev_state(kind, state, move='out'):
    path = path_for(move, kind)
    if state not in path:
        return None
    index = path.index(state)
    if index == 0:
        return None
    return path[index - 1]


def can_convert(kind, state, move='out'):
    return (move or 'out') == 'out' and kind == 'test' and state in CONVERT_FROM


def can_reclaim(kind, state, move='out'):
    return (move or 'out') == 'out' and kind == 'test' and state in RECLAIM_FROM


def transition_allowed(kind, state, new_kind, new_state, move='out', new_move=None):
    move = move or 'out'
    new_move = new_move or move
    if new_move != move:
        return state == 'company' and new_state == 'company' and new_kind == kind
    if new_kind == kind and new_state == state:
        return True
    if state in ('done', 'cancel'):
        return False
    if new_state == 'cancel' and new_kind == kind:
        return True
    if move != 'out':
        if new_kind != kind:
            return False
        return new_state in (next_state(kind, state, move), prev_state(kind, state, move))
    if new_kind == kind and new_state == next_state(kind, state, move):
        return True
    if new_kind == kind and new_state == prev_state(kind, state, move):
        return True
    if new_kind == kind and new_state == 'reclaim' and can_reclaim(kind, state, move):
        return True
    if new_kind == 'business' and new_state == 'deliver' and can_convert(kind, state, move):
        return True
    if state == 'company' and new_state == 'company' and new_kind != kind:
        return True
    return False


def state_label(state):
    return dict(STATES).get(state, state)


def step_label(move, state):
    return STEP_LABELS.get(move or 'out', STEP_LABELS['out']).get(state, state_label(state))


def team_for(state):
    if state == 'company':
        return 'sales'
    if state in ('allocate', 'deliver'):
        return 'delivery'
    if state in ('accept', 'decide', 'reclaim', 'done'):
        return 'service'
    return None


def team_for_move(move, state):
    """Who presses the button at this step. 出 keeps the sales → delivery → service handoff."""
    move = move or 'out'
    if move == 'out':
        return team_for(state)
    if move == 'in':
        return 'delivery' if state in ('company', 'allocate', 'deliver') else None
    if move == 'back':
        if state == 'company':
            return 'sales'
        if state == 'reclaim':
            return 'delivery'
        return 'service' if state == 'done' else None
    if move == 'cutover':
        if state in ('company', 'allocate'):
            return 'delivery'
        if state in ('deliver', 'accept', 'done'):
            return 'service'
    return None

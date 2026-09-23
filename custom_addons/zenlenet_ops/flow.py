"""Person-assigned handoff. No Odoo imports."""

STATES = [
    ('company', '录入公司'),
    ('allocate', '分配资源'),
    ('deliver', '交付'),
    ('accept', '验收'),
    ('decide', '测试结论'),
    ('reclaim', '回收'),
    ('done', '完成'),
    ('cancel', '已取消'),
]

BUSINESS = ('company', 'allocate', 'deliver', 'accept', 'done')
TEST = ('company', 'allocate', 'deliver', 'accept', 'decide', 'reclaim', 'done')
CONVERT_FROM = ('accept', 'decide', 'reclaim')
RECLAIM_FROM = ('accept', 'decide')


def _path(kind):
    return TEST if kind == 'test' else BUSINESS


def next_state(kind, state):
    if kind == 'test' and state == 'decide':
        return None
    path = _path(kind)
    if state not in path:
        return None
    index = path.index(state)
    if index >= len(path) - 1:
        return None
    return path[index + 1]


def prev_state(kind, state):
    path = _path(kind)
    if state not in path:
        return None
    index = path.index(state)
    if index == 0:
        return None
    return path[index - 1]


def can_convert(kind, state):
    return kind == 'test' and state in CONVERT_FROM


def can_reclaim(kind, state):
    return kind == 'test' and state in RECLAIM_FROM


def transition_allowed(kind, state, new_kind, new_state):
    if new_kind == kind and new_state == state:
        return True
    if state in ('done', 'cancel'):
        return False
    if new_state == 'cancel' and new_kind == kind:
        return True
    if new_kind == kind and new_state == next_state(kind, state):
        return True
    if new_kind == kind and new_state == prev_state(kind, state):
        return True
    if new_kind == kind and new_state == 'reclaim' and can_reclaim(kind, state):
        return True
    if new_kind == 'business' and new_state == 'deliver' and can_convert(kind, state):
        return True
    if state == 'company' and new_state == 'company' and new_kind != kind:
        return True
    return False


def state_label(state):
    return dict(STATES).get(state, state)


def team_for(state):
    if state == 'company':
        return 'sales'
    if state in ('allocate', 'deliver'):
        return 'delivery'
    if state in ('accept', 'decide', 'reclaim', 'done'):
        return 'service'
    return None

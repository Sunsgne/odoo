"""Ticket SLA and state order. No Odoo imports."""

from datetime import timedelta

STATES = [
    ('new', '新建'),
    ('assigned', '已派单'),
    ('processing', '处理中'),
    ('waiting', '等待客户'),
    ('resolved', '已解决'),
    ('closed', '已关闭'),
    ('cancel', '已取消'),
]
FLOW = ('new', 'assigned', 'processing', 'resolved', 'closed')
PRIORITIES = [
    ('0', '低'),
    ('1', '普通'),
    ('2', '高'),
    ('3', '紧急'),
]
SLA_HOURS = {'0': 72, '1': 24, '2': 8, '3': 4}
KINDS = [
    ('fault', '故障'),
    ('change', '变更'),
    ('consult', '咨询'),
    ('complaint', '投诉'),
]


def sla_hours(priority):
    return SLA_HOURS.get(str(priority), SLA_HOURS['1'])


def due_at(opened, priority):
    if not opened:
        return None
    return opened + timedelta(hours=sla_hours(priority))


def next_state(state):
    if state == 'waiting':
        return 'processing'
    if state not in FLOW:
        return None
    index = FLOW.index(state)
    if index >= len(FLOW) - 1:
        return None
    return FLOW[index + 1]


def prev_state(state):
    if state == 'waiting':
        return 'processing'
    if state not in FLOW:
        return None
    index = FLOW.index(state)
    if index == 0:
        return None
    return FLOW[index - 1]


def is_open(state):
    return state not in ('closed', 'cancel')


def is_overdue(state, due, now):
    return bool(due) and state not in ('resolved', 'closed', 'cancel') and now > due


def state_label(state):
    return dict(STATES).get(state, state)

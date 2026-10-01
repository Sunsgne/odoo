"""Public path of this console.

The application framework still owns its own client prefix. These helpers
only rewrite the paths this module chooses itself.
"""

CONSOLE = '/obss'
_LEGACY = '/odoo'


def console_path(path):
    if not isinstance(path, str) or not path:
        return path
    if path == _LEGACY or path.startswith(_LEGACY + '/') or path.startswith(_LEGACY + '?'):
        return CONSOLE + path[len(_LEGACY):]
    if path == '/web' or path.startswith('/web?'):
        return CONSOLE + path[len('/web'):]
    return path

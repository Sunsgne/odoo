from odoo import http
from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.session import Session
from odoo.addons.web.controllers.utils import is_user_internal
from odoo.http import request

from odoo.addons.zenlenet_ops.console_path import CONSOLE, console_path


class ObssHome(Home):
    @http.route()
    def index(self, s_action=None, db=None, **kw):
        if request.db and request.session.uid and not is_user_internal(request.session.uid):
            return super().index(s_action=s_action, db=db, **kw)
        return request.redirect_query(CONSOLE, query=request.params)

    def _login_redirect(self, uid, redirect=None):
        url = super()._login_redirect(uid, redirect=redirect)
        return console_path(url) if isinstance(url, str) else url

    def _obss_client_readonly(self, rule, args):
        return False

    @http.route(
        ['/obss', '/obss/<path:subpath>'],
        type='http',
        auth='none',
        readonly=_obss_client_readonly,
    )
    def obss_client(self, s_action=None, **kw):
        return self.web_client(s_action=s_action, **kw)


class ObssSession(Session):
    @http.route()
    def logout(self, redirect=CONSOLE):
        request.session.logout(keep_db=True)
        return request.redirect(console_path(redirect), 303)

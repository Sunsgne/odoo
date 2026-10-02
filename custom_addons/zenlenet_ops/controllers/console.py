from odoo import http
from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.session import Session
from odoo.addons.web.controllers.utils import is_user_internal
from odoo.http import request
from odoo.tools.misc import file_path

from odoo.addons.zenlenet_ops.console_path import CONSOLE, console_path

APP = '/zenlenet/console'


class ObssHome(Home):
    @http.route()
    def index(self, s_action=None, db=None, **kw):
        if request.db and request.session.uid and not is_user_internal(request.session.uid):
            return super().index(s_action=s_action, db=db, **kw)
        return request.redirect_query(APP, query=request.params)

    def _login_redirect(self, uid, redirect=None):
        url = super()._login_redirect(uid, redirect=redirect)
        if isinstance(url, str) and url in ('/odoo', '/obss', '/web'):
            return APP
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
    def logout(self, redirect=APP):
        request.session.logout(keep_db=True)
        return request.redirect(console_path(redirect) if redirect not in (APP, CONSOLE) else APP, 303)


class ZenlenetConsole(http.Controller):
    @http.route('/zenlenet/console', type='http', auth='public', readonly=True)
    def app(self, **kwargs):
        with open(file_path('zenlenet_ops/static/console/index.html'), encoding='utf-8') as handle:
            body = handle.read()
        return request.make_response(body, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-cache'),
        ])

    @http.route('/zenlenet/console/who', type='jsonrpc', auth='public')
    def who(self):
        user = request.env.user
        public = not user or user._is_public()
        return {
            'db': request.db or '',
            'uid': False if public else user.id,
            'name': '' if public else user.name,
        }

import logging

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.rates import MAJORS, pull

_logger = logging.getLogger(__name__)

NAMES = {
    'USD': '美元',
    'EUR': '欧元',
    'GBP': '英镑',
    'HKD': '港币',
    'JPY': '日元',
    'AUD': '澳大利亚元',
    'CAD': '加拿大元',
    'SGD': '新加坡元',
    'CHF': '瑞士法郎',
    'CNY': '人民币',
}


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    @api.model
    def zenlenet_enable_majors(self):
        Currency = self.sudo().with_context(active_test=False)
        currencies = Currency.search([('name', 'in', list(NAMES))])
        inactive = currencies.filtered(lambda currency: not currency.active)
        if inactive:
            inactive.write({'active': True})
        for currency in currencies:
            label = NAMES.get(currency.name)
            if label and currency.full_name != label:
                currency.full_name = label
        return currencies

    @api.model
    def zenlenet_setup_currencies(self):
        self.zenlenet_enable_majors()
        try:
            self.zenlenet_pull_rates()
        except Exception:
            _logger.exception('汇率没有拉到')

    @api.model
    def _cron_pull_rates(self):
        try:
            self.zenlenet_pull_rates()
        except Exception:
            _logger.exception('汇率没有拉到')

    @api.model
    def zenlenet_pull_rates(self):
        roots = self.env['res.company'].sudo().search([]).root_id
        stored = 0
        day = ''
        for company in roots:
            code = company.currency_id.name
            if not code:
                continue
            try:
                table, rate_day = pull(code)
            except Exception as exc:
                _logger.warning('汇率没有拉到 %s %s', code, exc)
                continue
            stored += self._zenlenet_store_rates(company, table, rate_day)
            day = rate_day
        if stored and day:
            self.env['ir.config_parameter'].sudo().set_param('zenlenet.rate_pulled', day)
        if not stored:
            raise UserError('汇率没有拉到。')
        return stored

    def _zenlenet_store_rates(self, company, table, day):
        Currency = self.sudo().with_context(active_test=False)
        Rate = self.env['res.currency.rate'].sudo()
        company = company.root_id or company
        wanted = set(MAJORS)
        wanted.add(company.currency_id.name)
        count = 0
        for name, value in table.items():
            if name not in wanted or not value or value <= 0:
                continue
            currency = Currency.search([('name', '=', name)], limit=1)
            if not currency:
                continue
            existing = Rate.search([
                ('name', '=', day),
                ('currency_id', '=', currency.id),
                ('company_id', '=', company.id),
            ], limit=1)
            if existing:
                existing.rate = value
            else:
                Rate.create({
                    'name': day,
                    'currency_id': currency.id,
                    'company_id': company.id,
                    'rate': value,
                })
            count += 1
        return count

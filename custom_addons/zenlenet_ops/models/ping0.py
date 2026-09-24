import ipaddress
import logging
import time
from datetime import timedelta

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.zenlenet_ops.ping0 import (
    BUTTON_LIMIT,
    DAILY_LIMIT,
    FRESH_HOURS,
    auth_failed,
    block24_of,
    labels,
    lookup_url,
    sample_host,
    slash24s,
)

_logger = logging.getLogger(__name__)


class ZenlenetIpProbe(models.Model):
    _name = 'zenlenet.ip.probe'
    _description = 'IP 段查询'
    _order = 'cidr'
    _rec_name = 'cidr'

    cidr = fields.Char(string='IP段', required=True, index=True)
    sample = fields.Char(string='抽查地址')
    ip_type = fields.Char(string='IP 类型')
    ip_native = fields.Char(string='原生 IP')
    ip_risk = fields.Integer(string='风控')
    location = fields.Char(string='位置')
    asn = fields.Char(string='AS')
    checked_at = fields.Datetime(string='查询时间', index=True)
    error = fields.Char(string='错误')

    _cidr_unique = models.Constraint('unique(cidr)', '这个地址段已经查过。')

    @api.model
    def _fetch(self, key, ip):
        response = requests.get(lookup_url(key, ip), timeout=20)
        try:
            payload = response.json()
        except ValueError:
            payload = {'error': (response.text or '')[:200]}
        return response.status_code, payload

    @api.model
    def _key(self):
        return (self.env['ir.config_parameter'].sudo().get_param('zenlenet.ping0_key') or '').strip()

    @api.model
    def _wanted_cidrs(self):
        seen = []
        have = set()

        def add(text):
            for network in slash24s(text):
                cidr = str(network)
                if cidr not in have:
                    have.add(cidr)
                    seen.append(cidr)

        for prefix in self.env['zenlenet.prefix'].sudo().search([('status', '!=', 'deprecated'), ('family', '=', '4')]):
            add(prefix.prefix)
        self.env.cr.execute(
            "SELECT DISTINCT block24 FROM zenlenet_address WHERE block24 IS NOT NULL AND block24 <> ''"
        )
        for (cidr,) in self.env.cr.fetchall():
            add(cidr)
        return seen

    @api.model
    def _store(self, cidr, ip, status, payload):
        parsed = labels(payload) if status == 200 else None
        row = self.sudo().search([('cidr', '=', cidr)], limit=1)
        now = fields.Datetime.now()
        if not parsed:
            message = ''
            if isinstance(payload, dict):
                message = str(payload.get('error') or '')[:200]
            values = {'sample': ip, 'error': message or f'HTTP {status}', 'checked_at': now}
            if row:
                row.write(values)
            else:
                self.sudo().create(dict(values, cidr=cidr))
            _logger.warning('ping0 %s failed: %s', cidr, values['error'])
            return False
        values = {
            'sample': ip,
            'ip_type': parsed['ip_type'],
            'ip_native': parsed['ip_native'],
            'location': parsed['location'],
            'asn': parsed['asn'],
            'error': False,
            'checked_at': now,
        }
        if parsed['ip_risk'] is not None:
            values['ip_risk'] = parsed['ip_risk']
        if row:
            row.write(values)
        else:
            row = self.sudo().create(dict(values, cidr=cidr))
        addr_values = {
            'ip_type': parsed['ip_type'],
            'ip_native': parsed['ip_native'],
            'ip_checked': now,
        }
        if parsed['ip_risk'] is not None:
            addr_values['ip_risk'] = parsed['ip_risk']
        addresses = self.env['zenlenet.address'].sudo().with_context(netbox_skip_push=True).search([
            ('block24', '=', cidr),
        ])
        if addresses and (parsed['ip_type'] or parsed['ip_native']):
            addresses.write(addr_values)
        _logger.info('ping0 %s -> %s %s', cidr, parsed['ip_type'], parsed['ip_native'])
        return True

    @api.model
    def check_cidrs(self, cidrs, force=False, commit=False):
        key = self._key()
        if not key:
            return {'checked': 0, 'error': 'no_key'}
        cutoff = fields.Datetime.now() - timedelta(hours=FRESH_HOURS)
        checked = 0
        failed = 0
        for cidr in cidrs:
            networks = slash24s(cidr)
            if len(networks) != 1:
                continue
            row = self.sudo().search([('cidr', '=', cidr)], limit=1)
            if not force and row and row.checked_at and row.checked_at > cutoff and not row.error:
                continue
            host = sample_host(networks[0])
            status, payload = self._fetch(key, host)
            if auth_failed(status, payload):
                _logger.warning('ping0 rejected the key')
                return {'checked': checked, 'error': 'auth'}
            ok = self._store(cidr, host, status, payload)
            if commit and not self.env.context.get('ping0_test'):
                self.env.cr.commit()
                time.sleep(0.2)
            if ok:
                checked += 1
                failed = 0
            else:
                failed += 1
                if failed >= 5:
                    return {'checked': checked, 'error': 'down'}
        return {'checked': checked}

    @api.model
    def check_due(self):
        key = self._key()
        if not key:
            _logger.info('ping0 key missing')
            return {'checked': 0, 'error': 'no_key'}
        cidrs = self._wanted_cidrs()
        cutoff = fields.Datetime.now() - timedelta(hours=FRESH_HOURS)
        existing = {
            row.cidr: row
            for row in self.sudo().search([('cidr', 'in', cidrs)])
        } if cidrs else {}
        pending = []
        for cidr in cidrs:
            row = existing.get(cidr)
            if row and row.checked_at and row.checked_at > cutoff and not row.error:
                continue
            pending.append(cidr)
        return self.check_cidrs(pending[:DAILY_LIMIT], force=True, commit=True)

    @api.model
    def _cron_daily(self):
        try:
            self.check_due()
        except Exception:
            _logger.exception('ping0 check failed')

    @api.model
    def attach(self, blocks):
        """Copy the /24 result onto each grid block and the addresses inside it."""
        keys = []
        rolled = []
        for block in blocks:
            covered = slash24s(block.get('prefix') or '')
            key = str(covered[0]) if len(covered) == 1 else ''
            rolled.append(key)
            if key:
                keys.append(key)
        rows = {row.cidr: row for row in self.sudo().search([('cidr', 'in', keys)])} if keys else {}
        types, natives = [], []
        latest = False
        single_risk = None
        for block, key in zip(blocks, rolled):
            row = rows.get(key)
            ip_type = row.ip_type or '' if row else ''
            ip_native = row.ip_native or '' if row else ''
            block['ip_type'] = ip_type
            block['ip_native'] = ip_native
            block['ip_risk'] = row.ip_risk if row and row.checked_at else ''
            block['ip_checked'] = fields.Datetime.to_string(row.checked_at) if row and row.checked_at else ''
            for cell in block.get('cells') or []:
                cell['ip_type'] = ip_type
                cell['ip_native'] = ip_native
            if ip_type:
                types.append(ip_type)
            if ip_native:
                natives.append(ip_native)
            if row and row.checked_at and (not latest or row.checked_at > latest):
                latest = row.checked_at
                single_risk = row.ip_risk
        unique_types = list(dict.fromkeys(types))
        unique_natives = list(dict.fromkeys(natives))
        return {
            'ip_type': '、'.join(unique_types),
            'ip_native': '、'.join(unique_natives),
            'ip_risk': single_risk if len(blocks) == 1 and latest else None,
            'ip_checked': fields.Datetime.to_string(latest) if latest else '',
        }


class ZenlenetPrefixPing(models.Model):
    _inherit = 'zenlenet.prefix'

    def ipam_ping0(self):
        """Check the /24s of the prefix open on the address page."""
        self.ensure_one()
        if not self.has_access('write'):
            raise UserError('没有权限。')
        cidrs = [str(network) for network in slash24s(self.prefix)]
        if not cidrs:
            try:
                network = ipaddress.ip_network(self.prefix, strict=False)
            except ValueError as error:
                raise UserError('网段格式不对。') from error
            if network.version == 4 and network.prefixlen < 16:
                cidrs = [str(item) for item in list(network.subnets(new_prefix=24))[:BUTTON_LIMIT]]
        cidrs = cidrs[:BUTTON_LIMIT]
        result = self.env['zenlenet.ip.probe'].check_cidrs(cidrs, force=True)
        if result.get('error') == 'no_key':
            raise UserError('还没有 Ping0 Key。')
        if result.get('error') == 'auth':
            raise UserError('Ping0 Key 无效。')
        if result.get('error') == 'down':
            raise UserError('Ping0 没有返回结果。')
        return result


class ZenlenetAddressPing(models.Model):
    _inherit = 'zenlenet.address'

    block24 = fields.Char(string='IP段', compute='_compute_block24', store=True, index=True)
    ip_type = fields.Char(string='IP 类型', index=True)
    ip_native = fields.Char(string='原生 IP', index=True)
    ip_risk = fields.Integer(string='风控')
    ip_checked = fields.Datetime(string='查询时间')

    @api.depends('address')
    def _compute_block24(self):
        for record in self:
            record.block24 = block24_of(record.address)

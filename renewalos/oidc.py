"""Provider-neutral, local-only OIDC authorization-code/PKCE adapter.

No discovery, dynamic URLs, email role grants, or production enablement. The
admin configures a reviewed issuer and exact endpoints. Tokens are always
verified against that issuer's pinned JWKS endpoint and mapped to explicitly
pre-provisioned PostgreSQL identities.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from jwt.exceptions import PyJWTError

from .access import AccessDenied
from .pg_auth import memberships, audit, digest
from .pg_store import _driver

MAX_JSON = 131072
ALLOWED_AMR = frozenset({'mfa', 'otp', 'hwk', 'webauthn'})


class OIDCRejected(ValueError):
    """A generic, client-safe OIDC rejection (no token or provider payload)."""


def _safe_https_url(value):
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or not p.hostname or p.username or p.password
                or p.query or p.fragment or '\\' in value or len(value) > 2048):
            raise ValueError
        return p.hostname
    except (ValueError, TypeError) as exc:
        raise OIDCRejected('OIDC配置不符合安全要求') from exc


@dataclass(frozen=True)
class OIDCConfig:
    issuer: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    redirect_uri: str
    required_acr: str = ''
    client_secret: str = ''

    @classmethod
    def from_env(cls, env=None):
        e = os.environ if env is None else env
        required = ['RENEWAL_OIDC_ISSUER', 'RENEWAL_OIDC_CLIENT_ID',
                    'RENEWAL_OIDC_AUTHORIZATION_ENDPOINT', 'RENEWAL_OIDC_TOKEN_ENDPOINT',
                    'RENEWAL_OIDC_JWKS_URI', 'RENEWAL_OIDC_REDIRECT_URI']
        if any(not e.get(k) for k in required):
            raise OIDCRejected('OIDC配置未完成')
        cfg = cls(*(e[k] for k in required),
                  e.get('RENEWAL_OIDC_REQUIRED_ACR', ''),
                  e.get('RENEWAL_OIDC_CLIENT_SECRET', ''))
        host = _safe_https_url(cfg.issuer)
        if any(_safe_https_url(v) != host for v in
               (cfg.authorization_endpoint, cfg.token_endpoint, cfg.jwks_uri)):
            raise OIDCRejected('OIDC端点必须与审核的签发者同域')
        redirect = urlsplit(cfg.redirect_uri)
        if (redirect.scheme not in ('http', 'https')
                or redirect.hostname not in ('localhost', '127.0.0.1', '::1')
                or redirect.username or redirect.password or redirect.fragment
                or redirect.query or not re.fullmatch(r'[A-Za-z0-9_.-]{3,150}', cfg.client_id)
                or len(cfg.required_acr) > 256 or len(cfg.client_secret) > 512):
            raise OIDCRejected('OIDC回调或客户端配置不安全')
        # This stage is intentionally limited to local HTTP app callback.
        if redirect.path not in ('/', ''):
            raise OIDCRejected('仅允许本地工作台回调')
        return cfg


def _hash(s):
    return hashlib.sha256(s.encode('utf8')).hexdigest()


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def start(dsn, cfg):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(32)
    cookie = secrets.token_urlsafe(32)
    with _driver().connect(dsn) as con:
        # Constrain anonymous flow churn. Expired flows are deleted first.
        con.execute('DELETE FROM renewalos_auth.oidc_flows WHERE expires_at < now()')
        (n,) = con.execute('SELECT count(*) FROM renewalos_auth.oidc_flows').fetchone()
        if n >= 100:
            raise OIDCRejected('登录请求过多，请稍后再试')
        con.execute('''INSERT INTO renewalos_auth.oidc_flows
                       (state_hash,cookie_hash,issuer,nonce,pkce_verifier,expires_at)
                       VALUES(%s,%s,%s,%s,%s,now()+interval '5 minutes')''',
                    (_hash(state), _hash(cookie), cfg.issuer, nonce, verifier))
    url = cfg.authorization_endpoint + '?' + urlencode({
        'response_type': 'code', 'client_id': cfg.client_id,
        'redirect_uri': cfg.redirect_uri, 'scope': 'openid',
        'state': state, 'nonce': nonce,
        'code_challenge': _challenge(verifier), 'code_challenge_method': 'S256',
    })
    return url, cookie


def _json_response(response):
    if response.status_code != 200 or len(response.content) > MAX_JSON:
        raise OIDCRejected('OIDC上游请求未通过')
    try:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, TypeError) as exc:
        raise OIDCRejected('OIDC响应无效') from exc


def verify_id_token(token, jwks, cfg, nonce):
    try:
        hdr = jwt.get_unverified_header(token)
        if hdr.get('alg') != 'RS256' or not isinstance(hdr.get('kid'), str):
            raise OIDCRejected('OIDC签名算法无效')
        keys = jwks.get('keys')
        if not isinstance(keys, list) or len(keys) > 30:
            raise OIDCRejected('OIDC公钥集合无效')
        matches = [k for k in keys if isinstance(k, dict)
                   and k.get('kid') == hdr['kid'] and k.get('kty') == 'RSA'
                   and k.get('use', 'sig') == 'sig'
                   and k.get('alg', 'RS256') == 'RS256']
        if len(matches) != 1:
            raise OIDCRejected('OIDC签名密钥无法匹配')
        key = jwt.PyJWK.from_dict(matches[0], algorithm='RS256').key
        claims = jwt.decode(token, key, algorithms=['RS256'],
                            issuer=cfg.issuer, audience=cfg.client_id,
                            options={'require': ['iss','sub','aud','exp','iat','nonce']},
                            leeway=30)
        if (not isinstance(claims['sub'], str) or not claims['sub']
                or len(claims['sub']) > 255 or len(claims['sub']) < 2
                or not hmac.compare_digest(str(claims['nonce']), nonce)):
            raise OIDCRejected('OIDC身份声明无效')
        aud = claims['aud']
        if isinstance(aud, list) and len(aud) > 1 and claims.get('azp') != cfg.client_id:
            raise OIDCRejected('OIDC授权接收方无效')
        if cfg.required_acr:
            if claims.get('acr') != cfg.required_acr:
                raise OIDCRejected('OIDC多因素认证未满足要求')
        elif not (isinstance(claims.get('amr'), list)
                  and set(x for x in claims['amr'] if isinstance(x, str)) & ALLOWED_AMR):
            raise OIDCRejected('OIDC多因素认证未满足要求')
        return claims['sub']
    except OIDCRejected:
        raise
    except (PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise OIDCRejected('OIDC身份验证未通过') from exc


def _consume_flow(dsn, cfg, state, cookie):
    if (not isinstance(state, str) or not isinstance(cookie, str)
            or len(state) < 30 or len(state) > 200
            or len(cookie) < 30 or len(cookie) > 200):
        raise OIDCRejected('OIDC会话已失效')
    with _driver().connect(dsn) as con:
        # Atomic single-use state AND browser-bound double-submit cookie.
        row = con.execute('''DELETE FROM renewalos_auth.oidc_flows
                             WHERE state_hash=%s AND cookie_hash=%s
                               AND issuer=%s AND expires_at>now()
                             RETURNING nonce,pkce_verifier''',
                          (_hash(state),_hash(cookie),cfg.issuer)).fetchone()
    if not row:
        raise OIDCRejected('OIDC会话已失效')
    return row


def _http_client_factory():
    return httpx.Client(timeout=5.0, follow_redirects=False)


def complete(dsn, cfg, state, cookie, code, transport=None):
    nonce, verifier = _consume_flow(dsn,cfg,state,cookie)
    if not isinstance(code, str) or not 1 <= len(code) <= 2048:
        raise OIDCRejected('OIDC授权响应无效')
    try:
        client = transport or _http_client_factory()
        try:
            payload = {'grant_type':'authorization_code','code':code,
                       'redirect_uri':cfg.redirect_uri,'client_id':cfg.client_id,
                       'code_verifier':verifier}
            if cfg.client_secret:
                payload['client_secret'] = cfg.client_secret
            token_response = _json_response(client.post(cfg.token_endpoint,data=payload))
            id_token = token_response.get('id_token')
            if not isinstance(id_token,str) or len(id_token)>12000:
                raise OIDCRejected('缺少OIDC身份令牌')
            keys = _json_response(client.get(cfg.jwks_uri))
            sub = verify_id_token(id_token,keys,cfg,nonce)
        finally:
            if transport is None:
                client.close()
    except OIDCRejected:
        raise
    except (httpx.RequestError, httpx.HTTPError) as exc:
        raise OIDCRejected('OIDC服务暂不可用') from exc
    return _issue_external_session(dsn,cfg.issuer,sub)


def _issue_external_session(dsn, issuer, subject):
    # No email/username inference or JIT creation. The mapping is manually
    # provisioned and must already refer to an active authorized PG user.
    from datetime import datetime, timedelta, timezone
    with _driver().connect(dsn) as con:
        row = con.execute('''SELECT user_id FROM renewalos_auth.oidc_bindings
                             WHERE issuer=%s AND subject=%s AND enabled''',
                          (issuer,subject)).fetchone()
        user = row[0] if row else None
        scopes = memberships(con,user) if user else {}
        if not scopes:
            audit(con,None,'oidc_login','denied')
            con.commit()
            raise AccessDenied('外部身份尚未获得门店授权')
        token=secrets.token_urlsafe(32)
        expires=datetime.now(timezone.utc)+timedelta(hours=4)
        con.execute('''INSERT INTO renewalos_auth.sessions
                       (token_hash,user_id,expires_at,oidc_issuer,oidc_subject)
                       VALUES(%s,%s,%s,%s,%s)''',
                    (digest(token),user,expires,issuer,subject))
        audit(con,user,'oidc_login','allowed')
        return {'access_token':token,'token_type':'bearer',
                'expires_on':expires.isoformat(),'user_id':user,
                'memberships':scopes,'identity_backend':'postgres'}

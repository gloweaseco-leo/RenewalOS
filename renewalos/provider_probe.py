"""G1-I read-only, strictly pinned OIDC provider interoperability preflight.

This never enables a new issuer, writes accounts, accepts customer data, or
changes the public-deployment blocker. Use against an explicitly approved IdP.
"""
import json

import httpx
import jwt

from .oidc import MAX_JSON, OIDCConfig, OIDCRejected


def _provider_json(client, url):
    try:
        response = client.get(url, follow_redirects=False)
        if response.status_code != 200 or len(response.content) > MAX_JSON:
            raise OIDCRejected('身份服务响应不符合要求')
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError('not an object')
        return value
    except (httpx.HTTPError, ValueError) as exc:
        raise OIDCRejected('身份服务预检失败') from exc


def inspect_provider(cfg: OIDCConfig, *, client=None):
    """Only inspect exact pre-approved endpoints over verified HTTPS.

    Fail closed on changed issuer/endpoint, missing S256 or RS256, redirects,
    malformed JWKS, or weak RSA signing keys. Do not automatically trust
    discovered endpoint URLs as runtime config.
    """
    owner = client is None
    if owner:
        client = httpx.Client(timeout=5.0, follow_redirects=False)
    try:
        doc = _provider_json(client, cfg.issuer.rstrip('/') + '/.well-known/openid-configuration')
        if doc.get('issuer') != cfg.issuer:
            raise OIDCRejected('签发者与预审配置不一致')
        pairs = (
            ('authorization_endpoint', cfg.authorization_endpoint),
            ('token_endpoint', cfg.token_endpoint),
            ('jwks_uri', cfg.jwks_uri),
        )
        if any(doc.get(key) != pinned for key, pinned in pairs):
            raise OIDCRejected('身份服务端点与预审配置不一致')
        if ('code' not in doc.get('response_types_supported', [])
                or 'S256' not in doc.get('code_challenge_methods_supported', [])
                or 'RS256' not in doc.get('id_token_signing_alg_values_supported', [])):
            raise OIDCRejected('身份服务不支持所需的安全协议能力')
        keys = _provider_json(client, cfg.jwks_uri).get('keys', [])
        if not isinstance(keys, list) or not 1 <= len(keys) <= 30:
            raise OIDCRejected('身份服务公钥集合无效')
        valid = 0
        for entry in keys:
            if not isinstance(entry, dict) or entry.get('kty') != 'RSA' or entry.get('use','sig') != 'sig' or entry.get('alg','RS256') != 'RS256':
                continue
            if not isinstance(entry.get('kid'), str) or not entry['kid'] or len(entry['kid']) > 256:
                continue
            try:
                key = jwt.PyJWK.from_dict(entry, algorithm='RS256').key
                if key.key_size >= 2048:
                    valid += 1
            except (ValueError, KeyError, TypeError):
                continue
        if not valid:
            raise OIDCRejected('身份服务缺少合格RSA签名公钥')
        # This is an interoperability probe, not a statement that MFA policy,
        # real-user sign-in, lifecycle provisioning or staging is approved.
        return {
            'provider_contract': 'PASS',
            'issuer_pinned': True,
            's256_pkce': True,
            'rs256_keys_available': True,
            'mfa_verified': False,
            'real_user_login_verified': False,
            'public_release': 'NO_GO',
        }
    finally:
        if owner:
            client.close()

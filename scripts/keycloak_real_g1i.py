"""Use an actual disposable Keycloak HTTP authority; reject a password-only MFA bypass.

No FakeTransport, no JWT forged by the application, no real users and no public server.
The positive test is live discovery + PKCE auth-code exchange + RSA/JWKS wiring;
by design password-only login MUST fail G1-H's MFA gate.
"""
import html.parser
import os
import time
from urllib.parse import parse_qs,urlsplit

import httpx

from renewalos.oidc import OIDCConfig, OIDCRejected, complete, start
from renewalos.provider_probe import inspect_provider

ISSUER='https://127.0.0.1:18443/realms/renewalos-ci'
CLIENT='renewalos-local-interop'


class LoginForm(html.parser.HTMLParser):
    action=None
    def handle_starttag(self,tag,attrs):
        if tag!='form':return
        attrs=dict(attrs)
        if attrs.get('id')=='kc-form-login' or 'login-actions/authenticate' in attrs.get('action',''):
            self.action=attrs.get('action')


def run():
    if os.getenv('CI')!='true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP')!='I_ACCEPT_CI_ONLY':
        raise SystemExit('Only disposable CI fixtures')
    dsn=os.environ['RENEWAL_PG_AUTH_DSN']
    # Explicitly pin admin-reviewed endpoints. Discovery MUST agree; never
    # dynamically adopt provider-controlled endpoint fields as app settings.
    cfg=OIDCConfig.from_env({
        'RENEWAL_OIDC_ISSUER':ISSUER,'RENEWAL_OIDC_CLIENT_ID':CLIENT,
        'RENEWAL_OIDC_AUTHORIZATION_ENDPOINT':ISSUER+'/protocol/openid-connect/auth',
        'RENEWAL_OIDC_TOKEN_ENDPOINT':ISSUER+'/protocol/openid-connect/token',
        'RENEWAL_OIDC_JWKS_URI':ISSUER+'/protocol/openid-connect/certs',
        'RENEWAL_OIDC_REDIRECT_URI':'http://127.0.0.1:8000/',
    })
    with httpx.Client(timeout=8.0) as client:
        deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            try:
                if client.get(ISSUER+'/.well-known/openid-configuration').status_code==200:
                    break
            except httpx.HTTPError:pass
            time.sleep(2)
        else:raise RuntimeError('Disposable Keycloak was not ready')
        probe=inspect_provider(cfg,client=client)
        assert probe['provider_contract']=='PASS' and probe['mfa_verified'] is False
        url,cookie=start(dsn,cfg)
        with httpx.Client(timeout=12.0,follow_redirects=True) as browser:
            page=browser.get(url)
            assert page.status_code==200, 'Keycloak login form did not load'
            form=LoginForm();form.feed(page.text)
            assert form.action and form.action.startswith(ISSUER+'/login-actions/'), 'Keycloak form missing'
            login=browser.post(form.action,data={'username':'synthetic-operator',
                              'password':'G1I-Synthetic-Password-No-Real-Accounts'},
                              follow_redirects=False)
            assert login.status_code in (302,303), 'Synthetic Keycloak password login failed'
            target=login.headers.get('location','')
            assert target.startswith(cfg.redirect_uri), 'Unexpected Keycloak callback URL'
            q=parse_qs(urlsplit(target).query)
            assert q['code'] and q['state'], 'Keycloak authorization code missing'
            assert q['state'][0]==parse_qs(urlsplit(url).query)['state'][0]
        try:
            complete(dsn,cfg,q['state'][0],cookie,q['code'][0])
        except OIDCRejected as exc:
            assert str(exc)=='OIDC多因素认证未满足要求', 'Failed at another reason: '+str(exc)
        else:
            raise AssertionError('SECURITY: password-only Keycloak session bypassed MFA gate')
        try:
            complete(dsn,cfg,q['state'][0],cookie,q['code'][0])
        except OIDCRejected:
            pass
        else:
            raise AssertionError('SECURITY: OIDC state replay succeeded')
    print('G1-I REAL KEYCLOAK HTTPS/PKCE EXCHANGE SUCCESS; PASSWORD-ONLY MFA REJECTED; NO-GO',flush=True)


if __name__=='__main__':run()

"""Real disposable Keycloak two-factor protocol test. NEVER a deployed login.

Uses a fixture-only TOTP secret in an ephemeral CI realm; checks a genuine
Keycloak-signed ID token after executing a password and OTP challenge.
"""
import base64
import hashlib
import hmac
import html.parser
import os
import struct
import time
from urllib.parse import parse_qs, urlsplit

import httpx

from renewalos.oidc import OIDCConfig, OIDCRejected, start, complete
from renewalos.pg_auth import identity, logout
from renewalos.access import AccessDenied
from renewalos.provider_probe import inspect_provider

ISSUER='https://127.0.0.1:18443/realms/renewalos-ci'
CLIENT='renewalos-local-interop'
TOTP_SECRET='JBSWY3DPEHPK3PXP'  # Public synthetic CI fixture, never a real credential.
SYNTHETIC_SUB='8e7f51f1-4715-46db-8eb2-d1f37e8a5e33'


class Forms(html.parser.HTMLParser):
    def __init__(self):
        super().__init__();self.forms=[];self.current=None
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=='form':
            self.current={'action':a.get('action',''),'fields':set(),'id':a.get('id','')}
        elif tag=='input' and self.current is not None:
            self.current['fields'].add(a.get('name',''))
    def handle_endtag(self,tag):
        if tag=='form' and self.current is not None:
            self.forms.append(self.current);self.current=None


def totp(secret, moment=None):
    """RFC6238 6-digit SHA1 code generated at run time (never printed)."""
    stamp=int(time.time() if moment is None else moment)
    raw=base64.b32decode(secret+'='*((-len(secret))%8))
    mac=hmac.new(raw,struct.pack('>Q',stamp//30),hashlib.sha1).digest()
    offset=mac[-1]&15
    return f'{(int.from_bytes(mac[offset:offset+4],"big")&0x7fffffff)%1000000:06d}'


def find_form(body, names):
    parser=Forms();parser.feed(body)
    forms=[f for f in parser.forms if names.issubset(f['fields']) and f['action'].startswith(ISSUER+'/login-actions/')]
    if len(forms)!=1:
        raise AssertionError('Expected one Keycloak form, got form IDs '+','.join(f['id'] for f in parser.forms))
    return forms[0]


def configuration():
    return OIDCConfig.from_env({
        'RENEWAL_OIDC_ISSUER':ISSUER,'RENEWAL_OIDC_CLIENT_ID':CLIENT,
        'RENEWAL_OIDC_AUTHORIZATION_ENDPOINT':ISSUER+'/protocol/openid-connect/auth',
        'RENEWAL_OIDC_TOKEN_ENDPOINT':ISSUER+'/protocol/openid-connect/token',
        'RENEWAL_OIDC_JWKS_URI':ISSUER+'/protocol/openid-connect/certs',
        'RENEWAL_OIDC_REDIRECT_URI':'http://127.0.0.1:8000/',
    })


def run():
    if os.getenv('CI')!='true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP')!='I_ACCEPT_CI_ONLY':
        raise SystemExit('CI disposable provider ONLY')
    dsn=os.environ['RENEWAL_PG_AUTH_DSN']
    cfg=configuration()
    # Test-only explicit administrator provisioning. Keycloak token claims never
    # create staff, memberships or roles on behalf of this application.
    import psycopg
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as con:
        con.execute("INSERT INTO renewalos.organizations(org_id,label) VALUES('g1j_mfa','Synthetic MFA test')")
        con.execute("INSERT INTO renewalos.stores(org_id,store_id,label) VALUES('g1j_mfa','pool','Synthetic pool')")
        con.execute("INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES('g1j_mfa','Synthetic MFA operator')")
        con.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES('g1j_mfa','g1j_mfa','member')")
        con.execute("INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES('g1j_mfa','pool','g1j_mfa','manager')")
        con.execute("INSERT INTO renewalos_auth.oidc_bindings(issuer,subject,user_id) VALUES(%s,%s,'g1j_mfa')",
                    (ISSUER,SYNTHETIC_SUB))
    with httpx.Client(timeout=12.0) as client:
        probe=inspect_provider(cfg,client=client)
        assert probe['provider_contract']=='PASS' and probe['mfa_verified'] is False
        url,cookie=start(dsn,cfg)
        with httpx.Client(timeout=15.0,follow_redirects=True) as browser:
            res=browser.get(url)
            assert res.status_code==200,'Password login form must load'
            password_form=find_form(res.text,{'username','password'})
            res=browser.post(password_form['action'],data={'username':'synthetic-mfa-operator',
                      'password':'G1J-Disposable-Password-Only'},follow_redirects=False)
            if res.status_code not in (200,302,303):
                raise AssertionError('Synthetic Keycloak password stage failed')
            if res.status_code in (302,303):
                dest=res.headers.get('location','')
                if dest.startswith(cfg.redirect_uri):
                    raise AssertionError('SECURITY: TOTP-enabled test account skipped second factor')
                if not dest.startswith(ISSUER):
                    raise AssertionError('Unexpected Keycloak redirect path: '+urlsplit(dest).path)
                res=browser.get(dest)
            assert res.status_code==200,'OTP challenge page must load'
            otp_form=find_form(res.text,{'otp'})
            # One factor alone cannot yield the callback; a legitimate TOTP must
            # be presented before the IdP issues its signed authorization code.
            res=browser.post(otp_form['action'],data={'otp':totp(TOTP_SECRET),'login':'Log in'},follow_redirects=False)
            assert res.status_code in (302,303),'OTP challenge was not accepted'
            location=res.headers.get('location','')
            if not location.startswith(cfg.redirect_uri):
                raise AssertionError('OTP did not complete flow; next path: '+urlsplit(location).path)
            params=parse_qs(urlsplit(location).query)
            assert params.get('code') and params.get('state'),'OIDC code missing'
            assert params['state'][0]==parse_qs(urlsplit(url).query)['state'][0]
        # Actual Keycloak HTTPS code exchange and RS256/MFA checks inside
        # renewalos.oidc.complete (no synthetic JWTs or transport mocks).
        session=complete(dsn,cfg,params['state'][0],cookie,params['code'][0])
        assert session['user_id']=='g1j_mfa' and session['memberships']=={'g1j_mfa:pool':'manager'}
        bearer=session['access_token']
        assert identity(dsn,bearer)['user_id']=='g1j_mfa'
        try:
            complete(dsn,cfg,params['state'][0],cookie,params['code'][0])
        except OIDCRejected:
            pass
        else:
            raise AssertionError('SECURITY: OIDC state replay accepted')
        logout(dsn,bearer)
        try:
            identity(dsn,bearer)
        except AccessDenied:
            pass
        else:
            raise AssertionError('SECURITY: logged-out MFA session remains active')
    print('G1-J KEYCLOAK MFA POSITIVE: password+TOTP -> genuine signed ID token -> MFA verified; replay denied',flush=True)


if __name__=='__main__':run()

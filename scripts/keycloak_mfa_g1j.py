"""Real disposable Keycloak password + TOTP (positive MFA) and instant revocation.

Runs only in GitHub's isolated PostgreSQL/Keycloak CI. No credentials or OAuth
codes are emitted in logs. All test accounts and the TOTP seed are synthetic.
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
import psycopg

from renewalos.access import AccessDenied
from renewalos.oidc import OIDCConfig, OIDCRejected, complete, start
from renewalos.pg_auth import identity, authorize_store
from scripts.keycloak_real_g1i import ISSUER, CLIENT, LoginForm

USER = 'g1j_mfa_user'
SUBJECT = 'b31d5bba-d7b5-489c-a7ef-4c15d3436278'
SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'


def totp(timestamp=None):
    t = int(time.time() if timestamp is None else timestamp)
    key = base64.b32decode(SECRET)
    counter = struct.pack('>Q', t // 30)
    sig = hmac.new(key, counter, hashlib.sha1).digest()
    offset = sig[-1] & 15
    return str((int.from_bytes(sig[offset:offset+4], 'big') & 0x7fffffff) % 10**6).zfill(6)


def _callback(url, cfg):
    if not url.startswith(cfg.redirect_uri):
        # Do not reveal authorization codes, state or cookies in CI logs.
        raise AssertionError('Keycloak MFA step did not reach callback (path only): '+urlsplit(url).path)
    params = parse_qs(urlsplit(url).query)
    assert len(params.get('code',[])) == 1 and len(params.get('state',[])) == 1, 'OIDC callback missing code/state'
    return params


def run():
    if os.getenv('CI') != 'true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP') != 'I_ACCEPT_CI_ONLY':
        raise SystemExit('CI-only synthetic Keycloak OTP verification')
    cfg = OIDCConfig.from_env({
        'RENEWAL_OIDC_ISSUER':ISSUER,
        'RENEWAL_OIDC_CLIENT_ID':CLIENT,
        'RENEWAL_OIDC_AUTHORIZATION_ENDPOINT':ISSUER+'/protocol/openid-connect/auth',
        'RENEWAL_OIDC_TOKEN_ENDPOINT':ISSUER+'/protocol/openid-connect/token',
        'RENEWAL_OIDC_JWKS_URI':ISSUER+'/protocol/openid-connect/certs',
        'RENEWAL_OIDC_REDIRECT_URI':'http://127.0.0.1:8000/',
    })
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as con:
        con.execute("INSERT INTO renewalos.organizations(org_id,label) VALUES('g1j_org','G1J synthetic org')")
        con.execute("INSERT INTO renewalos.stores(org_id,store_id,label) VALUES('g1j_org','pool','Synthetic pool')")
        con.execute("INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES(%s,'MFA employee')",(USER,))
        con.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES('g1j_org',%s,'member')",(USER,))
        con.execute("INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES('g1j_org','pool',%s,'manager')",(USER,))
        con.execute("INSERT INTO renewalos_auth.oidc_bindings(issuer,subject,user_id) VALUES(%s,%s,%s)",(ISSUER,SUBJECT,USER))
    url,cookie=start(os.environ['RENEWAL_PG_AUTH_DSN'],cfg)
    with httpx.Client(timeout=15.0,follow_redirects=True) as browser:
        page=browser.get(url)
        assert page.status_code == 200, 'Keycloak MFA user login page failed'
        form=LoginForm();form.feed(page.text)
        assert form.action and form.action.startswith(ISSUER+'/login-actions/'), 'Keycloak login form not found'
        password_response=browser.post(form.action,data={
            'username':'synthetic-mfa-operator','password':'G1J-CI-only-Password',
        },follow_redirects=False)
        assert password_response.status_code in (302,303), 'Keycloak did not progress after password'
        step=password_response.headers.get('location','')
        assert step.startswith(ISSUER+'/login-actions/'), 'Keycloak did not require OTP step'
        otp_page=browser.get(step)
        assert otp_page.status_code==200, 'Keycloak OTP form not available'
        otp_form=LoginForm();otp_form.feed(otp_page.text)
        assert otp_form.action and otp_form.action.startswith(ISSUER+'/login-actions/'), 'OTP form action not found'
        otp_response=browser.post(otp_form.action,data={'otp':totp()},follow_redirects=False)
        assert otp_response.status_code in (302,303), 'Keycloak OTP form submission failed'
        params=_callback(otp_response.headers.get('location',''),cfg)
        state=params['state'][0]
        assert state==parse_qs(urlsplit(url).query)['state'][0], 'state altered by provider'
    result=complete(os.environ['RENEWAL_PG_AUTH_DSN'],cfg,state,cookie,params['code'][0])
    assert result['user_id']==USER and result['memberships']=={'g1j_org:pool':'manager'}, 'MFA identity not prebound'
    token=result['access_token']
    dsn=os.environ['RENEWAL_PG_AUTH_DSN']
    assert identity(dsn,token)['user_id']==USER
    assert authorize_store(dsn,token,'g1j_org','pool')['role']=='manager'
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as con:
        con.execute("UPDATE renewalos_auth.oidc_bindings SET enabled=false WHERE issuer=%s AND subject=%s",(ISSUER,SUBJECT))
    try:
        identity(dsn,token)
    except AccessDenied:pass
    else:raise AssertionError('SECURITY: session survived OIDC binding revocation')
    # Re-enabling a binding cannot resurrect any session issued before revocation.
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as con:
        con.execute("UPDATE renewalos_auth.oidc_bindings SET enabled=true WHERE issuer=%s AND subject=%s",(ISSUER,SUBJECT))
    try:
        identity(dsn,token)
    except AccessDenied:pass
    else:raise AssertionError('SECURITY: revoked session was resurrected')
    print('G1-J REAL KEYCLOAK PASSWORD+TOTP OIDC SUCCESS; PREBOUND SESSION PERMANENTLY REVOKED; NO-GO',flush=True)


if __name__=='__main__':run()

"""OIDC PKCE/MFA and pre-provisioned identity tests; synthetic data only."""
import json
import os
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from renewalos.main import app
from renewalos.oidc import OIDCConfig, OIDCRejected, verify_id_token, _challenge
from renewalos.access import AccessDenied
from renewalos.release_gate import assert_local_only, ReleaseBlocked

PG = pytest.importorskip('psycopg')
ISS = 'https://idp.synthetic.example/oidc'


def config_env():
    return {
        'RENEWAL_OIDC_ISSUER':ISS,
        'RENEWAL_OIDC_CLIENT_ID':'renewalos-local-ci',
        'RENEWAL_OIDC_AUTHORIZATION_ENDPOINT':'https://idp.synthetic.example/authorize',
        'RENEWAL_OIDC_TOKEN_ENDPOINT':'https://idp.synthetic.example/token',
        'RENEWAL_OIDC_JWKS_URI':'https://idp.synthetic.example/keys',
        'RENEWAL_OIDC_REDIRECT_URI':'http://127.0.0.1:8000/',
    }


@pytest.fixture(scope='module')
def keys():
    priv=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    jwk=json.loads(RSAAlgorithm.to_jwk(priv.public_key()))
    jwk.update({'kid':'test-key', 'use':'sig', 'alg':'RS256'})
    return priv, {'keys':[jwk]}


def id_token(private, cfg, nonce, **change):
    now=int(datetime.now(timezone.utc).timestamp())
    claims={'iss':cfg.issuer,'aud':cfg.client_id,'sub':'synthetic-oidc-sub',
            'iat':now,'exp':now+180,'nonce':nonce,'amr':['pwd','mfa']}
    claims.update(change)
    return jwt.encode(claims,private,algorithm='RS256',headers={'kid':'test-key'})


def test_issuer_and_endpoint_must_be_pinned_and_redirect_loopback():
    cfg=OIDCConfig.from_env(config_env())
    assert cfg.issuer==ISS
    assert len(_challenge('x'*50))==43
    for mutation in (
        {'RENEWAL_OIDC_TOKEN_ENDPOINT':'http://idp.synthetic.example/token'},
        {'RENEWAL_OIDC_TOKEN_ENDPOINT':'https://malicious.example/token'},
        {'RENEWAL_OIDC_JWKS_URI':'https://idp.synthetic.example:443/keys#fragment'},
        {'RENEWAL_OIDC_REDIRECT_URI':'https://outside.example/'},
        {'RENEWAL_OIDC_REDIRECT_URI':'http://127.0.0.1:8000/attacker'},
        {'RENEWAL_OIDC_CLIENT_ID':'bad token'},
    ):
        with pytest.raises(OIDCRejected): OIDCConfig.from_env({**config_env(),**mutation})


def test_signed_jwt_and_mfa_claims_strict(keys):
    private,jwks=keys
    cfg=OIDCConfig.from_env(config_env())
    assert verify_id_token(id_token(private,cfg,'nonce'),jwks,cfg,'nonce')=='synthetic-oidc-sub'
    for mutation in (
        {'aud':'unknown'}, {'iss':'https://another.example'},
        {'exp':0}, {'amr':['pwd']}, {'nonce':'other'},
        {'aud':[cfg.client_id,'other']}, {'sub':''},
    ):
        with pytest.raises(OIDCRejected): verify_id_token(id_token(private,cfg,'nonce',**mutation),jwks,cfg,'nonce')
    with pytest.raises(OIDCRejected): verify_id_token(id_token(private,cfg,'nonce'),jwks,cfg,'other')
    with pytest.raises(OIDCRejected): verify_id_token(id_token(private,cfg,'nonce'),{'keys':[]},cfg,'nonce')
    with pytest.raises(OIDCRejected):
        verify_id_token(jwt.encode({'sub':'attacker'},'secret',algorithm='HS256',headers={'kid':'test-key'}),jwks,cfg,'nonce')
    strict=OIDCConfig.from_env({**config_env(),'RENEWAL_OIDC_REQUIRED_ACR':'urn:corp:mfa'})
    with pytest.raises(OIDCRejected):verify_id_token(id_token(private,strict,'nonce'),jwks,strict,'nonce')
    assert verify_id_token(id_token(private,strict,'nonce',acr='urn:corp:mfa'),jwks,strict,'nonce')


@pytest.fixture(scope='module')
def seed():
    dsn=os.getenv('RENEWAL_PG_MIGRATION_DSN')
    if not dsn:yield False;return
    with PG.connect(dsn) as con:
        con.execute("INSERT INTO renewalos.organizations(org_id,label) VALUES('g1h_org','Synthetic G1H')")
        con.execute("INSERT INTO renewalos.stores(org_id,store_id,label) VALUES('g1h_org','pool','Pool')")
        con.execute("INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES('g1h_user','G1H synthetic user')")
        con.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES('g1h_org','g1h_user','member')")
        con.execute("INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES('g1h_org','pool','g1h_user','manager')")
        con.execute("INSERT INTO renewalos_auth.oidc_bindings(issuer,subject,user_id) VALUES(%s,%s,'g1h_user')",
                    (ISS,'synthetic-oidc-sub'))
    yield True


def test_real_pg_oidc_cookie_pkce_no_password_login(monkeypatch,keys,seed,tmp_path):
    if not seed:pytest.skip('Requires disposable PostgreSQL 16 CI service')
    from renewalos import oidc
    from renewalos.pg_auth import identity
    private,jwks=keys
    for k,v in config_env().items():monkeypatch.setenv(k,v)
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    monkeypatch.setenv('RENEWAL_AUTH_BACKEND','oidc')
    monkeypatch.setenv('RENEWAL_PG_AUTH_DSN',os.environ['RENEWAL_PG_AUTH_DSN'])
    monkeypatch.setenv('RENEWAL_PG_APP_DSN',os.environ['RENEWAL_PG_TEST_DSN'])
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'must-not-create.sqlite'))
    monkeypatch.delenv('RENEWAL_DEPLOYMENT_TARGET',raising=False)
    with TestClient(app) as c:
        assert c.get('/api/auth/methods').json()['method']=='oidc'
        assert c.post('/api/auth/login',json={'username':'g1h_user','password':'whatever'}).status_code==403
        start=c.post('/api/auth/oidc/start',json={})
        assert start.status_code==200,start.text
        cookie=start.cookies.get('renewal_oidc_csrf')
        query=parse_qs(urlsplit(start.json()['authorization_url']).query)
        state=query['state'][0];nonce=query['nonce'][0]
        assert query['code_challenge_method']==['S256']
        assert 'code_verifier' not in start.text
        with TestClient(app) as outsider:
            assert outsider.post('/api/auth/oidc/complete',json={'code':'fake','state':state}).status_code==401
        token=id_token(private,OIDCConfig.from_env(config_env()),nonce)
        def handle(request):
            if request.url.path=='/token':
                assert request.method=='POST'
                assert 'code_verifier=' in request.content.decode()
                return httpx.Response(200,json={'id_token':token})
            if request.url.path=='/keys':return httpx.Response(200,json=jwks)
            return httpx.Response(404)
        monkeypatch.setattr(oidc,'_http_client_factory',lambda: httpx.Client(transport=httpx.MockTransport(handle)))
        done=c.post('/api/auth/oidc/complete',json={'code':'synthetic-code','state':state})
        assert done.status_code==200,done.text
        assert done.json()['memberships']=={'g1h_org:pool':'manager'}
        bearer=done.json()['access_token']
        assert identity(os.environ['RENEWAL_PG_AUTH_DSN'],bearer)['user_id']=='g1h_user'
        assert c.post('/api/auth/oidc/complete',json={'code':'synthetic-code','state':state}).status_code==401
        assert c.get('/api/v1/orgs/g1h_org/stores/pool/opportunities',headers={'Authorization':'Bearer '+bearer}).status_code==200
        assert c.post('/api/auth/logout',headers={'Authorization':'Bearer '+bearer}).status_code==200
        assert c.get('/api/v1/me',headers={'Authorization':'Bearer '+bearer}).status_code==401
    assert not (tmp_path/'must-not-create.sqlite').exists()


def test_unbound_subject_does_not_become_customer_account(monkeypatch,keys,seed):
    if not seed:pytest.skip('Disposable PostgreSQL required')
    from renewalos.oidc import _issue_external_session
    with pytest.raises(AccessDenied):
        _issue_external_session(os.environ['RENEWAL_PG_AUTH_DSN'],ISS,'not-a-real-binding')
    with PG.connect(os.environ['RENEWAL_PG_TEST_DSN']) as con:
        with pytest.raises(PG.errors.InsufficientPrivilege):
            con.execute('SELECT * FROM renewalos_auth.oidc_bindings')


def test_oidc_does_not_override_no_public_deployment():
    with pytest.raises(ReleaseBlocked):
        assert_local_only({**config_env(),'RENEWAL_DEPLOYMENT_TARGET':'production','RENEWAL_AUTH_BACKEND':'oidc'})

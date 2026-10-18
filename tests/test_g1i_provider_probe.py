"""Provider metadata must exactly match pinned admin configuration; no auto trust."""
import json
from datetime import datetime

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from renewalos.oidc import OIDCConfig, OIDCRejected
from renewalos.provider_probe import inspect_provider


def conf():
    issuer='https://idp.testing.example/realm'
    return OIDCConfig(issuer,'test-client',issuer+'/auth',issuer+'/token',issuer+'/keys','http://127.0.0.1:8000/')


def fixtures():
    c=conf();priv=rsa.generate_private_key(65537,2048)
    key=json.loads(RSAAlgorithm.to_jwk(priv.public_key()))
    key.update(kid='new-kid',alg='RS256',use='sig')
    metadata={
        'issuer':c.issuer,'authorization_endpoint':c.authorization_endpoint,
        'token_endpoint':c.token_endpoint,'jwks_uri':c.jwks_uri,
        'response_types_supported':['code'],'code_challenge_methods_supported':['S256'],
        'id_token_signing_alg_values_supported':['RS256']}
    return metadata, {'keys':[key]}


def probe(metadata, jwks, statuses=None):
    cfg=conf()
    def handler(req):
        if statuses and req.url.path in statuses:
            return httpx.Response(statuses[req.url.path])
        if req.url.path.endswith('openid-configuration'):
            return httpx.Response(200,json=metadata)
        if req.url.path.endswith('/keys'):
            return httpx.Response(200,json=jwks)
        raise AssertionError('unapproved URL '+str(req.url))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return inspect_provider(cfg, client=client)


def test_exact_metadata_and_real_rsa_pubkey_pass():
    meta,jwks=fixtures()
    result=probe(meta,jwks)
    assert result['provider_contract']=='PASS'
    assert result['public_release']=='NO_GO'
    assert result['mfa_verified'] is False


@pytest.mark.parametrize('key,val',[
    ('issuer','https://other.testing.example'),
    ('authorization_endpoint','https://other.testing.example/auth'),
    ('token_endpoint','https://idp.testing.example:444/token'),
    ('jwks_uri','https://idp.testing.example/hijacked-keys'),
    ('response_types_supported',['id_token']),
    ('code_challenge_methods_supported',['plain']),
    ('id_token_signing_alg_values_supported',['HS256']),
])
def test_provider_metadata_drift_is_rejected(key,val):
    meta,jwks=fixtures();meta[key]=val
    with pytest.raises(OIDCRejected):probe(meta,jwks)


def test_redirect_and_malformed_jwks_rejected():
    meta,jwks=fixtures()
    with pytest.raises(OIDCRejected):probe(meta,jwks,{ '/realm/.well-known/openid-configuration':302})
    with pytest.raises(OIDCRejected):probe(meta,{'keys':[]})
    with pytest.raises(OIDCRejected):probe(meta,{'keys':[{'kid':'forged','kty':'RSA','n':'AQAB','e':'AQAB'}]})


def test_issuer_is_case_and_path_sensitive():
    meta,jwks=fixtures();meta['issuer']='https://idp.testing.example/Realm'
    with pytest.raises(OIDCRejected):probe(meta,jwks)

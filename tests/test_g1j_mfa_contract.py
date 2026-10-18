"""Real two-factor testing has to use actual Keycloak authenticator results."""
import json
from pathlib import Path
from scripts.keycloak_mfa_g1j import totp, SYNTHETIC_SUB, TOTP_SECRET

ROOT=Path(__file__).resolve().parents[1]

def test_totp_rfc6238_vector_and_unique_repeating_window():
    # RFC6238 test vector (SHA1 8-digit 94287082, truncated to 6 digits).
    assert totp('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ',59)=='287082'
    assert totp(TOTP_SECRET,1700000000)==totp(TOTP_SECRET,1700000005)
    # Keycloak's pre-imported raw credential is Base32-encoded only in QR codes.
    from base64 import b32encode
    assert totp(TOTP_SECRET,1700000000,raw_credential=True)==totp(b32encode(TOTP_SECRET.encode()).decode(),1700000000)

def test_real_mfa_account_uses_non_mapped_otp_credential():
    fixture=json.loads((ROOT/'tests/fixtures/g1i_keycloak/renewalos-ci-realm.json').read_text('utf8'))
    mfa=next(u for u in fixture['users'] if u['username']=='synthetic-mfa-operator')
    assert mfa['id']==SYNTHETIC_SUB
    otp=next(c for c in mfa['credentials'] if c['type']=='otp')
    assert json.loads(otp['secretData'])['value']==TOTP_SECRET
    assert json.loads(otp['credentialData'])['subType']=='totp'
    assert any(p['protocolMapper']=='oidc-amr-mapper' for p in fixture['clients'][0]['protocolMappers'])
    assert not any(p['protocolMapper']=='oidc-hardcoded-claim-mapper' for p in fixture['clients'][0]['protocolMappers'])

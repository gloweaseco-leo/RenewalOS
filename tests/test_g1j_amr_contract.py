"""Native OTP reference is attached only to Keycloak authenticator execution."""
from pathlib import Path
from scripts.keycloak_amr_setup_g1j import REFERENCE_KEY
ROOT=Path(__file__).resolve().parents[1]

def test_reference_is_native_authenticator_execution_config():
    setup=(ROOT/'scripts/keycloak_amr_setup_g1j.py').read_text('utf8')
    assert REFERENCE_KEY=='default.reference.value'
    assert "execution.get('providerId')=='auth-otp-form'" in setup
    assert "{REFERENCE_KEY:'otp'}" in setup
    assert 'oidc-hardcoded-claim-mapper' not in setup

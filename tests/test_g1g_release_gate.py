"""Release blocker tests require no infrastructure or credentials."""
from fastapi.testclient import TestClient
import pytest
from renewalos.main import app
from renewalos.release_gate import ReleaseBlocked, assert_local_only, assert_dedicated_pg_roles, local_readiness
from scripts.release_audit_g1g import audit
from scripts.backup_restore_g1g import ci_guard


GOOD = {
    "RENEWAL_DEPLOYMENT_TARGET": "local",
    "RENEWAL_RUNTIME_MODE": "secure_local",
    "RENEWAL_AUTH_BACKEND": "postgres",
    "RENEWAL_PG_AUTH_DSN": "postgresql://dedicated_auth:secret_auth@127.0.0.1:5432/testdb",
    "RENEWAL_PG_APP_DSN": "postgresql://dedicated_business:secret_app@127.0.0.1:5432/testdb",
}


def test_public_environment_never_accepted():
    for env in ({"RENEWAL_DEPLOYMENT_TARGET":"production"}, {"RENEWAL_DEPLOYMENT_TARGET":"staging"},
                {"VERCEL":"1"}, {"K_SERVICE":"renewalos"},
                {"RENEWAL_PUBLIC_BASE_URL":"https://renewalos.example.com"}):
        with pytest.raises(ReleaseBlocked): assert_local_only(env)


def test_same_role_root_remote_or_different_db_rejected():
    assert assert_dedicated_pg_roles(GOOD)
    for updates in ({"RENEWAL_PG_APP_DSN":GOOD["RENEWAL_PG_AUTH_DSN"]},
                    {"RENEWAL_PG_APP_DSN":"postgresql://dedicated_auth@127.0.0.1:5432/testdb"},
                    {"RENEWAL_PG_APP_DSN":"postgresql://postgres@127.0.0.1:5432/testdb"},
                    {"RENEWAL_PG_APP_DSN":"postgresql://dedicated_business@public.example.com/testdb"},
                    {"RENEWAL_PG_APP_DSN":"postgresql://dedicated_business@127.0.0.1/otherdb"}):
        with pytest.raises(ReleaseBlocked): assert_dedicated_pg_roles({**GOOD,**updates})


def test_public_profile_rejected_before_app_boot(monkeypatch,tmp_path):
    monkeypatch.setenv('RENEWAL_DEPLOYMENT_TARGET','production')
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','demo')
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'should_not_exist.sqlite'))
    with pytest.raises(ReleaseBlocked):
        with TestClient(app): pass
    assert not list(tmp_path.iterdir())


def test_ready_is_not_a_public_release_claim(monkeypatch):
    monkeypatch.delenv('RENEWAL_DEPLOYMENT_TARGET',raising=False)
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    monkeypatch.setenv('RENEWAL_AUTH_BACKEND','sqlite')
    with TestClient(app) as c:
        response=c.get('/api/ready')
        assert response.status_code==503
        assert response.json()['ready'] is False
        assert response.headers['cache-control']=='no-store'
        assert c.get('/api/health').status_code==200
    assert local_readiness(GOOD)['ready'] is False


def test_audit_reports_no_go_without_secrets():
    r=audit(GOOD)
    assert r['public_release']=='NO_GO'
    assert r['local_synthetic_ready_for_db_check'] is True
    assert 'OIDC_MFA' in r['unresolved_gates']
    assert 'secret' not in str(r)
    assert audit({"RENEWAL_DEPLOYMENT_TARGET":"production"})['issues']


def test_backup_drill_strict_ci_scope():
    with pytest.raises(RuntimeError): ci_guard({})
    with pytest.raises(RuntimeError): ci_guard({'CI':'true','RENEWAL_PG_CI_BOOTSTRAP':'I_ACCEPT_CI_ONLY',
        'RENEWAL_PG_MIGRATION_DSN':'postgresql://postgres:pass@external.org/renewalos_ci'})
    with pytest.raises(RuntimeError): ci_guard({'CI':'true','RENEWAL_PG_CI_BOOTSTRAP':'I_ACCEPT_CI_ONLY',
        'RENEWAL_PG_MIGRATION_DSN':'postgresql://postgres:pass@127.0.0.1/prod'})


def test_real_ci_postgres_readiness(monkeypatch):
    import os
    auth=os.getenv('RENEWAL_PG_AUTH_DSN')
    app_dsn=os.getenv('RENEWAL_PG_TEST_DSN')
    if not auth or not app_dsn:
        pytest.skip('Needs disposable PostgreSQL CI database')
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    monkeypatch.setenv('RENEWAL_AUTH_BACKEND','postgres')
    monkeypatch.setenv('RENEWAL_PG_APP_DSN',app_dsn)
    monkeypatch.delenv('RENEWAL_DEPLOYMENT_TARGET',raising=False)
    with TestClient(app) as c:
        r=c.get('/api/ready')
        assert r.status_code==200,r.text
        assert r.json()=={'ready':True,'profile':'LOCAL_SYNTHETIC_ONLY'}
        assert 'postgresql://' not in r.text

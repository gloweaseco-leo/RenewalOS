"""Static and unauthenticated safeguards for G1-D PostgreSQL UX."""
from pathlib import Path
from fastapi.testclient import TestClient
from renewalos.main import app

ROOT=Path(__file__).resolve().parent.parent


def test_g1d_scope_and_synthetic_warning_on_login_page(monkeypatch,tmp_path):
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'identity.sqlite'))
    with TestClient(app) as c:
        html=c.get('/').text
        assert '机构代号' in html and '模拟' in html
        assert '销售待办' in html and '经理复盘' in html
        script=c.get('/static/secure.js').text
        assert "/api/v1/orgs/" in script
        assert "/api/v1/stores/" not in script
        assert "/api/demo/" not in script
        assert 'cash-events' in script and 'followups' in script
        assert c.get('/static/app.js').status_code==403


def test_g1d_detail_requires_login_before_database_scope(monkeypatch,tmp_path):
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'identity.sqlite'))
    with TestClient(app) as c:
        res=c.get('/api/v1/orgs/example/stores/pool/opportunities/example-opp')
        assert res.status_code==401
        assert c.get('/api/v1/orgs/example/stores/pool/management').status_code==401


def test_g1d_ui_contains_no_browser_token_persistence_or_html_injection():
    script=(ROOT/'static/secure.js').read_text(encoding='utf-8')
    # Existing G1-A regression deliberately expects 'localStorage' in a comment;
    # never CALL browser storage or interpolate customer fields into markup.
    assert 'localStorage.setItem' not in script
    assert 'localStorage.getItem' not in script
    assert '.innerHTML=' not in script
    assert 'textContent' in script
    assert 'state.drafts' in script

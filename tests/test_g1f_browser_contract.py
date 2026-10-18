"""G1-F browser test must be real and guarded, not a fixture-only pass."""
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def test_browser_runner_refuses_non_ci_without_db_access():
    env=os.environ.copy()
    env.pop('CI',None)
    env.pop('RENEWAL_PG_CI_BOOTSTRAP',None)
    r=subprocess.run([sys.executable,'-m','scripts.browser_http_e2e_g1f'],cwd=ROOT,env=env,
                     capture_output=True,text=True,timeout=8)
    assert r.returncode!=0
    assert 'restricted to disposable CI PostgreSQL' in (r.stderr+r.stdout)


def test_real_browser_ci_is_not_an_api_mock():
    suite=(ROOT/'scripts/browser_http_e2e_g1f.py').read_text('utf8')
    flow=(ROOT/'.github/workflows/ci.yml').read_text('utf8')
    assert "page.goto(base+'/',wait_until='domcontentloaded')" in suite
    assert 'page.route(' not in suite and 'page.set_content(' not in suite
    for action in ('分配员工任务','记录客户跟进','登记模拟续费合同','登记模拟付款',
                   '登记模拟退款','经理复盘','退出登录'):
        assert action in suite
    assert 'python -m playwright install --with-deps chromium' in flow
    assert 'python -m scripts.browser_http_e2e_g1f' in flow
    assert 'Upload synthetic-only browser screenshot on failure' in flow


def test_role_tab_and_invalid_scope_fail_closed_in_browser_client():
    js=(ROOT/'static/secure.js').read_text('utf8')
    assert "$('managementTab').hidden=state.role!=='manager'" in js
    assert "try{context();}catch(err)" in js
    assert "state.tab='opportunities'" in js
    assert 'localStorage.setItem' not in js

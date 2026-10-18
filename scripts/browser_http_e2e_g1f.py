"""Real Chromium → loopback Uvicorn → PostgreSQL 16 regression (synthetic only).

The script only runs in a disposable GitHub Actions DB. It seeds its own fixture,
uses real browser interactions (no page.route or fetch mocks), and writes a
screenshot when a browser assertion fails. No cookies/traces or secrets exported.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ARTIFACT_DIR = Path('browser_artifacts')
ORG = 'g1f_alpha'
STORE = 'pool'
ORG_OTHER = 'g1f_beta'
MANAGER = 'g1fmanager'
STAFF = 'g1fstaff'
COLLEAGUE = 'g1fcolleague'
OTHER_MANAGER = 'g1fothermanager'
OPPORTUNITY = 'g1f-opportunity'
OPPORTUNITY_OTHER = 'g1f-other-opportunity'
# CI-only synthetic credentials; not production secrets.
PASSWORDS = {MANAGER: 'G1F_Manager_Test_Only_2026', STAFF: 'G1F_Staff_Test_Only_2026',
             COLLEAGUE: 'G1F_Colleague_Test_Only_2026', OTHER_MANAGER: 'G1F_Other_Test_Only_2026'}


def guard() -> None:
    if os.getenv('CI') != 'true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP') != 'I_ACCEPT_CI_ONLY':
        raise SystemExit('G1-F browser test is restricted to disposable CI PostgreSQL')
    for key in ('RENEWAL_PG_MIGRATION_DSN', 'RENEWAL_PG_TEST_DSN', 'RENEWAL_PG_AUTH_DSN'):
        if not os.getenv(key):
            raise SystemExit(f'Missing CI PostgreSQL configuration: {key}')


def seed() -> None:
    import psycopg
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as db:
        for org in (ORG, ORG_OTHER):
            db.execute('INSERT INTO renewalos.organizations(org_id,label) VALUES(%s,%s)', (org, 'synthetic browser fixture'))
            db.execute('INSERT INTO renewalos.stores(org_id,store_id,label) VALUES(%s,%s,%s)', (org, STORE, 'synthetic pool'))
        for user, org, role in ((MANAGER, ORG, 'manager'), (STAFF, ORG, 'staff'),
                                (COLLEAGUE, ORG, 'staff'), (OTHER_MANAGER, ORG_OTHER, 'manager')):
            db.execute('INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES(%s,%s)', (user, user))
            db.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES(%s,%s,'member')", (org, user))
            db.execute('INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES(%s,%s,%s,%s)',
                       (org, STORE, user, role))
            salt=bytes(range(16))
            digest=hashlib.pbkdf2_hmac('sha256', PASSWORDS[user].encode(),salt,390000)
            db.execute('INSERT INTO renewalos_auth.credentials(user_id,password_salt,password_hash,iterations) VALUES(%s,%s,%s,390000)',
                       (user, salt, digest))
        for org, opp in ((ORG, OPPORTUNITY), (ORG_OTHER, OPPORTUNITY_OTHER)):
            db.execute('INSERT INTO renewalos.households(org_id,store_id,household_id) VALUES(%s,%s,%s)', (org, STORE, 'family'))
            db.execute('''INSERT INTO renewalos.learners(org_id,store_id,learner_id,household_id,alias,contact_consent)
                          VALUES(%s,%s,%s,%s,%s,true)''', (org, STORE, 'kid', 'family', 'synthetic-kid'))
            db.execute('''INSERT INTO renewalos.course_packages(org_id,store_id,package_id,learner_id,course_type,purchased_on,
                          expires_on,purchased_sessions,remaining_sessions,price_cents)
                          VALUES(%s,%s,%s,%s,'swim','2026-01-01','2026-12-31',20,2,150000)''',
                       (org, STORE, 'package', 'kid'))
            db.execute('''INSERT INTO renewalos.renewal_opportunities(org_id,store_id,opportunity_id,source_package_id,
                          learner_id,arm,priority) VALUES(%s,%s,%s,%s,%s,'rules',80)''',
                       (org, STORE, opp, 'package','kid'))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def wait_until_ready(proc: subprocess.Popen, base: str) -> None:
    import httpx
    with httpx.Client(timeout=1) as client:
        for _ in range(100):
            if proc.poll() is not None:
                raise AssertionError('Uvicorn process exited before becoming ready')
            try:
                if client.get(base+'/api/health').status_code==200:
                    return
            except (httpx.ConnectError, httpx.ReadTimeout):
                pass
            time.sleep(.15)
    raise AssertionError('Uvicorn did not start on loopback')


def browser_suite(base: str) -> None:
    from playwright.sync_api import sync_playwright, expect
    
    ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
    browser = None
    page = None
    with sync_playwright() as playwright:
        try:
            # Playwright Chromium is installed explicitly by the CI workflow.
            browser = playwright.chromium.launch(headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':960},locale='zh-CN')
            page=context.new_page()
            page.set_default_timeout(12000)
            responses=[]
            page.on('response',lambda r: responses.append((r.request.method,r.status,r.url))
                    if '/api/' in r.url else None)

            def login(user: str) -> None:
                page.goto(base+'/',wait_until='domcontentloaded')
                expect(page.locator('#loginPanel')).to_be_visible()
                page.locator('#username').fill(user)
                page.locator('#password').fill(PASSWORDS[user])
                page.locator('#loginForm button').click()
                expect(page.locator('#workspace')).to_be_visible()
                expect(page.locator('#org')).to_have_value(ORG_OTHER if user==OTHER_MANAGER else ORG)
                page.get_by_role('button',name='刷新').click()
                expect(page.locator('#status')).to_contain_text('PostgreSQL')

            def select_case(opp: str) -> None:
                page.locator('#list button.record').filter(has=page.get_by_text(opp,exact=True)).click()
                expect(page.locator('#detail h3').first).to_contain_text(opp)

            def submit_form(heading: str, button: str) -> None:
                section=page.locator('#detail section.section').filter(has=page.get_by_role('heading',name=heading))
                section.get_by_role('button',name=button).click()
                expect(page.locator('#status')).to_contain_text('PostgreSQL')

            # Manager: business workflow via rendered forms and real TCP requests.
            login(MANAGER)
            select_case(OPPORTUNITY)
            assignee=page.locator('#detail section.section').filter(has=page.get_by_role('heading',name='分配员工任务'))
            assignee.get_by_label('员工账号').fill(STAFF)
            assignee.get_by_label('截止日期').fill('2026-11-05')
            submit_form('分配员工任务','创建任务')
            expect(page.locator('#detail')).to_contain_text(STAFF)
            page.get_by_role('button',name='销售待办').click()
            expect(page.locator('#list')).to_contain_text(STAFF)
            page.get_by_role('button',name='续费机会').click()
            select_case(OPPORTUNITY)
            assert page.get_by_role('heading',name='记录客户跟进').count()==1
            # Manager may record followup as well, but we verify the employee path instead.
            page.get_by_role('button',name='退出登录').click()
            expect(page.locator('#loginPanel')).to_be_visible()
            expect(page.locator('#workspace')).to_be_hidden()

            # Unassigned colleague cannot see the assigned opportunity or financial data.
            login(COLLEAGUE)
            expect(page.locator('#list')).not_to_contain_text(OPPORTUNITY)
            expect(page.locator('#managementTab')).to_be_hidden()
            page.get_by_role('button',name='退出登录').click()

            # Staff can see assigned work and follow up, never contract / cash details.
            login(STAFF)
            select_case(OPPORTUNITY)
            expect(page.locator('#detail')).not_to_contain_text('合同与资金事件（经理权限）')
            submit_form('记录客户跟进','保存跟进')
            expect(page.locator('#detail')).to_contain_text('已联系')
            expect(page.locator('#managementTab')).to_be_hidden()
            page.get_by_role('button',name='退出登录').click()

            # Manager records contract and ledger via UI, then sees exact net cash.
            login(MANAGER)
            select_case(OPPORTUNITY)
            contract=page.locator('#detail section.section').filter(has=page.get_by_role('heading',name='登记模拟续费合同'))
            contract.get_by_label('合同金额（元）').fill('1200')
            submit_form('登记模拟续费合同','创建合成合同')
            payment=page.locator('#detail section.section').filter(has=page.get_by_role('heading',name='登记模拟付款'))
            payment.get_by_label('本次模拟收款（元）').fill('800')
            submit_form('登记模拟付款','登记付款')
            expect(page.locator('#detail')).to_contain_text('¥800.00')
            refund=page.locator('#detail section.section').filter(has=page.get_by_role('heading',name='登记模拟退款'))
            refund.get_by_label('模拟退款金额（元）').fill('200')
            submit_form('登记模拟退款','登记退款')
            expect(page.locator('#detail')).to_contain_text('¥600.00')
            page.get_by_role('button',name='经理复盘').click()
            page.get_by_role('button',name='本门店经营快照').click()
            expect(page.locator('#detail')).to_contain_text('¥600.00')
            # UI-level unauthorized tenant selection: original manager has no beta membership.
            page.locator('#org').fill(ORG_OTHER)
            page.get_by_role('button',name='刷新').click()
            expect(page.locator('#status')).to_contain_text('没有该机构/门店权限')
            page.locator('#org').fill(ORG)
            page.get_by_role('button',name='刷新').click()
            expect(page.locator('#status')).to_contain_text('PostgreSQL')
            page.get_by_role('button',name='退出登录').click()
            expect(page.locator('#loginPanel')).to_be_visible()
            # Browser logout returns to the login screen; the HTTP regression checks token revocation.
            # Cross-tenant manager on identical store name can see only other org fixture.
            login(OTHER_MANAGER)
            expect(page.locator('#list')).to_contain_text(OPPORTUNITY_OTHER)
            expect(page.locator('#list')).not_to_contain_text(OPPORTUNITY)
            page.get_by_role('button',name='退出登录').click()

            # No failed business API calls during the authorized manager/staff actions.
            forbidden=[(method,status,url) for method,status,url in responses if status>=500]
            assert not forbidden, 'Unexpected server failures on real browser requests'
            print('G1-F REAL BROWSER HTTP E2E SUCCESS: manager → task → staff followup → contract → payment → refund → management; permissions and logout')
        except Exception:
            if page is not None:
                # Only synthetic accounts/data; password is masked and never exported in trace.
                try:
                    page.screenshot(path=str(ARTIFACT_DIR/'failure.png'),full_page=True,timeout=6000)
                except Exception:
                    pass  # Preserve the original browser test exception
            raise
        finally:
            if browser is not None:
                browser.close()


def main() -> None:
    guard()
    seed()
    port=free_port()
    env={**os.environ,'RENEWAL_RUNTIME_MODE':'secure_local','RENEWAL_AUTH_BACKEND':'postgres',
         'RENEWAL_PG_APP_DSN':os.environ['RENEWAL_PG_TEST_DSN'],
         'RENEWAL_DB_PATH':'/proc/g1f_forbidden_sqlite.db'}
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','renewalos.main:app',
         '--host','127.0.0.1','--port',str(port),'--no-access-log'],
         env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        base=f'http://127.0.0.1:{port}'
        wait_until_ready(proc,base)
        browser_suite(base)
    finally:
        proc.terminate()
        try:proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait()

if __name__=='__main__':
    main()

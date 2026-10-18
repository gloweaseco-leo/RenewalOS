"""Real G1-C PostgreSQL + authenticated FastAPI integration tests.

Entire fixture uses dedicated disposable CI PostgreSQL and synthetic identities.
"""
import os
from datetime import date
import pytest
from fastapi.testclient import TestClient
from renewalos.main import app
from renewalos.access import create_local_user
from renewalos.pg_store import TenantScope, tenant_transaction

pg=pytest.importorskip('psycopg',reason='PostgreSQL extra unavailable')
ADMIN=os.getenv('RENEWAL_PG_MIGRATION_DSN')
APP=os.getenv('RENEWAL_PG_TEST_DSN')
pytestmark=pytest.mark.skipif(not ADMIN or not APP,reason='real PostgreSQL CI environment required')

@pytest.fixture(scope='module',autouse=True)
def fixture_pg():
    if not ADMIN or not APP:
        yield;return
    with pg.connect(ADMIN) as con:
        for org in ['g1ca','g1cb']:
            con.execute('INSERT INTO renewalos.organizations(org_id,label) VALUES(%s,%s)',(org,org))
            for store in (['pool','annex'] if org=='g1ca' else ['pool']):
                con.execute('INSERT INTO renewalos.stores(org_id,store_id,label) VALUES(%s,%s,%s)',(org,store,store))
        for u in ['managerA','staffA','staffOther','managerB']:
            con.execute('INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES(%s,%s)',(u,u))
        for org,users in [('g1ca',['managerA','staffA','staffOther']),('g1cb',['managerB'])]:
            for u in users:
                con.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES(%s,%s,'member')",(org,u))
        members=[('g1ca','pool','managerA','manager'),('g1ca','annex','managerA','manager'),
                 ('g1ca','pool','staffA','staff'),('g1ca','pool','staffOther','staff'),
                 ('g1cb','pool','managerB','manager')]
        for org,store,u,role in members:
            con.execute('''INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role)
                VALUES(%s,%s,%s,%s)''',(org,store,u,role))
        for org,store in [('g1ca','pool'),('g1ca','annex'),('g1cb','pool')]:
            base=f'{org}-{store}'
            con.execute('INSERT INTO renewalos.households(org_id,store_id,household_id) VALUES(%s,%s,%s)',(org,store,base+'-family'))
            con.execute('''INSERT INTO renewalos.learners(org_id,store_id,learner_id,household_id,alias,contact_consent)
                VALUES(%s,%s,%s,%s,%s,true)''',(org,store,base+'-learner',base+'-family','synthetic'))
            con.execute('''INSERT INTO renewalos.course_packages
                (org_id,store_id,package_id,learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cents)
                VALUES(%s,%s,%s,%s,'swim','2026-01-01','2026-12-31',24,3,200000)''',
                (org,store,base+'-package',base+'-learner'))
            con.execute('''INSERT INTO renewalos.renewal_opportunities
                (org_id,store_id,opportunity_id,source_package_id,learner_id,arm)
                VALUES(%s,%s,%s,%s,%s,'rules')''',
                (org,store,base+'-opp',base+'-package',base+'-learner'))
        # Test control contamination on a separate case.
        con.execute('''INSERT INTO renewalos.course_packages
                (org_id,store_id,package_id,learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cents)
                VALUES('g1ca','pool','control-pkg','g1ca-pool-learner','swim','2026-01-01','2026-12-31',10,3,100000)''')
        con.execute('''INSERT INTO renewalos.renewal_opportunities
                (org_id,store_id,opportunity_id,source_package_id,learner_id,arm)
                VALUES('g1ca','pool','control-opp','control-pkg','g1ca-pool-learner','control')''')
    yield

@pytest.fixture
def client(monkeypatch,tmp_path):
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'auth.sqlite'))
    monkeypatch.setenv('RENEWAL_PG_APP_DSN',APP or '')
    with TestClient(app) as c:
        create_local_user('managerA','A_Strong_Login_Secret_2026',{'pool':'manager','annex':'manager'})
        create_local_user('staffA','A_Staff_Login_Secret_2026',{'pool':'staff'})
        create_local_user('staffOther','Other_Staff_Secret_2026',{'pool':'staff'})
        create_local_user('managerB','B_Strong_Login_Secret_2026',{'pool':'manager'})
        yield c

def auth(c,username,secret):
    x=c.post('/api/auth/login',json={'username':username,'password':secret})
    assert x.status_code==200,x.text
    return {'Authorization':'Bearer '+x.json()['access_token']}

def base(org='g1ca',store='pool'):
    return f'/api/v1/orgs/{org}/stores/{store}'


def test_full_authenticated_renewal_business_chain(client):
    man=auth(client,'managerA','A_Strong_Login_Secret_2026')
    staff=auth(client,'staffA','A_Staff_Login_Secret_2026')
    assert client.get(base()+'/opportunities',headers=man).status_code==200
    assert client.get(base()+'/opportunities',headers=staff).json()['items']==[]
    task={'opportunity_id':'g1ca-pool-opp','task_id':'g1c-task','assigned_user_id':'staffA','due_on':'2026-11-01'}
    r=client.post(base()+'/tasks',json=task,headers=man)
    assert r.status_code==200,r.text
    assert r.json()['created'] is True
    r=client.post(base()+'/tasks',json=task,headers=man)
    assert r.json()['created'] is False
    assert [x['task_id'] for x in client.get(base()+'/tasks',headers=staff).json()['items']]==['g1c-task']
    follow={'opportunity_id':'g1ca-pool-opp','followup_id':'g1c-follow','result':'contacted','note':'synthetic outreach'}
    r=client.post(base()+'/followups',headers=staff,json=follow)
    assert r.status_code==200,r.text
    assert r.json()['created']
    assert client.post(base()+'/followups',headers=staff,json=follow).json()['created'] is False
    contract={'opportunity_id':'g1ca-pool-opp','contract_id':'g1c-contract','signed_on':'2026-10-18','amount_cents':120000}
    r=client.post(base()+'/contracts',headers=man,json=contract)
    assert r.status_code==200,r.text
    assert r.json()['provenance']=='synthetic'
    assert client.post(base()+'/contracts',headers=man,json=contract).json()['created'] is False
    assert client.post(base()+'/contracts',headers=staff,json=contract).status_code==403
    payment={'contract_id':'g1c-contract','event_id':'g1c-payment','kind':'payment','amount_cents':100000,'occurred_on':'2026-10-18'}
    r=client.post(base()+'/cash-events',headers=man,json=payment)
    assert r.status_code==200,r.text
    assert r.json()['net_cents']==100000
    assert client.post(base()+'/cash-events',headers=man,json=payment).json()['created'] is False
    assert client.post(base()+'/cash-events',headers=staff,json=payment).status_code==403
    refund={'contract_id':'g1c-contract','event_id':'g1c-refund','kind':'refund','amount_cents':25000,'occurred_on':'2026-10-18','refund_of':'g1c-payment'}
    r=client.post(base()+'/cash-events',headers=man,json=refund)
    assert r.status_code==200,r.text
    assert r.json()['net_cents']==75000
    report=client.get(base()+'/management',headers=man)
    assert report.status_code==200
    assert report.json()['synthetic_cash_net_cents']==75000
    assert report.json()['incremental_roi'] is None
    assert report.json()['stages']['paid']==1
    with tenant_transaction(APP,TenantScope('g1ca','pool','managerA')) as con:
        entries=con.execute("SELECT action FROM renewalos.business_action_events WHERE resource_id IN ('g1c-task','g1c-follow','g1c-contract','g1c-payment','g1c-refund')").fetchall()
        assert len(entries)==5


def test_cross_tenant_cross_store_and_wrong_staff_denied(client):
    a=auth(client,'managerA','A_Strong_Login_Secret_2026')
    b=auth(client,'managerB','B_Strong_Login_Secret_2026')
    colleague=auth(client,'staffOther','Other_Staff_Secret_2026')
    staff=auth(client,'staffA','A_Staff_Login_Secret_2026')
    assert client.get(base('g1ca','annex')+'/opportunities',headers=a).status_code==200
    assert client.get(base('g1cb','pool')+'/opportunities',headers=a).status_code==403
    assert client.get(base('g1ca','pool')+'/opportunities',headers=b).status_code==403
    assert client.get(base('g1ca','annex')+'/tasks',headers=staff).status_code==403
    assert client.get(base()+'/management',headers=staff).status_code==403
    wrong={'opportunity_id':'g1ca-pool-opp','followup_id':'colleague-attack','result':'contacted','note':'wrong'}
    assert client.post(base()+'/followups',json=wrong,headers=colleague).status_code==403
    assert client.post(base()+'/tasks',headers=staff,json={
       'opportunity_id':'g1ca-pool-opp','task_id':'staff-fraud','assigned_user_id':'staffA','due_on':'2026-11-01'}).status_code==403


def test_control_arm_cannot_be_targeted_but_can_record_natural_sale(client):
    a=auth(client,'managerA','A_Strong_Login_Secret_2026')
    task={'opportunity_id':'control-opp','task_id':'control-target','assigned_user_id':'staffA','due_on':'2026-11-01'}
    assert client.post(base()+'/tasks',json=task,headers=a).status_code==409
    contract={'opportunity_id':'control-opp','contract_id':'control-sale','signed_on':'2026-10-18','amount_cents':25000}
    r=client.post(base()+'/contracts',json=contract,headers=a)
    assert r.status_code==200,r.text
    assert r.json()['provenance']=='synthetic'


def test_cash_rejections_and_no_double_count(client):
    a=auth(client,'managerA','A_Strong_Login_Secret_2026')
    over={'contract_id':'g1c-contract','event_id':'overcap','kind':'payment','amount_cents':50000,'occurred_on':'2026-10-18'}
    assert client.post(base()+'/cash-events',json=over,headers=a).status_code==409
    badrefund={'contract_id':'g1c-contract','event_id':'refund-over','kind':'refund','amount_cents':90000,'occurred_on':'2026-10-18','refund_of':'g1c-payment'}
    assert client.post(base()+'/cash-events',json=badrefund,headers=a).status_code==409
    changed={'contract_id':'g1c-contract','event_id':'g1c-payment','kind':'payment','amount_cents':50000,'occurred_on':'2026-10-18'}
    assert client.post(base()+'/cash-events',json=changed,headers=a).status_code==409
    assert client.get(base()+'/management',headers=a).json()['synthetic_cash_net_cents']==75000


def test_fail_closed_when_not_configured_or_not_logged_in(client,monkeypatch):
    assert client.get(base()+'/opportunities').status_code==401
    a=auth(client,'managerA','A_Strong_Login_Secret_2026')
    monkeypatch.delenv('RENEWAL_PG_APP_DSN')
    assert client.get(base()+'/opportunities',headers=a).status_code==503
    # Legacy synthetic finance remains disabled when auth mode is on.
    assert client.post('/api/demo/sales/payments',headers=a,json={}).status_code==403

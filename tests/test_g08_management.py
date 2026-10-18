"""G0.8 regression: process truth != AI attribution or actual profits."""
from datetime import date, timedelta
from fastapi.testclient import TestClient
import pytest
from renewalos.main import app
from renewalos.db import connect
from renewalos.management import manager_snapshot


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('RENEWAL_DB_PATH', str(tmp_path/'g08.sqlite'))
    monkeypatch.delenv('RENEWAL_AI_API_KEY', raising=False)
    with TestClient(app) as c:
        assert c.post('/api/demo/reset').status_code == 200
        yield c


def opportunities(client):
    return client.get('/api/opportunities').json()['items']


def pick(client, arm='rules'):
    return next(x for x in opportunities(client) if x['arm'] == arm)


def post_task(client, item, due=None):
    return client.post('/api/tasks',json={
        'opportunity_id':item['opportunity_id'],'owner':'顾问甲',
        'due_on':(due or date.today()).isoformat(), 'note':'合成排班'})


def test_snapshot_consistency_empty_and_synthetic(client):
    before=client.get('/api/management/overview').json()
    assert before['summary']['opportunities'] == before['case_count']
    assert sum(before['stage_counts'].values()) == before['case_count']
    assert before['summary']['roi'] is None
    assert before['summary']['incremental_profit_cny'] is None
    assert before['summary']['attribution_status']=='NOT_ESTABLISHED'
    with connect() as con:
        old=con.execute('SELECT COUNT(*) FROM work_task_events').fetchone()[0]
    after=client.get('/api/management/overview').json()
    assert before==after
    with connect() as con:
        assert con.execute('SELECT COUNT(*) FROM work_task_events').fetchone()[0]==old
    assert client.get('/api/management/overview?store_id=').status_code == 422


def test_overdue_task_and_owner_review(client):
    item=pick(client)
    yesterday=date.today()-timedelta(days=1)
    result=post_task(client,item,yesterday)
    assert result.status_code == 200,result.text
    report=client.get('/api/management/overview').json()
    assert report['summary']['task_overdue']==1
    assert report['milestones']['assigned']==1
    assert report['milestones']['followed']==0
    owner=next(x for x in report['owner_workload'] if x['owner']=='顾问甲')
    assert owner['overdue']==1 and owner['open']==1
    assert any(x['kind']=='overdue' and x['opportunity_id']==item['opportunity_id'] for x in report['alerts'])


def test_control_group_appears_in_stage_but_not_action_alerts(client):
    control=pick(client,'control')
    view=client.get('/api/management/overview').json()
    row=next(x for x in view['cases'] if x['opportunity_id']==control['opportunity_id'])
    assert row['stage']=='control'
    assert all(x['opportunity_id'] != control['opportunity_id'] for x in view['alerts'])
    assert view['stage_counts']['control']>0
    assert client.post('/api/tasks',json={'opportunity_id':control['opportunity_id'],
                'owner':'经理','due_on':date.today().isoformat()}).status_code==422


def test_payment_refund_shifts_stage_without_creating_ai_uplift(client):
    item=pick(client)
    pkg=item['package_id']
    cid='G08-C-'+pkg
    day=date.today().isoformat()
    assert client.post('/api/demo/sales/contracts',json={
        'source_package_id':pkg,'contract_id':cid,'signed_on':day,'amount_cny':'2000'}).status_code==200
    snap=client.get('/api/management/overview').json()
    current=next(c for c in snap['cases'] if c['package_id']==pkg)
    assert current['stage']=='contract_no_net'
    assert client.post('/api/demo/sales/payments',json={
        'contract_id':cid,'event_id':'G08-PAID','event_on':day,'amount_cny':'2000'}).status_code==200
    snap=client.get('/api/management/overview').json()
    current=next(c for c in snap['cases'] if c['package_id']==pkg)
    assert current['stage']=='net_paid' and current['net_paid_cny']==2000
    assert snap['summary']['linked_net_cash_cny']==2000
    assert snap['summary']['roi'] is None
    assert client.post('/api/demo/sales/refunds',json={
        'payment_event_id':'G08-PAID','event_id':'G08-REF','event_on':day,'amount_cny':'2000'}).status_code==200
    snap=client.get('/api/management/overview').json()
    current=next(c for c in snap['cases'] if c['package_id']==pkg)
    assert current['stage']=='contract_no_net' and current['net_paid_cny']==0
    assert snap['summary']['linked_net_cash_cny']==0
    assert any(x['kind']=='net_zero_after_refund' and x['opportunity_id']==item['opportunity_id'] for x in snap['alerts'])


def test_old_payment_separate_from_new_cash(client):
    item=pick(client)
    with connect() as con:
        con.execute('INSERT INTO renewals VALUES(?,?,?,?,?,?)',(
            'G08-LEGACY',item['learner_id'],item['package_id'],date.today().isoformat(),17500,'paid'))
    client.post('/api/recompute')
    s=client.get('/api/management/overview').json()
    record=next(c for c in s['cases'] if c['package_id']==item['package_id'])
    assert record['stage']=='legacy_paid'
    assert s['summary']['legacy_net_cash_cny']>=175
    assert s['summary']['linked_net_cash_cny']==0
    assert s['summary']['incremental_profit_cny'] is None


def test_store_scope_and_no_public_access(client):
    c1=client.get('/api/management/overview').json()
    s1=client.get('/api/management/overview?store_id=DEMO-STORE').json()
    assert s1['case_count']<=c1['case_count']
    assert all(x['store_id']=='DEMO-STORE' for x in s1['cases'])
    nonexistent=client.get('/api/management/overview?store_id=NOT-A-STORE').json()
    assert nonexistent['case_count']==0 and nonexistent['summary']['linked_net_cash_cny']==0
    assert client.get('/api/management/overview',headers={'Host':'example.com'}).status_code==403
    html=client.get('/').text
    assert '门店经营复盘' in html and 'mgStages' in html and 'mgAlerts' in html
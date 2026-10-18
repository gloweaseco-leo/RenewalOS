"""G0.6: synthetic workbench sales, immutable fact chain and archived history."""
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from renewalos.db import connect
from renewalos.main import app


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'local.sqlite'))
    with TestClient(app) as c:
        assert c.post('/api/demo/reset').status_code == 200
        yield c


def pick(c,arm=None):
    records=c.get('/api/opportunities').json()['items']
    return next(r for r in records if arm is None or r['arm']==arm)


def contract(c,r,cid='DC-001',amount='2500.00'):
    return c.post('/api/demo/sales/contracts',json={
        'source_package_id':r['package_id'],'contract_id':cid,
        'signed_on':date.today().isoformat(),'amount_cny':amount})


def payment(c, cid='DC-001', eid='DP-001',amount='2500.00'):
    return c.post('/api/demo/sales/payments',json={
        'contract_id':cid,'event_id':eid,'event_on':date.today().isoformat(),'amount_cny':amount})


def refund(c, pay='DP-001',eid='DR-001',amount='250.00'):
    return c.post('/api/demo/sales/refunds',json={
        'payment_event_id':pay,'event_id':eid,'event_on':date.today().isoformat(),'amount_cny':amount})


def test_full_demo_loop_preserves_archived_history(client):
    c=client
    r=pick(c,arm='rules')
    assert c.post('/api/followups',json={'opportunity_id':r['opportunity_id'], 'owner':'demo-staff',
                                           'status':'contacted','note':'合成联系记录'}).status_code==200
    assert contract(c,r).status_code==200
    assert payment(c).status_code==200
    # A positive paid contract removes the case from the active queue but history persists.
    active=c.get('/api/opportunities').json()['items']
    assert r['opportunity_id'] not in {item['opportunity_id'] for item in active}
    archived=c.get('/api/opportunities?include_archived=true').json()['items']
    closed=next(item for item in archived if item['opportunity_id']==r['opportunity_id'])
    assert closed['is_active']==0
    assert c.get('/api/followups/'+r['opportunity_id']).json()['items'][0]['status']=='contacted'
    facts=c.get('/api/demo/sales/'+r['package_id']).json()
    assert facts['net_paid_cny']==2500.0 and facts['status']=='net_paid'
    assert facts['contract']['contract_id']=='DC-001'
    assert c.post('/api/followups',json={'opportunity_id':r['opportunity_id'],'owner':'staff',
                                           'status':'planned','note':''}).status_code==404
    assert refund(c,amount='2500.00').status_code==200
    reopened={item['opportunity_id'] for item in c.get('/api/opportunities').json()['items']}
    assert r['opportunity_id'] in reopened
    assert c.get('/api/demo/sales/'+r['package_id']).json()['net_paid_cny']==0.0
    timeline=c.get('/api/cycles/'+r['package_id']+'/timeline').json()['events']
    assert {'package','followup','renewal_contract','payment','refund'} <= {e['event_type'] for e in timeline}
    assert c.get('/api/report').json()['roi'] is None


def test_simulated_payments_idempotent_no_over_collection(client):
    c=client;r=pick(c)
    assert contract(c,r).status_code==200
    assert contract(c,r).status_code==200  # same fact retry
    assert contract(c,r,cid='DIFF').status_code==422
    assert payment(c,amount='1100.00').status_code==200
    assert payment(c,amount='1100.00').status_code==200  # identical event retry
    assert payment(c,eid='DP-002',amount='1500').status_code==422
    assert payment(c,eid='DP-002',amount='1400.00').status_code==200
    assert refund(c,amount='1200.00').status_code==422
    assert refund(c,amount='1000.00').status_code==200
    assert refund(c,eid='DR-002',amount='101.00').status_code==422
    assert refund(c,eid='DR-002',amount='100.00').status_code==200
    assert refund(c,amount='1000.00').status_code==200 # identical replay
    sale=c.get('/api/demo/sales/'+r['package_id']).json()
    assert sale['net_paid_cny']==1400.0
    with connect() as con:
        assert con.execute('SELECT COUNT(*) FROM cash_events').fetchone()[0]==4


def test_ownership_future_invalid_input_and_no_real_payment_claim(client):
    c=client;r=pick(c)
    assert c.get('/api/demo/sales/missing').status_code==404
    future=(date.today()+timedelta(days=1)).isoformat()
    assert c.post('/api/demo/sales/contracts',json={
        'source_package_id':r['package_id'],'contract_id':'FUTURE',
        'signed_on':future,'amount_cny':'100'}).status_code==422
    assert contract(c,r,amount='0').status_code==422
    assert contract(c,r).status_code==200
    assert c.post('/api/demo/sales/payments',json={
        'contract_id':'DC-001','event_id':'DP-FUTURE',
        'event_on':future,'amount_cny':'50'}).status_code==422
    assert payment(c,amount='-1').status_code==422
    assert payment(c).status_code==200
    assert '模拟' in c.get('/api/demo/sales/'+r['package_id']).json()['disclaimer']
    assert c.post('/api/demo/sales/refunds',json={'payment_event_id':'DP-001','event_id':'DR-X',
        'event_on':future,'amount_cny':'20'}).status_code==422
    assert c.post('/api/demo/sales/payments',json={'contract_id':'DC-001','event_id':'DP-X',
        'event_on':date.today().isoformat(),'amount_cny':'1'},
        headers={'Host':'another.example'}).status_code==403


def test_control_group_can_record_outcome_but_not_marketing(client):
    c=client;r=pick(c,arm='control')
    assert c.post('/api/followups',json={'opportunity_id':r['opportunity_id'], 'owner':'agent',
        'status':'contacted','note':'x'}).status_code==403
    assert contract(c,r).status_code==200
    assert payment(c).status_code==200
    assert c.get('/api/demo/sales/'+r['package_id']).json()['net_paid_cny']==2500
    assert c.get('/api/report').json()['incremental_profit_cny'] is None

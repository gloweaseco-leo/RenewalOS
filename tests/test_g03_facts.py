"""G0.3 business truth invariants; all data is synthetic and isolated by tmp_path."""
from datetime import date,timedelta
from fastapi.testclient import TestClient
import pytest
from renewalos.main import app
from renewalos.db import connect
from renewalos.facts import cohort_summary,freeze_cohort,BusinessRuleError

@pytest.fixture()
def c(tmp_path,monkeypatch):
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'new.sqlite'))
    with TestClient(app) as client:
        assert client.post('/api/demo/reset').status_code==200
        yield client


def csv_post(c,kind,header,*rows):
    content='\n'.join([header,*rows])+'\n'
    return c.post('/api/import/'+kind,content=content.encode(),headers={'Content-Type':'text/csv'})


def pkg(c):
    r=c.get('/api/opportunities').json()['items']
    return next(i for i in r if i['learner_id']!='L001' and i['expires_on'] >= date.today().isoformat())


def contract(c,p,contract_id='C-G03'):
    return csv_post(c,'contracts',
        'contract_id,learner_id,source_package_id,signed_on,contracted_amount_cny',
        f"{contract_id},{p['learner_id']},{p['package_id']},{date.today().isoformat()},2600.00")


def payment(c,contract_id='C-G03',event_id='PAY-01',amount='2600.00',day=None):
    day=day or date.today()
    return csv_post(c,'cash_events',
        'event_id,contract_id,event_on,kind,amount_cny,refund_of',
        f'{event_id},{contract_id},{day.isoformat()},payment,{amount},')


def refund(c,contract_id='C-G03',event_id='REF-01',pay='PAY-01',amount='600.00',day=None):
    day=day or date.today()
    return csv_post(c,'cash_events',
        'event_id,contract_id,event_on,kind,amount_cny,refund_of',
        f'{event_id},{contract_id},{day.isoformat()},refund,{amount},{pay}')


def test_freeze_idempotent_sticky_and_no_backdating(c):
    a=c.post('/api/cohorts/freeze',json={'store_id':'DEMO-STORE'})
    assert a.status_code==200, a.text
    assert a.json()['attribution_status']=='OBSERVATION_PENDING'
    assert a.json()['arms']['control']['eligible_families']>=0
    assert sum(x['member_packages'] for x in a.json()['arms'].values())>0
    b=c.post('/api/cohorts/freeze',json={'store_id':'DEMO-STORE'})
    assert a.json()==b.json()
    with connect() as con:
        members=con.execute('SELECT * FROM renewal_cohort_members').fetchall()
        assert len(members)>0
        assert 'PK001' not in {m['source_package_id'] for m in members} # paid before enrollment
        assert len({m['source_package_id'] for m in members})==len(members)
        assert con.execute('SELECT COUNT(*) FROM cohorts').fetchone()[0]==1
    with pytest.raises(BusinessRuleError):freeze_cohort('DEMO-STORE',today=date.today()-timedelta(days=1))


def test_contract_to_payment_to_partial_refund_and_timeline(c):
    p=pkg(c)
    cohort=c.post('/api/cohorts/freeze',json={'store_id':'DEMO-STORE'}).json()
    assert contract(c,p).status_code==200
    assert payment(c).status_code==200
    assert refund(c).status_code==200
    timeline=c.get('/api/cycles/'+p['package_id']+'/timeline').json()['events']
    assert {'renewal_contract','payment','refund','cohort_freeze','package'}<=set(e['event_type'] for e in timeline)
    report=c.get('/api/cohorts').json()['items'][0]
    arm=p['arm']
    assert report['arms'][arm]['net_paid_cny']>=2000.0
    assert report['incremental_profit_cny'] is None and report['roi'] is None
    assert report['attribution_status']=='OBSERVATION_PENDING'
    before=c.get('/api/opportunities').json()['items']
    assert p['opportunity_id'] in {x['opportunity_id'] for x in before}
    assert c.post('/api/recompute').status_code==200
    after=c.get('/api/opportunities').json()['items']
    assert p['opportunity_id'] not in {x['opportunity_id'] for x in after}
    with connect() as con:
        assert con.execute('SELECT is_active FROM opportunities WHERE opportunity_id=?',(p['opportunity_id'],)).fetchone()[0]==0


def test_payments_are_immutable_idempotent_and_batch_atomic(c):
    p=pkg(c)
    assert contract(c,p).status_code==200
    assert payment(c).status_code==200
    assert payment(c).status_code==200 # same event replay allowed
    assert payment(c,amount='2000.00').status_code==422
    invalid=csv_post(c,'cash_events',
        'event_id,contract_id,event_on,kind,amount_cny,refund_of',
        f"PAY-02,C-G03,{date.today()},payment,150,",
        f"REF-OVER,C-G03,{date.today()},refund,9999,PAY-02")
    assert invalid.status_code==422
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM cash_events WHERE event_id='PAY-02'").fetchone()[0]==0
        assert con.execute("SELECT COUNT(*) FROM cash_events WHERE event_id='PAY-01'").fetchone()[0]==1


def test_contract_owner_and_one_successor_rule(c):
    p=pkg(c)
    bad=csv_post(c,'contracts',
        'contract_id,learner_id,source_package_id,signed_on,contracted_amount_cny',
        f"X-C,L999,{p['package_id']},{date.today()},2600")
    assert bad.status_code==422
    assert contract(c,p).status_code==200
    assert contract(c,p).status_code==200
    duplicate=csv_post(c,'contracts',
        'contract_id,learner_id,source_package_id,signed_on,contracted_amount_cny',
        f"DIFF-C,{p['learner_id']},{p['package_id']},{date.today()},2600")
    assert duplicate.status_code==422


def test_refunds_require_actual_payment_in_same_contract(c):
    p=pkg(c)
    assert contract(c,p).status_code==200
    assert refund(c).status_code==422
    assert payment(c).status_code==200
    assert refund(c,amount='2700').status_code==422
    assert refund(c).status_code==200
    assert refund(c,event_id='REF-02',amount='2100').status_code==422
    assert refund(c,event_id='REF-02',amount='2000').status_code==200
    assert refund(c,event_id='REF-03',amount='1.00').status_code==422


def test_frozen_baseline_immutable_but_remaining_sessions_can_change(c):
    p=pkg(c)
    assert c.post('/api/cohorts/freeze',json={'store_id':'DEMO-STORE'}).status_code==200
    with connect() as con:
        original=con.execute('SELECT * FROM packages WHERE package_id=?',(p['package_id'],)).fetchone()
        pkgrow=dict(original)
    header='package_id,learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cny'
    def upload(expires,remaining):
        return csv_post(c,'packages',header,
                 f"{p['package_id']},{p['learner_id']},{pkgrow['course_type']},{pkgrow['purchased_on']},{expires},{pkgrow['purchased_sessions']},{remaining},{pkgrow['price_cents']/100:.2f}")
    new_expiry=(date.fromisoformat(pkgrow['expires_on'])+timedelta(days=4)).isoformat()
    assert upload(new_expiry,pkgrow['remaining_sessions']).status_code==422
    assert upload(pkgrow['expires_on'],pkgrow['remaining_sessions']).status_code==200
    assert upload(pkgrow['expires_on'],max(pkgrow['remaining_sessions']-1,0)).status_code==200
    with connect() as con:
        assert con.execute('SELECT expires_on FROM packages WHERE package_id=?',(p['package_id'],)).fetchone()[0]==pkgrow['expires_on']


def test_reassignment_of_learner_is_forbidden(c):
    header='learner_id,family_id,guardian_alias,store_id,contact_consent'
    assert csv_post(c,'learners',header,'L002,CHANGED,家长,DEMO-STORE,yes').status_code==422
    assert csv_post(c,'learners',header,'L002,F001,家长,NEW-STORE,yes').status_code==422


def test_outcome_window_and_refund_linkage(c):
    p=pkg(c)
    co=c.post('/api/cohorts/freeze',json={'store_id':'DEMO-STORE'}).json()
    assert contract(c,p).status_code==200
    assert payment(c).status_code==200
    # A payment after the outcome cutoff is not counted.
    late_day=date.today()+timedelta(days=47)
    assert payment(c,event_id='PAY-LATE',amount='900',day=late_day).status_code==200
    assert refund(c,event_id='REF-LATE',pay='PAY-LATE',amount='100',day=late_day).status_code==200
    assert refund(c,event_id='REF-EARLY',pay='PAY-01',amount='400',day=late_day).status_code==200
    with connect() as con:
        observed=cohort_summary(co['cohort_id'],con=con,as_of=date.today()+timedelta(days=60))
    assert observed['mature'] is True
    # First window payment 2600 minus linked refund 400; late payment's refund excluded.
    assert observed['arms'][p['arm']]['net_paid_cny']>=2200
    assert observed['roi'] is None


def test_demo_reset_clears_all_new_fact_tables(c):
    p=pkg(c)
    assert c.post('/api/cohorts/freeze',json={'store_id':'DEMO-STORE'}).status_code==200
    assert contract(c,p).status_code==200
    assert payment(c).status_code==200
    assert c.post('/api/demo/reset').status_code==200
    with connect() as con:
        for name in ['cohorts','renewal_cohort_members','renewal_contracts','cash_events']:
            assert con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]==0

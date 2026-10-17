from datetime import date, timedelta
import io
import pytest
from fastapi.testclient import TestClient
from renewalos.main import app
from renewalos.db import initialize,connect
from renewalos.core import list_opportunities,recompute
from renewalos.demo import load_demo

@pytest.fixture()
def cli(tmp_path,monkeypatch):
    db=tmp_path/'demo.sqlite'
    monkeypatch.setenv('RENEWAL_DB_PATH',str(db))
    monkeypatch.delenv('RENEWAL_AI_BASE_URL',raising=False)
    monkeypatch.delenv('RENEWAL_AI_API_KEY',raising=False)
    monkeypatch.delenv('RENEWAL_AI_MODEL',raising=False)
    with TestClient(app) as c:yield c

def test_demo_opportunities_and_consent(cli):
    r=cli.post('/api/demo/reset');assert r.status_code==200
    items=cli.get('/api/opportunities').json()['items']
    assert 0<len(items)<36
    ids={x['learner_id'] for x in items}
    assert 'L001' not in ids  # already paid renewal
    assert 'L012' not in ids and 'L024' not in ids # no marketing consent
    assert all(x['reason'] for x in items)
    assert all(x['rule_advice'] is None for x in items if x['arm']=='control')
    assert all(x['rule_advice'] for x in items if x['arm']!='control')
    assert all(0<=x['priority']<=100 for x in items)

def test_household_assignment_stable(cli):
    cli.post('/api/demo/reset')
    with connect() as con:
        a=con.execute('SELECT family_key,arm,assigned_on FROM experiment_assignments ORDER BY family_key').fetchall()
    cli.post('/api/recompute')
    with connect() as con:
        b=con.execute('SELECT family_key,arm,assigned_on FROM experiment_assignments ORDER BY family_key').fetchall()
    assert [tuple(x) for x in a]==[tuple(x) for x in b]
    assert set(r['arm'] for r in b).issubset({'ai','rules','control'})
    assert len(b)>0

def test_followup_control_protection(cli):
    cli.post('/api/demo/reset')
    items=cli.get('/api/opportunities').json()['items']
    ctrl=next(x for x in items if x['arm']=='control')
    active=next(x for x in items if x['arm']=='rules')
    data={'opportunity_id':ctrl['opportunity_id'],'owner':'测试员工','status':'contacted','note':'demo'}
    assert cli.post('/api/followups',json=data).status_code==403
    data['opportunity_id']=active['opportunity_id']
    assert cli.post('/api/followups',json=data).status_code==200
    after=cli.get('/api/opportunities').json()['items']
    assert next(x for x in after if x['opportunity_id']==active['opportunity_id'])['last_status']=='contacted'

def test_ai_never_faked(cli):
    cli.post('/api/demo/reset')
    items=cli.get('/api/opportunities').json()['items']
    ai=next(x for x in items if x['arm']=='ai')
    result=cli.post('/api/opportunities/'+ai['opportunity_id']+'/ai-advice')
    assert result.status_code==409
    assert cli.get('/api/health').json()['ai_configured'] is False

def test_report_does_not_claim_impact(cli):
    cli.post('/api/demo/reset')
    r=cli.get('/api/report').json()
    assert r['roi'] is None and r['incremental_profit_cny'] is None
    assert r['attribution_status']=='NOT_ESTABLISHED'
    assert r['paid_record_count']==1 and r['net_paid_cny']==2850

def test_import_transaction_rollback(cli):
    valid='learner_id,family_id,guardian_alias,store_id,contact_consent\nZZZ,FZ,匿名甲,S1,yes\n'
    r=cli.post('/api/import/learners',content=valid.encode(),headers={'Content-Type':'text/csv'})
    assert r.status_code==200 and r.json()['imported']==1
    bad='learner_id,family_id,guardian_alias,store_id,contact_consent\nYY1,F1,匿名乙,S1,yes\nYY2,F2,匿名丙,S1,invalid\n'
    r=cli.post('/api/import/learners',content=bad.encode(),headers={'Content-Type':'text/csv'})
    assert r.status_code==422
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM learners WHERE learner_id='YY1'").fetchone()[0]==0
    assert cli.post('/api/import/learners',content=b'x'*2100000).status_code==413

def test_refund_removes_paid_renewal_exclusion(cli):
    cli.post('/api/demo/reset')
    with connect() as con:
        con.execute('INSERT INTO renewals VALUES(?,?,?,?,?,?)',('R-REFUND','L001','PK001',date.today().isoformat(),285000,'refunded'))
    recompute()
    ids={x['learner_id'] for x in list_opportunities()}
    assert 'L001' in ids

def test_root_and_assets(cli):
    assert cli.get('/').status_code==200
    assert 'RenewalOS' in cli.get('/').text
    assert cli.get('/static/app.js').status_code==200
    assert cli.get('/static/style.css').status_code==200


def test_followup_history_survives_deactivation_and_no_new_actions(cli):
    cli.post('/api/demo/reset')
    target=next(x for x in cli.get('/api/opportunities').json()['items'] if x['arm']=='rules')
    oid=target['opportunity_id']
    r=cli.post('/api/followups',json={'opportunity_id':oid,'owner':'顾问A','status':'contacted','note':'已提供正常课程服务'})
    assert r.status_code==200
    with connect() as con:
        con.execute('INSERT INTO renewals VALUES(?,?,?,?,?,?)',
                    ('PAY-TEST',target['learner_id'],target['package_id'],date.today().isoformat(),30000,'paid'))
    cli.post('/api/recompute')
    active={x['opportunity_id'] for x in cli.get('/api/opportunities').json()['items']}
    assert oid not in active
    history=cli.get('/api/followups/'+oid).json()['items']
    assert len(history)==1 and history[0]['note']=='已提供正常课程服务'
    with connect() as con:
        row=con.execute('SELECT is_active,closed_at FROM opportunities WHERE opportunity_id=?',(oid,)).fetchone()
        assert row['is_active']==0 and row['closed_at']
    assert cli.post('/api/followups',json={'opportunity_id':oid,'owner':'顾问A','status':'planned','note':''}).status_code==404


def test_same_family_id_in_two_stores_does_not_share_assignment_record(cli):
    cli.post('/api/demo/reset')
    with connect() as con:
        con.execute("INSERT INTO learners VALUES(?,?,?,?,?)",('OTHER-LEARNER','F001','合成监护人','OTHER-STORE',1))
        con.execute("INSERT INTO packages VALUES(?,?,?,?,?,?,?,?)",
                    ('OTHER-PKG','OTHER-LEARNER','少儿游泳',
                     (date.today()-timedelta(days=30)).isoformat(),
                     (date.today()+timedelta(days=5)).isoformat(),12,2,30000))
    cli.post('/api/recompute')
    with connect() as con:
        rows=con.execute("SELECT family_key,store_id,family_id FROM experiment_assignments WHERE family_id='F001'").fetchall()
        assert {r['family_key'] for r in rows}=={'DEMO-STORE:F001','OTHER-STORE:F001'}
        assert len(rows)==2
    other=next(x for x in cli.get('/api/opportunities').json()['items'] if x['learner_id']=='OTHER-LEARNER')
    assert other['arm'] in ('control','rules','ai')


def test_model_advice_only_ai_and_no_control_message(cli):
    cli.post('/api/demo/reset')
    for item in cli.get('/api/opportunities').json()['items']:
        if item['arm']=='control':
            assert item['rule_advice'] is None and item['model_advice'] is None
            assert cli.post('/api/opportunities/'+item['opportunity_id']+'/ai-advice').status_code==403
            break


def test_rerun_is_idempotent_and_does_not_delete_history(cli):
    cli.post('/api/demo/reset')
    before=cli.get('/api/opportunities').json()['items']
    cli.post('/api/recompute')
    after=cli.get('/api/opportunities').json()['items']
    assert {i['opportunity_id'] for i in before}=={i['opportunity_id'] for i in after}
    assert cli.get('/api/report').json()['archived_opportunities']==0


def test_cross_customer_renewal_rejected(cli):
    cli.post('/api/demo/reset')
    invalid='renewal_id,learner_id,source_package_id,paid_on,amount_cny,status\nR-X,L002,PK001,2026-10-17,3000,paid\n'
    r=cli.post('/api/import/renewals',content=invalid.encode(),headers={'Content-Type':'text/csv'})
    assert r.status_code==422
    assert '不一致' in r.json()['detail']
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM renewals WHERE renewal_id='R-X'").fetchone()[0]==0


def test_cross_site_post_rejected(cli):
    r=cli.post('/api/demo/reset',headers={'Origin':'https://malicious.example'})
    assert r.status_code==403
    r=cli.post('/api/demo/reset',headers={'Host':'evil.example'})
    assert r.status_code==403


def test_v01_database_migration_preserves_history(tmp_path):
    import sqlite3
    path=tmp_path/'previous.sqlite'
    legacy=sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE learners (learner_id TEXT PRIMARY KEY,family_id TEXT NOT NULL,guardian_alias TEXT NOT NULL,store_id TEXT NOT NULL,contact_consent INTEGER NOT NULL);
        CREATE TABLE opportunities (opportunity_id TEXT PRIMARY KEY,learner_id TEXT NOT NULL,package_id TEXT NOT NULL UNIQUE,signals_json TEXT NOT NULL,priority INTEGER NOT NULL,reason TEXT NOT NULL,rule_advice TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE experiment_assignments (family_id TEXT PRIMARY KEY, arm TEXT NOT NULL,assigned_on TEXT NOT NULL);
        INSERT INTO learners VALUES('LM','FM','家长','S1',1);
        INSERT INTO experiment_assignments VALUES('FM','rules','2026-01-01');
        INSERT INTO opportunities VALUES('OM','LM','PM','{}',90,'历史记录','原建议','2026-01-01');
    """)
    legacy.close()
    initialize(path)
    with connect(path) as con:
        assert con.execute("SELECT is_active FROM opportunities WHERE opportunity_id='OM'").fetchone()[0]==1
        row=con.execute('SELECT store_id,family_key,arm FROM experiment_assignments').fetchone()
        assert tuple(row)==('S1','S1:FM','rules')
    initialize(path)
    with connect(path) as con:
        assert con.execute('SELECT COUNT(*) FROM experiment_assignments').fetchone()[0]==1

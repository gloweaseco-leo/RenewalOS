"""G0.7 task assignment, staff queue, transition and audit protections."""
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from renewalos.main import app
from renewalos.db import connect
from renewalos.core import recompute
from renewalos.demo import load_demo


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'g07.sqlite'))
    monkeypatch.delenv('RENEWAL_AI_BASE_URL',raising=False)
    monkeypatch.delenv('RENEWAL_AI_API_KEY',raising=False)
    monkeypatch.delenv('RENEWAL_AI_MODEL',raising=False)
    with TestClient(app) as c:
        assert c.post('/api/demo/reset').status_code==200
        yield c


def pick(c,arm='rules'):
    return next(x for x in c.get('/api/opportunities').json()['items'] if x['arm']==arm)


def create(c,item=None,day=None,owner='顾问甲'):
    item=item or pick(c)
    return c.post('/api/tasks',json={'opportunity_id':item['opportunity_id'],'owner':owner,
                                    'due_on':day or date.today().isoformat(),'note':'合成任务'})


def test_create_queue_and_owner_filter(client):
    target=pick(client)
    res=create(client,target)
    assert res.status_code==200,res.text
    taskid=res.json()['task_id']
    assert taskid.startswith('T-')
    q=client.get('/api/tasks').json()
    assert q['summary']['total']==1 and q['summary']['due_today']==1 and q['summary']['open']==1
    assert q['items'][0]['owner']=='顾问甲' and q['items'][0]['task_id']==taskid
    assert q['items'][0]['opportunity_id']==target['opportunity_id']
    assert client.get('/api/tasks?owner=顾问乙').json()['items']==[]
    assert len(client.get('/api/tasks?owner=顾问甲&due_bucket=today').json()['items'])==1
    assert client.get('/api/tasks?store_id=OTHER').json()['items']==[]
    assert len(client.get('/api/tasks/'+taskid+'/history').json()['items'])==1


def test_no_task_for_control_or_unknown_and_no_repeat(client):
    assert create(client,pick(client,'control')).status_code==422
    assert client.post('/api/tasks',json={'opportunity_id':'O-UNKNOWN','owner':'test',
           'due_on':date.today().isoformat()}).status_code==422
    active=pick(client)
    assert create(client,active).status_code==200
    assert create(client,active).status_code==422
    assert client.get('/api/tasks').json()['summary']['total']==1
    assert client.get('/api/tasks?status=imaginary').status_code==422
    assert client.get('/api/tasks?due_bucket=imaginary').status_code==422


def test_reschedule_ownership_and_due_buckets(client):
    tomorrow=(date.today()+timedelta(days=1)).isoformat()
    yesterday=(date.today()-timedelta(days=1)).isoformat()
    t=create(client).json()['task_id']
    response=client.patch('/api/tasks/'+t,json={'actor':'主管','owner':'顾问乙','due_on':yesterday,
                                               'status':'in_progress','note':'接手并复核计划'})
    assert response.status_code==200
    task=client.get('/api/tasks').json()['items'][0]
    assert task['owner']=='顾问乙' and task['due_bucket']=='overdue'
    assert client.get('/api/tasks?due_bucket=overdue').json()['summary']['overdue']==1
    assert client.patch('/api/tasks/'+t,json={'actor':'顾问乙','due_on':tomorrow}).status_code==200
    assert client.get('/api/tasks').json()['items'][0]['due_bucket']=='upcoming'
    assert len(client.get('/api/tasks/'+t+'/history').json()['items'])==3


def test_followup_atomic_and_legacy_path_sync(client):
    target=pick(client)
    t=create(client,target).json()['task_id']
    r=client.post('/api/tasks/'+t+'/followups',json={'actor':'顾问甲','status':'contacted','note':'确认课程进度'})
    assert r.status_code==200
    assert client.get('/api/tasks').json()['items'][0]['status']=='in_progress'
    assert client.get('/api/followups/'+target['opportunity_id']).json()['items'][0]['note']=='确认课程进度'
    r=client.post('/api/followups',json={'opportunity_id':target['opportunity_id'],
        'owner':'顾问甲','status':'no_response','note':'待回访'})
    assert r.status_code==200
    assert client.get('/api/tasks').json()['items'][0]['status']=='waiting'
    evs=client.get('/api/tasks/'+t+'/history').json()['items']
    assert len(evs)==3 and evs[-1]['details'].startswith('no_response')


def test_terminal_requires_note_and_preserves_history(client):
    t=create(client).json()['task_id']
    assert client.patch('/api/tasks/'+t,json={'actor':'经理','status':'done','note':''}).status_code==422
    assert client.patch('/api/tasks/'+t,json={'actor':'经理','status':'done','note':'无需追加营销'}).status_code==200
    assert client.get('/api/tasks?due_bucket=resolved').json()['summary']['resolved']==1
    assert client.post('/api/tasks/'+t+'/followups',json={'actor':'经理','status':'contacted'}).status_code==422
    assert client.patch('/api/tasks/'+t,json={'actor':'经理','status':'open'}).status_code==422
    assert client.patch('/api/tasks/'+t,json={'actor':'经理','status':'open','note':'经核验客户仍需要服务'}).status_code==200
    assert client.get('/api/tasks').json()['items'][0]['status']=='open'
    assert len(client.get('/api/tasks/'+t+'/history').json()['items'])==3


def test_archived_opportunity_retains_task_and_forbids_more_marketing(client):
    target=pick(client)
    tid=create(client,target).json()['task_id']
    with connect() as con:
        con.execute('INSERT INTO renewals VALUES(?,?,?,?,?,?)',('G07-PAID',target['learner_id'],target['package_id'],
                                                                date.today().isoformat(),20000,'paid'))
    assert client.post('/api/recompute').status_code==200
    task=client.get('/api/tasks').json()['items'][0]
    assert task['task_id']==tid and not task['is_active']
    assert client.post('/api/tasks/'+tid+'/followups',json={'actor':'顾问甲','status':'contacted'}).status_code==422
    assert client.patch('/api/tasks/'+tid,json={'actor':'主管','status':'done','note':'已核对模拟交易，不是AI增量'}).status_code==200
    assert client.patch('/api/tasks/'+tid,json={'actor':'主管','status':'open','note':'重新启动'}).status_code==422
    with connect() as con:
        con.execute('INSERT INTO renewals VALUES(?,?,?,?,?,?)',('G07-REFUND',target['learner_id'],target['package_id'],
                                                                date.today().isoformat(),20000,'refunded'))
    client.post('/api/recompute')
    assert client.patch('/api/tasks/'+tid,json={'actor':'主管','status':'open','note':'原付款已全额退款，恢复合成服务观察'}).status_code==200


def test_reset_removes_tasks_and_events(client):
    tid=create(client).json()['task_id']
    assert client.post('/api/demo/reset').status_code==200
    assert client.get('/api/tasks').json()['items']==[]
    assert client.get('/api/tasks/'+tid+'/history').status_code==404
    with connect() as con:
        assert con.execute('SELECT COUNT(*) FROM work_task_events').fetchone()[0]==0


def test_no_real_roi_and_no_public_access(client):
    t=create(client).json()['task_id']
    assert client.get('/api/report').json()['roi'] is None
    assert client.post('/api/tasks/'+t+'/followups',json={'actor':'顾问甲','status':'closed','note':'完成'}) .status_code==200
    assert client.get('/api/report').json()['incremental_profit_cny'] is None
    assert client.post('/api/tasks',json={'opportunity_id':'x','owner':'a','due_on':date.today().isoformat()},
          headers={'Host':'other.example'}).status_code==403
    assert client.get('/').status_code==200
    assert '销售待办' in client.get('/').text


def test_operator_note_does_not_silently_reassign_task(client):
    target=pick(client)
    t=create(client,target,owner='顾问甲').json()['task_id']
    assert client.post('/api/tasks/'+t+'/followups',json={'actor':'协作教练',
        'status':'contacted','note':'协助核实上课安排'}).status_code==200
    assert client.get('/api/tasks').json()['items'][0]['owner']=='顾问甲'
    assert client.post('/api/followups',json={'opportunity_id':target['opportunity_id'],
        'owner':'合作顾问','status':'no_response','note':'稍后回复'}).status_code==200
    assert client.get('/api/tasks').json()['items'][0]['owner']=='顾问甲'


def test_cash_event_archives_task_but_keeps_history(client):
    target=pick(client)
    tid=create(client,target).json()['task_id']
    cid='G07-CONTRACT'
    c=client.post('/api/demo/sales/contracts',json={'source_package_id':target['package_id'],
        'contract_id':cid,'signed_on':date.today().isoformat(),'amount_cny':'1280.00'})
    assert c.status_code==200,c.text
    pay=client.post('/api/demo/sales/payments',json={'contract_id':cid,
        'event_id':'G07-PAY','event_on':date.today().isoformat(),'amount_cny':'1280.00'})
    assert pay.status_code==200,pay.text
    item=client.get('/api/tasks').json()['items'][0]
    assert item['task_id']==tid and item['is_active']==0 and item['net_paid_cny']==1280.0
    assert client.post('/api/tasks/'+tid+'/followups',json={'actor':'顾问甲','status':'contacted'}).status_code==422
    assert client.patch('/api/tasks/'+tid,json={'actor':'主管','status':'done','note':'已核对模拟收款事实'}).status_code==200
    assert len(client.get('/api/tasks/'+tid+'/history').json()['items'])==2
    refund=client.post('/api/demo/sales/refunds',json={'payment_event_id':'G07-PAY',
        'event_id':'G07-REF','event_on':date.today().isoformat(),'amount_cny':'1280.00'})
    assert refund.status_code==200,refund.text
    item=client.get('/api/tasks').json()['items'][0]
    assert item['net_paid_cny']==0 and item['is_active']==1
    assert client.patch('/api/tasks/'+tid,json={'actor':'主管','status':'open','note':'已全额退款，重新核实需求'}).status_code==200
    assert client.get('/api/report').json()['roi'] is None


def test_database_reinitialize_preserves_task_and_followup_history(client):
    from renewalos.db import initialize
    opportunity=pick(client)
    tid=create(client,opportunity).json()['task_id']
    assert client.post('/api/tasks/'+tid+'/followups',json={'actor':'顾问甲',
        'status':'contacted','note':'合成记录'}).status_code==200
    initialize()  # simulate restart / schema upgrade; must not erase existing task facts
    assert client.get('/api/tasks').json()['summary']['total']==1
    assert len(client.get('/api/tasks/'+tid+'/history').json()['items'])==2
    assert len(client.get('/api/followups/'+opportunity['opportunity_id']).json()['items'])==1

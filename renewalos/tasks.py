"""G0.7 local task operations: synthetic only, append-only action history.

No identities or permissions are inferred from an owner alias. Not production auth.
"""
from datetime import date, timedelta
from uuid import uuid4
from .db import connect
from .core import now_iso

OPEN = {'open', 'in_progress', 'waiting'}
STATES = OPEN | {'done', 'cancelled'}
FOLLOWUP_TO_TASK = {
    'planned': 'open', 'contacted': 'in_progress', 'no_response': 'waiting',
    'not_suitable': 'cancelled', 'closed': 'done'
}

class TaskRuleError(ValueError):
    pass


def _require_day(value):
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise TaskRuleError('任务日期必须为 YYYY-MM-DD') from exc
    if parsed.isoformat() != value:
        raise TaskRuleError('任务日期必须为 YYYY-MM-DD')
    if parsed < date.today() - timedelta(days=365) or parsed > date.today() + timedelta(days=365):
        raise TaskRuleError('任务日期仅允许在今天前后365天范围内')
    return parsed


def _opportunity(con, opportunity_id):
    return con.execute('''SELECT o.opportunity_id,o.is_active,o.priority,o.package_id,l.store_id,l.family_id,
          l.guardian_alias,l.contact_consent,a.arm
          FROM opportunities o JOIN learners l ON o.learner_id=l.learner_id
          JOIN experiment_assignments a ON a.store_id=l.store_id AND a.family_id=l.family_id
          WHERE o.opportunity_id=?''',(opportunity_id,)).fetchone()


def create_task(opportunity_id, owner, due_on, note='', path=None):
    _require_day(due_on)
    owner = owner.strip()
    if not owner or len(owner)>50 or len(note)>1000:
        raise TaskRuleError('责任人或备注长度不合法')
    with connect(path) as con:
        o=_opportunity(con, opportunity_id)
        if o is None or not o['is_active']:
            raise TaskRuleError('只能给活跃续费机会创建跟进任务')
        if o['arm']=='control' or not o['contact_consent']:
            raise TaskRuleError('对照组或未授权客户不可创建额外营销任务')
        existing=con.execute('SELECT task_id FROM work_tasks WHERE opportunity_id=?',(opportunity_id,)).fetchone()
        if existing:
            raise TaskRuleError('该机会已有任务，请修改原任务而不是重复创建')
        ident='T-'+uuid4().hex
        when=now_iso()
        con.execute('''INSERT INTO work_tasks(task_id,opportunity_id,store_id,owner,due_on,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?)''',(ident,opportunity_id,o['store_id'],owner,due_on,'open',when,when))
        con.execute('''INSERT INTO work_task_events(task_id,actor,event_kind,details,logged_at)
                       VALUES(?,?,?,?,?)''',(ident,owner,'created',note,when))
        return {'task_id':ident,'status':'open'}


def list_tasks(store_id=None, owner=None, status=None, due_bucket=None, path=None, today=None):
    today=today or date.today()
    with connect(path) as con:
        rows=con.execute('''SELECT t.*,o.is_active,o.priority,p.course_type,l.guardian_alias,l.learner_id,
            a.arm, (SELECT COUNT(*) FROM followups f WHERE f.opportunity_id=t.opportunity_id) AS followup_count,
            (SELECT COALESCE(SUM(CASE WHEN ce.kind='payment' THEN ce.amount_cents ELSE -ce.amount_cents END),0)
             FROM renewal_contracts rc JOIN cash_events ce ON ce.contract_id=rc.contract_id
             WHERE rc.source_package_id=o.package_id) AS linked_net_cents
            FROM work_tasks t JOIN opportunities o ON t.opportunity_id=o.opportunity_id
            JOIN packages p ON p.package_id=o.package_id
            JOIN learners l ON l.learner_id=o.learner_id
            JOIN experiment_assignments a ON a.store_id=l.store_id AND a.family_id=l.family_id
            ORDER BY t.due_on ASC,t.created_at ASC''').fetchall()
        result=[]
        for r in rows:
            item=dict(r)
            if store_id and item['store_id']!=store_id:continue
            if owner and item['owner'].casefold()!=owner.strip().casefold():continue
            if status and status!='all' and item['status']!=status:continue
            if item['status'] in OPEN:
                bucket='overdue' if item['due_on']<today.isoformat() else 'today' if item['due_on']==today.isoformat() else 'upcoming'
            else:
                bucket='resolved'
            if due_bucket and due_bucket!='all' and bucket!=due_bucket:continue
            item['due_bucket']=bucket
            item['net_paid_cny']=round(item.pop('linked_net_cents')/100,2)
            result.append(item)
        return result


def task_summary(store_id=None, owner=None, path=None, today=None):
    items=list_tasks(store_id,owner,path=path,today=today)
    return {'total':len(items), 'open':sum(x['status'] in OPEN for x in items),
            'due_today':sum(x['due_bucket']=='today' for x in items),
            'overdue':sum(x['due_bucket']=='overdue' for x in items),
            'resolved':sum(x['due_bucket']=='resolved' for x in items),
            'note':'合成经营工作量统计，未接认证账户和真实支付，不是AI增量收益。'}


def task_history(task_id, path=None):
    with connect(path) as con:
        if not con.execute('SELECT 1 FROM work_tasks WHERE task_id=?',(task_id,)).fetchone():
            raise TaskRuleError('任务不存在')
        return [dict(x) for x in con.execute('SELECT * FROM work_task_events WHERE task_id=? ORDER BY event_id',(task_id,))]


def update_task(task_id, actor, *, owner=None, due_on=None, status=None, note='', path=None):
    actor=actor.strip()
    if not actor or len(actor)>50 or len(note)>1000:
        raise TaskRuleError('操作人或备注长度不合法')
    if due_on is not None:_require_day(due_on)
    if owner is not None and (not owner.strip() or len(owner.strip())>50):
        raise TaskRuleError('责任人不合法')
    if status is not None and status not in STATES:
        raise TaskRuleError('任务状态无效')
    with connect(path) as con:
        row=con.execute('SELECT * FROM work_tasks WHERE task_id=?',(task_id,)).fetchone()
        if not row:raise TaskRuleError('任务不存在')
        new_status=status or row['status']
        if row['status'] in ('done','cancelled') and new_status in OPEN:
            source=con.execute('''SELECT o.is_active,l.contact_consent,a.arm FROM opportunities o
                JOIN learners l ON l.learner_id=o.learner_id
                JOIN experiment_assignments a ON a.store_id=l.store_id AND a.family_id=l.family_id
                WHERE o.opportunity_id=?''',(row['opportunity_id'],)).fetchone()
            if not source or not source['is_active'] or not source['contact_consent'] or source['arm']=='control':
                raise TaskRuleError('当前机会未重新符合跟进资格，禁止重启任务')
            if not note.strip():
                raise TaskRuleError('重新开启已结束任务必须填写原因，保留原历史')
        if new_status in ('done','cancelled') and not note.strip():
            raise TaskRuleError('结束任务必须填写结果或原因')
        new_owner=owner.strip() if owner is not None else row['owner']
        new_day=due_on if due_on is not None else row['due_on']
        if new_status==row['status'] and new_owner==row['owner'] and new_day==row['due_on'] and not note.strip():
            return {'task_id':task_id,'status':row['status'],'unchanged':True}
        when=now_iso()
        con.execute('''UPDATE work_tasks SET owner=?,due_on=?,status=?,updated_at=?,resolved_at=? WHERE task_id=?''',
                    (new_owner,new_day,new_status,when,when if new_status in ('done','cancelled') else None,task_id))
        details='；'.join(x for x in [f"状态：{row['status']}→{new_status}" if new_status!=row['status'] else '',
                     f"负责人：{row['owner']}→{new_owner}" if new_owner!=row['owner'] else '',
                     f"截止：{row['due_on']}→{new_day}" if new_day!=row['due_on'] else '',note.strip()] if x)
        con.execute('INSERT INTO work_task_events(task_id,actor,event_kind,details,logged_at) VALUES(?,?,?,?,?)',
                    (task_id,actor,'updated',details,when))
        return {'task_id':task_id,'status':new_status,'unchanged':False}


def record_task_followup(task_id, actor, status, note, path=None):
    actor=actor.strip()
    if not actor or len(actor)>50 or len(note)>1000:
        raise TaskRuleError('操作人或记录不合法')
    if status not in FOLLOWUP_TO_TASK:
        raise TaskRuleError('跟进状态不合法')
    with connect(path) as con:
        row=con.execute('''SELECT t.*,o.is_active,l.contact_consent,a.arm FROM work_tasks t
          JOIN opportunities o ON t.opportunity_id=o.opportunity_id
          JOIN learners l ON o.learner_id=l.learner_id
          JOIN experiment_assignments a ON a.store_id=l.store_id AND a.family_id=l.family_id
          WHERE task_id=?''',(task_id,)).fetchone()
        if not row:raise TaskRuleError('任务不存在')
        if row['arm']=='control' or not row['contact_consent']:
            raise TaskRuleError('未授权干预')
        if not row['is_active'] or row['status'] not in OPEN:
            raise TaskRuleError('归档机会或已结束任务不可新增营销跟进')
        when=now_iso()
        con.execute('INSERT INTO followups(opportunity_id,owner,status,note,logged_at) VALUES(?,?,?,?,?)',
                    (row['opportunity_id'],actor,status,note,when))
        next_status=FOLLOWUP_TO_TASK[status]
        con.execute('UPDATE work_tasks SET status=?,updated_at=?,resolved_at=? WHERE task_id=?',
                    (next_status,when,when if next_status in ('done','cancelled') else None,task_id))
        con.execute('INSERT INTO work_task_events(task_id,actor,event_kind,details,logged_at) VALUES(?,?,?,?,?)',
                    (task_id,actor,'followup',status+(' · '+note.strip() if note.strip() else ''),when))
        return {'task_id':task_id,'task_status':next_status,'followup_status':status}

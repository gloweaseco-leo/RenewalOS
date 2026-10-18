"""G1-C tenant-scoped PostgreSQL business commands (synthetic money only).

The caller MUST supply a server-verified TenantScope, never raw request user_id.
All operations use one transaction; rows are scoped by org+store, and role is
checked by the adapter and a restrictive database RLS policy.
"""
from datetime import date
from uuid import uuid4

from .pg_store import TenantScope, TenantAccessError, tenant_transaction, ID


class BusinessConflict(ValueError):
    pass


class BusinessMissing(LookupError):
    pass


def _id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('IDs must be 2-64 ASCII letters, numbers, underscore or hyphen')
    return value


def _amount(value):
    if type(value) is not int or not 0 < value <= 100_000_000:
        raise ValueError('amount_cents must be a positive integer <= 100000000')
    return value


def _date(value):
    if isinstance(value, date) and type(value) is date:
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError('invalid ISO date')


def _role(con, scope):
    row = con.execute("SELECT renewalos.actor_store_role()").fetchone()
    role = row[0] if row else None
    if role not in ('manager', 'staff'):
        raise TenantAccessError('membership unavailable or disabled')
    return role


def _manager(con, scope):
    if _role(con, scope) != 'manager':
        raise TenantAccessError('manager role required')


def _audit(con, scope, action, resource):
    con.execute('''INSERT INTO renewalos.business_action_events
      (org_id,store_id,event_id,actor_user_id,action,resource_id)
      VALUES(%s,%s,%s,%s,%s,%s)''',
      (scope.org_id,scope.store_id,str(uuid4()),scope.user_id,action,resource))


def _opp(con, scope, opportunity_id, *, lock=False):
    row=con.execute('''SELECT o.source_package_id,o.learner_id,o.assigned_user_id,
          o.arm,o.stage,l.contact_consent
        FROM renewalos.renewal_opportunities o
        JOIN renewalos.learners l ON l.org_id=o.org_id AND l.store_id=o.store_id
             AND l.learner_id=o.learner_id
        WHERE o.org_id=%s AND o.store_id=%s AND o.opportunity_id=%s'''+
        (' FOR UPDATE OF o' if lock else ''),
        (scope.org_id,scope.store_id,_id(opportunity_id))).fetchone()
    if row is None:
        raise BusinessMissing('opportunity not found in authorized store')
    return row


def _assert_contactable(opp):
    if not opp[5]:
        raise BusinessConflict('no contact consent; cannot create marketing task or followup')
    if opp[3] == 'control':
        raise BusinessConflict('control arm may record factual sales only, not new marketing')
    if opp[4] in ('signed','paid','closed'):
        raise BusinessConflict('opportunity no longer eligible for marketing')


def assign_task(dsn, scope:TenantScope, opportunity_id, task_id, assignee_id, due_on):
    _id(task_id); _id(assignee_id)
    due = _date(due_on)
    with tenant_transaction(dsn,scope,roles=('manager',)) as con:
        _manager(con,scope)
        opp=_opp(con,scope,opportunity_id,lock=True)
        existing=con.execute('''SELECT task_id,assigned_user_id,due_on
            FROM renewalos.work_tasks WHERE org_id=%s AND store_id=%s AND opportunity_id=%s''',
            (scope.org_id,scope.store_id,opportunity_id)).fetchone()
        if existing is not None:
            if (existing[0],existing[1],existing[2])==(task_id,assignee_id,due):
                return {'task_id':task_id,'created':False}
            raise BusinessConflict('this opportunity already has a task; no silent reassignment')
        _assert_contactable(opp)
        member=con.execute('SELECT renewalos.is_active_store_member(%s)',
                           (assignee_id,)).fetchone()
        if member is None or not member[0]:
            raise TenantAccessError('assignee is not an enabled store member')
        con.execute('''INSERT INTO renewalos.work_tasks
           (org_id,store_id,task_id,opportunity_id,assigned_user_id,due_on)
           VALUES(%s,%s,%s,%s,%s,%s)''',
           (scope.org_id,scope.store_id,task_id,opportunity_id,assignee_id,due))
        con.execute('''UPDATE renewalos.renewal_opportunities
           SET assigned_user_id=%s,stage='assigned',updated_at=now()
           WHERE org_id=%s AND store_id=%s AND opportunity_id=%s''',
           (assignee_id,scope.org_id,scope.store_id,opportunity_id))
        _audit(con,scope,'task_assigned',task_id)
    return {'task_id':task_id,'created':True}


def record_followup(dsn,scope:TenantScope,opportunity_id,followup_id,result,note=''):
    _id(followup_id)
    if result not in ('contacted','no_answer','customer_declined','followup_later'):
        raise ValueError('unsupported followup result')
    if not isinstance(note,str) or len(note)>1000:
        raise ValueError('note too long')
    # Data minimization: this is NOT a channel for names, phone numbers, or diagnosis.
    with tenant_transaction(dsn,scope) as con:
        role=_role(con,scope)
        existing=con.execute('''SELECT opportunity_id,actor_user_id,result,note
            FROM renewalos.followup_events WHERE org_id=%s AND store_id=%s AND followup_id=%s''',
            (scope.org_id,scope.store_id,followup_id)).fetchone()
        if existing:
            if tuple(existing)==(opportunity_id,scope.user_id,result,note):
                return {'followup_id':followup_id,'created':False}
            raise BusinessConflict('followup ID already used for different facts')
        opp=_opp(con,scope,opportunity_id,lock=True)
        _assert_contactable(opp)
        task=con.execute('''SELECT assigned_user_id,status FROM renewalos.work_tasks
          WHERE org_id=%s AND store_id=%s AND opportunity_id=%s FOR UPDATE''',
          (scope.org_id,scope.store_id,opportunity_id)).fetchone()
        if task is None or task[1] in ('done','cancelled'):
            raise BusinessConflict('no active work task')
        if role!='manager' and task[0]!=scope.user_id:
            raise TenantAccessError('not assigned to this task')
        con.execute('''INSERT INTO renewalos.followup_events
          (org_id,store_id,followup_id,opportunity_id,actor_user_id,result,note)
          VALUES(%s,%s,%s,%s,%s,%s,%s)''',
          (scope.org_id,scope.store_id,followup_id,opportunity_id,scope.user_id,result,note))
        con.execute('''UPDATE renewalos.work_tasks SET status='in_progress'
           WHERE org_id=%s AND store_id=%s AND opportunity_id=%s''',
           (scope.org_id,scope.store_id,opportunity_id))
        con.execute('''UPDATE renewalos.renewal_opportunities
           SET stage='contacted',updated_at=now()
           WHERE org_id=%s AND store_id=%s AND opportunity_id=%s''',
           (scope.org_id,scope.store_id,opportunity_id))
        _audit(con,scope,'followup_recorded',followup_id)
    return {'followup_id':followup_id,'created':True}


def sign_synthetic_contract(dsn,scope:TenantScope,opportunity_id,contract_id,signed_on,amount_cents):
    _id(contract_id); _amount(amount_cents); signed=_date(signed_on)
    with tenant_transaction(dsn,scope,roles=('manager',)) as con:
        _manager(con,scope)
        opp=_opp(con,scope,opportunity_id,lock=True)
        current=con.execute('''SELECT contract_id,signed_on,contracted_amount_cents
           FROM renewalos.renewal_contracts WHERE org_id=%s AND store_id=%s AND source_package_id=%s''',
           (scope.org_id,scope.store_id,opp[0])).fetchone()
        if current:
            if tuple(current)==(contract_id,signed,amount_cents):
                return {'contract_id':contract_id,'created':False,'provenance':'synthetic'}
            raise BusinessConflict('source package already has a different renewal contract')
        con.execute('''INSERT INTO renewalos.renewal_contracts
          (org_id,store_id,contract_id,source_package_id,learner_id,signed_on,contracted_amount_cents,provenance)
          VALUES(%s,%s,%s,%s,%s,%s,%s,'synthetic')''',
          (scope.org_id,scope.store_id,contract_id,opp[0],opp[1],signed,amount_cents))
        con.execute('''UPDATE renewalos.renewal_opportunities
            SET stage='signed',updated_at=now()
            WHERE org_id=%s AND store_id=%s AND opportunity_id=%s''',
            (scope.org_id,scope.store_id,opportunity_id))
        _audit(con,scope,'synthetic_contract_signed',contract_id)
    return {'contract_id':contract_id,'created':True,'provenance':'synthetic'}


def record_synthetic_cash(dsn,scope:TenantScope,contract_id,event_id,kind,amount_cents,occurred_on,refund_of=None):
    _id(contract_id);_id(event_id);_amount(amount_cents); occurred=_date(occurred_on)
    if kind not in ('payment','refund') or (kind=='refund')!=bool(refund_of):
        raise ValueError('refund requires source payment; payment must have none')
    if refund_of:
        _id(refund_of)
    with tenant_transaction(dsn,scope,roles=('manager',)) as con:
        _manager(con,scope)
        contract=con.execute('''SELECT source_package_id,signed_on,provenance FROM renewalos.renewal_contracts
           WHERE org_id=%s AND store_id=%s AND contract_id=%s FOR UPDATE''',
           (scope.org_id,scope.store_id,contract_id)).fetchone()
        if not contract:
            raise BusinessMissing('contract not found')
        if contract[2]!='synthetic':
            raise BusinessConflict('this API records synthetic transactions only')
        if occurred<contract[1]:
            raise BusinessConflict('cash date before contract signature')
        if refund_of:
            payment=con.execute('''SELECT occurred_on FROM renewalos.cash_events
                WHERE org_id=%s AND store_id=%s AND contract_id=%s AND event_id=%s AND kind='payment' ''',
                (scope.org_id,scope.store_id,contract_id,refund_of)).fetchone()
            if payment and occurred<payment[0]:
                raise BusinessConflict('refund predates source payment')
        old=con.execute('''SELECT contract_id,occurred_on,kind,amount_cents,refund_of,provenance
             FROM renewalos.cash_events WHERE org_id=%s AND store_id=%s AND event_id=%s''',
             (scope.org_id,scope.store_id,event_id)).fetchone()
        if old:
            if tuple(old)==(contract_id,occurred,kind,amount_cents,refund_of,'synthetic'):
                return {'event_id':event_id,'created':False,'provenance':'synthetic'}
            raise BusinessConflict('cash ID already used for different facts')
        con.execute('''INSERT INTO renewalos.cash_events
             (org_id,store_id,event_id,contract_id,occurred_on,kind,amount_cents,refund_of,provenance)
             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'synthetic')''',
             (scope.org_id,scope.store_id,event_id,contract_id,occurred,kind,amount_cents,refund_of))
        net=con.execute('''SELECT coalesce(sum(CASE WHEN kind='payment' THEN amount_cents ELSE -amount_cents END),0)
             FROM renewalos.cash_events WHERE org_id=%s AND store_id=%s AND contract_id=%s''',
             (scope.org_id,scope.store_id,contract_id)).fetchone()[0]
        con.execute('''UPDATE renewalos.renewal_opportunities
             SET stage=%s,updated_at=now()
             WHERE org_id=%s AND store_id=%s AND source_package_id=%s''',
             ('paid' if net>0 else 'signed',scope.org_id,scope.store_id,contract[0]))
        _audit(con,scope,'synthetic_'+kind+'_recorded',event_id)
    return {'event_id':event_id,'created':True,'net_cents':net,'provenance':'synthetic'}


def manager_snapshot(dsn,scope:TenantScope):
    with tenant_transaction(dsn,scope,roles=('manager',)) as con:
        _manager(con,scope)
        stages=dict(con.execute('''SELECT stage,count(*) FROM renewalos.renewal_opportunities
            WHERE org_id=%s AND store_id=%s GROUP BY stage''',(scope.org_id,scope.store_id)).fetchall())
        cash=con.execute('''SELECT
           coalesce(sum(CASE WHEN kind='payment' THEN amount_cents ELSE -amount_cents END),0),
           count(*) FROM renewalos.cash_events
           WHERE org_id=%s AND store_id=%s AND provenance='synthetic' ''',
           (scope.org_id,scope.store_id)).fetchone()
        task_stats=dict(con.execute('''SELECT status,count(*) FROM renewalos.work_tasks
           WHERE org_id=%s AND store_id=%s GROUP BY status''',(scope.org_id,scope.store_id)).fetchall())
        return {'org_id':scope.org_id,'store_id':scope.store_id,'stages':stages,
                'task_statuses':task_stats,'synthetic_cash_net_cents':cash[0],
                'cash_event_count':cash[1], 'incremental_roi':None,
                'disclaimer':'模拟资金事实不是支付机构对账，也不是AI增量收入。'}

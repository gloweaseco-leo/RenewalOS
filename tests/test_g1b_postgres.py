"""Real PostgreSQL acceptance. In local no PG env, tests skip (CI must run them)."""
import os
import pytest
from renewalos.pg_store import (TenantScope, TenantAccessError,
  tenant_transaction, list_store_opportunities, list_assigned_tasks, contract_net_cash)

pg = pytest.importorskip("psycopg", reason="PostgreSQL extra not installed")
ADMIN = os.getenv('RENEWAL_PG_MIGRATION_DSN')
APP = os.getenv('RENEWAL_PG_TEST_DSN')
pytestmark = pytest.mark.skipif(not (ADMIN and APP),reason="dedicated PostgreSQL test service required")


@pytest.fixture(scope='module',autouse=True)
def seed():
    """Dedicated disposable CI database only; no real personal data."""
    if not ADMIN or not APP:
        yield
        return
    with pg.connect(ADMIN) as db:
        with db.cursor() as cur:
            for org in ('alpha','beta'):
                cur.execute("INSERT INTO renewalos.organizations(org_id,label) VALUES(%s,%s)",
                            (org,org))
                for store in ('east','west'):
                    cur.execute('INSERT INTO renewalos.stores(org_id,store_id,label) VALUES(%s,%s,%s)',
                                (org,store,store))
            for uid in ('alice','andy','bravo'):
                cur.execute('INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES(%s,%s)',
                            (uid,uid))
            for org,uid in (('alpha','alice'),('alpha','andy'),('beta','bravo')):
                cur.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES(%s,%s,'member')",
                            (org,uid))
            for org,store,uid,role in (
                ('alpha','east','alice','manager'),('alpha','west','alice','manager'),
                ('alpha','east','andy','staff'),('beta','east','bravo','manager')):
                cur.execute('INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES(%s,%s,%s,%s)',
                            (org,store,uid,role))
            for org,store,who in (('alpha','east','alice'),('alpha','west','alice'),('beta','east','bravo')):
                src=f'{org}-{store}'
                cur.execute('INSERT INTO renewalos.households(org_id,store_id,household_id) VALUES(%s,%s,%s)',
                            (org,store,src+'-family'))
                cur.execute('''INSERT INTO renewalos.learners(org_id,store_id,learner_id,household_id,alias)
                               VALUES(%s,%s,%s,%s,%s)''',
                            (org,store,src+'-kid',src+'-family',src))
                cur.execute('''INSERT INTO renewalos.course_packages(org_id,store_id,package_id,
                             learner_id,course_type,purchased_on,expires_on,purchased_sessions,
                             remaining_sessions,price_cents)
                             VALUES(%s,%s,%s,%s,'swim','2026-01-01','2026-12-31',20,4,150000)''',
                            (org,store,src+'-p',src+'-kid'))
                cur.execute('''INSERT INTO renewalos.renewal_opportunities(org_id,store_id,
                             opportunity_id,source_package_id,learner_id,assigned_user_id)
                             VALUES(%s,%s,%s,%s,%s,%s)''',
                            (org,store,src+'-o',src+'-p',src+'-kid',who))
                cur.execute('''INSERT INTO renewalos.work_tasks(org_id,store_id,task_id,
                             opportunity_id,assigned_user_id,due_on)
                             VALUES(%s,%s,%s,%s,%s,'2026-11-01')''',
                            (org,store,src+'-t',src+'-o',who))
                cur.execute('''INSERT INTO renewalos.renewal_contracts(org_id,store_id,
                             contract_id,source_package_id,learner_id,signed_on,
                             contracted_amount_cents,provenance)
                             VALUES(%s,%s,%s,%s,%s,'2026-10-18',100000,'synthetic')''',
                            (org,store,src+'-c',src+'-p',src+'-kid'))
        db.commit()
    yield


def test_tenant_and_store_rows_cannot_leak_even_when_sql_has_no_where():
    a = TenantScope('alpha','east','alice')
    assert [x['opportunity_id'] for x in list_store_opportunities(APP,a)] == ['alpha-east-o']
    assert [x['task_id'] for x in list_assigned_tasks(APP,a)] == ['alpha-east-t']
    b = TenantScope('beta','east','bravo')
    assert [x['opportunity_id'] for x in list_store_opportunities(APP,b)] == ['beta-east-o']
    with tenant_transaction(APP,a) as con:
        assert con.execute('SELECT count(*) FROM renewalos.learners').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM renewalos.cash_events').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM renewalos.stores').fetchone()[0] == 1


def test_missing_session_and_membership_fail_closed():
    with pg.connect(APP) as con:
        assert con.execute('SELECT count(*) FROM renewalos.learners').fetchone()[0] == 0
    with pytest.raises(TenantAccessError):
        list_store_opportunities(APP,TenantScope('alpha','west','andy'))
    with pytest.raises(TenantAccessError):
        list_store_opportunities(APP,TenantScope('beta','east','alice'))
    with pytest.raises(ValueError):
        TenantScope('alpha','','alice')


def test_staff_sees_only_assigned_tasks():
    assert list_assigned_tasks(APP,TenantScope('alpha','east','andy')) == []
    assert len(list_assigned_tasks(APP,TenantScope('alpha','east','alice'))) == 1


def test_cross_tenant_and_cross_learner_fk_rejected():
    # Admin bypasses RLS, so this proves composite FK rather than only policy filtering.
    with pytest.raises(pg.errors.ForeignKeyViolation):
        with pg.connect(ADMIN) as con:
            con.execute('''INSERT INTO renewalos.course_packages(org_id,store_id,package_id,
                learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cents)
                VALUES('beta','west','fraud-1','alpha-east-kid','swim','2026-01-01','2026-12-31',10,2,1000)''')
    with pytest.raises(pg.errors.ForeignKeyViolation):
        with pg.connect(ADMIN) as con:
            con.execute('''INSERT INTO renewalos.renewal_contracts(org_id,store_id,contract_id,
                source_package_id,learner_id,signed_on,contracted_amount_cents,provenance)
                VALUES('alpha','east','fraud-2','alpha-east-p','beta-east-kid','2026-10-18',1000,'synthetic')''')


def test_money_append_only_refund_boundaries_and_scope():
    a=TenantScope('alpha','east','alice')
    with tenant_transaction(APP,a) as con:
        con.execute('''INSERT INTO renewalos.cash_events(org_id,store_id,event_id,contract_id,
             occurred_on,kind,amount_cents,provenance)
             VALUES('alpha','east','a-pay','alpha-east-c','2026-10-18','payment',70000,'synthetic')''')
    assert contract_net_cash(APP,a,'alpha-east-c') == 70000
    with pytest.raises(pg.errors.CheckViolation):
        with tenant_transaction(APP,a) as con:
            con.execute('''INSERT INTO renewalos.cash_events(org_id,store_id,event_id,contract_id,
              occurred_on,kind,amount_cents,provenance)
              VALUES('alpha','east','a-over','alpha-east-c','2026-10-18','payment',50000,'synthetic')''')
    with tenant_transaction(APP,a) as con:
        con.execute('''INSERT INTO renewalos.cash_events(org_id,store_id,event_id,contract_id,
             occurred_on,kind,amount_cents,refund_of,provenance)
             VALUES('alpha','east','a-refund','alpha-east-c','2026-10-18','refund',20000,'a-pay','synthetic')''')
    assert contract_net_cash(APP,a,'alpha-east-c') == 50000
    with pytest.raises(pg.errors.CheckViolation):
        with tenant_transaction(APP,a) as con:
            con.execute('''INSERT INTO renewalos.cash_events(org_id,store_id,event_id,contract_id,
             occurred_on,kind,amount_cents,refund_of,provenance)
             VALUES('alpha','east','a-refund-over','alpha-east-c','2026-10-18','refund',60000,'a-pay','synthetic')''')
    with pytest.raises(pg.errors.ForeignKeyViolation):
        with pg.connect(ADMIN) as con:
            con.execute('''INSERT INTO renewalos.cash_events(org_id,store_id,event_id,contract_id,
              occurred_on,kind,amount_cents,refund_of,provenance)
              VALUES('beta','east','b-bad-ref','beta-east-c','2026-10-18','refund',100,'a-pay','synthetic')''')
    with pytest.raises(pg.errors.CheckViolation):
        with pg.connect(ADMIN) as con:
            con.execute("UPDATE renewalos.cash_events SET amount_cents=1 WHERE event_id='a-pay'")


def test_other_tenant_cannot_insert_or_read_cash():
    b=TenantScope('beta','east','bravo')
    assert contract_net_cash(APP,b,'alpha-east-c') == 0
    with pytest.raises(pg.errors.InsufficientPrivilege):
        with tenant_transaction(APP,b) as con:
            con.execute('''INSERT INTO renewalos.cash_events(org_id,store_id,event_id,contract_id,
             occurred_on,kind,amount_cents,provenance)
             VALUES('alpha','east','injected','alpha-east-c','2026-10-18','payment',200,'synthetic')''')


def test_scoped_context_does_not_leak_to_next_connection():
    with tenant_transaction(APP,TenantScope('alpha','east','alice')) as con:
        assert con.execute('SELECT count(*) FROM renewalos.learners').fetchone()[0] == 1
    with pg.connect(APP) as con:
        assert con.execute('SELECT count(*) FROM renewalos.learners').fetchone()[0] == 0

"""Reject accidental regression to demo-only isolation semantics."""
from pathlib import Path
import pytest
from renewalos.pg_store import TenantScope, TenantAccessError, tenant_transaction

SQL=Path('migrations/postgres/001_tenant_core.sql').read_text()


def test_tenant_dimensions_and_rls_isolation_covered():
    for table in ('households','learners','course_packages','renewal_opportunities',
                  'work_tasks','followup_events','renewal_contracts','cash_events'):
        assert f'CREATE TABLE renewalos.{table}' in SQL
        assert f"'{table}'" in SQL
    assert 'FORCE ROW LEVEL SECURITY' in SQL
    assert 'FOREIGN KEY(org_id,store_id,contract_id,refund_of)' in SQL
    assert 'REFERENCES renewalos.cash_events(org_id,store_id,contract_id,event_id)' in SQL
    assert 'CREATE TRIGGER cash_append_only' in SQL
    assert 'CREATE TRIGGER cash_validate' in SQL


def test_scope_validation_fails_closed_without_database():
    for identity in (('', 'east', 'alice'),('alpha','', 'alice'),('alpha','east','')):
        with pytest.raises(ValueError):
            TenantScope(*identity)
    with pytest.raises(ValueError):
        with tenant_transaction('', TenantScope('alpha','east','alice')):
            pass


def test_pg_migration_script_is_not_silently_reentrant():
    from scripts import pg_apply
    assert 'confirm-new-database' in Path(pg_apply.__file__).read_text()
    assert 'schema contains tables' in Path(pg_apply.__file__).read_text()

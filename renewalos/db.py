"""Local SQLite prototype. Deliberately not a production multi-tenant datastore."""
import os
import sqlite3
from pathlib import Path

DB_DEFAULT = Path(__file__).resolve().parent.parent / 'renewalos_local.db'

DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS learners (
 learner_id TEXT PRIMARY KEY, family_id TEXT NOT NULL, guardian_alias TEXT NOT NULL,
 store_id TEXT NOT NULL, contact_consent INTEGER NOT NULL CHECK(contact_consent IN (0,1))
);
CREATE TABLE IF NOT EXISTS packages (
 package_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL REFERENCES learners(learner_id),
 course_type TEXT NOT NULL, purchased_on TEXT NOT NULL, expires_on TEXT NOT NULL,
 purchased_sessions INTEGER NOT NULL CHECK(purchased_sessions>0),
 remaining_sessions INTEGER NOT NULL CHECK(remaining_sessions>=0),
 price_cents INTEGER NOT NULL CHECK(price_cents>=0)
);
CREATE TABLE IF NOT EXISTS attendance (
 event_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL REFERENCES learners(learner_id),
 session_date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('present','absent','excused'))
);
CREATE TABLE IF NOT EXISTS renewals (
 renewal_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL REFERENCES learners(learner_id),
 source_package_id TEXT NOT NULL REFERENCES packages(package_id), paid_on TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
 status TEXT NOT NULL CHECK(status IN ('paid','refunded','void'))
);
CREATE TABLE IF NOT EXISTS opportunities (
 opportunity_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL REFERENCES learners(learner_id),
 package_id TEXT NOT NULL UNIQUE REFERENCES packages(package_id),
 signals_json TEXT NOT NULL, priority INTEGER NOT NULL,
 reason TEXT NOT NULL, rule_advice TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
 closed_at TEXT
);
CREATE TABLE IF NOT EXISTS experiment_assignments (
 family_key TEXT PRIMARY KEY,
 store_id TEXT NOT NULL,
 family_id TEXT NOT NULL,
 arm TEXT NOT NULL CHECK(arm IN ('control','rules','ai')),
 assigned_on TEXT NOT NULL,
 UNIQUE(store_id, family_id)
);
CREATE TABLE IF NOT EXISTS work_tasks (
 task_id TEXT PRIMARY KEY,
 opportunity_id TEXT NOT NULL UNIQUE REFERENCES opportunities(opportunity_id),
 store_id TEXT NOT NULL,
 owner TEXT NOT NULL,
 due_on TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('open','in_progress','waiting','done','cancelled')),
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS work_task_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 task_id TEXT NOT NULL REFERENCES work_tasks(task_id),
 actor TEXT NOT NULL,event_kind TEXT NOT NULL,details TEXT NOT NULL,logged_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_work_tasks_owner_due ON work_tasks(store_id,owner,due_on,status);
CREATE INDEX IF NOT EXISTS ix_task_event_history ON work_task_events(task_id,event_id);
CREATE TABLE IF NOT EXISTS followups (
 followup_id INTEGER PRIMARY KEY AUTOINCREMENT,
 opportunity_id TEXT NOT NULL REFERENCES opportunities(opportunity_id),
 owner TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('planned','contacted','no_response','not_suitable','closed')),
 note TEXT NOT NULL, logged_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_advice (
 opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(opportunity_id),
 advice TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL,
 signal_hash TEXT, action_code TEXT, evidence_keys_json TEXT,
 uncertainty TEXT, review_status TEXT DEFAULT 'pending_review', policy_version TEXT
);
CREATE TABLE IF NOT EXISTS ai_advice_attempts (
 attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, opportunity_id TEXT NOT NULL REFERENCES opportunities(opportunity_id),
 signal_hash TEXT NOT NULL, model_name TEXT NOT NULL, status TEXT NOT NULL,
 rejection_reason TEXT, attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_advice_attempts ON ai_advice_attempts(opportunity_id,attempt_id);
CREATE TABLE IF NOT EXISTS ai_advice_reviews (
 review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 opportunity_id TEXT NOT NULL REFERENCES opportunities(opportunity_id),
 signal_hash TEXT NOT NULL, reviewer TEXT NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
 reviewed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_reviews ON ai_advice_reviews(opportunity_id,review_id);
CREATE INDEX IF NOT EXISTS ix_packages_learner ON packages(learner_id);
CREATE INDEX IF NOT EXISTS ix_att_learner_date ON attendance(learner_id,session_date);
CREATE INDEX IF NOT EXISTS ix_renewals_package ON renewals(source_package_id,paid_on);

-- G0.3: Frozen enrollment; only new source packages can join a cohort.
CREATE TABLE IF NOT EXISTS cohorts (
 cohort_id TEXT PRIMARY KEY, store_id TEXT NOT NULL, opened_on TEXT NOT NULL,
 cutoff_on TEXT NOT NULL, refund_grace_until TEXT NOT NULL, frozen_at TEXT NOT NULL,
 UNIQUE(store_id,opened_on)
);
CREATE TABLE IF NOT EXISTS renewal_cohort_members (
 cohort_id TEXT NOT NULL REFERENCES cohorts(cohort_id),
 source_package_id TEXT NOT NULL UNIQUE REFERENCES packages(package_id),
 learner_id TEXT NOT NULL REFERENCES learners(learner_id),
 family_key TEXT NOT NULL, arm TEXT NOT NULL CHECK(arm IN ('control','rules','ai')),
 expiry_at_freeze TEXT NOT NULL,
 PRIMARY KEY(cohort_id,source_package_id)
);
-- The new accounting facts are append-only and intentionally separate from legacy renewals.
CREATE TABLE IF NOT EXISTS renewal_contracts (
 contract_id TEXT PRIMARY KEY,
 learner_id TEXT NOT NULL REFERENCES learners(learner_id),
 source_package_id TEXT NOT NULL UNIQUE REFERENCES packages(package_id),
 signed_on TEXT NOT NULL, contracted_amount_cents INTEGER NOT NULL CHECK(contracted_amount_cents>0)
);
CREATE TABLE IF NOT EXISTS cash_events (
 event_id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES renewal_contracts(contract_id),
 event_on TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('payment','refund')),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0), refund_of TEXT REFERENCES cash_events(event_id)
);
CREATE INDEX IF NOT EXISTS ix_cash_contract ON cash_events(contract_id,event_on);
CREATE INDEX IF NOT EXISTS ix_member_cohort ON renewal_cohort_members(cohort_id,arm);
CREATE INDEX IF NOT EXISTS ix_opportunity_priority ON opportunities(priority);
"""

def connect(path=None):
    target = str(path or os.getenv('RENEWAL_DB_PATH') or DB_DEFAULT)
    c = sqlite3.connect(target, timeout=15, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=15000')
    return c

def initialize(path=None):
    with connect(path) as con:
        con.executescript(DDL)
        columns = {r['name'] for r in con.execute('PRAGMA table_info(opportunities)')}
        if 'is_active' not in columns:
            con.execute('ALTER TABLE opportunities ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
        if 'closed_at' not in columns:
            con.execute('ALTER TABLE opportunities ADD COLUMN closed_at TEXT')
        assignments = {r['name'] for r in con.execute('PRAGMA table_info(experiment_assignments)')}
        # V0.1 used family_id as a global key. Migrate without deleting records.
        if 'family_key' not in assignments:
            con.execute('ALTER TABLE experiment_assignments RENAME TO experiment_assignments_v01')
            con.execute("""CREATE TABLE experiment_assignments (
                family_key TEXT PRIMARY KEY, store_id TEXT NOT NULL, family_id TEXT NOT NULL,
                arm TEXT NOT NULL CHECK(arm IN ('control','rules','ai')),
                assigned_on TEXT NOT NULL, UNIQUE(store_id,family_id))""")
            con.execute("""INSERT OR IGNORE INTO experiment_assignments
                (family_key,store_id,family_id,arm,assigned_on)
                SELECT DISTINCT l.store_id || ':' || l.family_id,l.store_id,l.family_id,
                       a.arm,a.assigned_on
                FROM experiment_assignments_v01 a
                JOIN learners l ON l.family_id=a.family_id""")
            con.execute('DROP TABLE experiment_assignments_v01')
        con.execute('CREATE INDEX IF NOT EXISTS ix_active_opportunity ON opportunities(is_active,priority)')

        # G0.4 legacy G0.2/G0.3 advice is unvalidated and MUST NOT be served.
        ai_columns={r['name'] for r in con.execute('PRAGMA table_info(ai_advice)')}
        additions={'signal_hash':'TEXT','action_code':'TEXT','evidence_keys_json':'TEXT',
                   'uncertainty':'TEXT','review_status':"TEXT DEFAULT 'pending_review'",'policy_version':'TEXT'}
        for name,column_type in additions.items():
            if name not in ai_columns:
                con.execute(f'ALTER TABLE ai_advice ADD COLUMN {name} {column_type}')

-- G1-B / PostgreSQL 15+. Apply only with a dedicated migration role.
-- Do not run this SQL against the SQLite demo database.
BEGIN;
CREATE SCHEMA IF NOT EXISTS renewalos;
CREATE TABLE IF NOT EXISTS renewalos.schema_migrations (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE renewalos.organizations (
  org_id text PRIMARY KEY,
  label text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (length(org_id) BETWEEN 2 AND 64)
);
CREATE TABLE renewalos.stores (
  org_id text NOT NULL REFERENCES renewalos.organizations(org_id),
  store_id text NOT NULL,
  label text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id,store_id)
);
CREATE TABLE renewalos.identity_users (
  user_id text PRIMARY KEY,
  display_alias text NOT NULL,
  enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE renewalos.org_memberships (
  org_id text NOT NULL REFERENCES renewalos.organizations(org_id),
  user_id text NOT NULL REFERENCES renewalos.identity_users(user_id),
  role text NOT NULL CHECK(role IN ('admin','member','auditor')),
  enabled boolean NOT NULL DEFAULT true,
  PRIMARY KEY (org_id,user_id)
);
CREATE TABLE renewalos.store_memberships (
  org_id text NOT NULL,
  store_id text NOT NULL,
  user_id text NOT NULL,
  role text NOT NULL CHECK(role IN ('manager','staff','auditor')),
  enabled boolean NOT NULL DEFAULT true,
  PRIMARY KEY(org_id,store_id,user_id),
  FOREIGN KEY(org_id,store_id) REFERENCES renewalos.stores(org_id,store_id),
  FOREIGN KEY(org_id,user_id) REFERENCES renewalos.org_memberships(org_id,user_id)
);
CREATE TABLE renewalos.households (
  org_id text NOT NULL, store_id text NOT NULL, household_id text NOT NULL,
  external_source text NOT NULL DEFAULT 'unknown', external_id text,
  PRIMARY KEY(org_id,store_id,household_id),
  FOREIGN KEY(org_id,store_id) REFERENCES renewalos.stores(org_id,store_id),
  UNIQUE(org_id,store_id,external_source,external_id)
);
CREATE TABLE renewalos.learners (
  org_id text NOT NULL, store_id text NOT NULL, learner_id text NOT NULL,
  household_id text NOT NULL, alias text NOT NULL,
  contact_consent boolean NOT NULL DEFAULT false,
  PRIMARY KEY(org_id,store_id,learner_id),
  FOREIGN KEY(org_id,store_id,household_id)
    REFERENCES renewalos.households(org_id,store_id,household_id)
);
CREATE TABLE renewalos.course_packages (
  org_id text NOT NULL, store_id text NOT NULL, package_id text NOT NULL,
  learner_id text NOT NULL, course_type text NOT NULL,
  purchased_on date NOT NULL, expires_on date NOT NULL,
  purchased_sessions integer NOT NULL CHECK(purchased_sessions>0),
  remaining_sessions integer NOT NULL,
  price_cents bigint NOT NULL CHECK(price_cents>=0),
  PRIMARY KEY(org_id,store_id,package_id),
  UNIQUE(org_id,store_id,package_id,learner_id),
  FOREIGN KEY(org_id,store_id,learner_id)
    REFERENCES renewalos.learners(org_id,store_id,learner_id),
  CHECK (expires_on >= purchased_on),
  CHECK (remaining_sessions BETWEEN 0 AND purchased_sessions)
);
CREATE TABLE renewalos.attendance_events (
  org_id text NOT NULL, store_id text NOT NULL, event_id text NOT NULL,
  learner_id text NOT NULL, session_on date NOT NULL,
  status text NOT NULL CHECK(status IN ('present','absent','excused')),
  PRIMARY KEY(org_id,store_id,event_id),
  FOREIGN KEY(org_id,store_id,learner_id)
    REFERENCES renewalos.learners(org_id,store_id,learner_id)
);
CREATE TABLE renewalos.renewal_opportunities (
  org_id text NOT NULL, store_id text NOT NULL, opportunity_id text NOT NULL,
  source_package_id text NOT NULL, learner_id text NOT NULL,
  stage text NOT NULL DEFAULT 'open' CHECK(stage IN ('open','assigned','contacted','signed','paid','closed')),
  signals jsonb NOT NULL DEFAULT '{}'::jsonb,
  priority integer NOT NULL DEFAULT 0 CHECK(priority BETWEEN 0 AND 100),
  assigned_user_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(org_id,store_id,opportunity_id),
  UNIQUE(org_id,store_id,source_package_id),
  FOREIGN KEY(org_id,store_id,source_package_id,learner_id)
    REFERENCES renewalos.course_packages(org_id,store_id,package_id,learner_id),
  FOREIGN KEY(org_id,store_id,assigned_user_id)
    REFERENCES renewalos.store_memberships(org_id,store_id,user_id)
);
CREATE TABLE renewalos.work_tasks (
  org_id text NOT NULL, store_id text NOT NULL, task_id text NOT NULL,
  opportunity_id text NOT NULL, assigned_user_id text NOT NULL,
  due_on date NOT NULL,
  status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','waiting','done','cancelled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(org_id,store_id,task_id),
  UNIQUE(org_id,store_id,opportunity_id),
  FOREIGN KEY(org_id,store_id,opportunity_id)
    REFERENCES renewalos.renewal_opportunities(org_id,store_id,opportunity_id),
  FOREIGN KEY(org_id,store_id,assigned_user_id)
    REFERENCES renewalos.store_memberships(org_id,store_id,user_id)
);
CREATE TABLE renewalos.followup_events (
  org_id text NOT NULL, store_id text NOT NULL, followup_id text NOT NULL,
  opportunity_id text NOT NULL, actor_user_id text NOT NULL,
  result text NOT NULL, note text NOT NULL DEFAULT '',
  recorded_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(org_id,store_id,followup_id),
  FOREIGN KEY(org_id,store_id,opportunity_id)
    REFERENCES renewalos.renewal_opportunities(org_id,store_id,opportunity_id),
  FOREIGN KEY(org_id,store_id,actor_user_id)
    REFERENCES renewalos.store_memberships(org_id,store_id,user_id)
);
CREATE TABLE renewalos.renewal_contracts (
  org_id text NOT NULL, store_id text NOT NULL, contract_id text NOT NULL,
  source_package_id text NOT NULL, learner_id text NOT NULL,
  signed_on date NOT NULL,
  contracted_amount_cents bigint NOT NULL CHECK(contracted_amount_cents>0),
  provenance text NOT NULL CHECK(provenance IN ('synthetic','imported_unverified','provider_verified')),
  PRIMARY KEY(org_id,store_id,contract_id),
  UNIQUE(org_id,store_id,source_package_id),
  FOREIGN KEY(org_id,store_id,source_package_id,learner_id)
    REFERENCES renewalos.course_packages(org_id,store_id,package_id,learner_id)
);
CREATE TABLE renewalos.cash_events (
  org_id text NOT NULL, store_id text NOT NULL, event_id text NOT NULL,
  contract_id text NOT NULL,
  occurred_on date NOT NULL,
  kind text NOT NULL CHECK(kind IN ('payment','refund')),
  amount_cents bigint NOT NULL CHECK(amount_cents>0),
  refund_of text,
  provenance text NOT NULL CHECK(provenance IN ('synthetic','imported_unverified','provider_verified')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(org_id,store_id,event_id),
  UNIQUE(org_id,store_id,contract_id,event_id),
  FOREIGN KEY(org_id,store_id,contract_id)
    REFERENCES renewalos.renewal_contracts(org_id,store_id,contract_id),
  FOREIGN KEY(org_id,store_id,contract_id,refund_of)
    REFERENCES renewalos.cash_events(org_id,store_id,contract_id,event_id),
  CHECK ((kind='payment' AND refund_of IS NULL) OR (kind='refund' AND refund_of IS NOT NULL))
);
CREATE INDEX ix_cash_contract ON renewalos.cash_events(org_id,store_id,contract_id,occurred_on);
CREATE INDEX ix_task_assignee ON renewalos.work_tasks(org_id,store_id,assigned_user_id,due_on);
CREATE INDEX ix_opp_stage ON renewalos.renewal_opportunities(org_id,store_id,stage);

-- Only the migration owner / db administrator provisions orgs and identity.
-- Business tables are always evaluated in a single trusted transaction context.
CREATE FUNCTION renewalos.scope_org() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('renewalos.org_id',true),'')
$$;
CREATE FUNCTION renewalos.scope_store() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('renewalos.store_id',true),'')
$$;
-- IMPORTANT: custom GUCs are writable by the database client; no direct client DB logins.
-- The trusted application authenticates actor and authorizes memberships before setting scope.
ALTER TABLE renewalos.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE renewalos.organizations FORCE ROW LEVEL SECURITY;
CREATE POLICY org_scope ON renewalos.organizations
  USING (org_id=renewalos.scope_org()) WITH CHECK (org_id=renewalos.scope_org());
ALTER TABLE renewalos.org_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE renewalos.org_memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY org_membership_scope ON renewalos.org_memberships
  USING (org_id=renewalos.scope_org()) WITH CHECK (org_id=renewalos.scope_org());

-- Explicit tenant isolation for all store-scoped tables, including source and cash ledger.
DO $block$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
   'stores','store_memberships','households','learners','course_packages',
   'attendance_events','renewal_opportunities','work_tasks','followup_events',
   'renewal_contracts','cash_events'
  ] LOOP
    EXECUTE format('ALTER TABLE renewalos.%I ENABLE ROW LEVEL SECURITY',table_name);
    EXECUTE format('ALTER TABLE renewalos.%I FORCE ROW LEVEL SECURITY',table_name);
    EXECUTE format('CREATE POLICY tenant_scope ON renewalos.%I USING (org_id=renewalos.scope_org() AND store_id=renewalos.scope_store()) WITH CHECK (org_id=renewalos.scope_org() AND store_id=renewalos.scope_store())',table_name);
  END LOOP;
END
$block$;

-- Serialize money movements per contract and reject unsupported cash assertions.
-- This is a consistency guard, NOT proof a payment provider actually settled a charge.
CREATE FUNCTION renewalos.validate_cash_insert() RETURNS trigger
LANGUAGE plpgsql AS $body$
DECLARE
  paid_so_far bigint;
  contract_limit bigint;
  source_payment renewalos.cash_events%ROWTYPE;
  refunded_so_far bigint;
BEGIN
  -- Triggers execute before RLS WITH CHECK; reject scope violations BEFORE
  -- querying amounts, otherwise SQL errors can leak another tenant's state.
  IF NEW.org_id IS DISTINCT FROM renewalos.scope_org()
     OR NEW.store_id IS DISTINCT FROM renewalos.scope_store() THEN
    RAISE EXCEPTION 'tenant scope required for cash events' USING ERRCODE='42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(
      NEW.org_id || '|' || NEW.store_id || '|' || NEW.contract_id, 0));
  IF NEW.kind = 'payment' THEN
    SELECT contracted_amount_cents INTO contract_limit
      FROM renewalos.renewal_contracts
      WHERE org_id=NEW.org_id AND store_id=NEW.store_id AND contract_id=NEW.contract_id;
    SELECT coalesce(sum(amount_cents),0) INTO paid_so_far
      FROM renewalos.cash_events WHERE org_id=NEW.org_id AND store_id=NEW.store_id
      AND contract_id=NEW.contract_id AND kind='payment';
    IF contract_limit IS NULL OR paid_so_far + NEW.amount_cents > contract_limit THEN
      RAISE EXCEPTION 'payments exceed contract limit' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT * INTO source_payment FROM renewalos.cash_events
       WHERE org_id=NEW.org_id AND store_id=NEW.store_id
       AND contract_id=NEW.contract_id AND event_id=NEW.refund_of;
    IF NOT FOUND OR source_payment.kind <> 'payment'
       OR source_payment.provenance <> NEW.provenance THEN
      RAISE EXCEPTION 'refund source is not a matching original payment' USING ERRCODE='23514';
    END IF;
    SELECT coalesce(sum(amount_cents),0) INTO refunded_so_far
      FROM renewalos.cash_events WHERE org_id=NEW.org_id AND store_id=NEW.store_id
      AND contract_id=NEW.contract_id AND kind='refund' AND refund_of=NEW.refund_of;
    IF refunded_so_far + NEW.amount_cents > source_payment.amount_cents THEN
      RAISE EXCEPTION 'refund exceeds source payment' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END
$body$;
CREATE TRIGGER cash_validate BEFORE INSERT ON renewalos.cash_events
FOR EACH ROW EXECUTE FUNCTION renewalos.validate_cash_insert();

-- No DELETE/UPDATE on accounting source. Corrections are new events.
CREATE FUNCTION renewalos.prohibit_cash_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'cash_events is append-only; create a corrective event instead'
    USING ERRCODE='23514';
END $$;
CREATE TRIGGER cash_append_only BEFORE UPDATE OR DELETE ON renewalos.cash_events
FOR EACH ROW EXECUTE FUNCTION renewalos.prohibit_cash_mutation();

INSERT INTO renewalos.schema_migrations(version) VALUES ('001_tenant_core');
COMMIT;

-- G1-C: constrained synthetic business write path.
-- Apply once, AFTER 001. Use migration-owner credentials, never application credentials.
BEGIN;
ALTER TABLE renewalos.renewal_opportunities
  ADD COLUMN arm text NOT NULL DEFAULT 'control'
  CHECK (arm IN ('control','rules','ai'));

CREATE TABLE renewalos.business_action_events (
  org_id text NOT NULL, store_id text NOT NULL, event_id text NOT NULL,
  actor_user_id text NOT NULL, action text NOT NULL, resource_id text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(org_id,store_id,event_id),
  FOREIGN KEY(org_id,store_id,actor_user_id)
    REFERENCES renewalos.store_memberships(org_id,store_id,user_id)
);
ALTER TABLE renewalos.business_action_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE renewalos.business_action_events FORCE ROW LEVEL SECURITY;
CREATE POLICY business_action_scope ON renewalos.business_action_events
  USING (org_id=renewalos.scope_org() AND store_id=renewalos.scope_store())
  WITH CHECK (org_id=renewalos.scope_org() AND store_id=renewalos.scope_store());

-- Roles derive from authenticated, server-set transaction scope. Never expose the
-- application DB credentials to a browser or to an untrusted SQL client.
CREATE FUNCTION renewalos.actor_store_role() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,renewalos AS $$
  SELECT sm.role FROM renewalos.store_memberships sm
  JOIN renewalos.org_memberships om ON om.org_id=sm.org_id AND om.user_id=sm.user_id
  JOIN renewalos.identity_users u ON u.user_id=sm.user_id
  WHERE sm.org_id=renewalos.scope_org()
    AND sm.store_id=renewalos.scope_store()
    AND sm.user_id=nullif(current_setting('renewalos.actor_id',true),'')
    AND sm.enabled AND om.enabled AND u.enabled
$$;

-- A narrow Boolean check for manager-initiated assignment; no global identity
-- rows or password data are made visible to the application database login.
CREATE FUNCTION renewalos.is_active_store_member(target_user_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,renewalos AS $$
 SELECT EXISTS(
   SELECT 1 FROM renewalos.store_memberships sm
   JOIN renewalos.org_memberships om ON om.org_id=sm.org_id AND om.user_id=sm.user_id
   JOIN renewalos.identity_users u ON u.user_id=sm.user_id
   WHERE sm.org_id=renewalos.scope_org() AND sm.store_id=renewalos.scope_store()
     AND sm.user_id=target_user_id AND sm.role IN ('manager','staff')
     AND sm.enabled AND om.enabled AND u.enabled
 )
$$;
REVOKE ALL ON FUNCTION renewalos.actor_store_role() FROM PUBLIC;
REVOKE ALL ON FUNCTION renewalos.is_active_store_member(text) FROM PUBLIC;

-- Existing G1-B tenant_scope policy is permissive; ADD RESTRICTIVE policies
-- so actor authorization is combined with tenant scope rather than OR-ed.
CREATE POLICY opportunity_actor_update ON renewalos.renewal_opportunities
  AS RESTRICTIVE FOR UPDATE USING (
    renewalos.actor_store_role()='manager' OR
    (renewalos.actor_store_role()='staff' AND assigned_user_id=current_setting('renewalos.actor_id',true))
  ) WITH CHECK (
    renewalos.actor_store_role()='manager' OR
    (renewalos.actor_store_role()='staff' AND assigned_user_id=current_setting('renewalos.actor_id',true))
  );
CREATE POLICY task_actor_update ON renewalos.work_tasks
  AS RESTRICTIVE FOR UPDATE USING (
    renewalos.actor_store_role()='manager' OR
    (renewalos.actor_store_role()='staff' AND assigned_user_id=current_setting('renewalos.actor_id',true))
  ) WITH CHECK (
    renewalos.actor_store_role()='manager' OR
    (renewalos.actor_store_role()='staff' AND assigned_user_id=current_setting('renewalos.actor_id',true))
  );
CREATE POLICY task_manager_insert ON renewalos.work_tasks
  AS RESTRICTIVE FOR INSERT WITH CHECK (renewalos.actor_store_role()='manager');
CREATE POLICY contract_manager_insert ON renewalos.renewal_contracts
  AS RESTRICTIVE FOR INSERT WITH CHECK (renewalos.actor_store_role()='manager');
CREATE POLICY cash_manager_insert ON renewalos.cash_events
  AS RESTRICTIVE FOR INSERT WITH CHECK (renewalos.actor_store_role()='manager');
CREATE POLICY followup_actor_insert ON renewalos.followup_events
  AS RESTRICTIVE FOR INSERT WITH CHECK (
    actor_user_id=current_setting('renewalos.actor_id',true)
    AND renewalos.actor_store_role() IN ('manager','staff')
  );
CREATE POLICY audit_actor_insert ON renewalos.business_action_events
  AS RESTRICTIVE FOR INSERT WITH CHECK (
    actor_user_id=current_setting('renewalos.actor_id',true)
    AND renewalos.actor_store_role() IN ('manager','staff')
  );

-- Application role should be created separately in production, with explicit
-- grants. CI role only exists on disposable DBs; migration guards its absence.
DO $block$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='renewalos_ci_app') THEN
   GRANT EXECUTE ON FUNCTION renewalos.actor_store_role() TO renewalos_ci_app;
   GRANT EXECUTE ON FUNCTION renewalos.is_active_store_member(text) TO renewalos_ci_app;
   GRANT SELECT,INSERT ON renewalos.business_action_events TO renewalos_ci_app;
   GRANT UPDATE(assigned_user_id,stage,updated_at) ON renewalos.renewal_opportunities TO renewalos_ci_app;
   GRANT UPDATE(status) ON renewalos.work_tasks TO renewalos_ci_app;
 END IF;
END $block$;

INSERT INTO renewalos.schema_migrations(version) VALUES ('002_business_write');
COMMIT;

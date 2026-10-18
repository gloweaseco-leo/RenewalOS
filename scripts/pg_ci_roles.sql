-- Test-only bootstrap. Never run against customer databases.
DO $block$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='renewalos_ci_app') THEN
   CREATE ROLE renewalos_ci_app LOGIN PASSWORD 'g1b-ci-test-password';
 END IF;
END
$block$;
GRANT USAGE ON SCHEMA renewalos TO renewalos_ci_app;
GRANT SELECT ON ALL TABLES IN SCHEMA renewalos TO renewalos_ci_app;
GRANT INSERT ON renewalos.households,renewalos.learners,
  renewalos.course_packages,renewalos.attendance_events,
  renewalos.renewal_opportunities,renewalos.work_tasks,
  renewalos.followup_events,renewalos.renewal_contracts,
  renewalos.cash_events TO renewalos_ci_app;
-- No unscoped global identity access, no schema changes, no UPDATE/DELETE on cash.
REVOKE ALL ON renewalos.identity_users FROM renewalos_ci_app;
REVOKE INSERT,UPDATE,DELETE ON renewalos.organizations,renewalos.stores,
 renewalos.org_memberships,renewalos.store_memberships FROM renewalos_ci_app;

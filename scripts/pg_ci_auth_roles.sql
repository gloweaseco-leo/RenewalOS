-- CI-only database identities; not for customer infrastructure.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='renewalos_ci_auth') THEN
   CREATE ROLE renewalos_ci_auth LOGIN PASSWORD 'g1e-ci-auth-test-only';
 END IF;
END $$;
GRANT USAGE ON SCHEMA renewalos_auth TO renewalos_ci_auth;
GRANT SELECT ON renewalos_auth.credentials,renewalos_auth.sessions TO renewalos_ci_auth;
GRANT INSERT,UPDATE ON renewalos_auth.sessions TO renewalos_ci_auth;
GRANT INSERT ON renewalos_auth.audit TO renewalos_ci_auth;
GRANT USAGE ON SEQUENCE renewalos_auth.audit_audit_id_seq TO renewalos_ci_auth;
GRANT EXECUTE ON FUNCTION renewalos_auth.active_memberships(text) TO renewalos_ci_auth;
REVOKE ALL ON SCHEMA renewalos_auth FROM renewalos_ci_app;

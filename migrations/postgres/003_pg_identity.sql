-- G1-E: PostgreSQL credentials and sessions; NEVER a production IdP.
BEGIN;
CREATE SCHEMA renewalos_auth;
CREATE TABLE renewalos_auth.credentials (
 user_id text PRIMARY KEY REFERENCES renewalos.identity_users(user_id),
 password_salt bytea NOT NULL CHECK(octet_length(password_salt)>=16),
 password_hash bytea NOT NULL CHECK(octet_length(password_hash)=32),
 iterations integer NOT NULL CHECK(iterations>=200000)
);
CREATE TABLE renewalos_auth.sessions (
 token_hash text PRIMARY KEY CHECK(length(token_hash)=64),
 user_id text NOT NULL REFERENCES renewalos.identity_users(user_id),
 issued_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 revoked_at timestamptz,
 CHECK(expires_at > issued_at)
);
CREATE INDEX ix_pg_session_user ON renewalos_auth.sessions(user_id,expires_at);
CREATE TABLE renewalos_auth.audit (
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 user_id text, action text NOT NULL, outcome text NOT NULL,
 org_id text, store_id text, created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(action IN ('login','logout','authz')),
 CHECK(outcome IN ('allowed','denied'))
);
-- Function is owned by migration user: do not expose global memberships to app role.
CREATE FUNCTION renewalos_auth.active_memberships(p_user text)
RETURNS TABLE(org_id text,store_id text,role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT sm.org_id,sm.store_id,sm.role
 FROM renewalos.store_memberships sm
 JOIN renewalos.org_memberships om ON om.org_id=sm.org_id AND om.user_id=sm.user_id
 JOIN renewalos.identity_users u ON u.user_id=sm.user_id
 WHERE sm.user_id=p_user AND u.enabled AND om.enabled AND sm.enabled
 AND sm.role IN ('manager','staff')
$$;
REVOKE ALL ON FUNCTION renewalos_auth.active_memberships(text) FROM PUBLIC;
REVOKE ALL ON SCHEMA renewalos_auth FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA renewalos_auth FROM PUBLIC;
INSERT INTO renewalos.schema_migrations(version) VALUES('003_pg_identity');
COMMIT;

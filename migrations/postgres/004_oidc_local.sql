-- G1-G/2: local-only OIDC foundation. Does NOT approve public deployment.
BEGIN;
CREATE TABLE renewalos_auth.oidc_bindings (
 issuer text NOT NULL CHECK(length(issuer) BETWEEN 10 AND 2048),
 subject text NOT NULL CHECK(length(subject) BETWEEN 2 AND 255),
 user_id text NOT NULL REFERENCES renewalos.identity_users(user_id),
 enabled boolean NOT NULL DEFAULT true,
 bound_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(issuer,subject),
 UNIQUE(issuer,user_id)
);
CREATE INDEX oidc_bindings_user ON renewalos_auth.oidc_bindings(user_id);
CREATE TABLE renewalos_auth.oidc_flows (
 state_hash text PRIMARY KEY CHECK(length(state_hash)=64),
 cookie_hash text NOT NULL CHECK(length(cookie_hash)=64),
 issuer text NOT NULL,
 nonce text NOT NULL,
 pkce_verifier text NOT NULL,
 expires_at timestamptz NOT NULL
);
CREATE INDEX oidc_flows_expiry ON renewalos_auth.oidc_flows(expires_at);
ALTER TABLE renewalos_auth.audit DROP CONSTRAINT audit_action_check;
ALTER TABLE renewalos_auth.audit ADD CONSTRAINT audit_action_check
 CHECK(action IN ('login','logout','authz','oidc_login'));
REVOKE ALL ON renewalos_auth.oidc_bindings, renewalos_auth.oidc_flows FROM PUBLIC;
GRANT SELECT ON renewalos_auth.oidc_bindings TO renewalos_ci_auth;
GRANT SELECT,INSERT,DELETE ON renewalos_auth.oidc_flows TO renewalos_ci_auth;
INSERT INTO renewalos.schema_migrations(version) VALUES('004_oidc_local');
COMMIT;

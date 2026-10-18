-- G1-J: tag external sessions to enforce live binding revocation.
BEGIN;
ALTER TABLE renewalos_auth.sessions
  ADD COLUMN identity_source text NOT NULL DEFAULT 'password'
    CHECK(identity_source IN ('password', 'oidc'));
INSERT INTO renewalos.schema_migrations(version) VALUES('005_oidc_session_revocation');
COMMIT;

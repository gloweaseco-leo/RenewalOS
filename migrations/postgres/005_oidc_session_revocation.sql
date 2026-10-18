-- G1-J: immediately fail existing OIDC sessions if provider subject binding is disabled.
-- Local synthetic migration; no production enablement.
BEGIN;
ALTER TABLE renewalos_auth.sessions
  ADD COLUMN oidc_issuer text,
  ADD COLUMN oidc_subject text;
ALTER TABLE renewalos_auth.sessions
  ADD CONSTRAINT session_oidc_source_pair
  CHECK ((oidc_issuer IS NULL AND oidc_subject IS NULL)
      OR (oidc_issuer IS NOT NULL AND oidc_subject IS NOT NULL));
CREATE INDEX session_oidc_identity ON renewalos_auth.sessions(oidc_issuer,oidc_subject)
  WHERE oidc_issuer IS NOT NULL;
-- Existing sessions cannot be proven to be OIDC or password-based. Fail closed:
-- revoke all sessions on migration, so stale tokens cannot bypass binding validation.
UPDATE renewalos_auth.sessions SET revoked_at=now() WHERE revoked_at IS NULL;
-- Revocation remains permanent even if an administrator re-enables a mapping.
CREATE FUNCTION renewalos_auth.revoke_affected_oidc_sessions()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF OLD.enabled AND NOT NEW.enabled THEN
   UPDATE renewalos_auth.sessions
     SET revoked_at=now()
     WHERE oidc_issuer=OLD.issuer AND oidc_subject=OLD.subject
       AND revoked_at IS NULL;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION renewalos_auth.revoke_affected_oidc_sessions() FROM PUBLIC;
CREATE TRIGGER oidc_binding_revoke_session
 AFTER UPDATE OF enabled ON renewalos_auth.oidc_bindings
 FOR EACH ROW EXECUTE FUNCTION renewalos_auth.revoke_affected_oidc_sessions();

CREATE FUNCTION renewalos_auth.revoke_disabled_user_sessions()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF OLD.enabled AND NOT NEW.enabled THEN
   UPDATE renewalos_auth.sessions SET revoked_at=now()
     WHERE user_id=OLD.user_id AND revoked_at IS NULL;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION renewalos_auth.revoke_disabled_user_sessions() FROM PUBLIC;
CREATE TRIGGER identity_user_revoke_session
 AFTER UPDATE OF enabled ON renewalos.identity_users
 FOR EACH ROW EXECUTE FUNCTION renewalos_auth.revoke_disabled_user_sessions();
INSERT INTO renewalos.schema_migrations(version) VALUES('005_oidc_session_revocation');
COMMIT;

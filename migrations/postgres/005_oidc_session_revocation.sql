-- G1-J: OIDC session validity follows explicit identity binding revocation.
-- Applies only after 004; no public deployment permission.
BEGIN;
ALTER TABLE renewalos_auth.sessions
 ADD COLUMN oidc_issuer text,
 ADD COLUMN oidc_subject text,
 ADD CONSTRAINT sessions_oidc_pair CHECK ((oidc_issuer IS NULL) = (oidc_subject IS NULL));
CREATE INDEX sessions_oidc_identity ON renewalos_auth.sessions(oidc_issuer,oidc_subject)
 WHERE oidc_issuer IS NOT NULL;
-- Explicit disable revokes all outstanding sessions before commit.
CREATE FUNCTION renewalos_auth.revoke_disabled_oidc_bindings()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF OLD.enabled AND NOT NEW.enabled THEN
    UPDATE renewalos_auth.sessions SET revoked_at=now()
    WHERE oidc_issuer=NEW.issuer AND oidc_subject=NEW.subject
      AND revoked_at IS NULL;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION renewalos_auth.revoke_disabled_oidc_bindings() FROM PUBLIC;
CREATE TRIGGER revoke_disabled_oidc_binding
 AFTER UPDATE OF enabled ON renewalos_auth.oidc_bindings
 FOR EACH ROW EXECUTE FUNCTION renewalos_auth.revoke_disabled_oidc_bindings();
INSERT INTO renewalos.schema_migrations(version) VALUES('005_oidc_session_revocation');
COMMIT;

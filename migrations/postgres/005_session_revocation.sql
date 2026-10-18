-- G1-J: irreversible revocation of pre-existing sessions on identity / entitlement changes.
-- Run only as migration owner, not the low-privilege application role.
BEGIN;
CREATE FUNCTION renewalos_auth.revoke_user_sessions(p_user text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  UPDATE renewalos_auth.sessions
     SET revoked_at = now()
   WHERE user_id = p_user AND revoked_at IS NULL;
END;
$$;
REVOKE ALL ON FUNCTION renewalos_auth.revoke_user_sessions(text) FROM PUBLIC;

CREATE FUNCTION renewalos_auth.on_identity_restriction()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.enabled IS DISTINCT FROM NEW.enabled) THEN
    PERFORM renewalos_auth.revoke_user_sessions(OLD.user_id);
  END IF;
  RETURN NULL;
END;
$$;
CREATE TRIGGER g1j_identity_restriction
AFTER UPDATE OF enabled ON renewalos.identity_users
FOR EACH ROW EXECUTE FUNCTION renewalos_auth.on_identity_restriction();

CREATE FUNCTION renewalos_auth.on_membership_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP = 'DELETE' OR
     (TG_OP = 'UPDATE' AND
       (OLD.enabled IS DISTINCT FROM NEW.enabled OR OLD.role IS DISTINCT FROM NEW.role)) THEN
    PERFORM renewalos_auth.revoke_user_sessions(OLD.user_id);
  END IF;
  RETURN NULL;
END;
$$;
CREATE TRIGGER g1j_org_membership_change
AFTER UPDATE OF enabled,role OR DELETE ON renewalos.org_memberships
FOR EACH ROW EXECUTE FUNCTION renewalos_auth.on_membership_change();
CREATE TRIGGER g1j_store_membership_change
AFTER UPDATE OF enabled,role OR DELETE ON renewalos.store_memberships
FOR EACH ROW EXECUTE FUNCTION renewalos_auth.on_membership_change();
CREATE FUNCTION renewalos_auth.on_binding_change()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND OLD.enabled IS DISTINCT FROM NEW.enabled) THEN
    PERFORM renewalos_auth.revoke_user_sessions(OLD.user_id);
  END IF;
  RETURN NULL;
END;
$$;
CREATE TRIGGER g1j_oidc_binding_change
AFTER UPDATE OF enabled OR DELETE ON renewalos_auth.oidc_bindings
FOR EACH ROW EXECUTE FUNCTION renewalos_auth.on_binding_change();

REVOKE ALL ON FUNCTION renewalos_auth.on_identity_restriction() FROM PUBLIC;
REVOKE ALL ON FUNCTION renewalos_auth.on_membership_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION renewalos_auth.on_binding_change() FROM PUBLIC;
INSERT INTO renewalos.schema_migrations(version) VALUES ('005_session_revocation');
COMMIT;

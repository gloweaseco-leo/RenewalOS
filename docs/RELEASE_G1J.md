# RenewalOS G1-J · MFA positive / instant revocation (CI synthetic)

**Status:** PostgreSQL session revocation implemented and tested; real Keycloak TOTP succeeds but its MFA claim mapping is **not configured** and the app correctly rejects the session. Positive OIDC MFA authorization is **NOT PASSED**. **PUBLIC RELEASE NO-GO**. Do not merge `main` or change Vercel.

## Delivered

1. PostgreSQL `005_oidc_session_revocation` adds issuer+subject provenance to OIDC sessions, revokes all older unprovable sessions during migration, and installs triggers that irrevocably revoke sessions when an OIDC binding or employee account is disabled.
2. Every authenticated API request verifies that the session's original `(issuer, subject)` still maps to the **same enabled user**. Re-enabling a binding or employee account does **not** revive revoked tokens.
3. OIDC start/complete cookies now use `Secure` when the pinned **loopback HTTPS** callback is configured; default HTTP loopback remains for disposable test harnesses, and production is still blocked.
4. Independent Keycloak realm includes a synthetic OTP-equipped operator with a real TOTP credential and an OIDC AMR mapper. The CI script must exercise the real password → OTP challenge → authorization code → PKCE exchange. The existing password-only control test must be **rejected**. The real OTP flow reaches an authorization code, but the default Keycloak flow does not issue a supported signed `amr`/MFA `acr` claim; our app must continue to **reject** its token. Positive MFA grant is blocked until the IdP's OTP execution reference / assurance mapping is configured and proven.
5. CI retains PostgreSQL roles/RLS, HTTP API business flow, Chromium UI, pg_dump/pg_restore, Keycloak password-only negative test.

## What G1-J does not authorize

This is **not** a real employer's account, corporate MFA policy, signed-off preproduction, or public OIDC callback. The Keycloak test account and TOTP seed in the repository are **synthetic and must never be reused**. The release blocker remains in force.

This checkpoint may pass CI by proving both real password-only **and real password+TOTP without signed MFA evidence** fail closed, alongside permanent PostgreSQL session revocation. This is not a positive corporate MFA login acceptance. The remaining IdP step is to configure an authenticator execution reference `otp` and validate a provider-signed `amr` before enabling session issuance.

## Remaining release blockers

Select and provision an actual corporate IdP under the customer's control; verify genuine MFA enrollment and ACR/AMR policy end-to-end, corporate account offboarding, forced session revocation, public HTTPS/BFF secure-cookie model, CSRF/clickjacking defense, production secret rotation, encrypted backups and recovery, safe data-import/legal review including children, operational monitoring, rollback and incident response. No real customer data or live payments in this phase.

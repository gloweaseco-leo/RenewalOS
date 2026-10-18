# RenewalOS G1-J · MFA positive / instant revocation (CI synthetic)

**Status:** engineering gate under test, **PUBLIC RELEASE NO-GO**. Do not merge `main` or change Vercel.

## Delivered

1. PostgreSQL `005_oidc_session_revocation` adds issuer+subject provenance to OIDC sessions, revokes all older unprovable sessions during migration, and installs triggers that irrevocably revoke sessions when an OIDC binding or employee account is disabled.
2. Every authenticated API request verifies that the session's original `(issuer, subject)` still maps to the **same enabled user**. Re-enabling a binding or employee account does **not** revive revoked tokens.
3. OIDC start/complete cookies now use `Secure` when the pinned **loopback HTTPS** callback is configured; default HTTP loopback remains for disposable test harnesses, and production is still blocked.
4. Independent Keycloak realm includes a synthetic OTP-equipped operator with a real TOTP credential and an OIDC AMR mapper. The CI script must exercise the real password → OTP challenge → authorization code → PKCE exchange. Only a verified signed token with MFA evidence may create the employee session. The existing password-only control test must still be **rejected**.
5. CI retains PostgreSQL roles/RLS, HTTP API business flow, Chromium UI, pg_dump/pg_restore, Keycloak password-only negative test.

## What G1-J does not authorize

This is **not** a real employer's account, corporate MFA policy, signed-off preproduction, or public OIDC callback. The Keycloak test account and TOTP seed in the repository are **synthetic and must never be reused**. The release blocker remains in force.

The only acceptable completion evidence is the latest GitHub Actions run showing both Python matrices green, actual Keycloak positive OTP + negative password-only tests, and revocation tests. Until then G1-J is in progress.

## Remaining release blockers

Select and provision an actual corporate IdP under the customer's control; verify genuine MFA enrollment and ACR/AMR policy end-to-end, corporate account offboarding, forced session revocation, public HTTPS/BFF secure-cookie model, CSRF/clickjacking defense, production secret rotation, encrypted backups and recovery, safe data-import/legal review including children, operational monitoring, rollback and incident response. No real customer data or live payments in this phase.

# G1-J: OIDC session revocation, synthetic-only

This increment closes an identity lifecycle gap: disabling a pre-bound OIDC identity invalidates active bearer sessions in the same transaction. On re-enabling an identity, revoked old tokens remain invalid. Requests also re-check currently enabled issuer+subject binding to fail closed.

Changes: PostgreSQL migration 005, scoped session check, OIDC session provenance, disposable CI regression test. No public deployment, real IdP MFA enrollment, production cookies, or customer information is authorized. Existing G1-I live Keycloak negative MFA and G1-F Chromium workflows remain CI gates.

G1-J does not claim a successful MFA-positive Keycloak flow or a live preproduction HTTPS deployment. Those remain explicit blockers.

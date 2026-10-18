# RenewalOS G1-J · MFA正向验证与不可恢复会话撤销

**范围：本地/隔离CI合成数据；生产和公网预发依然 NO-GO。**

## 关键增量

1. `005_session_revocation.sql`：正式用户状态、机构/门店授权状态、角色、OIDC绑定变更会永久撤销该用户之前的**全部**会话。即便稍后重新启用授权，旧令牌仍无效；重新登录才能获得新会话。写入由受限触发器在同一事务中完成。
2. `tests/test_g1j_revocation.py`：真实 PostgreSQL 16 测试四种撤权及恢复场景，证明 `revoked_at` 已持久化；无需信赖UI隐藏按钮。
3. Keycloak原生OTP执行器配置 `default.reference.value=otp`，完成OTP后再由Keycloak内建AMR mapper写入令牌；禁止在用户属性或应用代码中硬编码MFA声明。
4. Keycloak合成OTP账号：仅CI使用的公开、不可复用测试TOTP种子，以Keycloak自有OTP认证器完成密码+OTP认证，令牌来源是独立IdP而非合成JWT。
5. `scripts/keycloak_mfa_g1j.py`：真实授权码 + PKCE + Keycloak HTTPS端点；调用应用自己的 `complete()` 完成RS256签名、Nonce、Audience、MFA属性与预绑定用户校验，完成真实本地授权会话、退出与重放拦截。未满足认证事实的Token仍会失败。
6. CI先执行PostgreSQL 005迁移和测试，再验证原有G1-F浏览器业务、G1-G恢复演练、G1-I单因素拒绝，最后执行G1-J正向MFA验收。禁止将真实账户、真实TOTP种子或个人信息放入GitHub日志。

## 尚未放行的事项

- 本测试的CI Keycloak **不是**目标客户的身份服务实例；尚无生产Tenant开户审核、SCIM同步、员工批量撤权集成与管理员操作审计。
- **没有部署公网预发或正式环境**。生产HTTPS、BFF/Cookie会话模式、密钥轮换、MFA供应商身份配置、加密备份恢复、最小权限运维仍是上线前条件。
- 前端旧的本地Bearer模式不能直接作为公网浏览器会话交付。

## 验收证据

合成PostgreSQL迁移/反向测试、独立Keycloak登录流程以及GitHub Actions运行链接（须取得全绿结果后补充）；PR保持Draft，不合并 `main`。

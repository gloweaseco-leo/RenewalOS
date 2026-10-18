# G1-G｜部署放行硬门槛与恢复演练（Phase 1）

## 本版交付

- `renewalos.release_gate.assert_local_only()`：拒绝 `production` / `staging` 和云平台环境标志。**这是生产环境的 NO-GO 防误启动开关，不是正式上线的开关。**
- `assert_dedicated_pg_roles()`：两条数据库连接必须是不同权限角色、同一回环地址的同一测试库，拒绝 postgres / root 等高权限账户。
- `/api/ready`：仅为本地合成测试环境提供 PostgreSQL 身份/业务连接与001—003迁移就绪检查，正常返回200，不就绪返回503。响应不包含DSN、令牌、SQL异常、用户数量；`/api/health`仍只是进程健康。
- `python -m scripts.release_audit_g1g`：输出可机器读取的环境门槛，`public_release` 永远为 `NO_GO`，并列出未完成的正式上线条件。
- `python -m scripts.backup_restore_g1g`：**仅限GitHub一次性CI数据库**，使用真实 `pg_dump` / `pg_restore` 备份和恢复，检查18张关键表行数、合同总额、净收退款和迁移版本完全一致，成功或失败都会清理仅为此次演练创建的恢复数据库。拒绝远程、非CI环境和生产数据库，绝不上传备份或秘密。
- GitHub CI同时运行 Python3.11/3.12回归与真实HTTP测试，3.11独立运行Chromium浏览器和数据库恢复演练。

## 运行示例

在**合成数据本地测试**环境下：

```bash
RENEWAL_RUNTIME_MODE=secure_local \
RENEWAL_AUTH_BACKEND=postgres \
RENEWAL_PG_AUTH_DSN='postgresql://DEDICATED_AUTH@127.0.0.1:5432/LOCAL_TEST_DB' \
RENEWAL_PG_APP_DSN='postgresql://DEDICATED_BUSINESS@127.0.0.1:5432/LOCAL_TEST_DB' \
python -m scripts.release_audit_g1g
```

成功退出只表示允许继续**本地合成环境的数据库就绪验证**；不会表示可以公网部署或接入真实数据。

## 仍未放行的生产条件

| 条件 | 状态 |
|---|---|
| 企业级OIDC+PKCE / MFA / 正式SSO提供商选择和联调 | 未开发，NO-GO |
| 正式员工生命周期、角色审批与审计 | 未验收，NO-GO |
| 客户真实数据采集授权、未成年人数据治理、存储期限和删除 | 未完成，NO-GO |
| 真实支付/退款交易来源核验和财务对账 | 未完成，NO-GO |
| 生产密钥存储、轮转和应急吊销 | 未完成，NO-GO |
| 加密异地备份、定期恢复演练、RPO/RTO、灾难切换 | 仅完成CI合成库演练，NO-GO |
| 受保护云端预发环境、HTTPS、跨域、网络准入、安全扫描和回滚 | 未完成，NO-GO |
| 真实客户续费增量、AI优于纯规则的经济证据 | 未取得 |

`CI pg_dump/pg_restore通过` 不等于生产级备份策略。数据从未迁移到真实客户环境；所有模拟金额不可称作实际收入。

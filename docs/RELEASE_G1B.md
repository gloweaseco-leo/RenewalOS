# RenewalOS G1-B｜PostgreSQL多租户数据基座（工程验证版）

**性质：可验证的数据库基座，不是正式客户部署，也不是完整业务迁移。**

## 已实现

- PostgreSQL 16 专用 schema：机构/门店/账户与成员关系、家庭/学员/课包/出勤、续费机会/任务/跟进、合同和付款退款事件。
- 业务复合外键均涵盖 `(org_id,store_id)`；续费合同和机会的学员必须对应其原课包的学员。
- 所有机构/门店业务表启用 `FORCE ROW LEVEL SECURITY`。同机构不同门店与跨机构访问均按可信事务租户上下文隔离。
- 账务来源字段区分 `synthetic / imported_unverified / provider_verified`。退款必须关联同一合同的付款，并限定累计退款；付款总额不得超过合同金额。
- `cash_events` 由触发器禁止 UPDATE/DELETE，并使用事务级advisory lock防并发超收/超退（需生产级并发压力测试）。
- 新增 `renewalos.pg_store`：受信认证端输入的身份与机构/门店信息，在**单事务**内设置行级隔离上下文；验证门店成员资格，并提供只读的机会/员工任务/净现金示例。
- GitHub Actions PostgreSQL 16服务运行迁移、角色授权、真实SQL反向测试，并完整保留SQLite旧回归集。

## 本地操作（仅空白隔离数据库）

安装：`pip install -e '.[test,postgres]'`。用**专用空PostgreSQL数据库**配置 `RENEWAL_PG_MIGRATION_DSN`，运行：

```
python -m scripts.pg_apply --confirm-new-database
```

脚本检测到已有 `renewalos` 表将拒绝重复迁移。不可运行在客户现有数据库。`scripts/pg_ci_bootstrap.py`及测试账号只用于GitHub CI，不用于生产。

## 现阶段缺口与风险

1. `RENEWAL_RUNTIME_MODE=secure_local` 仍采用SQLite并保持仅本地可访问；**未切换为PostgreSQL**。旧G0.x API继续由G1-A安全门禁用。
2. `TenantScope`必须由可信认证中间件产生，不能从HTTP请求体直接构建；数据库自定义GUC可由持有数据库凭据者自行设置。**禁止把应用数据库登录名/连接串暴露给客户端**；RLS只是受信后端内的第二道防线，而不是替代身份认证。
3. `identity_users`及机构权限的创建/删除应由单独的受限管理流程完成。CI初始化脚本和角色密码绝不能进入生产。
4. 尚未实施历史SQLite→PostgreSQL的逐表数据迁移、真实收款对账与正式业务写入适配；也未完成OIDC、MFA、备份/恢复、并发压测、部署权限和正式隐私验收。
5. 真实收入只能采用授权且已核验的支付来源，数据库的`provider_verified`列本身**不能**证明第三方已经核验；需受控验证流程。

**G1-C准入**：认证与门店授权中间件绑定PG事务、实际任务和合同写入安全迁移、租户级数据导入对账、恢复和回滚演练。未达到前不得公网部署或导入可识别儿童数据。

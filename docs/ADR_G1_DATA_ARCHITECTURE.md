# ADR-G1-001｜从本地SQLite原型演进到PostgreSQL多租户业务架构

状态：**Approved direction, not yet implemented**。本文件是实施边界，而非已交付清单。

## 决策

1. 正式多租户使用PostgreSQL；业务数据的所有关键实体加 `org_id` 和明确的 `store_id`，并通过外键/唯一约束防止跨机构关联。
2. 用户与业务人员严格分离：`identity_users`、`org_memberships`、`store_memberships`、`staff_profiles`；G0.8里的 `owner` 文本别名只能用于历史展示，不能当权限主体。
3. 统一认证中间件验证OIDC/SSO或可信会话，再由独立授权层在每一笔读写操作里施加机构、门店和角色条件；对高敏操作以事务级 `org_id` 和数据库RLS双重保护。绝不直接根据请求体中的 `org_id` 信任身份。
4. 资金事件、AI评审和人工动作采用追加式业务审计，禁止静默覆盖；补偿/退款必须引用原交易。保留原始导入文件版本及其映射、幂等键和导入责任人。
5. PostgreSQL以事务版本化迁移、备份/恢复和回滚演练进入G1-B；现阶段禁止把SQLite路径作为Vercel/无状态函数的持久化方案。

## G1-B迁移顺序

- [ ] 创建独立 `organizations`、`stores`、`users`、`memberships`，实现机构ID和门店ID的外键完整性。
- [ ] 迁移学员/家庭/课包/出勤，使用 `(org_id, source_system, external_id)` 唯一键和数据来源追踪。
- [ ] 迁移机会/任务/状态/人工跟进，显式 `assigned_user_id`，将旧版 `owner` 保存为审计元数据。
- [ ] 迁移续费合同、净付款/退款来源，所有现金来源标注 `synthetic`、`imported_unverified`、`provider_verified`，防止演示钱与实际入账混合。
- [ ] 迁移实验分组/冻结队列/AI输出与人工审核；历史自然续费不能被重算为AI贡献。
- [ ] 添加行级安全策略、ORM/SQL一致性验证、权限拒绝审计、并发及删除测试。
- [ ] 完成双轨只读对账、现金分组总额与关系完整性校验，通过后冻结SQLite演示写入，再开放受认证的正式业务写入。

## 风险与反例

- SQLite可以通过自动化回归并不说明PostgreSQL行为一致，尤其是事务隔离、金额类型和并发控制。
- 单靠应用端查询过滤器或页面隐藏不能防止SQL越权；必须在数据库与API双层按机构强制约束。
- 只按 `store_id` 分区不够：不同机构可能有相同门店代号，业务主键与所有外键必须涵盖 `org_id`。
- G1-A是对旧演示系统的**只读受控封装**，不是可以在现有Vercel公网接客户数据的替代方案。

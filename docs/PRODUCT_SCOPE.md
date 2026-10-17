# RenewalOS MVP V0.1 — 产品与技术边界

## 目标与首个用例
独立于 aoguan-webapp 的体育培训机构续费机会管理演示工具：导入匿名业务记录、发现续费信号、规则建议与可选真实AI建议、人工跟进、核对净支付事实。

## 关键业务事实
- 机会不是成交；已付款订单不是AI增量；消课不是新增收入。
- 分组按家庭，三个分支：control/ rules/ ai，维持所有客户正常基础服务。
- 暂无数据支持因果增量、贡献毛利、统计显著性或ROI。
- 默认不连接大模型，未配置模型明确拒绝AI调用，不返回伪生成内容。
- 不使用真实未成年学员可识别信息，不部署公网。

## CSV输入
learners.csv: learner_id,family_id,guardian_alias,store_id,contact_consent
packages.csv: package_id,learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cny
attendance.csv: event_id,learner_id,session_date,status
renewals.csv: renewal_id,learner_id,source_package_id,paid_on,amount_cny,status
日期ISO格式；contact_consent=yes/no。只允许合法授权的去身份化演示数据。

## 一期功能
1. 文件导入与事务错误回滚。
2. 临近到期/余课偏少/出勤下降可解释规则识别。
3. 基于家庭ID持久化实验分组，不将AI建议派发给非AI组。
4. 人工执行任务及留痕。
5. 净支付流水事实看板，增量利润和ROI为不可计算状态。
6. 可选真实模型接口，只发送课程类型及非识别化信号。

## 禁止范围
自动发送客户消息；承诺折扣；未经许可连接第三方SaaS；自动营销未成年人；生产多租户/权限能力；大模型自行判断监护人缺课原因；将模拟数字包装成真实商业收益。

## 开发G1前提
授权与数据合同、脱敏策略、数据保留与删除、身份登录/权限、审计日志、数据来源映射、正确的续费周期口径、实验登记冻结、成本归因；在此之前不可进入生产。
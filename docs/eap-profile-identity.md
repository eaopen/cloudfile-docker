# Etech 身份集成（当前 V2）

更新：2026-10-20。本文适用于 CloudFile 当前 V2 dev；不恢复旧 EAP OAuth Bridge。

## 身份规则

- Etech `userId` 是唯一业务身份，对应原生 `Profile.login_id`。
- Directory 的 `attributes.employee_no` 当前承载 `org_user.account_`；允许数字账号、zhangsan、admin，禁止 cfadmin。合法字符为 ASCII 字母、数字、点、下划线和连字符，长度 1–200，不自动去空格；新原生用户名遵循 Seafile RPC 转小写的规则。登录账号不区分大小写，UID 仍精确匹配。
- 新原生账号使用 `account@auth.local`，账号名冲突拒绝；admin 仍是普通非 staff 用户。
- 已有 UID 精确绑定优先复用，保留 UUID 或历史后缀，不自动重命名、不按联系邮箱合并。
- 管理员解析只接收 UID 作为依据；未知 UID 独立读取可信 Directory 的账号与有效状态。EAP 同步使用返回的真实原生账号，不能猜测工号邮箱。
- 账号歧义只在有效用户间判断；停用历史记录不作为有效候选。多个有效 UID、大小写碰撞及 UID/账号碰撞拒绝解析，不选择最小 UID。

## 当前 V2 登录配置

当前镜像由 `build/v2/start-dev.py` 启动，从已有原生配置保留 `OAUTH_*` 和 Directory 连接设置，不调用 `scripts/scripts_14.0/bootstrap.py` 或其中的 `cloudfile.py`。

Etech 需在已有 `seahub_settings.py` 中明确配置：

```python
OAUTH_ATTRIBUTE_MAP = {
    'sub': (True, 'uid'),
    'userId': (True, 'login_id'),
    'name': (False, 'name'),
    'email': (False, 'contact_email'),
}
```

`preferred_username` 不能映射为 Etech 的 `login_id`。配置了可信 Directory 而没有明确的 userId 映射时，Hub 拒绝登录，防止兼容逻辑把 UID 改写成账号。映射明确后，缺失 userId 也必须拒绝，不能退回按邮箱关联或随机建号。

`CF_SSO_EAP_PROFILE_IDENTITY` 是已退役 Bridge 的开关，当前 V2 不得启用；旧文档建议设为 true 已失效。`/oidc/` 入口另需已有的 `OAUTH_OIDC_ISSUER`、`OAUTH_OIDC_JWKS_URI`，验证 ID Token 与 UserInfo 的身份一致性。Etech 首次 OIDC 建号要求 ID Token 和 UserInfo 均携带一致的 userId；可信 Directory 确认 UID、account 与有效状态后，由 V2 `SQLJITProvisioner` 创建/复用原生 User、Profile 并添加该 provider/sub 绑定。先登录或先 EAP 同步均得到同一 UID 原生用户。旧 OAuth 不创建用户，仅复用已有 UID。旧生成器若用于维护历史部署，显式 `CF_SSO_OAUTH_LOGIN_ID_CLAIM=userId` 才表示 UID 映射；不能照搬其启用 Bridge 的旧提示。

普通 Seafile CE OAuth、LDAP 和管理员本地建号保持其自身规则。以上配置说明不表示已改动任何 DEV/PROD 环境变量或持久配置。

## 构建与验证边界

最新 Docker dev 的默认组装会解析本地 Server/Hub dev 为固定 SHA，写入 `v2-source-receipt.json`；构建前需更新本地 dev，或显式传入已审核的 `--hub-ref`、`--server-ref`。`build/v2/source-set.json` 保留为显式 `--source-set` 历史快照，不能据它断言最新默认构建仍固定旧 Hub。

OIDC 登录建号与 OAuth 可信 UID 适配器分别位于 `cloudfile_ext/v2/jit.py`、`cloudfile_ext/v2/oauth_identity.py`，随精简 V2 overlay 一起组装；旧包仅保留导入转发，不能让精简产物依赖 `cloudfile_extensions`。

源码组装、模块测试和源码回执不等于镜像发布或 DEV 验收。本轮不改表、不运行数据库迁移、不清理历史账号、不部署。历史账号迁移单独审核，保留 UID、原生所有权、共享、组权限与认证绑定。


## 2026-10-20 风险清单复核

| 项目 | 最新 dev 的源码事实 |
| --- | --- |
| 构建始终固定 bfc7651f | 已过时：默认 dev 组装与显式历史快照已区分；实际运行镜像仍需另查 Digest，不能据源码推断已上线。 |
| Authentik preset 用 preferred_username 覆盖 UID | 旧生成器仍有该配置，但当前 V2 镜像不调用它。持久配置可能沿用旧映射，故 Hub 对 Etech Directory 的错误映射拒绝登录，不自动改写 UID。 |
| bootstrap 推荐已退役 Bridge | 旧生成器提示仍在；当前 V2 不调用它，本文替代旧 EAP 配置建议。 |
| 可选 userId 缺失会回退 | 最新 dev 仍有该风险，本轮已改为由配置决定严格模式，缺少 UID 不回退。已有 Token 签发方法也必须提供业务 UID；没有重新启用普通无 Cookie 请求的旧 Token 回退。 |
| by-login 多个有效账号选最小 UID | 最新 dev 仍有该行为，本轮改为歧义拒绝；只在职记录参与候选，单条有效记录不被停用历史记录阻断。登录账号不区分大小写，多个有效 UID 的大小写碰撞仍拒绝。 |

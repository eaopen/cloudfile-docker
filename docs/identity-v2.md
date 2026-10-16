# V2 身份与单用户成员投影契约

本契约适用于 `dev2` 的 M1 身份源码。未启用时保留现行部署行为；启用不代表已经完成环境验收。精简新装 Schema、旧受管库保护退场及完整文件业务验收分别推进。

## 双标识

- 稳定外部 UID 经已验证 OIDC claim 映射到 CE `Profile.login_id`；`issuer + sub` 继续使用原生 SocialAuth 绑定。不建立另一张用户主表，不以邮箱或登录名自动认领已有账户。
- `CLOUDFILE_OIDC_CONFIG_JSON.user_id_claim` 可配置为 `external_user_id`，兼容默认 `userId`。内部接口继续使用 `userId`。
- 可选 `login_name_claim` 指定登录名 claim，例如 `preferred_username`。该值必须同时出现在已签名 ID Token 与同一 `sub` 的 UserInfo，且与受信 Directory 当前 UID 上下文中的 `attributes.login_name` 一致；不允许与 UID claim 或 OIDC 身份保留字段混用。
- 通用 Directory 的 `attributes.login_name` 可使用 Unicode 或邮件形式，允许改名；新建 CE 用户使用不可由登录名推导的随机内部账号。同 UID 重新登录保留原生用户名、文件归属和绑定。兼容旧 Directory 的 `attributes.employee_no` 与已有 `工号@auth.local` 账号；两种属性同时存在时必须相同。
- 原 EAP OAuth 入口继续校验 UID、工号与目录；在 TTL 模式中，创建浏览器登录前必须完成同一套单用户投影。投影失败不得创建登录会话。

一个实例仍只配置一个业务 Directory Provider；裸 `Profile.login_id` 不支持多业务 Provider 的同值 UID 命名空间。目录来源必须对重复有效登录名返回歧义/失败，不能替调用者任选 UID；CloudFile 拒绝 UID/sub/Profile 不一致、原生账号冲突及停用账户，不通过邮箱补绑。

## 成员写入者

在既有 `CLOUDFILE_POLICY_CONFIG_JSON` 增加：

```json
{
  "membership_mode": "subject_ttl",
  "subject_ttl": 1800
}
```

这只是新增字段片段，须与已配置的数据库、Redis、Directory URL/机器凭据、Provider、原生 Schema、属性白名单与 C 核心路径合并。通用登录名需加入 `attribute_allowlist`；EAP 继续包含 `employee_no`。`membership_mode` 默认为兼容的 `snapshot`，部署必须显式选择 `subject_ttl`，不能同时运行两个模式的 worker。

- `subject_ttl` 下，周期/手动/旧 webhook 同步只创建或更新组织、角色实体及 `cf_sso_group_map`；即使旧 `/groups` 仍包含全量成员也全部忽略，不读取人口 Profile 或当前全组成员。
- 旧 additions-only 登录刷新和 UID 增量成员写入停用；GroupUser 唯一业务写入者为 `SubjectPreparation`。实体写入与投影使用同一 Provider authority lock，外部 HTTP 查询位于锁外。
- 按 UID 登录、TTL 到期或显式强刷读取当前组织、祖先及角色；只增删当前用户在本 Provider 拥有的 CE Group 中的普通成员，保留手工组、其他 Provider 组和非受管 staff。缺失组映射、祖先不完整、原生绑定不一致或无法事务化时拒绝发布 ready。
- 退役实体的映射保留，旧管理接口在该模式拒绝直接删除映射，避免旧 GroupUser 失去归属而永远不能撤销。部门改挂父级仍需显式迁移；不自动采用同名人工组或其他创建者的组。

## TTL 与故障

`subject_ttl` 为整数 60–1800 秒，默认 1800；抖动最多缩短 10%，缓存命中不续期。登录、请求和刷新 worker 使用同一值与 Redis 命名空间。投影提交和读回成功、世代仍有效后才能发布 ready；SQL 部分失败回滚，Redis 发布失败不得沿用旧 ready。

关系变化允许在有效 TTL 内延迟。过期后 Directory/Redis/映射不可用时，受保护入口必须拒绝继续授权；残留 GroupUser 只是投影事实，不能替代 ready 主体。停用上下文撤销本 Provider 的成员并保持禁止登录/内容访问。已有文件票据另受有限寿命和终判约束。CE-only 库和用户不因未配置外部 Directory 自动进入此模式。

当前保留旧 Schema 和受管库 guard；不要将此开关理解为所有原生 CE 客户端都已具备外部主体校验。普通 CE、受保护原生 API、Fileserver、上传最终提交、共享根、Agent/Office 的完整实际运行入口矩阵仍须在部署门禁验证。

## 可复现验证

独立 MariaDB 11.4 与 Redis 7，端口通过 `CF_TEST_DB_PORT` / `CF_TEST_REDIS_PORT` 指向临时实例。测试会创建随机 `cf_test_*` 数据库，不能指向业务环境。除 `tools/check-requirements.txt` 外，真实 Django MySQL 测试需 `mysqlclient>=2.2,<3`。

三仓并排检出相匹配的 `dev2` 后，在三仓父目录执行：

```bash
python3 cloudfile-docker/tools/check-hub-contracts.py -k 'identity or external_identity or contexts or projection or sql_bindings or bindings or provisioning or prepared_login or directory_catalog or directory_partial or subject_read_scope'
cd cloudfile-hub
python3 -m pytest cloudfile_ext/sso/ -q
```

`dev2.yml` 使用临时 MariaDB/Redis 服务执行这些检查。数据库与缓存真实运行；外部 Directory HTTP、IdP 与部分 CE RPC 为测试适配器，不能替代真实 OIDC、CE14 部署和业务字节验收。

# 方案 B：DEV 代码与部署验证（2026-10-09）

修改原因：记录 EAP、Authentik、CloudFile 的实际版本与验收边界，避免把源码测试
或历史目录兼容验证误写为完整登录验收。身份契约见 [eap-profile-identity.md](eap-profile-identity.md)。

## 已提交并推送的代码

- EAP `2e34439f`：有效工号确定性去重，只保留选中 UID 的部门和角色；DEV OIDC 登录核对业务 UID。
- CloudFile Hub `4ab885536`：复用原生 Profile，UID 优先复用，工号命名新账号；旧工号绑定只在已有可信 sub 与 EAP 目录一致时升级；异常身份隔离；登录权限按 UID 刷新。
- CloudFile Docker `47e9d34`：可选 UID 回调配置、app/worker 配置一致及配置生成测试。
- Authentik DEV 配置源码位于 etech-config 提交 `057bef9`，本地已提交；该仓另有历史未推送提交，未在本次推送整条分支。

## 本地回归

- Java 17 编译和定向测试 20 项通过，包含 6 项真实 MariaDB 测试。
- Hub 全量回归 1540 项通过、56 项因环境条件跳过；另行新增的 OAuth 实际 ORM/MariaDB 测试 1 项通过。
- Docker `tools/run-checks.sh` 全部通过，bootstrap 配置测试和 compose 示例解析通过。
- Authentik 工号/邮箱/UID 表达式测试 6 项通过。

## DEV 发布与只读验证

- dev162 的 `dev-etech-eap` 使用 `etech-eap:scheme-b-2e34439f-dev`。
- CloudFile app/worker 分别使用 `cloudfile/cloudfile:scheme-b-4ab885536-app-dev`、
  `cloudfile/cloudfile:scheme-b-4ab885536-worker-dev`，保留各自已有镜像基线及独立修复。
- 镜像记录 OCI revision/created；发布材料记录所用源码提交。通过本地编译和 SSH 发布，
  dev162 直接连接 `admin@10.9.8.162`。
- tool138 只更新 Authentik DEV：Portal、Studio、seafile dev、cloudfile 四个 provider 共用
  `etech-business-uid-dev` claim，读取受认证的 EAP 目录。不修改工号密码认证策略、client、sub 模式、会话时长或生产实例。
- 实际 Authentik 表达式引擎抽查三名有效员工，均得到字符串数字 UID，`userId == login_id`。
- DEV CloudFile 登录入口返回 302，并携带 S256 PKCE、nonce、state。
- 新运行时代码可读取 1131 组、4197 个不同 UID；当前 2 个 Profile 的 login_id 与目录 UID 精确匹配。
  这不是已完成全部员工迁移：旧账号需下一次可信登录复用并升级，未登录员工不会自动建号。
- UID 登录刷新已启用；增量样本 dry-run 为 add=0、remove=0，实际幂等执行返回 ok、add=0、remove=0。DEV 全量撤员比例和单用户最大撤员数仍为 0。
- 无效 state/code 回调显示拒绝提示，不设置 seahub_auth Cookie；app 健康、worker 运行，镜像 revision 与 Hub 源码提交一致。
- DEV 数据库可见表中没有 `cf_eap_user_binding`。

## 验收边界与回滚材料

未使用员工密码完成浏览器端全流程登录，不将上述协议入口、表达式和数据库测试称为
完整单点登录验收。没有批量合并用户、清理 EAP 原始数据、删除历史成员或修改生产。

EAP 备份：`/data/dev-data/backups/identity-scheme-b-20261009/`。
CloudFile 备份：`/data/etech-infra/cloudfile-dev/backups/identity-scheme-b-20261009/`。
Authentik scope mapping 备份：`/data/infra/backups/business-uid-dev-20261008T175748304435Z.json`。

备份包含原镜像、原 jar、原 Compose/环境配置，权限受限，不入 Git。回滚需按目标服务
选择性恢复，不能覆盖其他服务的并行配置，也不能自动重置数据库。

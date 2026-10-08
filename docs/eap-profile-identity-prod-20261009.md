# 2026-10-09 生产 SSO 兼容更新

修改原因：DEV 已验证 Profile UID 身份方案及 HTTP JWKS 兼容修复；生产 EAP 尚未提供可用的独立用户目录接口。按用户要求，EAP 单独发布，本次先更新 CloudFile 与 Authentik，并保留生产原登录协议。

## 已完成

- DEV CloudFile `sso-92901f851-app-dev` 已通过用户重新登录、查看网盘验证。
- 生产 CloudFile/worker 原镜像均为 `cloudfile/cloudfile:automatic-storage-20261008`；以该镜像为基础追加 SSO 补丁，保留生产存储改造和原 OAuth 兼容代码。
- 补丁来源：Hub `cc6b0e268`（独立目录认证）、`c6a036104`（UID 增量刷新）、`4ab885536`（Profile 身份桥）、`92901f851`（显式 HTTP 模式下 JWKS 兼容）；Docker `47e9d34` 中的 bootstrap 配置生成改动。
- 生产镜像为 `cloudfile/cloudfile:sso-92901f851-prod-staged`，镜像 ID `sha256:a65e1f4f599e35542f1a8701e43f681af46d5dca6f81526d9e3fe8cdfc286120`，主服务及 worker 均使用此镜像。
- minio157 `/data/etech-infra/cloudfile/.env` 的两个镜像变量及 `docker-compose.import-search.yml` 的两个镜像覆盖已更新。Compose 仍合并原 `docker-compose.yml`、`docker-compose.import-search.yml` 和 `docker-compose.library-storage.yml`。
- Authentik DEV/PROD 版本均为 `2026.2.2`，无需升级软件版本。生产新增 `etech-business-uid-prod` ScopeMapping，表达式与 DEV 相同，仅将配置路径改为 `/data/eap-directory-prod.json`；**未绑定任何 provider**，原 provider 映射未改变。表达式 SHA256：`73d8b31eba8523335f3c556ed8daa0ddd7b9ad0b45a99ec99b2f8aecb4a7bd8c`。

## 当前生效边界

- `CF_SSO_EAP_PROFILE_IDENTITY=False`，生产仍走原 OAuth callback。
- provider 保留 `authentik:seafile-pro`，`login_id` claim、客户端凭据、稳定 sub 和回调地址保持原值。
- 原生产目录地址与撤员比例 `0.5` 均未改动。没有把 DEV 的撤员保护或地址复制到生产。
- 未修改或重启 EAP、EAP Web、数据库及存储服务；未创建生产目录机器凭据，未迁移 Profile 或修改员工账号。
- 本次没有创建环境备份；原生产镜像仍保留。若需要回退，由操作员将上述两处镜像配置恢复为 `automatic-storage-20261008`，仅重建主服务与 worker，不回滚业务数据库。

## 验证

- 相关 SSO、SQL binding、OIDC 配置测试：141 passed、10 skipped（环境依赖测试），配置生成测试全部通过。
- 生产补丁镜像中 17 个相关 Python 模块编译检查通过。
- 主服务 healthy、worker running；原 Web/API、OAuth 跳转、回调地址、OIDC 发现、公钥、匿名访问拒绝、静态资源和文件入口等 17 项 HTTP 检查通过。
- 此次未使用生产员工凭据完成真实浏览器登录；不能将路由检查等同于完整生产 SSO 验收。

## EAP 单独发布后的后续步骤

1. 对生产两个 EAP 实例验证独立机器认证下的按工号、按 UID 目录查询及全量快照，核对两实例配置一致。
2. 配置生产专属目录凭据供 CloudFile 和 Authentik 使用，禁止复用 DEV 凭据；检查生产现有 Profile/sub 绑定冲突及权限差异。
3. 启用生产 v2 目录和 Profile UID 身份桥，并将已保存的 UID mapping 绑定到对应生产 provider，避免旧 employee-valued login_id 映射覆盖 UID。
4. 以真实员工完成登录、网盘访问和权限增量刷新验证；再确认生产撤员策略。

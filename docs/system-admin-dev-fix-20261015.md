# DEV 全局管理员最小修复（2026-10-15）

## 范围与原因

`7fb31f857` 在原库管理员判断中提前导入完整 `User`，触发 `config_parser` 的额外依赖并中断群组管理员判断。此次移除该导入，保留原个人/群组/库所有者路径，仅用原生账号与 AdminRole 查询补充系统管理员资格；严格诊断仍传播存储错误，不把错误当成无授权。

Server 和 Hub 内容资格同时收紧为有效原生 `system_admin`，遵守既有角色能力关闭覆盖。`daily_admin` 的后台库管理能力保留，但不自动获得全库内容访问；显式 `default_admin` 同样不提升。缺少 AdminRole 行的有效原生管理员保留 CE 既有默认语义。无需新表、管理组、每库管理员记录或新配置项。库内 ACL、硬只读、停用和屏障继续生效。

Hub：`4ced1faed`；Server：`af1c0ac`。Docker 本提交补齐 Compose 主服务与 worker 对既有 `CLOUDFILE_AUTHORIZATION_ENABLED`、`CLOUDFILE_TRANSFER_ENABLED` 的透传，均保持默认 false；管理员策略继续按现有自动初始化规则选择，避免引入额外管理员配置。

## 已完成的本地验证

- 20 项 Hub 定向回归通过，包括原两项失败用例；未增加 PyYAML 或其他依赖。
- Hub 两包完整回归：1535 passed、390 skipped；两条既有测试环境/Redis 警告。
- 共享 `run-checks.sh` 全部通过；系统角色 14 组跨仓用例在 Hub 与编译后的 C 实际资格函数中复用，涵盖日常管理员、撤销 staff、停用、能力关闭和无效角色。
- Compose 默认/显式开关两进程透传与存储模板检查 3 项通过。

## DEV 升级边界

现场已运行 `14.0.0-cf-dev-hotfix-7fb31f857`，其 Server 标签为 `e2fb5db`；不能沿用“未发布”判断。升级前备份当前 `.env`、Compose 与镜像 ID。只替换 DEV 主服务和 worker；不迁移身份、删除旧库或修改生产环境。

候选镜像应使用已验证源 SHA，记录 Hub、Server、Docker 三仓及基线镜像摘要与文件校验值。原生二进制必须在匹配的 amd64 运行时工具链内编译并检查动态链接依赖；不复制 macOS/arm64 构建结果。GitHub 三仓检查及 Server `build-c` 成功后才切换 DEV。

DEV 验收至少包含：ETech 两种真实身份 SSO 与 UID 核验、普通组织成员既有资料库读取、系统角色跨库资格、日常管理员无隐式全库读写、现有库管理员、文件上传/下载与目录共享。使用独立验收库和可识别的测试资源，已有业务权限不因验收而扩展。完整 v0.9 OIDC/传输通道若未配置依赖则维持关闭，不把该状态写成已验收。

## DEV 已完成验收

2026-10-15 19:22（北京时间）主服务与 worker 已切换到 `10.12.1.138:8041/cloudfile/cloudfile:14.0.0-cf-dev-hotfix-4ced1faed`，摘要 `sha256:2d120b3f7c9f4da77af1b7e889dc3447b735543c6581891581d619d6333ffd3b`。构建来源 Hub `4ced1faed`、Server `af1c0ac`、Docker `44450d9`；三仓 GitHub 共享检查、Server 完整 C 构建与 Go lint 均通过。镜像内 `/opt/seafile/system-admin-content-fix.json` 记录基线镜像和文件校验值，`system-admin-release.yaml` 固定原生组件 SHA。

- 补充真实 MariaDB/C 策略回归 37 项通过；临时数据库已移除。
- admin 与邓鹏现有 EAP 身份 SSO 均下发有效会话，工号/业务 UID 匹配；etech01 均正常返回 46 个根条目和 3 个子目录条目、权限 rw。
- 独立验收库由另一账号拥有，system_admin 无逐库授权即可初始化浏览、创建目录、上传 53 字节测试文件并下载，内容校验一致。
- 普通用户无库资格时根目录为 403；配置单目录 share_mode=1 后可以读取该目录，根目录仍为 403。
- 新建的临时原生账号依次验证 system_admin 为 rw，daily_admin/default_admin/audit_admin 无隐式内容权限；daily_admin 后台 can_manage_library 保留；停用系统管理员被拒绝。临时账号及角色已清理。
- 在验收库添加系统管理员专属 invisible 后，目录读取与上传链接均为 403；其他共享接收者仍能访问；测试拒绝规则移除后恢复 200。

验收库 `ef56dc98-5ce8-41c2-a735-5b2415103d9b` 仅包含合成测试文件；既有业务库授权不变。完整原生 OIDC/传输通道仍按当前部署保持关闭，既有 HTTP OAuth、管理员策略和原生文件读写均已验证。回滚备份在 minio157 `/data/etech-infra/cloudfile-dev/release-backups/system-admin-4ced1faed-20261015-192217`。

CI 证据：[Hub](https://github.com/eaopen/cloudfile-hub/actions/runs/38725730029)、[Server](https://github.com/eaopen/cloudfile-server/actions/runs/38725731735)、[Docker](https://github.com/eaopen/cloudfile-docker/actions/runs/38725714736)。

### 最终继承边界补充

复核发现管理专用 `LibraryWideManagementAuthority` 继承内容读取类，因此用一个覆盖方法保留其原管理判定，防止收紧内容角色时影响标签、审计等后台管理。Hub `3c56df23a` 完整回归仍为 1535 passed、390 skipped，[GitHub 检查通过](https://github.com/eaopen/cloudfile-hub/actions/runs/38727865252)。

19:33 DEV 主服务和 worker 已切换最终镜像 `14.0.0-cf-dev-hotfix-3c56df23a`，摘要 `sha256:b0996f6d57a7cb23f77b8b8e67da3429141f190e3e19c98f42b741ef8932da8c`。镜像源码为 Hub `3c56df23a`、Server `af1c0ac`、Docker `aab0d1a`（与前版 Docker 运行时代码相同，仅补验收文档）；Server 二进制沿用已通过完整构建的同一 SHA。

最终版本再次验证两人 SSO 与 etech01 读取、系统角色与停用、ACL 拒绝和恢复均通过。现场真实 SQL 额外确认：daily_admin 的内容资格为 false，管理专用资格与原生后台能力一致为 true。临时账号和测试拒绝规则均已清理。最终切换前的独立回滚备份为 `/data/etech-infra/cloudfile-dev/release-backups/system-admin-final-3c56df23a-20261015-193316`；原始升级前备份继续保留。

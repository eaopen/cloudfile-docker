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

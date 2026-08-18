# CloudFile 文档

> 用途：当前文档入口与阅读顺序
> 适用版本：Seafile CE 14 参考基线
> 当前状态：有效

## 使用与运维

| 文档 | 内容 |
|---|---|
| [项目概览](overview.md) | 基线、产品边界和事实口径 |
| [当前架构](architecture.md) | 三仓职责、数据边界和故障隔离 |
| [部署](deployment.md) | Compose 部署、升级、备份和恢复 |
| [配置](configuration.md) | 环境变量、profile 和配置生成规则 |
| [扩展能力矩阵](feature-matrix.md) | 每项能力的状态、来源、定位、证据和上游策略 |

## 能力说明

| 文档 | 当前状态 |
|---|---|
| [Authentik 与企业认证](features/sso-authentik.md) | 部分完成；通用 OIDC 与组织映射已有，Authentik 端到端待验证 |
| [多存储与 S3 兼容存储](features/storage-backends.md) | 已完成；优先验证 MinIO |
| [外部资料联邦与虚拟目录挂载](features/external-directory-mount.md) | 规划；拟拆分为独立项目，为 AI 和 CloudFile 提供不同消费接口 |
| [Seafile AI 与外接 LLM](features/seafile-ai.md) | 验证中；复用官方 Seafile AI，外接配置模型 |
| [目录 ACL 语义](acl-semantics.md) | 验证中；active-authority 故障与修订契约尚待跨层实现 |
| [写入生命周期](fileop-lifecycle.md) | 验证中 |
| [目录/文件操作日志](features/audit.md) | 验证中；已查询提交变更，完整操作与协议覆盖待补 |
| [目录/文件标签机制](features/tags.md) | 验证中；CE 通路存在，当前门禁未验证目录/文件绑定闭环 |
| [收藏对象 ID 化](features/favorites.md) | 验证中；收藏按对象 ID 跟随移动/重命名，旧记录无损回填，容器 E2E 待补 |
| [检索](features/search.md) | 部分完成 |
| [文件协作与本地应用](features/file-collaboration.md) | 部分完成 |
| [外部资料源](features/external-sources.md) | 部分完成 |

## 研发与决策

| 文档 | 内容 |
|---|---|
| [上游贡献建议](upstream-contribution.md) | 可提交、拆分后提交和内部保留的改动 |
| [路线图](roadmap.md) | 仅保留未完成项，不承诺日期 |
| [权限表与权限模型](permission-tables.md) | 权限相关表清单、字段语义、口径决策与收敛路线 |
| [分支与上游跟随](BRANCHES.md) | 当前分支、合并门槛和同步步骤 |
| [扩展点清单](EXTENSION-POINTS.md) | Hub/Server 扩展点及消费者技术参考 |
| [历史版本](history/README.md) | 被替代方案、旧规划和决策过程索引 |

`docs/upstream-patches/` 是上游修改登记，`acl-cases.json` 和
`fileop-cases.json` 是机器可读契约，不属于导航正文。历史文档不作为当前配置或功能状态
依据。

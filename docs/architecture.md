# 当前架构

> 用途：说明 CloudFile 的运行时分层、扩展边界和故障隔离
> 适用版本：Seafile CE 14 参考基线
> 当前状态：有效

## 架构原则

1. **上游优先**：Seafile 已有且可用的模块、协议、数据模型和扩展服务默认直接复用；
   CloudFile 不为相同问题维护平行实现。
2. **扩展而非替换**：新增能力以可关闭的 provider、hook、独立服务或客户端接入，关闭后
   保持 CE 默认行为；只有 CE 缺少必要扩展点时才做最小上游修改。
3. **完整 MVP**：每项特性先闭合入口、权限、数据、配置、故障隔离、运维和验证，再持续
   改进体验与覆盖；不能用单个页面、Compose profile 或规划文件代替 MVP 完成证据。
4. **独立边界**：可通用化的新场景优先拆为独立项目，通过版本化契约接入 CloudFile。

## 运行时分层

```text
浏览器 / Seafile 客户端 / WebDAV / 本地 Agent
                  │
                  ▼
cloudfile-hub（Seahub fork）
  Web/API、扩展注册、能力 UI、周期任务编排
                  │ RPC / HTTP
                  ▼
cloudfile-server（seafile-server fork）
  权限终判、写入生命周期、对象/块/资料库操作、存储路由
                  │
                  ├── 本地文件系统 / S3 兼容存储
                  ├── MariaDB / Redis
                  └── 可选外部服务
                       Authentik、SeaSearch/Meilisearch、metadata-server、OnlyOffice、seafile-ai

独立项目 / 客户端
  cloudfile-local-agent、cloudfile-chrome-extension
  规划中的 CloudFile 外部资料联邦（OpenList/rclone 适配）
```

`cloudfile-docker` 不承载业务请求，负责按 `release.yaml` 构建并用 Compose 写入配置、
创建扩展表、启动可选服务和执行验证。

## CE 与扩展版的边界

| 层 | Seafile CE 负责 | CloudFile 新增或修改 |
|---|---|---|
| Hub | 资料库 Web/API、OAuth2/OIDC、SAML、LDAP、元数据 UI/API、预览 | `cloudfile_ext/` 注册中心、ACL、组织映射、审计入口、检索 provider、外部资料源、本地应用会话 |
| Server | 资料库/提交/FS/Block 模型、同步与 RPC 基础 | `cf-ext`、写入生命周期、ACL/锁终判、S3 和多存储后端、离线迁移 |
| 部署 | 上游镜像脚本与组件约定 | CE 14 源码构建、统一环境变量、profile、配置块和跨仓门禁 |

修改上游文件的权威清单位于 `docs/upstream-patches/`，由
`tools/check-upstream-patches.sh` 检查并输出非阻断警告。能力代码优先放在新文件；新增上游修改仍应同时
更新清单和[上游贡献建议](upstream-contribution.md)。

## 扩展注册与开关

Hub 在 `cloudfile_ext/apps.py` 启动时调用各能力的 `register()`，随后封闭注册中心。
Server 在 `cf_ext_init()` 注册底层终判 provider。`bootstrap.py` 从同一组
`CF_ENABLE_*` 生成 Seahub 与 seaf-server 配置，避免界面开关和终判开关漂移。

开关关闭不等于删除扩展点：扩展点仍可被基线门禁验证，但没有 provider 时必须透传 CE
行为。详细契约见当前保留的 `acl-semantics.md` 和 `fileop-lifecycle.md`。

## 数据边界

- Seafile 原生对象继续使用资料库、commit、FS object 和 block 模型。
- `cf_*` 表由 `cloudfile-server/scripts/sql/*/cloudfile.sql` 声明，存放在
  `seafile-db`；Hub 模型使用 `managed=False`，不通过 Django migration 建表。
- 外部资料源记录与授权位于 `cf_external_source*`，文件内容仍留在外部挂载，不自动
  转成 Seafile 原生对象。
- Seafile AI 继续使用官方 `seafile-ai` 服务和 Seahub 入口；LLM 在
  `seafile_ai_config.yaml` 中外接配置，CloudFile 不维护平行 AI 后端。
- Authentik、OpenList、rclone、MinIO 等组件的数据与可用性不由 Seafile 事务保证。

## 外部服务与故障隔离

同步权限终判不得依赖网络调用。外部目录、检索和内容服务通过周期任务、缓存或独立入口
接入：调用失败不应放宽权限，也不应把外部目录误判为空。虚拟目录挂载的 OpenList/rclone
方向归入规划中的 CloudFile 外部资料联邦模块，必须先以独立项目验证，再通过版本化接口
为 AI 应用提供统一文件资料库、为 CloudFile 提供虚拟目录挂载；详见
[外部资料联邦与虚拟目录挂载](features/external-directory-mount.md)。

AI 能力优先复用 [Seafile AI](features/seafile-ai.md)。模型服务故障只应影响 AI 请求，
不得放宽资料库权限或阻塞基础文件读写；发送给外部 LLM 的内容、凭据与审计属于独立安全
边界。

## 构建与发布

`build/cloudfile_14.0/` 从锁定提交构建发行包，`image/cloudfile_14.0/` 生成镜像，
`deploy/compose/` 提供部署。`dev` 表示当前集成基线与已合入能力；功能是否可发布仍以
[功能矩阵](feature-matrix.md)和对应门禁结果为准，不能仅凭分支存在判断。

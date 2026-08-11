# 扩展能力矩阵

> 用途：统一记录能力状态、代码来源、产品定位、证据和上游策略
> 适用版本：Seafile CE 14 参考基线，当前 `dev` 代码
> 当前状态：有效；状态按代码、配置、测试和已记录验证保守判定

状态含义：**已完成**表示当前范围有实现及可复现验证；**验证中**表示实现存在但当前
环境、组件版本或端到端覆盖仍有限；**部分完成**表示只有定义范围的一部分可用；**规划**
表示没有可确认实现；**待确认**表示证据不足。门禁文件存在不等于门禁已经成功运行。

实现策略是先复用 Seafile 已有可用模块，再用可关闭扩展补齐缺口。每项能力先形成覆盖
权限、数据、配置、故障和验证的完整 MVP，再持续改进界面、兼容范围和运维自动化。

| 功能名称 | 当前状态 | 代码来源 | 改动范围 | 产品定位 | 主要依赖 | 证据 | 上游策略 | 重要说明 |
|---|---|---|---|---|---|---|---|---|
| CE 14 源码构建与扩展基线 | 已完成 | 复用 Seafile CE；本项目新增构建/配置 | 部署、配置、构建 | CE 补强 | Docker、锁定的上游提交 | [`release.yaml`](../release.yaml)、[`build-and-e2e.yml`](../.github/workflows/build-and-e2e.yml)、[`smoke.py`](../tests/e2e/smoke.py) | 拆分后 PR | 当前无正式 CE 14 镜像；不能把上游预览功能算作扩展版交付。通用构建修正可拆分，CloudFile 发布清单保留内部。 |
| 扩展注册与功能开关 | 已完成 | 扩展版既有代码；少量上游注入点 | 前端、后端、配置 | CE 补强 | Django、seafile-server RPC | [`cloudfile_ext/apps.py`](../../cloudfile-hub/cloudfile_ext/apps.py)、[`cf-ext.c`](../../cloudfile-server/common/cf-ext.c)、[`baseline.py`](../tests/e2e/baseline.py) | 拆分后 PR | 无 provider 时必须透传 CE；可提取通用 hook/registry 设计，CloudFile 命名和产品开关不提交。 |
| 目录级 ACL | 已完成 | 本项目新增 Hub/C 实现；复用 CE 库权限和组 | 前端、后端、数据结构 | Pro 平替 | `cf_dir_acl`、Seafile 身份/组 | [`acl-semantics.md`](acl-semantics.md)、[`acl-cases.json`](acl-cases.json)、[`acl-e2e.yml`](../.github/workflows/acl-e2e.yml) | 不适合 PR | 目标接近细粒度目录权限；当前证据不构成与 Pro 完全兼容。权限终判必须覆盖 Web、同步和 WebDAV。 |
| Authentik 登录入口 | 部分完成 | 复用 CE OAuth2/OIDC；本项目新增配置翻译；Authentik 提供协议/身份源适配 | 配置、部署、外部服务 | CE 补强 | Authentik 2026.5.6、Seahub OAuth2/OIDC | [`bootstrap.py`](../scripts/scripts_14.0/bootstrap.py)、[`seahub/oauth/`](../../cloudfile-hub/seahub/oauth/)、[认证说明](features/sso-authentik.md) | 拆分后 PR | 默认采用通用 OIDC Authorization Code，不开发专用协议；仓库仍缺 Authentik 登录、登出和恢复 E2E。生产固定稳定补丁版本，不使用 `latest`。 |
| 组织与组同步 | 已完成 | 本项目新增；复用 CE 组与登录信号 | 后端、数据结构、worker | Pro 平替 | `cf-worker`、目录 provider、`cf_sso_*` | [`cloudfile_ext/sso/`](../../cloudfile-hub/cloudfile_ext/sso/)、[`sso_matrix.py`](../tests/e2e/sso_matrix.py)、[`sso-e2e.yml`](../.github/workflows/sso-e2e.yml) | 不适合 PR | 已验证 `static` 目录语义；`external-service` 有代码和单测。LDAP/AD/Authentik 目录源未做专属 provider 验证。只同步已存在用户的组关系。 |
| 目录/文件操作日志（提交变更） | 验证中 | 本项目新增查询/UI；复用 CE/seafevents 事件 | 前端、后端、外部服务 | Pro 平替 | seafevents `Activity` | [操作日志](features/audit.md)、[`cloudfile_ext/audit/`](../../cloudfile-hub/cloudfile_ext/audit/)、[`audit_matrix.py`](../tests/e2e/audit_matrix.py)、[`audit-e2e.yml`](../.github/workflows/audit-e2e.yml) | 不适合 PR | 当前 E2E 验证目录创建/重命名和文件上传的查询；文件/目录移动、删除、恢复与各协议仍待逐项验收。不覆盖读取/下载访问日志、合规审计、不可抵赖或长期留存。 |
| 文件属性与多视图 | 验证中 | 复用 CE 前端/API/seafevents；复用官方 metadata-server；本项目新增部署配置 | 前端、后端、部署、外部服务 | CE 补强 | `seafile-md-server`、Redis、JWT | [`metadata-e2e.yml`](../.github/workflows/metadata-e2e.yml)、[`metadata_matrix.py`](../tests/e2e/metadata_matrix.py)、[`bootstrap.py`](../scripts/scripts_14.0/bootstrap.py) | 待确认 | `cloudfile_ext/metadata` 当前无自主存储实现。示例使用官方 testing tag，生产兼容性和稳定 tag 待确认。 |
| 目录/文件标签机制 | 验证中 | 复用 CE `repo_metadata`、`repo_tags`/`file_tags` 前端与 API；复用官方 metadata-server；本项目新增部署配置 | 前端、后端、部署、外部服务 | CE 补强 | `seafile-md-server`、Redis、JWT | [标签机制](features/tags.md)、[`metadata_matrix.py`](../tests/e2e/metadata_matrix.py)、[`repo_metadata/`](../../cloudfile-hub/seahub/repo_metadata/)、[目录表格前端](../../cloudfile-hub/frontend/src/components/dir-view-mode/dir-table-view/index.js) | 拆分后 PR | 旧 `FileTags` 只证明文件标签；元数据记录与目录表格提供了目录/文件统一绑定通路，但当前 E2E 只创建和读回标签定义，尚未验证绑定、移动跟随、恢复、权限和稳定镜像。 |
| 全文检索 | 部分完成 | 复用 CE/SeaSearch；可选本项目 Meilisearch provider 和索引器 | 前端、后端、worker、外部服务 | Pro 平替 | SeaSearch 或 Meilisearch | [`cloudfile_ext/search/`](../../cloudfile-hub/cloudfile_ext/search/)、[`search-e2e.yml`](../.github/workflows/search-e2e.yml)、[`search_matrix.py`](../tests/e2e/search_matrix.py) | 不适合 PR | 解开 Pro API 门控不适合提交；Meilisearch 仅提取通用 provider seam 后才可能讨论。SeaSearch 与 ACL `invisible` 过滤存在已知边界。 |
| 原生预览入口 | 验证中 | 复用 CE 预览；本项目新增动作选择和兼容补丁 | 前端、后端 | CE 补强 | Seahub 预览组件 | [`file_actions/`](../../cloudfile-hub/cloudfile_ext/file_actions/)、[`local-professional-software.md`](../../cloudfile-hub/docs/local-professional-software.md) | 拆分后 PR | CloudFile 不实现渲染器；格式覆盖与 Seafile CE 14 上游预览能力一致，预览版新增格式不能自动计入。 |
| OnlyOffice 在线编辑 | 部分完成 | 复用 CE/OnlyOffice 集成；本项目新增回调校验与锁协同 | 前端、后端、外部服务 | Pro 平替 | OnlyOffice Document Server、JWT、文件锁 | [`cloudfile_ext/office/`](../../cloudfile-hub/cloudfile_ext/office/)、[`docker-compose.yml`](../deploy/compose/docker-compose.yml) | 不适合 PR | 当前有回调与单测，缺少完整生产协议面和当前提交的容器级验收结论；不能声称与 Pro 在线编辑等价。 |
| 文件锁与签入签出 | 部分完成 | 本项目新增租约/终判；复用 CE 文件操作 | 前端、后端、数据结构 | Pro 平替 | 写入生命周期、`cf_lock_lease` | [`cf-lock.c`](../../cloudfile-server/common/cf-lock.c)、[`file_actions/`](../../cloudfile-hub/cloudfile_ext/file_actions/)、[`fileop-lifecycle.md`](fileop-lifecycle.md) | 不适合 PR | 文件锁已有底层实现；签入签出入口与覆盖仍不完整。目标接近 Pro 能力，但客户端兼容、恢复和锁语义未证明等价。 |
| 本地应用查看与编辑 | 验证中 | 本项目新增 Hub 会话；已创建独立项目 `cloudfile-local-agent`、`cloudfile-chrome-extension`；复用 CE 下载/写回 | 前端、后端、外部应用 | 新应用扩展 | Native Messaging、已安装桌面软件 | [`cloudfile-local-agent`](../../cloudfile-local-agent/README.md)、[`cloudfile-chrome-extension`](../../cloudfile-chrome-extension/README.md)、[`file_actions/`](../../cloudfile-hub/cloudfile_ext/file_actions/) | 不适合 PR | 两个客户端项目已经独立存在，但仍缺签名发布包、跨平台升级和完整下载—编辑—写回 E2E。 |
| 关注、转换与导出 | 部分完成 | 主要复用 CE/SeaDoc；本项目新增配置和 UI 接线 | 前端、部署、外部服务 | CE 补强 | 邮件任务、SeaDoc 2.0、JWT | [`.env.example`](../deploy/compose/.env.example)、[`docker-compose.yml`](../deploy/compose/docker-compose.yml)、Hub 前端补丁登记 | 拆分后 PR | 不应包装为自研渲染或转换；各格式和写回流程尚未形成独立 E2E 结论。通用 CE UI 修正可单独评估。 |
| 多存储与 S3 兼容存储 | 已完成 | 参考官方存储模型；本项目新增 CE C/Go 后端、部署、迁移和维护；MinIO 提供 S3 | 后端、部署、配置、数据结构 | Pro 平替 | MinIO、`RepoStorageId` | [存储说明](features/storage-backends.md)、[`storage-e2e.yml`](../.github/workflows/storage-e2e.yml)、[`storage_matrix.py`](../tests/e2e/storage_matrix.py) | 不适合 PR | 支持管理员为不同资料库指定存储方案；新建库自助选择/自动分配 UI 尚未完成。S3 兼容性当前只验证 MinIO，不承诺其他实现。 |
| SMB/NFS 外部资料源 | 部分完成 | 本项目新增入口、授权、影子路由、扫描/Overlay；宿主机和协议栈负责挂载 | 前端、后端、部署、外部存储 | 新应用扩展 | 宿主机 SMB/NFS mount、可选 Meilisearch | [外部资料源](features/external-sources.md)、[`external_sources/`](../../cloudfile-hub/cloudfile_ext/external_sources/)、[`external_sources-e2e.yml`](../.github/workflows/external_sources-e2e.yml) | 不适合 PR | 当前 `local-path` 为只读内容入口；不是 Seafile 原生资料库，桌面同步、WebDAV、历史和锁不适用。 |
| CloudFile 外部资料联邦与虚拟目录挂载 | 规划 | 计划独立项目；复用 OpenList/rclone 适配外部存储；CloudFile 负责消费接口 | 外部服务、部署、前端、后端 | 新应用扩展 | OpenList、rclone | [规划说明](features/external-directory-mount.md)；当前仓无匹配代码/配置/测试 | 不适合 PR | 模块计划同时为 AI 应用提供统一文件资料库、为 CloudFile 提供虚拟目录挂载。它不同于 Seafile 虚拟资料库和现有 `local-path`；模式均未实现。 |
| Seafile AI 与外接 LLM | 验证中 | 复用官方 Seahub/Seafile AI；本项目新增 Compose profile 与配置接线；模型由外部 LLM 提供 | 部署、配置、外部服务 | CE 补强 | `seafile-ai`、Metadata Server、Redis、OpenAI-compatible/local LLM | [AI 说明](features/seafile-ai.md)、[`docker-compose.yml`](../deploy/compose/docker-compose.yml)、[`.env.example`](../deploy/compose/.env.example) | 不适合 PR | `ai` profile、官方镜像和 `CF_AI_*` 配置已存在，但当前仓无容器 E2E 结果。CloudFile 不自研模型或平行 AI 后端。 |

## 复用与新增的关键结论

- OAuth2/OIDC 登录、SAML、LDAP、元数据 UI/API、预览及部分文件管理来自 Seafile CE；
  CloudFile 的贡献主要是配置、扩展接线或缺失的组织/权限逻辑。
- S3/多存储采用 Seafile 官方文档描述的存储类与 `RepoStorageId` 模型，但当前锁定 CE
  上游提交中没有 CloudFile 新增的 C/Go 后端实现，不能简单写成“直接启用官方 CE 代码”。
- Authentik、MinIO、Meilisearch、OnlyOffice、OpenList 和 rclone 的协议、存储、检索或
  渲染能力归各自项目；CloudFile 只拥有其配置、接口和产品集成部分。
- AI 默认复用官方 Seafile AI，并由运维从 [`seafile_ai_config.example.yaml`](../deploy/compose/seafile_ai_config.example.yaml) 创建运行时配置以外接 LLM；未来外部资料联邦
  只能作为新的资料入口，不能被描述为当前 AI 已有能力。
- “Pro 平替”是内部目标分类。所有相关行都保留了未验证的等价性、兼容性或运维限制。

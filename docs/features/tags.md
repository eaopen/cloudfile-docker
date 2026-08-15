<!-- generated-by: gsd-doc-writer -->
# 目录/文件标签机制

> **用途**：说明 CloudFile 复用的 Seafile CE 标签数据模型、目录与文件的实现边界及 MVP 验收缺口。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：验证中；CE 前端、API 和 Metadata Server 数据通路存在，当前容器门禁只验证标签定义的创建与读回，尚未验证目录/文件绑定全链路。P2-07 已在 `repo-tags` 上落地系统/用户标签分类、批量上限与权限校验。
> **边界**：CloudFile 不建立平行标签存储；默认复用 CE `repo_metadata`、`repo_tags`/`file_tags` 与官方 Metadata Server。

## 现有实现

CE 14 中同时保留两类标签数据通路：

1. `RepoTags` / `FileTags` 是旧的资料库标签和文件绑定模型，以文件路径与 UUID 为主，不能作为目录标签的证据。
2. `repo_metadata` 将标签定义存入标签表，通过 Metadata Server 的记录链接关联到元数据记录。元数据记录包含 `_is_dir`，目录表格前端也会将目录和文件的 `record_id` 交给同一标签更新接口。

第二条通路提供了目录/文件统一标签的实现基础，但接口仍命名为
`file-tags`，而且当前锁定的 Metadata Server 镜像尚无目录绑定端到端结论。
因此不能仅根据 `_is_dir` 字段或前端入口将“目录标签”判定为已完成。

## 系统/用户标签（P2-07）

评审清单要求标签区分「系统标签」与「用户标签」：系统标签由管理员配置、普通用户只读并带锁形图标；
用户标签由「对象编辑＋标签编辑」权限的用户维护；展示顺序为「用户标签 → 系统标签」；批量加标签有单次上限。

在 CloudFile 里这套语义落在 CE 的 `repo_tags` 通路（`repo_tags_repotags` 表），不另建平行存储：

| 项 | 实现 |
|---|---|
| 标记 | `RepoTags.is_system` 布尔列（`seahub/repo_tags/models.py`），`to_dict()` 返回 `is_system`；列由 docker bootstrap `apply_tag_schema_compatibility()` 幂等补齐，不编辑上游 SQL |
| 权限 | 系统标签变更仅 `admin`（`is_repo_admin`）可用；用户标签编辑需 `rw` 及以上；`r` 用户与普通用户改系统标签返回 403。开关关闭时保持原生 CE（写入仍需 `rw`） |
| 批量上限 | 单次 `PUT /repo-tags/` 携带标签数受 `CF_TAG_BATCH_LIMIT`（默认 100）约束，超出返回 400 |
| 展示顺序 | `GET /repo-tags/` 先用户标签后系统标签（`order_by('is_system', 'id')`） |
| 开关 | 全部逻辑以 `CF_ENABLE_TAGS` 为门；关闭时行为与原生 CE 一致（见 `seahub/api2/endpoints/repo_tags.py`） |

权限口径沿用 [roles-semantics.md](roles-semantics.md) §6：系统标签 = 仅 `admin`，用户标签 = `rw` 及以上，
不引入五级角色。

可执行验收是 [`review-tags-cases.json`](review-tags-cases.json) 与
[`review_tags_matrix.py`](../tests/e2e/review_tags_matrix.py)（api 用例 tags-001～tags-005），
由 [`review-tags-e2e.yml`](../.github/workflows/review-tags-e2e.yml) 在开启 `CF_ENABLE_TAGS` 的
容器门禁中执行。锁形图标、折叠展示与「点击不弹关联列表」仍是浏览器用例（channel: `ui`），留待浏览器套件。

## 数据与故障边界

- 标签定义、层级关系和记录链接由 Metadata Server 保存；CloudFile 只提供部署、配置和验收。
- Metadata Server 或 Redis 不可用时，标签和元数据操作应显式失败，不得影响资料库的核心文件读写。
- 标签不是 Seafile 目录 ACL；通过标签查询或视图返回记录时，仍必须依赖资料库和目录权限裁剪。
- 现有更新接口使用 `can_read_metadata` 作为授权条件；“可读者是否可修改标签”必须作为 MVP 权限策略单独验证，不能从页面按钮推导。
- 同步客户端传递文件内容和目录树，不等于客户端已支持标签管理。

## 当前证据

| 能力 | 代码证据 | 当前验证 |
|---|---|---|
| 启用元数据和标签表 | `seahub/repo_metadata/`、`metadata_matrix.py` | 已验证启用状态 |
| 创建与读取标签定义 | `MetadataTags` | 已纳入容器门禁 |
| 文件绑定与反向查询 | `MetadataFileTags`、`MetadataTagFiles` | 有实现，当前门禁未绑定文件 |
| 目录绑定 | `_is_dir`、目录表格 `record_id` 更新 | 有实现通路，无容器 E2E 结论 |
| 重命名/移动/恢复后保留 | 依赖 Metadata Server 的记录同步 | 未验证 |
| 权限和隐藏目录裁剪 | Hub 元数据 API 的权限处理 | 未形成目录/文件标签专项门禁 |
| 系统/用户标签分类与权限 | `repo_tags/models.py`、`api2/endpoints/repo_tags.py` | `review_tags_matrix.py` tags-002～tags-004（P2-07） |
| 批量加标签上限 | `CF_TAG_BATCH_LIMIT`（默认 100） | `review_tags_matrix.py` tags-005（P2-07） |

## MVP 验收清单

1. 同一资料库创建标签，分别绑定到文件和目录，通过列表、详情和按标签反查读回。
2. 重命名和同库移动目录/文件后标签保留；删除、回收站恢复与永久删除的链接语义明确。
3. 只读、可写、目录 ACL 与隐藏目录的查询/更新结果符合产品策略。
4. Metadata Server 不可用、超时或返回部分结果时，错误可观测且不破坏文件读写。
5. 固定可发布的 Metadata Server 镜像，验证 schema 升级、备份恢复以及旧 `FileTags` 数据的兼容或迁移策略。

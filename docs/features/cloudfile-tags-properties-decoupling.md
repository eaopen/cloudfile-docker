# CloudFile 标签与扩展属性从 Metadata Server 解耦（规划）

> 状态：设计方案，未实现、未验收；当前 `CF_ENABLE_TAGS` 仍要求 `CF_ENABLE_METADATA`，Compose 仍默认启动 Metadata Server。目标规模约 10 个资料库、每库 100–200 万文件、500 GB–2 TB。

## 目标与非目标

CloudFile 自己的文件/目录标签、少量业务属性以 Seahub 数据库为主存储，不再要求每个文件都进入 Seafile Metadata Server。官方 Metadata Server **保留**，继续支撑原生 `repo_metadata` 的 Table/Kanban/Gallery/列/链接及依赖它的 AI 功能；其 `MD_FILE_COUNT_LIMIT` 仍约束这些官方高级元数据能力，但不应约束 CloudFile 核心标签、属性和独立搜索入口。Seafile 的文件树、内容、版本、权限仍由 Seafile 负责，CloudFile **不创建 `cf_md_record`，不复制全量文件目录树**。[官方文档](https://manual.seafile.com/14.0/extension/metadata-server/)当前将 `MD_FILE_COUNT_LIMIT` 默认设为每库 10 万文件。

| 层 | 唯一真相 | 关系 |
|---|---|---|
| Seafile Core | 文件/目录、路径、大小、mtime、commit、ACL | CloudFile 按需解析，不持久化整棵树 |
| CloudFile Extension | Seahub 现有 `RepoTags`、`FileTags`、`FileUUIDMap`，及必要的稀疏业务属性表 | 只为有扩展数据的资源建立关联 |
| Seafile Advanced Metadata | 官方 Metadata Server | 原生 `repo_metadata` 页面/API 保持独立，不强行兼容或替换 |
| Search Projection | Meilisearch | 从 Seafile 基础信息 + Seahub 扩展数据生成；可重建、非主存储 |
| Cache / Events | Redis | 缓存失效、异步工作分发；不可作为唯一事件记录 |

首版复用当前 MariaDB 11.4，不新增 PostgreSQL 部署。这里的目标不是创建新元数据主库：若未来确需 PostgreSQL，应作为独立评估，不把 Seahub 原生标签表无证明地跨库迁走。

## 最小修复：先让现有文件标签独立可用

代码核对表明，无需先实现业务属性、目录标签或新的 metadata 服务，就能做一个可验证的 **M0 文件标签解耦**：

| 位置 | 最小改动 | 原因 |
|---|---|---|
| `scripts/scripts_14.0/bootstrap.py` | 删除 `CF_ENABLE_TAGS=true && CF_ENABLE_METADATA=false` 的启动拒绝；`CF_ENABLE_METADATA` 仍只控制官方 `ENABLE_METADATA_MANAGEMENT` | 当前硬耦合在此；原生 `ENABLE_FILE_TAGS=True` 已单独存在 |
| `seahub/repo_tags/models.py`、`seahub/file_tags/models.py` | 继续用 `RepoTags → FileTags → FileUUIDMap`，不建新标签表；补重复关联约束/索引前先清点存量数据 | 现有文件标签 API 和目录列表已经走这条 SQL 链 |
| `seahub/api2/endpoints/file_tag.py` | 写入/删除按目标路径检查 ACL，核对 `RepoTags.repo_id`、`FileUUIDMap.repo_id` 与请求库一致，并验证资源真实存在 | 当前实现主要检查根目录权限；按 ID 删除时缺目标库匹配，不可原样扩大使用 |
| `seahub/api2/endpoints/repo_tags.py` | `include_file_count` 改数据库 `GROUP BY repo_tag_id` 聚合，避免把整库 `FileTags` 逐行装入 Python | 百万级关联下现有计数路径线性耗内存和请求时间 |
| `frontend/src/hooks/metadata-status.js`、`frontend/src/features/library-view/dir-settings-view/`、`frontend/src/components/dirent-detail/` | 官方 `enableTags` 只表示 Metadata Server 标签；CloudFile 文件标签使用已有 `enableFileTags`/`repo-tags`/`file-tags` 入口，并在官方 metadata 开启时仍可独立显示，清楚标注两者 | 当前文件详情以 `!enableMetadata` 隐藏旧标签，设置页的 Tags 开关则直接调用 `/metadata/tags-status/` |

**不要改写** `MetadataTagsStatusManage`、`RepoMetadata.tags_enabled` 或 `/metadata/tags-status/` 为 SQL 标签开关：它们还负责官方标签表初始化/删除，前端 `DirTags`/`useTags` 消费的是 Metadata Server 的记录/层级 API，直接换存储会形成部分成功、部分报错。M0 不承诺官方 Table/Kanban 中出现 CloudFile 标签，也不把“旧标签迁移到官方标签”的按钮反向复用。对于不需要按库启停的部署，沿用现有全局 `CF_ENABLE_TAGS`（CloudFile 系统/用户标签规则）和原生 `ENABLE_FILE_TAGS` 即可；若产品必须保留**每库开关**，再加一个独立的最小状态表/API，不能借用 `RepoMetadata.enabled/tags_enabled`。要注意 `CF_ENABLE_TAGS` 目前只是 CloudFile 规则门禁，并非原生标签功能的总开关。

M0 的测试配置是 `CF_ENABLE_TAGS=true`、`CF_ENABLE_METADATA=false`，并在**不启动** `cloudfile-metadata` 时完成创建标签、文件绑定/解绑、目录列表和详情读回、权限拒绝；标签检索另以现有 `CF_ENABLE_SEARCH=true` + `db-tags` 降级路径验证，不要求 Meilisearch。还要验证官方 metadata 页面明确不可用而非静默落到旧标签。默认部署与现有官方高级元数据功能先不改。M0 必须测同步客户端/WebDAV 的重命名、移动、删除与恢复：`FileUUIDMap` 的路径跟随尚未证明完整，不能因为 SQL 标签读写通过就宣布迁移完成。

## 代码核对后的存储选择

1. `seahub/repo_tags/models.py::RepoTags` 已是按资料库定义的标签，含 CloudFile 增加的 `is_system`。保留它作为 CloudFile 标签定义；不新增平行 `cf_tag`。原有系统/用户权限、排序和批量上限继续有效。
2. `seahub/file_tags/models.py::FileTags` 通过 `FileUUIDMap` 关联标签，并非讨论稿假设的 `repo_id + path + tag_id` 独立表。`seahub/tags/models.py::FileUUIDMap` 是**稀疏的现成 UUID→路径映射**，含 `is_dir`；但 `FileTags` 的现有 manager/API 写死 `is_dir=False`，所以今天这条通路只支持文件。
3. 旧 `seahub/tags/models.py::Tags/FileTag` 使用同一 `FileUUIDMap`，已支持目录，却有另一套全局标签定义。检索后端目前同时读取新旧两套标签。`revision_tag` 是提交版本标签，`related_files` 是资源关联，不能混作 CloudFile 业务标签。
4. V1 优先让 `FileTags` 对 `is_dir=True` 的 `FileUUIDMap` 建立绑定，并在服务层抽象 `ResourceTagService`；先评估现有模型、API 与索引的兼容性。**不预设新增 `DirTags`**。只有现有 `FileTags` 的约束或升级兼容性证明无法安全扩展时，才引入单独目录绑定表，并写清与 `FileTags` 的映射。
5. `FileUUIDMap` 当前按父路径 MD5 + 文件名 + 类型查找，模型未声明组合唯一约束，查询也未核对完整 `repo_id/parent_path`；不能把 MD5 当作无碰撞身份。实现前先盘点重复行、虚拟库 origin 路径映射、现有移动/重命名维护者，再补精确比较、并发去重及回归。其 UUID 可用于稀疏绑定，但**不能假设已经可靠跟随所有协议的移动**。

业务属性也只存 Seafile 没有的值：建议 `cf_property_definition(repo_id, key, type, ... )` 与 `cf_resource_property(file_uuid, property_id, typed_value, ...)`；字段定义按库，值按稀疏 `FileUUIDMap` 关联。不要把 name/size/mtime/obj_id 再复制到 SQL 主表；这些只出现在查询时的 Seafile 回填或 Meilisearch 投影。属性需要类型校验、权限、可筛选/可排序白名单、唯一约束及审计。无标签、无属性的文件在 **CloudFile 新增属性/绑定表** 中应为零行（其他 Seahub 功能仍可能创建 `FileUUIDMap`）；实际行数取决于标注率，不能把“15% 标注”当成已测事实。

## CloudFile 与官方界面/API 分流

保留 `/metadata/...`、`MetadataServerAPI`、官方标签树和视图的现有行为；它们不会自动读到 CloudFile 的 `RepoTags/FileTags`。CloudFile 核心标签使用现有 `/repo-tags/`、`/file-tags/`，目录入口新增或扩展明确的 `resource-tags` API；业务属性使用 CloudFile 命名空间。前端应显式区分“CloudFile 标签/属性”与“官方高级元数据”，不得在同一控件内暗示两套标签自动同步。若产品要求 Table/Kanban 直接显示 CloudFile 标签，另立桥接需求，明确映射、方向和一致性成本。
扩展 API 必须核对目标路径实际存在、标签 `repo_id` 与请求资料库一致，并对目标路径执行目录 ACL 和写权限判定；不能只检查资料库根目录权限。现有文件标签端点有根目录权限检查和按 ID 查标签的路径，迁移时要专项审计跨库绑定/删除和隐藏目录访问，不能直接继承其安全假设。

目前 `bootstrap.py` 的 `CF_ENABLE_TAGS => CF_ENABLE_METADATA` 是**实存耦合**。实施时须将 CloudFile 标签开关与官方元数据开关分离（保留旧环境变量的兼容迁移策略），确保关闭 Metadata Server 后 CloudFile 标签 API、目录显示和标签检索仍可工作；官方高级元数据入口在关闭时明确不可用。只改 Compose 中的依赖声明不够，Hub API、前端门禁与回归用例也要同步检查。

## 文件变更跟随与稀疏身份

外部调用仍以 `(repo_id, path, is_dir)` 定位，内部用已有 `FileUUIDMap.uuid` 连接标签/属性；不建立每文件一行。Seafile rename/move/delete/restore 后，维护**仅有扩展数据的映射**，不扫写无标注文件。单文件移动更新一条映射；目录移动需批量更新目录自身以及其下有扩展数据的路径映射，工作量与被标注后代数相关而非整个文件数，但仍可能很大。复制产生新资源，不自动共享原 UUID；复制标签/属性是否继承必须定义产品规则。删除、回收站恢复和同路径新文件的绑定语义必须明确，不能让旧标签误附新对象。

`cf-worker` 可用现有 Activity 流做快速通知，但它是否完整表达同步客户端、WebDAV、批量移动及恢复，需要逐项验证；可靠恢复应以 Seafile commit/head 与差异核对为准，按库保存 SQL 检查点并提供全量核对命令。事件处理幂等，路径变更与检查点在同一数据库事务提交；Redis Streams 负责分发和重试，不充当无法重建的唯一日志。若发现 `FileUUIDMap` 已由上游链路维护移动，应复用并消除双重写入，而不是再造第二套跟随器。

目录标签继承只在目录自身保存一份显式绑定，不向后代 SQL 表复制百万行。详情读取时查询祖先标签并用带版本/路径的 Redis 缓存加速；目录移动、标签变化须失效相关缓存。注意这只保证**主库稀疏**，不自动保证搜索侧便宜：若要求 Meilisearch 对百万后代的“继承标签”提供实时过滤与精确 facet，仍需大量索引更新或另一种查询策略。V1 先把显式标签、属性做精确检索/facet；继承标签的搜索与计数另列性能门禁，未通过前不宣称实时、精确支持。

## Meilisearch 投影、权限与缓存

现有 `cloudfile_ext/search` 已有统一文件索引、Activity 增量索引器和内置 `db-tags` 降级路径。扩展同一索引/查询入口：Seafile 提供文件基础字段，Seahub 的 `FileTags`、旧 `FileTag` 和新属性提供扩展字段；目录标签若进入搜索，则索引器须新增目录文档或单独查询路径。对 1,000–2,000 万文件而言，**SQL 可保持稀疏，但 Meilisearch 若覆盖全量搜索仍需相应规模的文档**，须单独做磁盘、内存、初建和重建容量测试。现有索引器仅处理增量 Activity，不能代替历史文件全量回填。

属性/标签写入与持久化 outbox 同事务提交；索引 worker 批量投递，确认 Meilisearch 异步任务成功后前移投影检查点。Redis 可做队列、缓存和失效通知，丢失时从 SQL outbox 或 Seafile 检查点补发。标签/属性可立即从 SQL 读回，搜索结果允许有界延迟并暴露落后指标；Meilisearch 故障不阻塞 Seafile 文件读写，也不得静默返回“无结果”冒充正确答案。

搜索入口必须先限定可访问资料库，再对每条候选按实时目录 ACL 复核；Meilisearch 不直连浏览器。**查询后裁剪不足以保护 facet 计数**：只有可在索引过滤器中完整表达权限的范围才可直接返回 Meilisearch 分布；否则禁用/标注近似计数，或在已授权集合上由服务端精确计算，避免借计数推断隐藏目录。动态属性成为 `filterableAttributes` 前须做白名单与版本化索引设置，避免字段变更触发不可控全量重建。

## 迁移、阶段与验收

1. **契约盘点**：统计 `RepoTags`、`FileTags`、旧 `Tags/FileTag`、`FileUUIDMap` 的真实行数、重复/孤儿与路径跟随；列出当前页面/API 对官方 `/metadata` 的依赖，选定 CloudFile 核心标签入口。固定文件、目录、虚拟库、ACL、标签搜索的现有回归结果。
2. **稀疏主存储**：先在测试库让 `FileTags` 支持目录并保持旧文件 API 返回契约；实现属性定义/值、路径映射去重、目录移动/删除/恢复跟随及权限。仅当现有表无法安全承载目录时才添加 `DirTags`。
3. **开关解耦**：移除 CloudFile 标签对 `CF_ENABLE_METADATA` 的运行前置，保留官方高级元数据开关；分别验证四种开关组合。当前默认部署不在这一阶段前改变。
4. **投影与回填**：复用现有 Meilisearch provider，新增标签/属性变化事件和 Seafile 文件树全量回填；验证独立的 `db-tags` 降级路径、索引重建、延迟与权限/facet 边界。
5. **数据迁移**：保持现有 `RepoTags/FileTags` 不搬家；按产品决定是否将旧 `Tags/FileTag` 统一到该通路，必须保留名称/颜色/系统分类与关联的可追溯映射。官方 Metadata Server 的标签/自定义列**不自动迁移**；若其中有 CloudFile 必需的业务数据，逐库导出、冲突判定、校验后导入，不能仅从 Seafile 文件树恢复用户自定义值。
6. **逐库试点**：先在一个百万文件库证明标签、目录、属性、移动/恢复、ACL、搜索和索引追赶，再扩大至约 10 库。官方 Table/Kanban/Gallery/AI 的回归必须保持通过；不停止 `cloudfile-metadata`，也不把它的数据删除。

验收除功能正确性外，应分别记录：SQL 扩展行数与标注率、百万文件目录移动中需更新的映射数、Seafile 事件/检查点追赶、Meilisearch 全量文档及磁盘量、索引重建时间、Redis pending/失败重试、搜索与 facet 延迟、隐藏目录信息泄漏。对继承标签的大目录变更单独验收；若无法满足实时精确 facet，要明确降级语义而不是以缓存掩盖。

参考：[官方 Metadata Server 与文件数上限](https://manual.seafile.com/14.0/extension/metadata-server/)、[Meilisearch facet/filter](https://www.meilisearch.com/docs/capabilities/filtering_sorting_faceting/how_to/filter_with_facets)、[Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/)。

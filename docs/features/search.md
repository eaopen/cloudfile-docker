# 检索

> 用途：说明当前 SeaSearch/Meilisearch 路径、权限边界和验证状态
> 适用版本：Seafile CE 14 参考基线
> 当前状态：部分完成

`CF_ENABLE_SEARCH` 解开当前 CE 源码中两个受 Pro 判断限制的查询入口，并启用检索配置。
`CF_PROVIDER_SEARCH` 留空时复用 Seafile/SeaSearch 的索引和查询链；设为 `meilisearch` 时，
CloudFile 注册 provider，并由 `cf-worker` 增量构建索引。

| 部分 | 代码来源 | 边界 |
|---|---|---|
| Search API 与页面 | 复用 Seafile CE；CloudFile 影子路由绕过 Pro gate | 属 Pro 平替目标，不适合直接上游 PR |
| SeaSearch | 上游/官方组件 | CloudFile 只写配置，不拥有检索引擎 |
| Meilisearch | 外部开源服务 | CloudFile 新增 provider、索引器和权限过滤 |

当前 E2E 定义了 SeaSearch、切换 Meilisearch 和关闭后恢复原生状态三阶段。目录 ACL 与
检索同时启用时，两条路径在结果集上统一做查询后裁剪：`invisible` 与 `none` 规则命中的
文件不出现在检索/元数据结果中（复用 `cloudfile_ext.acl` resolver，加载失败按隐藏处理，
即 fail closed）。这补齐了上游 `is_invisible_path` 只覆盖原生 invisible 共享、不覆盖
目录 ACL 的缺口，且不依赖上游修复。

高级筛选（类型/位置/标签/创建人/时间/大小）走同一 `/api2/search/` 入口：类型、位置、
时间、大小由上游参数（`obj_type`/`search_path`/`time_from`/`size_from`）直接表达；标签与
创建人由 `tags`/`creator_emails` 参数转换为结构化过滤器（`cloudfile_ext.search_query`）交给
provider。Meilisearch 索引同时写入 `tags` 与 `creator` 字段，`tags` 参与检索，于是"标签名
命中"与"文件名命中"可区分：provider 请求 `attributesToHighlight=['tags']` 并把高亮命中
还原成 `matched_tags` 返回，前端据此显示"匹配标签"徽标，避免把标签命中误报为名称命中。

Meilisearch 文本提取只覆盖配置允许的纯文本和大小上限，不能替代 SeaSearch 的文档格式
解析。外部资料源索引只在 Meilisearch provider 下运行，索引故障不应阻塞原生资料库访问。

证据：`cloudfile-hub/cloudfile_ext/search/`、`cloudfile-docker/tests/e2e/search_matrix.py`、
`./tools/verify-local.sh cap search`。旧的方案比较和排期已移入[历史索引](../history/README.md)。


## 无外部索引时的降级：内置 db-tags 后端（2026-09-12）

外网/内网部署不一定有 Elasticsearch 或 Meilisearch，但"按标签找文件"不应因此不可用：
标签到路径的映射本来就在 Seahub 自己的表里（v2 `file_tags_filetags` / legacy `tags_filetag`
→ `tags_fileuuidmap`），是一个 join，而不是一次全文检索。

因此 `cloudfile_ext/search/backends/dbtags.py` 注册为内置 provider `db-tags`：

| 场景 | 行为 |
|---|---|
| `CF_PROVIDER_SEARCH=meilisearch` | 走 Meilisearch（含全文）；`db-tags` 不被使用 |
| `CF_PROVIDER_SEARCH=''` + `CF_SEARCH_DB_FALLBACK=True`（默认） | 纯全文请求 → 501（提示需索引 provider）；带 `tags=`/`creator_emails=` → **内置后端作答** |
| `CF_PROVIDER_SEARCH=''` + `CF_SEARCH_DB_FALLBACK=False` | 结构化过滤显式拒绝（不静默丢条件） |
| `CF_PROVIDER_SEARCH=db-tags` | 显式选中内置后端（等价于上一行的可查询路径） |
| 已配置 Elasticsearch/SeaSearch | 原生分支优先，降级不劫持 |

能力边界（写进文档是为了避免误解）：`keyword` 在标签命中集合内按名称/路径子串匹配；
`size_range`/`time_range` 需要 dirent，内置后端仅在候选数可控时逐条解析（超过 500 条显式拒绝）；
内容（正文）检索仍只有索引 provider 能做。两类标签都覆盖：v2 系统标签与 legacy 用户标签（后者含目录）。

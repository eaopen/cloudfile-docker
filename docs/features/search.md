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

当前 E2E 定义了 SeaSearch、切换 Meilisearch 和关闭后恢复原生状态三阶段。仍需保守处理
目录 ACL：上游 SeaSearch 分支没有执行与 ES/Meilisearch 分支相同的 `invisible` 路径过滤；
ACL 与检索同时启用时应使用已经接入权限裁剪的路径，或先补齐上游通用修正。

Meilisearch 文本提取只覆盖配置允许的纯文本和大小上限，不能替代 SeaSearch 的文档格式
解析。外部资料源索引只在 Meilisearch provider 下运行，索引故障不应阻塞原生资料库访问。

证据：`cloudfile-hub/cloudfile_ext/search/`、`cloudfile-docker/tests/e2e/search_matrix.py`、
`.github/workflows/search-e2e.yml`。旧的方案比较和排期已移入[历史索引](../history/README.md)。

# 检索（簇 E）规格与分阶段方案

簇 E 的规格，对应 Pro 的 **Full text search**。配套：[pro-parity.md](pro-parity.md)、
[upstream-reuse.md](upstream-reuse.md)（探针 3）、[FEATURES.md](FEATURES.md)、
[EXTENSION-POINTS.md](EXTENSION-POINTS.md)。

下面每条结论都附可复现的代码位置。

---

## 一、原则修订：优先复用官方组件，是否开源不是首要约束

CE 扩展版的原则正式调整为：

> **优先复用 Seafile 官方镜像与现有实现——无论它是开源还是仅二进制依赖。
> 只有当官方组件不能满足 CE 扩展需求时，才自行适配或替换。**

这与"最小化上游改动"的成本模型一致：复用一个官方镜像 = 零 fork 成本。元数据同理：
**默认用官方 metadata-server**，协议兼容的自建版本作"官方不满足需求时的后备"，
而不是起点（见 [upstream-reuse.md](upstream-reuse.md) 探针 1）。保留协议这层 seam
不花成本，正好把后备选项一直留着。

### 默认复用的官方组件

Compose 里**直接引用官方镜像**，不重新打包进 CloudFile 镜像——更新和替换更简单。

| 组件 | 默认镜像 | 定位 | 默认 |
|---|---|---|---|
| Seafile Core + Seahub | CloudFile 自有镜像（基于 CE + 必要补丁） | 文件/权限/Web | ● |
| Metadata Server | `seafileltd/seafile-md-server` | 属性、标签、元数据 | ○ 可选 |
| SeaSearch | `seafileltd/seasearch` | **默认全文检索** | ● |
| Notification Server | `seafileltd/notification-server` | 实时通知 | ○ 可选 |
| Thumbnail Server | `seafileltd/thumbnail-server` | 图片/PDF/视频缩略图 | ○ 可选 |
| SeaDoc | `seafileltd/sdoc-server` | 在线文档 | ○ 可选 |
| Seafile AI | `seafileltd/seafile-ai` | 自动属性/标签/摘要/OCR/语义（见 [ai.md](ai.md)） | ○ 可选，需自备 LLM |
| Meilisearch | `getmeili/meilisearch` | **可选替代搜索引擎** | ○ 可选 |

> **SeaSearch 授权**：官方 SeaSearch 三人以下免费。这不影响 CE 扩展版把它作为
> 默认——它是可替换的（见下的后端抽象），需要时切 Meilisearch。

---

## 二、核对：CE 的搜索链路，绝大部分已经在了

CE 搜索链路的现状，附代码位置：

| 判断 | 结论 | 代码位置 |
|---|---|---|
| seafevents 已有完整 SeaSearch 增量索引 / 内容提取 / 查询 | ✅ 属实 | `seafevents/repo_metadata/`（构建时 clone），`seafile_ai_api`/seasearch 客户端 |
| Seahub 已识别 `[SEASEARCH]` 配置 | ✅ 属实 | `seahub/utils/__init__.py` `check_seasearch_enabled()` → `HAS_FILE_SEASEARCH`；bootstrap 已写 `[SEASEARCH]` 段 |
| Seahub 已有全局搜索接口 | ✅ 属实 | `seahub/api2/views.py:458 class Search`，路由 `api2/search/` |
| 先算用户可访问库、再把 repo_id 发给搜索服务 | ✅ 属实 | `Search.get()` 的 `HAS_FILE_SEASEARCH` 分支：`get_search_repos()` → `format_repos()` → `ai_search_files()` |
| CE 的限制点是搜索接口的 `IsProVersion` | ✅ **属实，且已精确定位** | 见下 |

### 精确定位限制点：只有两个接口带 `IsProVersion`

```python
# seahub/api2/views.py:458
class Search(APIView):
    permission_classes = (IsAuthenticated, IsProVersion)   # ← 全局文件搜索，被挡在这

# seahub/api2/permissions.py
class IsProVersion(BasePermission):
    def has_permission(self, request, *args, **kwargs):
        return is_pro_version()                            # CE 恒为 False → 403
```

把整个搜索路径的接口权限扫一遍，**只有两个**带 `IsProVersion`：

| 接口 | 权限 | 需要解除？ |
|---|---|---|
| `Search`（`api2/search/`，全局文件搜索） | `(IsAuthenticated, IsProVersion)` | ✅ 是，主入口 |
| `PublishedRepoSearchView`（`public_repos_search`） | `(IsAuthenticatedOrReadOnly, IsProVersion)` | ✅ 是（发布库搜索） |
| `ItemsSearch`、`SearchFile`（按名）、`WikiSearch` 等 | 仅 `IsAuthenticated`，内部按 `HAS_FILE_SEARCH/HAS_FILE_SEASEARCH` 判 | — 已经是"按可用性判"，不用动 |

所以**其余搜索入口本来就是"按搜索是否可用"放行的**，唯独这两个多压了一层
Pro 门。解除面非常小。

### 铁律：不要动全局 `is_pro_version()`

`is_pro_version()` 被 **56 个文件**引用（SAML、审计、组织管理、机构管理……）。
把它整体改真，会连带放开一堆没打算放开的 Pro 功能。**只替换那两个接口上的
`IsProVersion` 权限类**，不碰函数本身。

---

## 三、确认的做法：用 URL 影子解除门控，**零上游改动**

解除门控用 CloudFile 自己的 `IsSearchAvailable`，且**不需要编辑 `views.py`**：
CloudFile 的 URL 注入点已经把扩展路由**排在原生路由之前**，注释里写明"让扩展在
必要时遮蔽原生入口"：

```python
# seahub/utils/rooturl.py  —— CloudFile patterns come first so an extension
# can shadow a native endpoint when it has to.
```

于是解除门控 = 注册一个遮蔽同名路由的薄子类，**只覆盖 `permission_classes`**，
`get()` 及其全部权限过滤/虚拟库逻辑原样继承：

```python
# cloudfile_ext/search/views.py  （新增文件，零上游改动）
from rest_framework.permissions import IsAuthenticated
from seahub.api2.views import Search as _UpstreamSearch
from cloudfile_ext.search.permissions import IsSearchAvailable

class Search(_UpstreamSearch):
    # 唯一改动：把 IsProVersion 换成"搜索是否可用"
    permission_classes = (IsAuthenticated, IsSearchAvailable)

# cloudfile_ext/search/permissions.py
class IsSearchAvailable(BasePermission):
    def has_permission(self, request, *a, **k):
        from seahub.utils import HAS_FILE_SEARCH, HAS_FILE_SEASEARCH
        return HAS_FILE_SEARCH or HAS_FILE_SEASEARCH   # 已有的可用性信号
```

```python
# cloudfile_ext/search/__init__.py  register()
registry.register_urls([
    re_path(r'^api2/search/$', Search.as_view(), name='cloudfile-search'),
    # 同法遮蔽 public_repos_search（如需放开发布库搜索）
])
```

**代价核对**：新增文件 + 一行 `register_urls`，三仓上游清单 **5/8/3 逐字节不变**。
这比"编辑 `views.py` 的 permission_classes"更省——后者会把 Hub 登记项从 5 涨到 6。

> 所以 seasearch 的**索引与查询后端**零新增代码（都在 seafevents），但**接口那层
> Pro 门必须由 CloudFile 解除**——零的是后端，不是端到端。

前端入口：CE 本来就按搜索可用性显示/隐藏搜索框（读 `HAS_FILE_SEARCH` 一类信号），
解除门控后它会自然出现，无需前端改造。

---

## 四、搜索后端抽象（P1），以及它该住在哪

后端抽象接口：

```python
class SearchBackend:
    def ensure_index(self, schema): ...
    def upsert_documents(self, documents): ...
    def delete_documents(self, document_ids): ...
    def delete_library(self, repo_id): ...
    def search(self, request): ...
    def health_check(self): ...
```

```
SearchBackend
├── SeaSearchBackend    默认，包装现有 SeaSearchAPI
└── MeilisearchBackend  可选，调用 Meilisearch API
```

但**"住在哪"要分两侧说清楚，否则会不小心 fork seafevents**：

| 侧 | 现状 | meilisearch 怎么接 |
|---|---|---|
| **查询侧** | CloudFile 基线**已有** `register_search_provider()`（特性 64）——这本就是"查询后端可替换"的 seam | MeilisearchBackend 的 `search()` 注册成一个 provider，**零上游改动** |
| **索引侧** | seafevents 的 seasearch 索引器（上游）把文档写进 seasearch | meilisearch 需要有人往里写。**别 fork seafevents**——那是第 4 个 fork/上游改动。CloudFile 惯用做法：`cf-worker` 里起一个消费同一提交事件流的索引器（`register_periodic_task` / 事件总线），写 meilisearch |

**结论**：查询侧的抽象基线已经有了；**索引侧的抽象才是 meilisearch 的真实成本**，
且它属于 CloudFile 侧（cf-worker），不属于 seafevents。seasearch 默认路径两侧都用
上游，不碰这个成本——这也是它当默认的理由。

---

## 五、统一索引文档

形成 CloudFile 自己的标准文档结构（引擎无关）：

```json
{
  "id": "repo-id:path-hash",
  "repo_id": "library-id",
  "path": "/项目/设计说明.docx",
  "name": "设计说明.docx",
  "extension": "docx",
  "object_type": "file",
  "size": 102400,
  "mtime": 1784800000,
  "last_modifier": "user@example.com",
  "content": "提取后的正文",
  "tags": ["设计", "汽轮机"],
  "properties": {"project": "项目A", "status": "已审核", "security_level": "内部"}
}
```

物理索引设计**藏在 Backend 内部**，上层不得依赖具体引擎：

- **SeaSearch**：延续官方"每库一个索引"。
- **Meilisearch**：优先"统一文件索引 + `repo_id` 过滤"，避免一次查询打很多索引。

> `tags` / `properties` 来自元数据（簇 D）。它们进索引就是**组合检索**（特性 41，
> D×E 跨簇），经第 67 项的结构化过滤契约解耦：D 喂字段、E 翻译过滤。这条正是
> 过滤契约当初存在的理由。

---

## 六、配置

第一版**仍读原生 `[SEASEARCH]`**（减少升级冲突）；等 Meilisearch 接入后，再引入
统一 `[SEARCH]`，并**兼容**原有段：

```ini
# 第二版起（统一）
[SEARCH]
enabled = true
backend = seasearch            # 或 meilisearch
url = http://seafile-seasearch:4080
api_key = xxx
index_file_content = true
index_metadata = true
```

---

## 七、分阶段

| 阶段 | 内容 | 上游成本 | 依赖 | 状态 |
|---|---|---|---|---|
| **P0** | CE 启用官方 SeaSearch：打通 seafevents 索引；**精确解除那两个接口的 Pro 门**（URL 影子）；支持文件名/正文/类型/时间/大小筛选；验证个人库、共享库、群组库、子目录权限、隐藏目录 | **0**（影子路由是新增文件） | 官方 SeaSearch 镜像 | 🟡 已实现，未随镜像验证 |
| **P1** | 抽出 `SearchBackend`，把现有 SeaSearch 包装为默认后端；对外 API 与前端不变 | 0 | P0 | ✅ **未新增包装类**——见下"实现偏离" |
| **P2** | Meilisearch：批量写/删/重建/查询；配 filterable/sortable/searchable；中文分词验证；后端切换与重建命令。**索引侧走 cf-worker，不 fork seafevents** | 0 | P1 | 🟡 已实现，未随镜像验证 |
| **P3** | 元数据与智能检索：把 Metadata Server 的标签/属性写入索引（组合检索，特性 41）；按项目/状态/专业/密级组合筛选；再接 AI 摘要/自动标签/语义检索 | 0 | 簇 D + P2 | ⬜ 未开始 |

**P0 的验收面**（与 ACL 矩阵同思路——不是"能搜到"，而是"权限边界在搜索里也成立"）：
个人库/共享库/群组库各能搜到自己该看的；子目录权限被尊重。这几项已进
`search-e2e.yml`/`tests/e2e/search_matrix.py`（三阶段，见下）。**ACL 隐藏目录/
受限目录不出现在结果里**这一项**未覆盖**——见下"已知边界"。

### 实现偏离（与本节原方案的差异，均为读代码后确认的简化，不是遗漏）

- **P1 没有 `SeaSearchBackend` 包装类。** 读 `seahub/api2/views.py` 发现
  `Search.get()`/`PublishedRepoSearchView.get()` 的形状是
  `if HAS_FILE_SEARCH: ... elif HAS_FILE_SEASEARCH: ai_search_files(...)`——
  SeaSearch 走的是**第二个分支**，upstream 自己的代码，完全不经过
  `search_files()`/`cloudfile_ext.hooks`，也就不经过 `CF_PROVIDER_SEARCH` 这个
  provider 机制。所以"默认用 SeaSearch"不需要注册任何 provider：
  `CF_PROVIDER_SEARCH` 留空就是默认，包一层只是重复调用
  `pro/python/seafevents/seasearch/utils/seasearch_api.py`（服务端已有的客户端），
  且这层重复代码只在 Hub 侧可达，没有意义。详见 `cloudfile_ext/search/__init__.py`
  的模块文档字符串。
- **主开关是 `CF_ENABLE_SEARCH`，不是本文档早前设想的"零配置直接可用"。**
  实测发现 `bootstrap.py` 原先无条件把 `[SEASEARCH] enabled` 写成 `true`——
  在 Pro 门解除之前无害，解除之后就会让没开开关的部署也把 `HAS_FILE_SEASEARCH`
  置真，指向一个根本没起的 `seasearch` 容器，报 500 而不是"功能未启用"的 404。
  已改为 `write_seafevents_search_config()`，跟 `write_cloudfile_settings()`
  一样每次启动重写，由 `CF_ENABLE_SEARCH` 门控；此前占位的
  `CF_ENABLE_MEILISEARCH` 开关（从未真正接线）随之退役。
- **Meilisearch 索引范围是元数据 + 纯文本正文，不是完整正文抽取。** 文本文件
  （`SEARCH_FILEEXT[TEXT]` 那组后缀）在 `CF_SEARCH_INDEX_TEXT_MAX_BYTES`
  （默认 1MB）以内索引正文；docx/pdf/xlsx 等二进制格式只索引文件名/路径/类型/
  大小/时间。完整正文抽取是 SeaSearch 通过 seafevents 已经做好的事，
  Meilisearch 路径存在的意义是"不想起 SeaSearch 时仍有可用的检索"，不是重做
  一遍正文管线——这条边界故意写在这里，不是代码里的隐藏行为。

### 已知边界（写在这里，不藏在代码注释里）

- **原生 SeaSearch 分支不过滤 ACL 隐藏目录。** `elif HAS_FILE_SEASEARCH` 分支
  没有 `Search.get()` 的 ES 分支那段 `is_invisible_path` 过滤循环——这是上游
  代码的既有行为，不是本次改动引入的。`CF_ENABLE_DIR_ACL` 标记为 `invisible`
  的子目录，其中的文件仍可能出现在原生 SeaSearch 的搜索结果里。
  `CF_PROVIDER_SEARCH=meilisearch` 路径**不受影响**：它走的是
  `if HAS_FILE_SEARCH:` 分支（`_cf_has_search_provider()` 把标志"或"成真），
  与 ES 共用同一段过滤后处理。**同时使用 `CF_ENABLE_DIR_ACL` 与检索的部署，
  在这一点修复之前应优先选 `CF_PROVIDER_SEARCH=meilisearch`。**
- **`search-e2e.yml` 尚未在真实容器栈上跑过**（本机与 CI 都还没有一次成功的
  跑次）。已验证的是：Hub 侧单测（`cloudfile_ext/search/tests/`）、配置生成的
  静态检查与执行测试（`preflight-checks.py`、`test-bootstrap-settings.py`）、
  compose 配置校验（`docker compose config`、各 profile 的服务清单）。

---

## 八、产品口径

> CloudFile 默认采用 Seafile 官方 Metadata Server、SeaSearch 等镜像，尽量与上游
> 兼容；通过 CE 服务端与 Seahub 的**最小改造**（两个接口的 Pro 门，经 URL 影子，
> 零上游改动）开放完整搜索链路，并提供 Meilisearch 等可替换搜索后端。

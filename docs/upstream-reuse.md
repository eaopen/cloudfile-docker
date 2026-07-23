# 上游已经有什么：探针结论

[BRANCHES.md](BRANCHES.md) 第八节列了三个决策探针，每个 1～2 天，结论直接改写
排期规模。这份文档是它们的归属地。

**为什么值得单独一份文档**：[FEATURES.md](FEATURES.md) 的待办 4 写着
"上游 CE 14.0 已带了 P2/P3 的一大半"。那句话如果只是一条待办，每个人动工前
都要自己重查一遍；写成结论，才能真的省下工作量。

> **探针的价值在于它可能让整段排期消失。** 反过来，**没做探针就动工，代价是
> 重写一遍上游已经开源的东西**——那不会报错，不会有冲突，只会在半年后以
> "我们为什么维护着两套属性系统"的形式出现。

| # | 探针 | 状态 | 结论 |
|---|---|---|---|
| 0 | SSO / 身份接入 | ✅ 已做 | 登录整套都在 CE 里，且无 Pro 门控。缺的只有**组织映射** |
| 1 | metadata-server 协议 | ✅ 已做 | **CloudFile 自建存储引擎，说同一套 HTTP 协议**。唯一闭源的就是协议背后的存储引擎；前端、Hub API、**投喂管线**（seafevents）全部开源。分两步：官方 server 作可选适配组件先验证，长期权威模型归 CloudFile |
| 2 | OnlyOffice 门控盘点 | ⬜ 未做 | 决定 3.2 的规模，顺带给 3.1 的 Hub 侧成本定量 |
| 3 | seasearch vs meilisearch | ✅ 已做 | **默认 seasearch（后端零新增代码），但接口的 Pro 门要 CloudFile 解除**（`Search` + `public_repos_search` 两个接口，URL 影子，零上游改动）；meilisearch 作可选 provider。完整方案见 [search.md](search.md) |

探针 0 不在原来的三个里面——它是做簇 B 时顺手做的，而它的结论**改变了这个
特性的形状**：原计划写一个认证后端，实际只需要写组织映射。所以它被补进来，
也说明这三个不是全部，凡是"上游可能已经有了"的地方都值得先查十分钟。

**探针 1 和 3 一起把线 2 的规模重写了一遍**：原排期是"D 元数据 + E 检索，两条
线各自从零做五个特性"，探针后变成"元数据 = 一个兼容服务 + 复用上游全部前端；
检索 = 配置上游已有的 seasearch"。这正是 BRANCHES.md 第八节那句话的兑现——
**探针的价值在于它可能让整段排期消失。**

---

## 探针 0：SSO / 身份接入（已做）

**问题**：特性 36 要不要自己实现一套 SSO 登录？

**做法**：直接读 fork 里的上游代码。命令都在下面，任何人可以复现。

### 结论：登录不用写，组织映射要写

CE 14.0 自带的认证方式：

| 模块 | 开关 | 说明 |
|---|---|---|
| `seahub/oauth/` | `ENABLE_OAUTH` | OAuth2 / OIDC 授权码流程，含属性映射、老用户按邮箱认领、`SocialAuthUser` 账号绑定 |
| `seahub/adfs_auth/` | `ENABLE_ADFS_LOGIN` / `ENABLE_MULTI_ADFS` | SAML 2.0，走 djangosaml2 |
| `seahub/django_cas_ng/` | `ENABLE_CAS` | CAS |
| `seahub/auth/backends.py` | `ENABLE_REMOTE_USER_AUTHENTICATION` | REMOTE_USER（反向代理鉴权） |
| `seahub/base/accounts.py` | `ENABLE_LDAP` | LDAP |
| `seahub/{dingtalk,work_weixin,weixin}/` | 各自开关 | 钉钉 / 企业微信 / 微信 |

**一处 Pro 门控都没有：**

```bash
grep -rl "is_pro_version" seahub/oauth/ seahub/adfs_auth/ seahub/django_cas_ng/ seahub/auth/
```

（输出为空。）

依赖也都在发行包里：`requests_oauthlib` 来自 `seahub/requirements.txt`
（装进 `thirdpartdir`，构建脚本没有把它 sed 掉），`djangosaml2` / `pysaml2` /
`python-ldap` 在镜像的 pip pin 里。**镜像不需要改。**

后端的挂载也是现成的，`seahub/settings.py` 在加载 `seahub_settings.py`
**之后**才决定要不要接：

```bash
sed -n '1437,1450p' seahub/settings.py    # if ENABLE_OAUTH or ...: AUTHENTICATION_BACKENDS += ...
```

所以打开 SSO 只需要往 CloudFile 配置块里写标量，**零上游改动**。

### 上游没有的：通用目录的组织映射

上游的 OAuth 只映射用户**属性**：

```bash
grep -n "OAUTH_ATTRIBUTE_MAP" -A 10 seahub/oauth/views.py   # name / contact_email / login_id / uid
```

组织归属只有企业微信和钉钉两个集成做了，用的是 `external_department` 表：

```bash
sed -n '150,170p' seahub/auth/models.py    # outer_id = models.BigIntegerField()
```

`outer_id` 是 BIGINT，**装不下通用目录的组标识**——OIDC 的组 claim 和 LDAP 的 DN
都是字符串。所以这张表不能复用，CloudFile 另建 `cf_sso_group_map`。

还有一处结构性限制值得记下：**登录断言里的 claim 拿不到**。
`seahub/oauth/views.py` 在自己内部消费 `user_info_json`，发出的
`seahub.auth.signals.user_logged_in` 只带 `request` 和 `user`：

```bash
sed -n '105,115p' seahub/auth/__init__.py
```

要拿 claim 就得改上游文件。这正是簇 B 选择"拉取而不是拦截"的第一条理由，
另外两条见 [sso-mapping.md](sso-mapping.md) 第二节。

### 对排期的影响

| | 原估 | 实际 |
|---|---|---|
| 登录 | 写一个认证后端 + 回调路由 | **0**，配置而已 |
| 组织映射 | 未单独计价 | 一个目录 provider + 编排 + 两个表 + 门禁 |
| 新增上游改动 | 0 | 0（不变） |

规模没有变小，但**变了形状**：原计划里"SSO"最大的一块（登录）消失了，取而代之
的是原计划里根本没有的一块（组织映射）。如果按原计划动工，会得到一个能登录、
但组织结构仍然要手工维护的产物——而后者才是企业提这个需求的原因。

---

## 探针 1：metadata-server 协议（已做）

**问题**：`seahub/repo_metadata/` 带了完整 API 与前端、无 Pro 门控，只缺一个
闭源的 metadata-server（默认 `127.0.0.1:8084`）。写一个协议兼容的服务，
能不能让原生前端跑起来？还是只能自研全套属性/标签系统？

**做法**：读 `metadata_server_api.py`（Hub 侧的客户端，316 行）定出完整协议，
再从 seafevents 的 `repo_metadata/`（构建时 clone，SHA 锁在 release.yaml）取出
SQL 生成逻辑，量一量 `/query` 那个端点到底要执行多复杂的 SQL。

### 结论：默认用官方 metadata-server；自建存储引擎是"官方不满足需求时"的后备

**这条结论经历过两次调整，把它记全，免得读起来自相矛盾。**

- 第一版（成本视角）：别重写前端，写个协议兼容的服务。
- 第二版（归属视角）：为了整套开源/可自建/可分发，把权威模型收回自己手里，
  自建存储引擎。
- **第三版（现行原则）**：[search.md](search.md) 第一节把 CE 扩展版的原则正式定为
  **优先复用官方组件，是否开源不是首要约束**。据此，**默认直接用官方
  `seafileltd/seafile-md-server` 镜像**，自建协议兼容版本降级为**后备**——
  只有当官方组件不能满足 CE 扩展需求时才做。

三版不矛盾，是同一件事在不同优先级下的排序：**官方镜像是起点**（零成本、零 fork），
**协议兼容的自建版是留好的退路**。而下面这条边界正是"退路随时可走"的保证——
保留这层 seam 不花成本。

**唯一闭源的就是协议背后那个存储/查询引擎，整条投喂管线是开源的。**
把这条边界钉死很重要：它意味着**官方 server 只是"协议的一个实现"**，
`METADATA_SERVER_URL` 指向谁都行——今天指官方镜像，哪天官方不够用，指自建后端，
前端/API/投喂 worker 一个字节不用改。

| 层 | 位置 | 开源？ |
|---|---|---|
| 前端（表格/画廊/视图） | `seahub/frontend/src/metadata/`（352 文件）+ 标签 88 | ✅ 在 CE |
| Hub API | `seahub/repo_metadata/apis.py`（3745 行）+ 读客户端 | ✅ 在 CE |
| **投喂管线**：订阅 repo 事件 → `metadata_update` Redis 频道 → 提交遍历 → 写入 | **`seafevents/repo_metadata/`**（`handlers.py`、`index_master.py`、`slow_task_handler.py`）**CloudFile 已 clone 并构建** | ✅ 开源 |
| **协议背后的存储/查询引擎** | `METADATA_SERVER_URL` 那个二进制（默认 `127.0.0.1:8084`） | ❌ **唯一闭源** |

所以用户手册里描述的那套机制（`repo_update` 事件、Redis 队列、增量提交遍历、
`metadata_update` channel）**不需要 CloudFile 重写——它已经在 seafevents 里开源了**。
开源的 worker 用 `insert_rows`/`add_column` 通过 HTTP 协议写入，开源的 Hub 用
`query_rows` 读。CloudFile 自建的服务只需要**成为那个存储后端**，不需要重建投喂它
的管线。

对照三种做法的量级：

| 做法 | 要写什么 | 量级 |
|---|---|---|
| ❌ 自研全套属性/标签 | 重写 352+88 前端 + 3745 行 API + 投喂管线 | 一个产品 |
| ❌ 把闭源 server 当核心 | 0，但**核心受制于未公开源码**——与开源/可构建/可分发的目标冲突 | 战略债 |
| ✅ **自建存储引擎，说同一套协议** | 协议背后那个引擎（~316 行协议面），投喂与 UI 全部白拿上游 | 一个有界的服务 |

### 分两步，别一步到位

存储引擎的选择就是一个环境变量 `METADATA_SERVER_URL`（`ENABLE_METADATA_MANAGEMENT`
env 门控，**非 Pro**），比一个 `cloudfile_ext` provider 还薄——Hub 侧零间接层。

| 阶段 | `METADATA_SERVER_URL` 指向 | 用途 |
|---|---|---|
| **1（快速验证）** | Seafile 官方二进制 | 当**可选适配组件**，先跑通属性/标签/多视图，验证协议理解无误 |
| **2（长期权威）** | CloudFile 自建后端 | 属性/标签/检索的权威数据模型归 CloudFile 掌握 |

前端、Hub API、投喂 worker 在两个阶段**逐字节相同**，变的只有 URL 背后的东西。
这是"官方 server 可选、我们的模型权威"能达到的最干净形态。

### 一条要说清的边界：自由改模型改到哪为止

自建后端给你存储层的完全掌控，以及**扩展**的自由（协议本身有 `add_column`）。
但表的**契约**（`METADATA_TABLE` 的列、视图 SQL）在开源的 seafevents + 前端里——
所以改列是自由的，改模型的**语义**（而不只是加字段）意味着还要动那两处。
仍然全开源、仍然可构建，但那时就不再是"只改我们自己的服务"了。写清楚这条，
免得有人以为能凭空重塑 schema 而不用跟进另外两个开源仓。

### 与 file_op 缺口无关（一个解耦红利）

投喂走的是 seafevents 的 `repo_update` 事件总线（Redis），**不是 Hub 的
`file_op` 钩子**。所以线 2（元数据）**不依赖**卡住审计的那个 `file_op` 基线缺口
（[EXTENSION-POINTS.md](EXTENSION-POINTS.md) 缺口 1），两者独立。
特性 42（元数据跟随移动）很可能直接来自提交 diff 遍历、**不需要** `file_op`——
落地前验证，但方向一致。

### 协议长什么样

`METADATA_SERVER_URL` 下的一个 HTTP 服务，鉴权是 **HS256 JWT，用
`JWT_PRIVATE_KEY` 签**——而那把密钥 **CloudFile 已经在生成**
（`bootstrap.py` 的 `write_seafile_env`），所以这一项零新增。payload 带
`base_id`（= repo_id）、`user`、`exp`。

端点是一个"每个库一张 base"的列式小型数据库：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST/DELETE | `/api/v1/base/<base_id>` | 建/删一个 base |
| GET | `…/metadata` | 取 base 的表/列结构 |
| POST/DELETE | `…/tables`、`…/tables/<id>` | 建/删表 |
| GET/POST/PUT/DELETE | `…/columns` | 列的增删改查（列是动态的） |
| POST | `…/link-columns`、`…/links`（+PUT/DELETE） | 表间关联 |
| POST/PUT/DELETE | `…/rows` | 行的增删改 |
| **POST** | **`…/query`** | **执行 SQL，返回 `{results, metadata}`** |

前七类是直白的 CRUD，一天能实现完。**全部风险集中在 `/query`**。

### `/query` 有多难：可控，因为服务端只需**执行** SQL，不需**生成**它

`/query` 收到的是一条已经拼好的 SQL 字符串加 `?` 参数。SQL 的生成
（seafevents 的 `view_data_sql.py`，**1336 行**）在 Hub 侧完成，服务端不必
重现它——只需要能把它吐出来的 SQL 跑对。这把问题从"实现 SeaTable"缩小到
"实现一个够用的 SQL 引擎"。

那个方言的实测边界（`grep` 全部 1336 行的产物）：

- 标识符用反引号包裹，参数用 `?`——**贴近 SQLite/MySQL**。
- 用到的算子只有 `LIKE` / `ILIKE` / `IN` / `NOT IN` / `IS (NOT) NULL` /
  比较 / `ORDER BY` / `LIMIT start,count` / 若干日期函数。
- **没有真正的 SQL JOIN**——`grep JOIN` 命中的 16 处全是 Python 的
  `", ".join(...)`，误报。表间关联在写入侧展开，查询侧不 join。
- 列有 27 种类型（`single-select`、`multiple-select`、`collaborator`、
  `geolocation`、`formula`、`link-formula`、`tags`、`face-vectors`、`rate`、
  `duration`…）。但**类型语义大多在 Hub 侧就翻译成了普通字符串比较**：
  例如单选在生成 SQL 前已把选项 id 换成存储值，标签的递归 `sub_links` 在
  `collect_all_tag_ids` 里先展开成一个 `IN (...)` 才发给服务端。
  服务端多数时候只是在存字符串、比字符串。

**最小可行实现**：每个 base 一个 SQLite 文件，列动态建，`/query` 把这个方言
翻译到 SQLite（反引号→双引号、`LIMIT a,b` 原样、`ILIKE`→`LIKE`
`COLLATE NOCASE`）。`face-vectors`（人脸识别）与 `formula` 可以第一版不做——
它们分别依赖 `ENABLE_SEAFILE_AI` 和公式引擎，都不是属性/标签的必经路径。

### 对排期的影响

原排期（[BRANCHES.md](BRANCHES.md) 线 2）：**D 元数据 = 属性 + 标签 + 移动跟随，
三个特性从零做**。探针后：**D = 一个 CloudFile 自建的存储引擎（说 metadata-server
的 HTTP 协议）+ 复用上游全部前端、API 与投喂管线**。属性、标签、移动跟随三者随之
基本"白拿"——前端、REST 层、事件投喂都在开源侧，只等一个能应答协议的后端。

**分两步落地**：阶段 1 把 `METADATA_SERVER_URL` 指向 Seafile 官方二进制，当可选
适配组件，先跑通并验证协议理解无误；阶段 2 换成 CloudFile 自建后端，把权威模型
收回自己手里。两阶段之间前端/API/worker 逐字节不变。

**未验证的一面**：本探针是静态读代码得出的，没有真起服务让前端连。阶段 1 的第一件
事就是配 `ENABLE_METADATA_MANAGEMENT=true` + `INNER_METADATA_SERVER_URL` 指向
官方（或最小自建）server，看原生前端能否建列、写值、按属性过滤。
**跑通那一刻才是这条结论的验收。** 阶段 2 的自建后端只需通过同一组冒烟。

### 起点（可复现）

```bash
# 协议（Hub 侧客户端）
grep -n "def \|/api/v1/" ../cloudfile-hub/seahub/repo_metadata/metadata_server_api.py
# 门控：env 开关，非 Pro
grep -n "ENABLE_METADATA_MANAGEMENT\|METADATA_SERVER_URL" ../cloudfile-hub/seahub/settings.py
# 前端与 API 规模
find ../cloudfile-hub/frontend/src/metadata -name '*.js' | wc -l
wc -l ../cloudfile-hub/seahub/repo_metadata/apis.py
# SQL 方言（构建时才 clone，按 release.yaml 的 SHA 取）
curl -sL https://raw.githubusercontent.com/haiwen/seafevents/<seafevents-SHA>/repo_metadata/view_data_sql.py | wc -l
```

## 探针 2：OnlyOffice 门控盘点（未做）

**问题**：`seahub/onlyoffice/` 的 views / converter / callback / models 都在
CE 里。数清 `is_pro_version()` 里哪些是真 Pro 依赖、哪些只是商业门控。

**决定**：3.2 的规模；顺带给 3.1（文件锁的 Hub 侧）定量——
见 [EXTENSION-POINTS.md](EXTENSION-POINTS.md) 缺口 5。

起点：

```bash
grep -rn "is_pro_version" ../cloudfile-hub/seahub/onlyoffice/ \
    ../cloudfile-hub/seahub/views/file.py ../cloudfile-hub/seahub/seadoc/apis.py
```

## 探针 3：seasearch vs meilisearch（已做）

**问题**：上游 CE 14.0 已自带 seasearch 集成（bootstrap 甚至默认启用它、
把 Elasticsearch 降为回落）。跟随上游 seasearch 还是自选 meilisearch？

**做法**：追 `HAS_FILE_SEASEARCH` 从定义到查询执行，看 seasearch 到底走哪条
代码路径，以及它和我们自己的检索扩展点（特性 64）是什么关系。

### 结论：用 seasearch，而且它根本不经过我们的 provider

关键发现是：**搜索视图里有两条互相独立的分支**，我们此前只接了其中一条。

```
seahub/api2/views.py  搜索入口
  if HAS_FILE_SEARCH:        → seahub.search.utils.search_files → es_search
  │                            ↑ 我们的 provider 补丁接在这里（特性 64），
  │                              meilisearch 就是填这个 es_search 槽
  elif HAS_FILE_SEASEARCH:   → ai_search_files（seafevents 里的 seasearch 客户端）
                               ↑ 完全独立的一条分支，与我们无关
```

含义有三点：

1. **seasearch 的索引与查询后端零 CloudFile 代码。** 它在 CE 里已完整集成、
   客户端在 seafevents，`[SEASEARCH]` 配置段 bootstrap 已经在写（默认
   `seasearch_url = http://seasearch:4080`、默认启用）。索引侧、查询侧都用上游，
   连 provider 都不用注册。

   > ⚠️ **更正一处早先的夸大**：这里最初写"seasearch 端到端零 CloudFile 代码"，
   > **不准确**。全局搜索接口 `seahub/api2/views.py:458 class Search` 被
   > `permission_classes = (IsAuthenticated, IsProVersion)` 挡着，CE 下恒 403——
   > 即便 seasearch 配好了也搜不了。**接口那层 Pro 门必须由 CloudFile 解除**
   > （只影响 `Search` 与 `public_repos_search` 两个接口，经 URL 影子子类覆盖
   > `permission_classes`，零上游改动；**不要动全局 `is_pro_version()`**——它被
   > 56 个文件引用，会连带放开 SAML/审计/组织管理）。零的是**后端**，不是端到端。
   > 详见 [search.md](search.md)。
2. **我们的 `register_search_provider` 扩展点，本质是"seasearch 之外的后端"。**
   meilisearch、企业自有检索走它；seasearch 不走。这不削弱特性 64 的价值——
   查询侧扩展点仍是让 meilisearch/企业检索零上游改动的地基——但它澄清了
   一件事：**扩展点不是为 seasearch 铺的**，seasearch 上游自己就通了。
3. **两条分支同时打开有一个静默的优先级**：`if HAS_FILE_SEARCH` 在
   `elif HAS_FILE_SEASEARCH` 之前，所以一旦同时配了 CloudFile provider
   （`CF_PROVIDER_SEARCH=meilisearch`）和 seasearch，**meilisearch 会盖过
   seasearch**。上游那句 `raise Exception('ES and seasearch cannot be
   configured simultaneously')` 拦不住这种组合——它在我们那行
   `HAS_FILE_SEARCH = ... or _cf_has_search_provider()` **之前**执行。这不是
   bug（运维两个都配了，选一个是合理的），但要写进文档，否则"我配了 seasearch
   怎么走的是 meilisearch"会很难查。

### 推荐

- **默认推荐 seasearch**：上游维护、跟随上游路线、长期成本最低，且零 CloudFile
  代码。簇 E（特性 40）第一版就指向它，Compose 的 `search` profile 换成
  seasearch 容器即可。
- **meilisearch 作为可选 provider 保留**：给明确想要 meilisearch 或要接企业
  自有索引的部署。它是纯能力（新增文件、零上游改动，扩展点已在特性 64 付过）。
- **不要因为"原计划是 meilisearch"就先做 meilisearch**——那个计划早于"发现
  seasearch 已在 CE"这个事实。

### 起点（可复现）

```bash
grep -n "HAS_FILE_SEASEARCH\|ai_search_files" ../cloudfile-hub/seahub/api2/views.py
grep -rn "def is_seasearch_enabled\|seasearch" \
  <seafevents>/  # 客户端在 seafevents，不在 seahub
grep -n "SEASEARCH" -A 6 scripts/scripts_14.0/bootstrap.py
```

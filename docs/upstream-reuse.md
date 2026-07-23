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
| 1 | metadata-server 协议 | ✅ 已做 | **实现一个兼容服务**。协议 316 行、完全已知；要重写的前端+API 是 **352+88 个前端文件 + 3745 行 apis.py**，都在 CE 里。量级差一个数量级已坐实 |
| 2 | OnlyOffice 门控盘点 | ⬜ 未做 | 决定 3.2 的规模，顺带给 3.1 的 Hub 侧成本定量 |
| 3 | seasearch vs meilisearch | ✅ 已做 | **seasearch，且不经我们的 provider**。它在 CE 里已完整集成、无 Pro 门控，走的是搜索视图里一条独立分支；meilisearch 作为可选 provider 保留 |

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

### 结论：实现一个兼容服务，不要自研

三个数字决定了方向：

| | 规模 | 谁写的 |
|---|---|---|
| 要**兼容**的协议 | `metadata_server_api.py` **316 行**，端点全部已知、稳定 | 我们只需实现服务端 |
| 要**复用**的前端 | `frontend/src/metadata/` **352 个文件** + 标签 **88 个** | 上游，已在 CE |
| 要**复用**的 API | `seahub/repo_metadata/apis.py` **3745 行** | 上游，已在 CE |

自研 = 把后两行从零重写一遍。兼容 = 实现第一行。**量级差一个数量级**，
而且兼容路线白拿上游的 SeaTable 式表格/画廊/视图 UI 和整套 REST API。

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
三个特性从零做**。探针后：**D = 一个协议兼容的 metadata-server（新增服务，
零上游改动）+ 复用上游全部前端与 API**。属性、标签、移动跟随三者随之基本
"白拿"——它们的前端和 REST 层都在 CE 里，只等一个能应答的后端。

**未验证的一面**：本探针是静态读代码得出的，没有真起一个服务去让前端连。
下一步（真正落地 D 时的第一件事）是按上表写一个最小服务，配
`ENABLE_METADATA_MANAGEMENT=true` + `INNER_METADATA_SERVER_URL` 指向它，
看原生前端能否建列、写值、按属性过滤。**跑通那一刻才是这条结论的验收。**

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

1. **seasearch 用起来零 CloudFile 代码。** 它在 CE 里已完整集成、**无 Pro
   门控**，客户端在 seafevents，`[SEASEARCH]` 配置段 bootstrap 已经在写
   （默认 `seasearch_url = http://seasearch:4080`、默认启用）。跟随上游意味着
   连 provider 都不用注册——配 seafevents 即可。
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

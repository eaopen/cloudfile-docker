<!-- generated-by: gsd-doc-writer -->
# 扩展点清单与特性关联

> **用途**：登记 Hub/Server 扩展点、消费者、上游改动成本和已知缺口。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前技术清单；各项按正文标记区分已验证、已实现待验与未实现。
> **边界**：CE 保留原生调用链；CloudFile 新增注册与终判接缝；SeaSearch、Metadata Server 等外部实现仅通过契约接入。

CloudFile 的**基础扩展能力**（基线 `dev` 提供的全部机制），以及每一个扩展点被
哪些后续特性依赖。配套：[扩展能力矩阵](feature-matrix.md)（特性状态）、
[BRANCHES.md](BRANCHES.md)（当前分支规则）、[BRANCHING.md](../BRANCHING.md)（分支模型）。

这份文档回答两个问题：

1. 一个新特性要落地，需要基线提供什么？（查下面的关联矩阵）
2. 基线里的某个扩展点能不能删/改？（查谁依赖它）

> **判断一个扩展点是否"到位"的唯一标准**：依赖它的特性能否做到**零新增上游改动**。
> 只要某个特性还得去改上游文件，那就是扩展点没铺好，正确做法是**先给基线补扩展点**，
> 而不是在能力分支上改上游。

---

## 一、两种扩展点形状

这个区别决定了新能力该用哪个注册函数，写错会导致语义错误而不只是风格问题。

| 形状 | 语义 | 注册 | 冲突处理 |
|---|---|---|---|
| **链（chain）** | 每个注册者都会跑。问的是"有谁想参与？" | `register_*()` | 多个能力可共存，按注册顺序串联 |
| **实现（provider）** | 同一件事的可互换实现，**同时只有一个生效** | `register_provider(kind, name, ...)` | 由 `CF_PROVIDER_<KIND>` 选中，重名直接拒绝 |

**为什么 search 是 provider 而不是链**：一次查询只能有一个后端给出结果集，
两个后端各返回一半没有意义。**meilisearch 是 search 的一种实现，不是 search 本身**——
seasearch、Elasticsearch、企业自有检索服务都可以是同一个 kind 下的另一个名字。

**为什么索引器（search_indexer）反而是链**：同一份文档流可以同时喂给全文索引和
审计留痕，互不冲突。

**provider 未选中时一律回落到原生 CE 行为**；选中了一个没人注册的名字则**显式失败**，
不静默回落——把 `CF_PROVIDER_SEARCH=meilisearh`（拼错）当成"用 Elasticsearch"是
更坏的结果。

---

## 二、基础扩展能力（基线 `dev`）

### Hub 侧（`cloudfile_ext/`）

| 扩展点 | 形状 | 上游调用点 | 基线行为 |
|---|---|---|---|
| `register_urls` | 链 | `seahub/utils/rooturl.py` | 无路由 |
| `register_menu` | 链 | 前端读 `/api/v2.1/cloudfile/features/` | 无菜单项 |
| `register_permission_check` | 链 | `seahub/views/__init__.py` 的 `check_folder_permission`（**覆盖 255 处调用点**） | 原样返回权限 |
| `register_search_provider` | **provider** | `seahub/search/utils.py` 的 `search_files` + `seahub/utils/__init__.py` 的 `HAS_FILE_SEARCH` | 未选中 → Elasticsearch 原生路径 |
| `register_search_indexer` | 链 | ⚠️ **无上游调用点**，靠 `register_periodic_task` 自驱动 | 无索引器 |
| `register_file_op_hook` | 链 | ⚠️ **无上游调用点**，见下方缺口 | 钩子永不触发 |
| `register_external_source_provider` | 按类型 keyed | 无上游调用点（**刻意**）：经自有路由暴露，阶段 3 再影子原生端点，见缺口 3 | 无外部源 |
| `register_periodic_task` | 链 | `cf_worker` 管理命令（自有进程） | 无任务，故 `worker` profile 非默认启用 |
| `register_provider(kind, …)` | provider | 由声明该 kind 的一方分发 | 未选中 → 原生行为 |

通用机制：

| 机制 | 位置 | 用途 |
|---|---|---|
| 功能开关 | `features.py`，10 个 `CF_ENABLE_*` | 默认全关；未知开关名直接抛异常而非回落 false |
| provider 选择 | `providers.py`，`CF_PROVIDER_<KIND>` | 设置名由 kind 推导，新增 kind 不需要改基线 |
| 结构化过滤词汇 | `search_query.py` | 让元数据簇与检索簇能各自独立开发验收，见第六节 |
| 身份解析 | `identity.py` | Seafile 14 之后身份 ≠ 邮箱，**每个存或比用户名的能力都撞上这一条**。放基线而不是放某个能力里：ACL 存规则主体、SSO 把目录成员变成组成员，用的是同一个答案，留在 `acl/` 会让 SSO 在运行时 import ACL、并让 ACL 的开关决定 SSO 能不能解析用户 |
| 外部服务回调 | `external_service.py`，`CF_SERVICE_<NAME>_*` | 超时 / JWT 签名 / 重试 / fail-closed 或 fail-open |
| `cf_*` 数据层 | `db_router.py` + `scripts/sql/*/cloudfile.sql` | 表落在 **seafile-db**，因为 seaf-server(C) 与 Go fileserver 只连 ccnet-db / seafile-db |
| 注册密封 | `registry.seal()` | 启动后再注册直接报错，避免"半装上"的状态 |

### Server 侧（`common/cf-ext.{c,h}`）

| 扩展点 | 上游调用点 | 基线行为 |
|---|---|---|
| `CfPermFunc` | `rpc-service.c` 的 `check_permission_by_path` | 透传原生权限 |
| `CfDirentFilterFunc` | `rpc-service.c` 的目录列举 RPC 出口 | 不过滤 |
| `CfRestrictedFunc` | `cf_find_restricted_path` RPC → 同步 / 打包下载 | 返回 NULL（子树全可达） |
| `CfFileOpPrepareFunc` | `repo-op.c` 全部 19 个写入口；Go 写入口经 `cf_fileop_prepare` RPC | 放行 |
| `CfFileOpCommittedFunc` | 同上，提交成功后 | 不发事件 |
| `CfFileOpAbortedFunc` | 同上，PREPARE 通过但操作失败后 | 不发事件 |

上面三个是**读侧**，下面三个是**写侧**（`common/cf-fileop.{c,h}`，规格见
[fileop-lifecycle.md](fileop-lifecycle.md)）。两组的形状不同：读侧的
`CfPermFunc` 是**串联**（每个 provider 拿到上一个的结果继续收紧），写侧的
`CfFileOpPrepareFunc` 是**一票否决**（第一个拒绝就终止，后面的不再执行）。
差别是有意的——权限是一个可以逐步收紧的值，而"这次写入能不能发生"是个布尔，
让第二个 provider 观察一次不会发生的写入只会制造副作用。

**规则：扩展只能收紧，不能放宽。** 两端各自穷举整个权限格验证过。
写侧对应的规则是**只能拒绝，不能改写**：provider 拿到的上下文是只读的，
否则 provider 的注册顺序就会决定结果，而那个顺序不是任何人设计过的。

---

## 三、扩展点 × 特性关联矩阵

`●` 依赖　`○` 可选用　空 = 不涉及

**簇**列即分支归属——同一簇的特性共享表/规格，必须同一条分支。
簇的划分依据见 [BRANCHES.md](BRANCHES.md) 第一之二节。

| 簇 | 特性 | 开关 | urls | menu | perm_check | search_provider | indexer | file_op | ext_source | periodic | provider(kind) | cf_* 表 | server 钩子 |
|---|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **A** | 目录 ACL | `DIR_ACL` | ● | ● | ● | | | | | ● | ● 规则来源 | ● | ● 全三个 |
| **B** | SSO 登录 | `SSO` | | | | | | | | | | | |
| **B** | 组织映射 | `SSO` | ● | ● | | | | | | ● | ● `sso_directory` | ● | |
| **C** | 操作日志 / 审计 | `AUDIT` | ● | ● | | | | ○ | | ○ | ○ | ○ | Server `repo-update` → `Activity` |
| **D** | 文件属性 | `METADATA` | ● | ● | | | ● | ● | | ● | | ● | |
| **D** | 标签 | `TAGS` | ● | ● | | | ● | ● | | | | ● | |
| **D** | 移动/重命名元数据跟随 | `METADATA` | | | | | ● | ● | | ● | | ● | |
| **E** | 检索后端 | `SEARCH` | ● | | | ● | ● | | | ● | ● `search` | ● | |
| **D×E** | 组合检索 | `SEARCH` | ● | ● | ○ | ● | | | | | | | |
| **F** | OnlyOffice | `ONLYOFFICE`；编辑依赖 `FILE_LOCK` | ● | | | | | ● | | | ○ | ● | ○ 编辑写回 |
| **F** | 文件锁基础 | `FILE_LOCK`（规划新增） | ● | ● | ● | | | ● | | ● | | ● 自有锁真值 | ● C/Go/WebDAV 终判 |
| **F** | 签入签出 | `CHECKOUT` | ● | ● | ● | | | ● | | ● | | ● | ● |
| **F** | iTeam 流程接口 | `CHECKOUT` | ● | | | | | | | ● | ○ | ● | |
| **G** | SMB/NFS 外部源 | `EXTERNAL_SOURCES` | ● | ● | ● | ○ | ○ | | ● | ● | ● 源类型 | ● | |
| **G** | 外部源增量扫描 | `EXTERNAL_SOURCES` | | | | | ● | | ● | ● | | ● | |
| **G** | 虚拟目录挂载 | `EXTERNAL_SOURCES` | ● | ● | ● | | | | ● | | | ● | ○ |
| **G×D** | Overlay 标签属性 | `EXTERNAL_SOURCES` | ● | | | | ● | | ● | | | ● | |
| **H** | S3 / 多存储 | `S3_STORAGE` | | | | | | | | | | | 🔴 见缺口 4：核心文件服务缺 S3 驱动 |

**两行标了跨簇**（`D×E` 组合检索、`G×D` Overlay），它们是仅有的两处会把两条
分支绑死的特性。处理方式：前者经第六节的结构化过滤契约解耦（已实现），
后者待 D 落地后再定归属。

**簇 B 拆成两行是探针的结果**，不是排版。SSO **登录**整行为空——CE 14.0 自带
OAuth2/SAML/CAS/LDAP 且无 Pro 门控，打开它只是往配置块里写标量，一个扩展点
都不需要。真正用到扩展点的是**组织映射**，上游对通用目录没有。
当前结论见 [Authentik 与企业认证](features/sso-authentik.md)；探针过程已归档。
它同时是"**先查上游再登记扩展点**"的一个实例：按原计划，这一行会占掉一个
`provider(认证后端)`，而那个扩展点根本不需要存在。

**读法**：`periodic` 列被 9 个特性依赖——`cf-worker` 是仅次于 `permission_check`
的第二关键投资。`file_op` 列被 8 个特性依赖，这是第二关键的扩展点；它现在有
生产者了（server 侧的写入生命周期，见缺口 1），但矩阵里这一列指的仍是 **Hub**
的 `register_file_op_hook`，那个钩子依旧只补 HTTP 上下文、没有上游触发点。
需要文件事实的特性应当消费 server 侧的 `COMMITTED`。

---

## 四、已知扩展点缺口

按影响范围排。每一条都写明"谁被卡住"和"补法"。

### 缺口 1：缺统一写入生命周期生产者与 veto 点 🟡 **已实现，待整机验收**

> **原文（已作废）**：「`register_file_op_hook()` 可以注册，但上游没有任何地方
> 调用 `run_file_op_hooks()`。Hub 改的 5 个上游文件里，没有一个会触发它。」

Server 侧已按 P0.5 补上 `common/cf-fileop.{c,h}`：`PREPARE`（一票否决）、
`COMMITTED`（成功一次的不可变事实）、`ABORTED`（尽力而为）。规格
[fileop-lifecycle.md](fileop-lifecycle.md)，共享用例集
[fileop-cases.json](fileop-cases.json)。

覆盖面：

- **C**：`server/repo-op.c` 的 19 个写入口，含批量删除、跨库复制/移动的异步
  分支、以及 `SEAF_ERR_CONCURRENT_UPLOAD` 重试循环（重试不会让事实翻倍）。
- **Go**：`fileserver/cf_fileop.go` 经 RPC 问 C，接进上传、更新、分块提交、
  裸块上传、逐级建目录和同步分支更新。**不做第二份判断。**
- **WebDAV**：**不重复校验**——seafdav 的写全部走 `seafile_api.*` → RPC →
  `repo-op.c`，C 的 seam 天然覆盖它。再写一份 Python 校验只会得到第二个真值。
  只补 `patches/seafdav/0002` 的状态码翻译，把 C 的 `CF_ERR_FILE_LOCKED` 拒绝
  从上游默认的 500 翻成 423 Locked。
- **Hub**：`register_file_op_hook` 保持原状，只补 HTTP 上下文，不作事实主路径。

代价：上游改动 33 → 35（`server/repo-op.c`、`fileserver/fileop.go`）。
为什么不放在已经登记过的 `rpc-service.c`——见 fileop-lifecycle.md 第五节。

**整机门禁已补齐但还没跑过**：`verify-local.sh cap fileop`、
两阶段矩阵 `tests/e2e/fileop_matrix.py`，以及它们要的假 provider
`common/cf-fileop-test.c`（默认关闭，刻意不进 `CF_ENABLE_*` 清单）。
单元级证据是 159 项 C 用例、6 项 Go 契约测试、50 个调用点的类型检查、
11 个变异全部被捕获；这些**都不能证明**运行时真的在每个入口被调用到。
所以这条缺口标 🟡 而不是 ✅——**门禁写好了不等于门禁跑过了**，而这正是 ACL
那轮的形状：`acl_matrix.py` 存在很久却没有任何东西调用它，第一次真跑起来就
抓到了第 71 项那个发布过两次的缺陷。

现有 `CfRestrictedFunc` 的路径规范化与子树包含语义已被复用（下沉为
`common/cf-path.c`，ACL 侧留薄转发）。**没有**把锁冲突注册成 ACL restricted
结果：那个 RPC 还服务同步和打包下载，混用会把只读访问误判为不可达。

### 缺口 2：审计的 HTTP 上下文 🟡

即便按缺口 1 的建议下沉到 server 侧，"谁的 IP、用哪个客户端"这类信息只有 Hub 有。
需要决定：是接受审计记录缺少这些字段，还是在 Hub 侧补一个轻量的请求上下文透传。
**建议第一版接受缺失**，等有明确合规要求再补。

### 缺口 3：外部源与虚拟目录融不进原生库列表 ✅ **已重新定价，不再是缺口**

> **原文（已作废）**：「要让它出现在原生文件浏览器的库列表中，**需要改上游的库
> 列举逻辑**。代价为 0 是因为另起了一个入口。」
>
> 这条写在 search 能力之前，**结论是错的**。

`seahub/utils/rooturl.py` 把 `cloudfile_ext.urls` **前置**到 Seahub 自己的
patterns 之前，注释原文是「CloudFile patterns come first so an extension can
shadow a native endpoint when it has to」。第 40 项已经用这个机制覆盖了两个 Pro
门控端点（`cloudfile_ext/search/views.py` 的影子子类），**零上游改动**。

所以真实取舍不是「两套界面 vs 改上游」，而是「两套界面 vs **影子约 8 个只读
端点**」——当前能力边界见 [SMB/NFS 外部资料源](features/external-sources.md)。

**但真正的硬边界不是库列表，是数据面**，而它原先根本没被计价：

```python
# seahub/api2/endpoints/file.py
token = seafile_api.get_fileserver_access_token(repo_id, obj_id, 'download', user)
```

`obj_id` 是内容寻址的 fs 对象 ID。外部源文件**没有 obj_id、没有 block**，这条链
从第一个参数就断了。所以文件内容必须由 Hub 自己吐出（已实现：
`cloudfile_ext/external_sources/apis.py`），而**桌面同步、WebDAV、目录打包下载
对外部源永久不可用**——它们全部以 commit/fs/block 表达。这不是"首版限制"。

**已决定**：先自有入口，再叠影子层。阶段 1 的核心（表、provider 契约、路径包含、
授权、读 API）与呈现方式无关，两种呈现共用同一套核心，所以这个产品决定推迟的
成本是零。

### 缺口 4：C 核心生命周期仍只有 FS 后端 🔴

完整核对见 [多存储与 S3](features/storage-backends.md)。Go fileserver 已实现 S3 与按库路由并经 MinIO
对象读写验证；C 主服务生命周期仍只有 FS：

- `common/obj-store.c:28` 写死 `obj_backend_fs_new`，只有 `obj-backend-fs.c` +
  遗留 `riak`——**没有 S3**。C 侧的 seaf-server / GC（`server/gc/gc-core.c`）/
  FSCK（`fsck.c`）都经这个 `obj_store`。
- Go fileserver 的 `backend_s3.go` 已覆盖 `read/write/exists/stat`，`newBackend()` 可选
  FS/S3/multiple，`RepoStorageId` 可路由到 FS+S3；尚缺真实 MariaDB 的服务级路由 E2E。
- seafobj（Python）已带 S3/OSS/Swift/Ceph，**但那只是 Python 读侧**（seahub 缩略图、
  seafevents 索引读对象），**不在核心写入/服务路径上**。

所以要补的是**C 核心生命周期的存储驱动**：`obj-backend-s3.c` + C 侧后端选择与多存储
`storage_id` 路由，覆盖上传/下载/同步/历史/GC/FSCK/迁移。
接口本身干净（Go 四方法、C 照 fs 后端形状），但这是**实现驱动**，不是登记一行——
是 roadmap 里最重的构建项之一。

### 缺口 5：CE 文件锁是空壳，需从零实现 🔴

源码复核结果：

- `include/seafile-rpc.h` 只有 `seafile_mark_file_locked` /
  `seafile_mark_file_unlocked` 声明；`common/rpc-service.c` 没有实现，
  `server/seaf-server.c` 和 `lib/rpc_table.py` 没有注册。
- `python/seaserv/api.py` 的 `check_file_lock()` 注释明确写着 CE 不支持锁并恒返回 0；
  `lock_file`、`unlock_file`、`get_lock_info` 不存在。
- Go fileserver 没有锁逻辑，`lib/dirent.vala` 的 `is_locked` 也没有 C 侧生产者。
- MySQL/MariaDB 虽有 `FileLocks` DDL，但没有代码读写，不能把“有表”当成锁基础设施。

因此 #44 不是解除 Hub 的 Pro 门控，而是新增 C lock manager、RPC 实现/注册和
Vala/searpc/Python 绑定，再经缺口 1 覆盖 C、Go、WebDAV 的每条写路径。权威数据必须是
CloudFile 自有 `cf_lock_lease(repo_id, normalized_path, generation, lease_until, …)`；
generation 每次获取都生成独立 UUID。`FileLocks.id` 不作 fencing：项目固定的
MariaDB 11.4 已持久化 InnoDB 自增计数器，普通重启复用的反馈不适用于本部署；但兼容
迁移目标表的主键仍不是安全协议，不能让 fencing 依赖其备份恢复、重建/重置和迁移行为。

桌面客户端探针已经证明它不读服务端 `FileLocks`，而是消费 locked-files HTTP、
lock/unlock HTTP、通知并维护本地 `filelocks.db`。因此 CE 运行期不双写 `FileLocks`；
该表只作 CE→Pro 停写迁移目标。租约终判只读 `cf_lock_lease.lease_until`，轮询 revision
来自自有 `cf_lock_repo_revision`。OnlyOffice 依赖 `CF_ENABLE_FILE_LOCK` 基础设施，
不依赖 `CF_ENABLE_CHECKOUT` 产品流程。

**Pro 冲突隔离**：内部 RPC 必须命名为 `cf_lock_*`，Hub 经 `LockBackend` adapter
选择 CE 或 Pro，不能猴子补丁 `seafile_api.lock_file`，也不能同时注册两套 backend。
公开 REST/fileserver 协议保持 Pro 兼容，但数据表和内部符号隔离。进程检测到
`CF_LOCK_BACKEND` 与版本不匹配、重复 RPC 或双 provider 时必须启动失败。

开源桌面客户端还揭示了一个部署陷阱：它只在 server property `is_pro=true` 时轮询
`/repo/locked-files`、自动锁 Office 文件和处理 `file-lock-changed` 通知。CE 不能为此
全局伪装 Pro，否则会连带启用目录权限等其他 Pro 假设；应新增 `file-lock-v1`
capability 并发布 CloudFile 客户端补丁。未修改客户端只能得到服务端写入保护，不能承诺
锁图标或本地只读状态。

行为基线必须对齐 Pro：默认锁期限 12 小时，保留 `expire=0/正数/负数冻结`、特殊 owner
`OnlineOffice`、四态 `check_file_lock`、虚拟库映射、目录锁字段、每库 revision 和通知。
父目录同库移动/重命名默认允许并原子迁移后代锁，父目录删除允许并撤销后代锁；原方案
默认 `strict` 与官方 Pro 语义冲突，已改为显式增强选项。完整矩阵见
[文件协作与本地应用](features/file-collaboration.md)。

---

## 五、目录权限的规则来源扩展

> 需求：目录权限要能从**本地 DB 配置**取，也要能**回调外部服务**取。

### 铁律：外部服务永远不在同步权限判定路径上

诱人的做法是"每次判权限就问一次客户的权限系统"。**不要这么做**：

- `check_folder_permission` 在 Hub 被调用 255 次；seaf-server 每个 RPC 都要判一次。
  在这条路径上加一次网络往返，一个慢接口就能拖垮整台服务器。
- 更糟的是它会把 HTTP 客户端塞进 **C 的终判路径**。那一层不应该做网络调用——
  超时、重试、TLS、连接池，每一样都是在最不该出问题的地方引入新的失败模式。
- 外部服务不可达时怎么办？fail-open 是安全漏洞，fail-closed 是全员被锁在门外。
  这个两难本身就说明位置放错了。

### 正确的位置：规则来源是 provider，终判永远读本地表

```
┌──────────────┐  拉取（cf-worker 周期任务）   ┌─────────────┐
│  外部权限系统 │ ←──────────────────────────── │ external-   │
│ （LDAP/OA/   │  推送（webhook → 自有路由）   │ service     │ ← provider
│   自研）      │ ────────────────────────────→ │ provider    │
└──────────────┘                               └──────┬──────┘
                                                      │ 写入
┌──────────────┐                                      ▼
│  管理员在 Web │ ─────────────────────────────→ ┌─────────────┐
│  上配置       │        local-db provider      │  cf_dir_acl │
└──────────────┘                               └──────┬──────┘
                                                      │ 只读
                        ┌─────────────────────────────┼─────────────────┐
                        ▼                             ▼                 ▼
                  Hub 求解器(Python)          seaf-server(C)      Go fileserver
                   友好错误 / UI              **终判**            同步前子树校验
```

选择由 `CF_PROVIDER_ACL_RULE_SOURCE` 决定：

| provider | 规则来自 | 写入方式 |
|---|---|---|
| `local-db` | 库主 / 管理员在 Web 上配置 | REST API 直接写 `cf_dir_acl` |
| `external-service` | 客户已有的权限系统 | `cf-worker` 周期拉取 + webhook 推送，写同一张表 |

这个设计的四个好处：

1. **求解器、C 侧、Go 侧一行都不用改。** 它们只知道读表，不知道规则从哪来。
2. **判权限的延迟不变**，外部服务再慢也影响不到在线请求。
3. **外部服务挂了，权限仍然按最后一次同步的规则执行**——既不放开也不锁死，
   而且这个行为是可解释、可监控的（同步时间戳可见）。
4. **复用了已经铺好的基线**：`register_periodic_task`（cf-worker）、
   `register_urls`（webhook 入口）、`cf_dir_acl` 表、`external_service.py`，
   四样全是现成的，**新增上游改动为 0**。

代价是**最终一致**：外部系统改了权限，到 CloudFile 生效有同步延迟。
webhook 推送可以把延迟压到秒级；纯周期拉取则取决于间隔。这个取舍必须写进
客户对接文档——它是这套设计里唯一真正的妥协。

**需要实时决策的场景**（例如按请求上下文动态判权）不在第一版范围内。真要做，
正确的位置是 Hub 侧的 `permission_check` 链里加一个带超时和缓存的 provider，
**且明确只影响 Hub 入口，不改变 server 的终判**——但那时要接受"两层结论可能不一致"，
需要单独的规格来定义。

### 实现归属

规则来源 provider 属于**目录 ACL 能力**，实现在 `feature/dir-acl`：

```
cloudfile_ext/acl/sources/local_db.py         ← register_provider('acl_rule_source', 'local-db', …)
cloudfile_ext/acl/sources/external_service.py ← register_provider('acl_rule_source', 'external-service', …)
```

基线只提供机制（`providers.py`、`external_service.py`、周期任务、webhook 路由能力），
不认识 `acl_rule_source` 这个 kind——设置名由 kind 推导，所以新增 kind 不需要改基线。

---

## 六、search 的扩展形状

> 需求：search 要可扩展，meilisearch 只是其中一种方式。

```
seahub/utils/__init__.py       HAS_FILE_SEARCH ← 或上 provider 是否已配置
        │                      （不接这里，CE 上六个入口根本不会路由到搜索）
        ▼
seahub/api2/…  搜索入口（6 处，全部读 HAS_FILE_SEARCH）
        ▼
seahub/search/utils.py  search_files()
        │
        ├─ CloudFile provider 应答 ──→ 返回 (hits, total)
        └─ 未选中 → es_search()（原生 Elasticsearch 路径，逐字节不变）
        │
        ▼
   Seahub 原有后处理：库归属解析、虚拟根重写、dirent 查询、**库级可见性收敛**
```

**为什么切在 `search_files` 而不是六个入口**：一是把上游改动压到一个函数；
二是 provider 自动继承 Seahub 的库范围收敛逻辑——如果让 provider 自己实现，
一旦写错就是跨库泄露文件。**让后端只负责"匹配文档"，不负责"能看见哪些库"。**

provider 契约：

```python
search_files(repos_map, search_path, keyword, obj_desc,
             start, size, org_id, search_filename_only,
             filters=None) -> (hits, total)
# hits: [{'repo_id': ..., 'fullpath': ..., ...}, ...]
```

### 结构化过滤：让元数据与检索能各自独立开发

`filters` 是**属性/标签谓词**（`cloudfile_ext/search_query.py`），与上游的
`obj_desc`（类型、后缀、时间、大小等文件固有属性）正交，两者同时传入。

**它存在的理由是分支切分，不是功能。** 组合检索——"标了『合同』、部门是
『法务』、正文含『违约金』的文件"——同时需要元数据簇（拥有字段）和检索簇
（拥有索引）。没有共享词汇，这个特性只能落在其中一条分支上，那条分支就再也
无法脱离另一条开发和验收，两个簇塌成一条大分支、一个长验收周期。

有了词汇表之后：

| 簇 | 职责 | 独立验收方式 |
|---|---|---|
| D 元数据 | 声明字段、喂索引、用这套词汇发起查询 | 假 provider 记录"被要求了什么" |
| E 检索 | 把词汇翻译成后端自己的过滤语法 | 合成文档验"过滤正确" |

组合检索的端到端验收需要两者同时在场，那属于 `dev` 上的**集成门禁**，
不归任一分支。

算子刻意保持精简（`eq` `ne` `in` `contains` `gt` `gte` `lt` `lte` `exists`）——
词汇表一旦超出最弱后端的表达能力，不兼容就只是被推迟到运行时。

**provider 必须声明自己支持哪些算子：**

```python
class MeilisearchProvider:
    supported_filter_ops = frozenset({search_query.EQ, search_query.IN})
```

未声明的算子在**调用 provider 之前**就被拒绝。不声明 = 不支持任何算子，
于是只会被以无过滤的形式调用——所以老 provider 不受影响。

> **为什么是拒绝而不是忽略**：被丢掉的谓词返回**比请求更大**的结果集，
> 而调用方无法区分"没有文件带这个标签"和"标签条件被忽略了"——两种情况看起来
> 一模一样。同样的道理适用于 `parse()` 拒绝无法识别的键：一个拼错的键
> 被丢掉，查询就悄悄变宽了。

已规划的实现：

| name | 归属 | 说明 |
|---|---|---|
| `meilisearch` | 簇 E，✅ 已实现 | `cloudfile_ext/search/backends/meilisearch.py`，`CF_PROVIDER_SEARCH=meilisearch` 选中 |
| （无 `seasearch` provider） | — | **确认不需要注册**：上游 CE 14.0 的 SeaSearch 走 `seahub/api2/views.py` 里独立的 `elif HAS_FILE_SEASEARCH` 分支（`ai_search_files`），完全不经过这个 provider 机制——`CF_PROVIDER_SEARCH` 留空就是默认，见 [检索](features/search.md) |
| 企业自有检索 | 客户对接，⬜ 未实现 | 经 `external_service.py` 调用，契约同上 |

> **两个上游改动的取舍**：`search/utils.py`（查询分发）与 `utils/__init__.py`
> （`HAS_FILE_SEARCH` 或上）。后者不接的话，CE 部署里六个入口根本不会走到搜索，
> provider 永远不被调用。两处都是"或上/回落"式的加法改动，不改变原生行为，
> 但**确实让 Hub 的上游文件从 3 个变成 5 个**，已登记在
> [upstream-patches/cloudfile-hub.txt](upstream-patches/cloudfile-hub.txt)。

---

## 七、维护这份文档

新增扩展点时：

1. 在第二节登记（形状、上游调用点、基线行为）
2. 在第三节矩阵里补一列，标出哪些特性依赖
3. 如果它**没有上游调用点**，写进第四节缺口，并说明谁被卡住

`tools/preflight-checks.py` 会检查 `registry.py` 里声明的每个钩子是否都在这份
文档的矩阵里出现——防止扩展点加了却没人知道。

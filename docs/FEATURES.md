# CloudFile 特性清单与完成情况

Seafile CE 企业扩展版的全部规划特性，以及截至 `14.0.0-cf.0` 的实际状态。

状态口径**刻意区分"写完"和"验证过"**——权限系统里这两者差别很大：

| 标记 | 含义 |
|---|---|
| ✅ | 已实现，**且有自动化测试或可复现的验证证据** |
| 🟡 | 已实现，但**尚未端到端验证**（多数是因为需要 Linux 构建或运行中的部署） |
| ⚠️ | 已知缺口，已在文档中声明 |
| ⬜ | 未开始，仅有占位与注册点 |

**交付分成两层**，各有各的门禁，互不阻塞：

| 层 | 归属 | 内容 | 门禁 |
|---|---|---|---|
| **扩展基线** | `dev` | 扩展点、构建、部署、发布机制 | 构建镜像 + 原生 CE 冒烟 + 扩展点验收（开关全关） |
| **能力** | 开发中在 `feature/<簇>`，**验收后合回 `dev`** | 具体能力，默认关闭 | 各自的用例集，开着自己那个开关跑 |

> **开关粒度 ≠ 分支粒度。** 十个 `CF_ENABLE_*` 对应**八个耦合簇**——例如属性与
> 标签是两个开关、一条分支，因为它们共享同一张表。簇的划分依据（共享表 /
> 共享规格 / 共享上游补丁 / 运行时互调）见 [BRANCHES.md](BRANCHES.md) 第一之二节。

> **基线已经真跑起来过了**（`ced53b2`，本机全流程）：发行包构建 → 镜像构建 →
> 起栈 → **12/12 原生 CE 冒烟 + 6/6 扩展点验收**。此前"完整镜像从未成功构建过"
> 那句话已经作废，大量 🟡 因此转 ✅。
>
> **仍未验证的一面**：这一轮是在本机（arm64）跑的，**CI 上尚未完整跑过一次**。
> 架构、磁盘配额、PATH 都是 CI 与本机的已知差异面——十二次失败里有六次
> 正是栽在这类边界上。

> **`feature/dir-acl` 已重建**（`feature/dir-acl-rebuild`）。原分支是 `dev` 的
> 祖先、没有任何独有提交，`git merge dev` 会快进并静默删光 ACL 代码。
> 新分支从最新基线重新接线，**三仓上游改动清单一个字节未变**（8 / 5 / 3），
> 这是扩展点设计的实证。已跑通：C 62 项、Python 52 项、Go 编译与 vet。
> **六入口矩阵仍未执行**——它需要构建镜像，见待办 1。

---

## P0 — CE 兼容基线

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 1 | 三仓 fork 与分支模型 | ✅ | `dev` 为主干，`upstream/master` remote-tracking ref 作纯净副本，见 [BRANCHING.md](../BRANCHING.md) |
| 2 | 统一版本号与发布清单 | ✅ | [release.yaml](../release.yaml)，各组件按 commit SHA 锁定 |
| 3 | 功能开关机制（10 个 `CF_ENABLE_*`） | ✅ | 默认全关；配置块重写幂等性已验证 |
| 4 | 扩展注册机制 | ✅ | URL / 菜单 / 权限 / 文件操作 / 索引器 / 外部源 / 周期任务；分发与 seal 行为已验证 |
| 5 | `cloudfile_ext` Django app | ✅ | 通过 `EXTRA_INSTALLED_APPS` 注册，未改 `settings.py` |
| 6 | 上游注入点最小化 | ✅ | Hub 5 个（2 处权限/路由 + 2 处检索扩展点 + 1 处数据追加）；Server 8 个；Docker 3 个。合计 **16**，清单由 `check-upstream-patches.sh` 卡住 |
| 7 | 前端骨架与入口注册 | ✅ | 入口映射已验证可加载；基线页面为能力总览；已随镜像打包 |
| 55 | 前端资源构建接入 | ✅ | `seafile-build.py` 的 Seahub 阶段只复制源码树，`media/assets` 只存在于上游 dist 分支——原先的构建会产出没有 Web 界面的镜像。已在 `cloudfile-build.sh` 中加入 `npm run build` + `make dist`，并在缺失时直接失败。**Node 版本已固定**：apt 给的是 18.19.1，seahub 前端需要 20+ |
| 56 | CI：快速检查门禁 | 🟡 | 三仓共用 `tools/run-checks.sh`；本地已全绿，**CI 上尚未跑过** |
| 57 | CI：构建 + E2E 门禁 | 🟡 | `build-and-e2e.yml` 的全部步骤已在本机经 `verify-local.sh` 跑通；**CI 上尚未执行过** |
| 61 | 本机全流程门禁 `verify-local.sh` | ✅ | 与 CI 同一套步骤搬到本机。存在的理由：CI 一轮 20 分钟，而前六次失败全在集成边界上，没有一个是 `bash -n` 或单元测试能发现的 |
| 62 | `preflight-checks.py` 静态一致性 | ✅ | 秒级。每一条都是一次已付出代价的失败的事后检查，且**每个检测器都通过"破坏它监视的东西"验证过会失败**——不会失败的检查比没有检查更危险，因为它读起来像覆盖 |
| 8 | CE 14.0 镜像 | ✅ | 与 13.0 CE 镜像的 diff 已核对（仅注释与版本 pin）；已构建成功（arm64；amd64 已验证构建脚本，未产出镜像） |
| 9 | SHA pin 构建脚本 | ✅ | 已实际执行并产出发行包 |
| 10 | Compose 一键部署 | ✅ | 4 个 profile 配置已验证；栈已实际启动并通过 E2E |
| 11 | `cf-worker` 后台进程 | 🟡 | 命令已实现；当前无任何周期任务注册，故置于 `worker` profile 而非默认集合。**未随栈启动验证过** |
| 12 | **原生 CE 回归测试** | ✅ | `tests/e2e/smoke.py`，**12/12 通过**：登录取 token、账号信息、建库、建目录、取上传链接、上传、列举、下载校验、分享链接、WebDAV 列举、可同步、删库 |
| 58 | server 侧扩展点 `cf-ext` | 🟡 | 能力注册表 + 权限/列举/子树三个分发钩子；**C 编译已通过 CI**，基线上三个钩子全透传（已由 baseline.py 间接验证），**注册了能力时的运行时行为未验证** |
| 59 | 扩展点装配验收 | ✅ | `tests/e2e/baseline.py`，**6/6 通过**。这条门禁的价值当场兑现了：`bootstrap` 写进 `seahub_settings.py` 的 `DATABASES['cloudfile']` 触发 `NameError`，被 seahub 吞掉后**丢弃了该文件全部 CloudFile 配置**——服务照常启动、冒烟全绿，而扩展框架根本没加载。只跑 smoke 发现不了 |
| 60 | 基线与能力分层 | ✅ | ACL 整体剥离到 `feature/dir-acl`；剥离前后三仓上游改动清单**逐字节不变**，证明能力可独立演进而不增加 fork 成本 |
| 63 | 扩展点形状：链 与 provider | ✅ | `providers.py`：同一件事的可互换实现，由 `CF_PROVIDER_<KIND>` 选中，未选中回落原生、选了不存在的名字则显式失败。**8 项单元测试，且经变异测试确认会失败** |
| 64 | 检索查询侧扩展点 | 🟡 | `register_search_provider()` + `seahub/search/utils.py`、`seahub/utils/__init__.py` 两处上游改动。meilisearch 由此成为**一种** provider 而非唯一方案。**未随镜像验证** |
| 65 | 外部服务回调机制 | 🟡 | `external_service.py`：超时 / JWT 签名 / 重试 / fail-closed。**刻意不放在同步权限判定路径上**，理由见 EXTENSION-POINTS.md 第五节。**尚无调用方** |
| 67 | 检索结构化过滤契约 | ✅ | `search_query.py`：属性/标签谓词词汇表 + provider 能力声明。**存在的理由是分支切分**——没有它，组合检索会把元数据和检索焊成一条大分支。硬性规定：provider 收到未声明支持的算子必须拒绝，**不允许静默忽略**（被丢掉的谓词返回比请求更大的结果集，而调用方看不出差别）。**15 项单元测试，3 个变异全部被捕获** |

---

## P1 — 目录级 ACL（`feature/dir-acl`）

代码已完成，等待它自己的 E2E 门禁。规格、用例集与矩阵随该分支走，不在 `dev` 上。

### 实现

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 13 | 语义规格 | ✅ | [acl-semantics.md](acl-semantics.md)，含继承、主体优先级、收紧不变量 |
| 14 | 共享用例集 | ✅ | [acl-cases.json](acl-cases.json)，21 个场景 / 49 条断言 |
| 15 | Hub 求解器（Python） | ✅ | 52 项测试通过 |
| 16 | Server 求解器（C） | ✅ | 62 项检查通过 |
| 17 | 两端语义一致性 | ✅ | 同一份用例集驱动两端，结果一致 |
| 18 | "只收紧不放宽"安全不变量 | ✅ | 两端各自穷举整个权限格验证 |
| 19 | `cf_dir_acl` 建表 | ✅ | SQLite DDL 已执行验证（含幂等）；MySQL DDL 语句解析已验证但**未对真实 MySQL 执行** |
| 20 | 每次启动建表（覆盖新装/升级/存量切换） | 🟡 | 逻辑已写；**未在真实容器中执行** |
| 21 | `check_permission_by_path` 接入扩展点 | ✅ | **C 编译已通过 CI**（`cf-acl.o` / `cf-acl-resolve.o`，零警告）；运行时未验证 |
| 22 | `cf_find_restricted_path` RPC | ✅ | 同上 |
| 68 | 经 `cf_ext_register` 接线（不再直连上游） | ✅ | 重建时改为在 `cf_acl_init()` 里注册三个函数，`rpc-service.c` 只认 `cf_ext_*`。**接线后三仓上游清单逐字节不变**（8 / 5 / 3），且 Go 侧零改动——seam 契约的实证 |
| 69 | ACL 能力门禁 `acl-e2e.yml` | 🟡 | **本轮补齐**。此前只有孤立的 `acl_matrix.py`，没有任何东西调用它——"有测试文件"和"有门禁"在权限系统里差别巨大。顺带给 `acl_matrix.py` 补了 `--insecure`（它写于 TLS 改动之前，在自签证书下必然连不上）。**尚未执行** |
| 23 | Go fileserver 同步前校验 | 🟡 | `go build` / `go vet` 通过；**未运行** |
| 24 | `is_repo_syncable` / `is_dir_downloadable` | 🟡 | 替换了 CE 的恒真桩；仅字节编译 |
| 25 | ACL 管理 REST API（库主） | 🟡 | 含"有效权限"排查接口；仅字节编译 |
| 26 | ACL 管理 REST API（系统管理员） | 🟡 | 含整库清空的应急出口；仅字节编译 |
| 27 | 前端配置面板 | 🟡 | 已写；**未打包运行** |

### ACL 入口覆盖

| # | 入口 | 状态 | 说明 |
|---|---|---|---|
| 28 | Web UI | 🟡 | 经 `check_folder_permission`，代码路径确认 |
| 29 | REST API | 🟡 | 同上，255 处调用点全覆盖 |
| 30 | WebDAV **写** | 🟡 | seafdav 的写操作全部经 `check_permission_by_path` RPC，已核对上游源码 |
| 31 | WebDAV **读** | ⚠️ | **已知缺口**：seafdav 列举与 GET 不经过该 RPC，`invisible` 在读侧不生效 |
| 32 | 分享链接 / 下载链接 | 🟡 | token 由 Hub 签发，天然覆盖 |
| 33 | 目录打包下载 | 🟡 | 经 `is_dir_downloadable`，子树内任一不可读即拒绝 |
| 34 | 桌面同步客户端 | 🟡 | Go fileserver 在同步前查子树；Hub 的 `is_repo_syncable` 只负责给出友好错误 |
| 35 | 移动 / 复制 / 重命名 | 🟡 | 已逐个审计：7 个批量端点均同时校验源与目标 |
| 54 | 目录列举过滤 `invisible` | 🟡 | **本轮补齐**。上游 `list_dir_with_perm` 只按库级判一次权限并盖到每个条目，`invisible` 目录仍会被列出。已在 `rpc-service.c` 的 RPC 出口按路径逐条过滤，覆盖全部调用方 |

### 其它 P1

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 36 | SSO 登录与用户/组织映射 | ⬜ | 占位，`CF_ENABLE_SSO`。真正的零上游成本 |
| 37 | 操作日志 / 审计 | ⬜ | 占位，`CF_ENABLE_AUDIT`。post 文件操作钩子已预留（吞异常，不影响写入），但 ⚠️ **它没有任何上游触发点**——见待办 3。落地前先定钩子位置 |
| 66 | ACL 规则来源可扩展 | ⬜ | 设计已定：`local-db` 与 `external-service` 两个 provider，**终判永远读本地表**，外部系统经 cf-worker 周期拉取 + webhook 推送喂表，C 侧不引入 HTTP。见 [EXTENSION-POINTS.md](EXTENSION-POINTS.md) 第五节。基线机制已就位，实现归 `feature/dir-acl` |

---

## P2 — 信息管理能力

**簇 D（`feature/metadata`）** —— 38 / 39 / 42 是一条分支，因为它们共享同一张表。
标签是属性的特化；42 是 38/39 的正确性要求，不是独立特性。两个开关
（`CF_ENABLE_METADATA`、`CF_ENABLE_TAGS`），一条分支。

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 38 | 文件属性扩展 | ⬜ | ⚠️ **上游 CE 已带 `seahub/repo_metadata/`**（完整 API + 前端，无 Pro 门控），经 SQL-over-HTTP 连一个闭源 metadata-server。写一个协议兼容的服务可能比自研便宜一个数量级 —— **先做探针** |
| 39 | 标签 | ⬜ | 与 38 同表同分支。上游还有 `seahub/tags/`、`file_tags/`、`repo_tags/` |
| 42 | 移动重命名时元数据关联更新 | ⬜ | 与 38 同分支。依赖 `file_op` 钩子（待办 3） |

**簇 E（`feature/search`）** —— 与簇 D **可真并行**，靠第 67 项的过滤契约解耦。

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 40 | 索引与检索 | ⬜ | 查询侧扩展点**已就位**（第 64 项）。meilisearch 是其中一个 provider；**seasearch 也是**，而上游 CE 14.0 已自带其集成——选型待探针 3 |
| 41 | 属性 / 标签 / 内容组合检索 | ⬜ | **跨簇（D × E）**。经第 67 项的契约解耦：D 喂字段、E 翻译过滤，各自独立验收；端到端验收属 `dev` 上的集成门禁，不归任一分支 |

Compose 的 `search` profile 与 `cf-worker` 已就位，实现时不需要再动部署。

> **这一段的规模高度不确定，且不确定性是可以消除的**：三个探针各 1～2 天，
> 结论可能让 P2 从"五个特性从零做"缩成"一个服务 + 配置"。
> 见 [BRANCHES.md](BRANCHES.md) 第八节。

---

## P3 — 协同与项目流程

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 43 | OnlyOffice 编辑与回调 | ⬜ | ⚠️ **上游 CE 已带 `seahub/onlyoffice/`**（views / converter / callback / models 全套），只有锁集成两行是 Pro 门控。规模远小于原估——待探针 2 |
| 44 | 文件锁定强制校验 | ⬜ | server 侧免费（`seafile_mark_file_locked` RPC 与 `FileLocks` 表上游都已有）；**Hub 侧被 `is_pro_version()` 门控**，散在四个未登记的上游文件里。见 [EXTENSION-POINTS.md](EXTENSION-POINTS.md) 缺口 5 |
| 45 | 签入签出流程 | ⬜ | 依赖 44 |
| 46 | iTeam 流程接口 | ⬜ | 依赖 45 |
| 47 | 编辑超时与异常解锁 | ⬜ | 依赖 44 |
| 48 | OnlyOffice 回调幂等 | ⬜ | 依赖 43 |

Compose 的 `office` profile 已就位。第一阶段只支持 Seafile 主存储文件。

---

## P4 — 存储扩展

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 49 | S3 类主存储 | ⬜ | 1 个新增登记项（`common/obj-store.c:28` 的后端选择）。seafobj 上游已自带 s3/ceph/swift/alioss，Python 读取侧无需 fork |
| 50 | SMB/NFS 外部资料源 | ⬜ | 零上游改动，但**代价是另起一个入口**——不改上游就进不了原生库列表。见 [EXTENSION-POINTS.md](EXTENSION-POINTS.md) 缺口 3。这是产品决定，不是技术决定 |
| 51 | 外部源增量扫描 | ⬜ | 依赖 50 + `cf-worker` |
| 52 | 虚拟目录挂载 | ⬜ | 依赖 50；融入原生 UI 的问题同 50 |
| 53 | Overlay 标签与属性 | ⬜ | 依赖 50 + 38 |

外部源首版只读，不进入 Seafile 的 repo/commit/block 模型。

---

## 待办与审计发现

按阻塞程度排。

1. 🔴 **跑一次 ACL 六入口矩阵**。分支已重建、`acl-e2e.yml` 已补齐，静态与单元
   层面全绿（C 62 / Python 52 / Go vet），但**矩阵本身从未执行过**——它需要一个
   构建出来的镜像。这是 ACL 合回 `dev` 的最后一道门槛：单元测试证明求解器算得对，
   只有矩阵能证明**每个入口真的执行了算出来的结果**，而 ACL 最容易出的问题恰恰
   是某个入口压根没走校验。
2. 🔴 **WebDAV 读侧 `invisible` 缺口**（第 31 项）。**这是发布阻塞项，不是待办**：
   一个"目录对某人不可见"的能力，在 WebDAV 入口下目录仍然可见，这个能力就是
   不成立的。修复需要改 seafdav，建议在 `cloudfile-docker/patches/seafdav/`
   放补丁由构建脚本 `git apply`，避免引入第四个 fork。
3. 🔴 **`file_op` 钩子没有生产者**。`register_file_op_hook()` 注册得了，但上游
   没有任何地方调用 `run_file_op_hooks()`——注册了一个永不触发的回调。审计、
   文件属性、标签、元数据跟随、OnlyOffice、文件锁、签入签出，**七个特性依赖它**。
   见 [EXTENSION-POINTS.md](EXTENSION-POINTS.md) 缺口 1。
4. 🟠 **在 CI 上完整跑一次 `build-and-e2e.yml`**。本机已全绿，CI 与本机在架构、
   磁盘配额、PATH 上都有已知差异，而十二次失败里六次正是栽在这类边界。
5. 🟠 **上游 CE 14.0 已带了 P2/P3 的一大半**（`repo_metadata`、`tags`、
   `file_tags`、`repo_tags`、`onlyoffice`、seasearch），且大多**无 Pro 门控**——
   `repo_metadata` 只缺闭源的 metadata-server。在 `cloudfile_ext` 里另起一套
   属性/标签系统等于重写上游已开源的前端和 API。**动工前先做探针**，
   见 [BRANCHES.md](BRANCHES.md) 第八节。
6. 🟡 **MySQL DDL 未对真实 MySQL 执行**（第 19 项），仅验证了语句切分与 SQLite 变体。
7. 🟡 **上游遗留问题**：`seahub/api2/endpoints/repos_batch.py` 的
   `BatchMoveItemsUpdatePath` 完全没有权限校验（上游 docstring 自述
   "all authenticated user can perform this action"）。它只更新路径记录、
   不搬运数据，但允许任何登录用户对任意库提交路径更新。属于上游问题，
   不是 CloudFile 引入的回归，需单独评估。
8. 🟡 **上游 `Seafile CI` 在 fork 上永远失败**：`ci/run.py` 写死
   `join(TOPDIR, 'seafile-server')`，而仓库名是 `cloudfile-server`。与我们的代码
   无关。已改为从自己的 workflow 里把仓库 checkout 成那个目录名来获得 C 编译覆盖。
   **待办：在 GitHub 的 Actions 页面把 `Seafile CI` 这个 workflow 停用**
   （仓库 → Actions → 选中该 workflow → Disable workflow）。
   刻意**不**改 `.github/workflows/ci.yml`——那是上游文件，为了消一个红叉把登记
   清单从 8 涨到 9 不划算，而 UI 上停用是零仓库改动。

## 十二次构建失败换来的东西

这段历史值得留着——它解释了 `verify-local.sh` 与 `preflight-checks.py` 为什么存在。

**CI 上六轮，六个集成边界问题**：PATH、构建期依赖链、系统库、版本号格式、
TLS、主机名。没有一个是 `bash -n`、单元测试或 code review 能发现的，
每一个都要花二十分钟才换来一条事实。这个循环太慢，于是把同样的门禁搬到本机。

**本机首跑，又六个**，其中三个是 CI 根本发现不了、甚至**主动掩盖**的：

- `DATABASES['cloudfile']` 的 `NameError` 吞掉全部 CloudFile 配置——服务看起来
  健康，扩展框架却没装上。更值得记的是它为什么溜过了此前的 Django 加载测试：
  那个测试的 fixture 是**手写的** `seahub_settings.py`，恰好没有那一行。
  **与被测代码实际产出不一致的 fixture，什么都证明不了。**
- Node 来自 apt（18.19.1），而 seahub 前端需要 20+。CI 一直是绿的，
  因为 runner 预装的 Node 20 排在 PATH 前面——**绿灯掩盖了构建对任何人都不可复现**。
- `docker-build.sh` 用 `release.yaml` 而不是版本参数打 tag，
  任何能力分支的构建都会悄悄覆盖发布 tag。

其余三个：14.0 的 `seafile.sh` 要求 `conf/.env` 里有 `JWT_PRIVATE_KEY` 否则退出 255
而没人生成它；Caddy 只绑到站点地址（对 IP 而言是容器自己的 loopback）；
对 IP 建 TLS 不发 SNI（RFC 禁止），Caddy 匹配不到证书。

**现在这十二条全部变成了秒级的 preflight 检查，且每一个检测器都通过"破坏它监视
的东西"确认过会失败。** 其中两个第一版是错的，正是这个动作抓出来的：开关清单
检查漏了 `re.M` 所以永远报"一致"，主机名检查读的是 sed 的查找模式而不是替换值。

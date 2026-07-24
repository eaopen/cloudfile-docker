# CloudFile 特性清单与完成情况

Seafile CE 企业扩展版的全部规划特性，以及截至 `14.0.0-cf.0` 的实际状态。

> **按 Pro 对标读这份清单**：哪些是"要构建的机制"、哪些只是"要启用的配置"，
> 见 [pro-parity.md](pro-parity.md)——它把官方 Pro vs CE 对比逐项映射到这里。
> 一句话结论：Pro 对比表约一半特性 CloudFile **已有源码、只差启用**（打包层，
> 不开分支）；要真写的机制集中在下面的耦合簇里，外加一个 Antivirus。

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
> 起栈 → **12/12 原生 CE 冒烟 + 9/9 扩展点验收**。此前"完整镜像从未成功构建过"
> 那句话已经作废，大量 🟡 因此转 ✅。
>
> **仍未验证的一面**：这一轮是在本机（arm64）跑的，**CI 上尚未完整跑过一次**。
> 架构、磁盘配额、PATH 都是 CI 与本机的已知差异面——十二次失败里有六次
> 正是栽在这类边界上。

> **`feature/dir-acl` 已重建并通过全部门禁**（`feature/dir-acl-rebuild`）。
> 原分支是 `dev` 的祖先、没有任何独有提交，`git merge dev` 会快进并静默删光
> ACL 代码。新分支从最新基线重新接线，**三仓上游改动清单一个字节未变**
> （8 / 5 / 3），Go 侧零改动——这是扩展点设计的实证。
>
> **六入口矩阵 28/28 通过**（含 WebDAV 读侧 5 项），开着 `CF_ENABLE_DIR_ACL` 的冒烟 12/12。
> 加上 C 62 项、Python 87 项、基线门禁 12/12 + 9/9，
> [BRANCHES.md](BRANCHES.md) 第六节的合并门槛已全部满足。

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
| 56 | CI：快速检查门禁 | ✅ | 三仓共用 `tools/run-checks.sh`；GitHub Actions `30048595750` 已成功 |
| 57 | CI：构建 + E2E 门禁 | ✅ | `build-and-e2e.yml` 的全部步骤已在本机经 `verify-local.sh` 跑通；GitHub Actions `30048596090` 已成功 |
| 61 | 本机全流程门禁 `verify-local.sh` | ✅ | 与 CI 同一套步骤搬到本机。存在的理由：CI 一轮 20 分钟，而前六次失败全在集成边界上，没有一个是 `bash -n` 或单元测试能发现的 |
| 62 | `preflight-checks.py` 静态一致性 | ✅ | 秒级。每一条都是一次已付出代价的失败的事后检查，且**每个检测器都通过"破坏它监视的东西"验证过会失败**——不会失败的检查比没有检查更危险，因为它读起来像覆盖 |
| 8 | CE 14.0 镜像 | ✅ | 与 13.0 CE 镜像的 diff 已核对（仅注释与版本 pin）；已构建成功（arm64；amd64 已验证构建脚本，未产出镜像） |
| 9 | SHA pin 构建脚本 | ✅ | 已实际执行并产出发行包 |
| 10 | Compose 一键部署 | ✅ | 4 个 profile 配置已验证；栈已实际启动并通过 E2E |
| 11 | `cf-worker` 后台进程 | ✅ | `worker` profile 共享主服务 RPC socket；SSO 矩阵验证首次周期任务成功执行，且不破坏上传、下载与 WebDAV |
| 12 | **原生 CE 回归测试** | ✅ | `tests/e2e/smoke.py`，**12/12 通过**：登录取 token、账号信息、建库、建目录、取上传链接、上传、列举、下载校验、分享链接、WebDAV 列举、可同步、删库 |
| 58 | server 侧扩展点 `cf-ext` | ✅ | 能力注册表 + 权限/列举/子树三个分发钩子。基线上全透传（baseline.py 9/9），**注册了 ACL 之后三个钩子的运行时行为均已验证**：权限收紧、`invisible` 从列举消失、子树校验拒绝同步与打包 |
| 59 | 扩展点装配验收 | ✅ | `tests/e2e/baseline.py`，**9/9 通过**（含新增的 provider 与检索三项）。这条门禁的价值当场兑现了：`bootstrap` 写进 `seahub_settings.py` 的 `DATABASES['cloudfile']` 触发 `NameError`，被 seahub 吞掉后**丢弃了该文件全部 CloudFile 配置**——服务照常启动、冒烟全绿，而扩展框架根本没加载。只跑 smoke 发现不了 |
| 60 | 基线与能力分层 | ✅ | ACL 整体剥离到 `feature/dir-acl`；剥离前后三仓上游改动清单**逐字节不变**，证明能力可独立演进而不增加 fork 成本 |
| 63 | 扩展点形状：链 与 provider | ✅ | `providers.py`：同一件事的可互换实现，由 `CF_PROVIDER_<KIND>` 选中，未选中回落原生、选了不存在的名字则显式失败。**8 项单元测试，且经变异测试确认会失败** |
| 64 | 检索查询侧扩展点 | 🟡 | `register_search_provider()` + `seahub/search/utils.py`、`seahub/utils/__init__.py` 两处上游改动。meilisearch 由此成为**一种** provider 而非唯一方案。**未随镜像验证** |
| 65 | 外部服务回调机制 | 🟡 | `external_service.py`：超时 / JWT 签名 / 重试 / fail-closed。**刻意不放在同步权限判定路径上**，理由见 EXTENSION-POINTS.md 第五节。**尚无调用方** |
| 67 | 检索结构化过滤契约 | ✅ | `search_query.py`：属性/标签谓词词汇表 + provider 能力声明。**存在的理由是分支切分**——没有它，组合检索会把元数据和检索焊成一条大分支。硬性规定：provider 收到未声明支持的算子必须拒绝，**不允许静默忽略**（被丢掉的谓词返回比请求更大的结果集，而调用方看不出差别）。**15 项单元测试，3 个变异全部被捕获** |

---

## P1 — 目录级 ACL（`feature/dir-acl`）

**已通过自己的 E2E 门禁（28/28），无已知缺口。** 规格、用例集与矩阵随该能力一起进 `dev`，
`acl-e2e.yml` 作为一个开着 `CF_ENABLE_DIR_ACL` 跑的 CI job。

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
| 20 | 每次启动建表（覆盖新装/升级/存量切换） | ✅ | 已在真实容器中执行：新装路径每轮重跑，`cf_dir_acl` 每次都建出来 |
| 21 | `check_permission_by_path` 接入扩展点 | ✅ | C 编译零警告；**运行时已验证**——矩阵每一条拒绝都经由它 |
| 22 | `cf_find_restricted_path` RPC | ✅ | 运行时已验证：打包下载与同步两项都靠它给出子树结论 |
| 68 | 经 `cf_ext_register` 接线（不再直连上游） | ✅ | 重建时改为在 `cf_acl_init()` 里注册三个函数，`rpc-service.c` 只认 `cf_ext_*`。**接线后三仓上游清单逐字节不变**（8 / 5 / 3），且 Go 侧零改动——seam 契约的实证 |
| 69 | ACL 能力门禁 `acl-e2e.yml` | ✅ | **本轮补齐**。此前只有孤立的 `acl_matrix.py`，没有任何东西调用它——"有测试文件"和"有门禁"在权限系统里差别巨大。顺带给 `acl_matrix.py` 补了 `--insecure`（写于 TLS 改动之前，自签证书下必然连不上）。已在本机跑通，**28/28**。第一次运行就当场抓到第 71 项那个缺陷——这条门禁的价值在它存在的第一天就兑现了 |
| 70 | 本地能力门禁 `verify-local.sh cap <能力>` | ✅ | 此前本地**只能跑基线门禁**，能力门禁得从 workflow 手抄——`acl_matrix.py` 缺 `--insecure` 就是这么留下来的。现在开着开关起栈 + 跑能力用例，与 `<能力>-e2e.yml` 同序。写完 `.env` 后**验证开关确实为 true**：开关没开却全绿的矩阵毫无意义，且失败完全静默 |
| 71 | ACL 主体身份解析 | ✅ | 🔴 **矩阵抓到的真实缺陷，且修复本身错了两次**。第一版与第二版都先问"这个字符串已经是身份了吗"（`ccnet_api.get_emailuser`），而**那个函数连邮箱也认**——于是邮箱通过了身份检查、被原样存下，缺陷原封不动。第三版把顺序倒过来：先做邮箱→身份映射，映射不动时才回落。查询函数改为可注入，**逻辑因此第一次变得可单测**——不可测正是它两轮没被发现的原因。7 项测试 + 变异复现了那个发布过两次的错误顺序。**第三版已随镜像验证：矩阵 23/23**。Seafile 14 把身份与邮箱拆开（账号主键是 `<hex>@auth.local`，邮箱降为登录属性），而终判拿到的是身份。**按邮箱下发的规则永远匹配不上，且不报错、不记日志、接口返回 200**——管理员以为限制了访问，实际没有。四个写入路径（库主/管理员 × 增/删）与"有效权限"接口现在都在写入前解析，解析不了直接拒绝。**运行时验证：用身份下规则时 ACL 完全正确**（`restricted` 逐条改写为 `r`、`secret` 从列举消失、`/restricted/sub` 继承 `r`、`/secret` 403），说明强制链路本来就对，错的只是存进去的内容 |
| 72 | 矩阵脚本静默失败 | ✅ | 建用户与共享两个调用的返回值都被丢弃，而共享接口**失败时返回 200**、错误装在 body 的 `failed` 数组里。于是矩阵在一个 B 根本看不见的库上跑完，每条断言都因同一个无信息的原因失败，表面症状却是列举辅助函数里的 `AttributeError`。两处已检查，共享额外检查 `failed` 非空 |
| 73 | 矩阵的两处恒真/错靶断言 | ✅ | 跑起来才暴露的两个测试缺陷。**安全不变量四项在规则一条都没生效时全绿**——接口出错或查错用户时 `native` 与 `eff` 同为 `None`，"未放宽"平凡成立；现在先断言接口可用且 `native` 非空。**移动校验打错了端点**：`/dir/?operation=move` 只支持 mkdir/rename/revert，请求以 `400` 被拒，而断言只要非 200 就算"被拒"——看起来 ACL 生效了，其实请求根本没走到权限判定。改为 `batch-move-item`，即第 35 项审计的那组端点 |
| 74 | 本地门禁不可重复运行 | ✅ | 各服务数据都是 `$STAGE_DIR/data/...` 的 bind mount，而 `stage_compose()` 上来就 `rm -rf $STAGE_DIR`——容器还挂着。db 不被重建、继续用旧库，seafile-data 却空了，setup 当成全新安装撞上已有 schema，退出 1，**表面只剩一个 Caddy 502**。首次跑没事纯粹因为当时没有存量栈，而能力门禁按定义就是第二次跑。现在先 `down -v` 再动目录 |
| 23 | Go fileserver 同步前校验 | ✅ | 矩阵「含不可读内容的库拒绝同步」通过——RPC 真的被调用并返回了受限路径 |
| 24 | `is_repo_syncable` / `is_dir_downloadable` | ✅ | 同步与打包下载两项均运行时验证 |
| 25 | ACL 管理 REST API（库主） | ✅ | 矩阵全程用它下发规则；"有效权限"接口是安全不变量四项的数据来源 |
| 26 | ACL 管理 REST API（系统管理员） | ✅ | ACL 矩阵新增管理员列规则、整库清空、清空后复查三项；本机真实栈 31/31 通过 |
| 27 | 前端配置面板 | 🟡 | `cloudfileAcl.js` 已确认打进镜像（入口与 import 链完整）；**页面本身未在浏览器中操作过** |

### ACL 入口覆盖

| # | 入口 | 状态 | 说明 |
|---|---|---|---|
| 28 | Web UI | 🟡 | 经 `check_folder_permission`（与 REST 同一咽喉，已验证）；**浏览器中未实操** |
| 29 | REST API | ✅ | 矩阵 7 项（列举过滤、读取拒绝、建目录拒绝、删除拒绝、正向对照）|
| 30 | WebDAV **写** | ✅ | 矩阵 3 项。补丁顺带**消除了一处存在性泄露**：`/secret` 从 403 变为 409（父目录解析不到），与只读目录的 403 区分开——此前光凭状态码差异就能确认不可见目录的存在 |
| 31 | WebDAV **读** | ✅ | `patches/seafdav/0001` 给四个读路径加上 `check_permission_by_path`，不可读一律当作不存在。构建期 `git apply`，**不引入第四个 fork**，应用失败即致命。**矩阵 5 项全过**：`/secret` 不出现在 PROPFIND、直接列举返回 404、只读目录仍可列举、`/public` 正常、外加防「WebDAV 整个坏掉也全绿」的对照 |
| 32 | 分享链接 / 下载链接 | ✅ | 矩阵 3 项：`/restricted` 取上传链接被拒、`/secret` 取下载链接被拒、`/public` 允许 |
| 33 | 目录打包下载 | ✅ | 矩阵 2 项：含不可读子树被拒、可读目录允许 |
| 34 | 桌面同步客户端 | ✅ | 矩阵 1 项：含不可读内容的库拒绝同步 |
| 35 | 移动 / 复制 / 重命名 | ✅ | 矩阵 3 项，经 `batch-move-item`：移入/移出 `/restricted` 均以 `Permission denied` 落进 `failed`，`/public` 内移动成功（正向对照）。**批量端点失败时返回 200**，逐项结果在 `failed`/`success` 里——这一轮被这个套路坑了三次 |
| 54 | 目录列举过滤 `invisible` | ✅ | **运行时已验证**：`/secret` 不出现在 B 的列举里，`restricted` 逐条改写为 `r`。上游 `list_dir_with_perm` 只按库级判一次权限并盖到每个条目，`invisible` 目录仍会被列出。已在 `rpc-service.c` 的 RPC 出口按路径逐条过滤，覆盖全部调用方 |

### 其它 P1

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 36 | SSO 登录与用户/组织映射 | ✅ | 见下方「P1 — SSO 与组织映射」。本机真实栈已通过两阶段矩阵；签名 webhook、周期同步/登录后刷新与真实 MySQL DDL 仍各自保留验证项 |
| 37 | 操作日志 / 审计 | ⬜ | 占位，`CF_ENABLE_AUDIT`。post 文件操作钩子已预留（吞异常，不影响写入），但 ⚠️ **它没有任何上游触发点**——见待办 3。落地前先定钩子位置 |
| 66 | ACL 规则来源可扩展 | 🟡 | `acl/sources.py`：**终判永远读 `cf_dir_acl`**，来源才是 provider。`local-db` 已实现（就是原有行为，现在有了名字）并接上 cf-worker 周期任务；`external-service` **已设计、刻意不注册桩**——桩会让 `cf_dir_acl` 保持空表，而空表看起来是"没配规则"不是"这个来源没实现"。5 项测试 + 2 个变异验证。**周期任务未在容器中跑过** |

---

## P1 — SSO 与组织映射（`feature/sso`）

规格 [sso-mapping.md](sso-mapping.md)，探针结论 [upstream-reuse.md](upstream-reuse.md)。

> **这个特性的形状被探针改了。** 原计划写一个认证后端——而 CE 14.0 自带
> OAuth2/OIDC、SAML、CAS、LDAP、REMOTE_USER，**一处 Pro 门控都没有**，依赖
> 也已经在发行包里。登录那一半的成本从"写一个后端"降到 0；取而代之的是原计划
> 里根本没有的一块：**通用目录的组织映射**，上游只对企业微信和钉钉做了，
> 而那张 `external_department` 表的 `outer_id` 是 BIGINT，装不下 OIDC 的组
> claim 或 LDAP 的 DN。
>
> 按原计划动工会得到一个能登录、但组织结构仍要手工维护的产物——而后者才是
> 企业提这个需求的原因。

**验证证据**：2026-07-24 已从本地 SSO 分支构建镜像，开着 `CF_ENABLE_SSO` 跑过
两阶段验收矩阵；阶段 1 的目录创建、成员关系、重复同步、干跑与状态检查 12/12
通过，阶段 2 改小目录并重启后验证成员移除、解除映射但保留组、管理员解除映射。
这证明结果确实落到了 ccnet；CI 仍须跑一次以覆盖架构、磁盘配额和 PATH 差异。

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 75 | 上游复用探针 | ✅ | [upstream-reuse.md](upstream-reuse.md) 探针 0。命令可复现；结论直接改写了本特性的形状 |
| 76 | 组织映射编排 | ✅ | `sso/reconcile.py`，无 Django/DB，纯数据进出。**14 项测试，5 个变异全部被捕获**。四条铁律：只碰自己建的组、组内成员即目录、离开目录只解除映射不删除、计划整体拒绝 |
| 77 | 两道拒绝闸门 | ✅ | 空快照 + 删除比例上限。存在的理由是**目录调用成功却返回空**（token 过期、端点改名、代理 200 空 body）——按字面理解就是"把每个组清空"，静默且日志里是 200 |
| 78 | 目录源 provider | ✅ | `sso/directory.py`，kind `sso_directory`：`static`（配置即目录，也是门禁用的源）与 `external-service`（两个 GET，走 `external_service.py`）。**12 项测试**。凡是"没读到目录"的路径一律转成 DirectoryError，绝不以空快照的形式往下传 |
| 79 | 身份解析下沉到基线 | ✅ | `acl/subjects.py` → `cloudfile_ext/identity.py`。Seafile 14 身份≠邮箱是**框架级事实**，不是 ACL 的。留在 `acl/` 会让 SSO 同步在运行时 import ACL 能力——按 [BRANCHES.md](BRANCHES.md) 的耦合判据，那等于把两个毫无关系的簇焊在一起，并让 ACL 的开关决定 SSO 能不能解析用户。ACL 侧留一层薄转发，既有测试逐字未改 |
| 80 | 配置块生成 | ✅ | `bootstrap.py` 的 `_settings_block_sso()`：把 `.env` 翻译成上游读的 `OAUTH_*` 与 CloudFile 自己的 `CF_SSO_*`。回调地址由部署主机名推导，不让运维手填 |
| 81 | 配置生成检查 `test-bootstrap-settings.py` | ✅ | **本轮新增的门禁**。preflight 那条是静态的、只认 `FOO['bar'] =` 一种形状；这条把生成函数抠出来实际 `exec()`，覆盖引号、字面量、claim 冲突，以及 LDAP/ADFS/角色/2FA 的结构与必填项。**23 项断言，9 个变异全部被捕获**；其中一个（uid 与 email 取同一 claim）会让 email 悄悄从必需项降级——静态检查完全看不出 |
| 82 | preflight 检查跟着扩大 | ✅ | `check_seahub_settings_block` 原本只扫主函数，而 body 现在是拼出来的——**一个不再覆盖被监视对象的检查比没有检查更危险，因为它读起来像覆盖**。改为连 `_settings_block_*` 一起扫，并补上单引号（原来只认双引号）。破坏新助手确认会红 |
| 83 | `cf_sso_group_map` / `cf_sso_sync_state` | ✅ | MariaDB 真实栈中 worker 会写入并由管理接口读取状态，证明 DDL 已实际执行 |
| 84 | 管理接口与 webhook | ✅ | 两阶段矩阵覆盖同步/干跑/映射列表/解除映射；签名 webhook 覆盖未签名拒绝、过期签名拒绝、有效 HS256 签名触发同步 |
| 85 | 周期同步与登录后刷新 | 🟡 | `cf-worker` 已随真实栈运行并完成首次 SSO 同步；登录后信号触发与失败不阻断登录仍待独立验收 |
| 86 | 两阶段验收矩阵 | ✅ | `tests/e2e/sso_matrix.py` + `sso-e2e.yml` + `verify-local.sh cap sso`。本机真实栈通过：原生冒烟 12/12，阶段一 15/15（含 worker、签名 webhook），阶段二 11/11；CI `30048595570` 已成功 |
| 87 | 本地门禁支持按能力定制 | ✅ | 能力不止需要开关，还需要 provider 选型这类配置，且不止跑一遍。约定 `cap_<名>_env` / `cap_<名>_run` 两个可选钩子，而不是把表格字段越加越多——"改配置、重启、再断言"这种形状塞不进一行 |
| 88 | 能力门禁两边成对的检查 | ✅ | verify-local 的 CAPABILITIES 与 `.github/workflows/<能力>-e2e.yml` 必须一一对应。本地门禁存在的全部理由就是不要手抄 workflow，而**只抄一半**正是它要防的事（`acl_matrix.py` 缺 `--insecure` 就是这么留下来的）。两个方向的变异都确认会红 |

### 已知边界（写在这里，不藏在代码注释里）

- **组是平的。** 目录契约里没有父子关系，建出来的是普通组，不是有层级和配额的部门。
- **不建用户。** 同步只处理组成员；账号仍由登录时创建或管理员创建。目录里有、
  Seafile 里没有的人，作为"无法解析"出现在同步报告里，**不会**被当成"已离开"而触发删除。
- **不处理 multi-tenant org**（`create_org_group` 那条路径没接）。
- **最终一致。** 目录改了到生效有延迟；webhook 压到秒级，纯拉取取决于间隔。
  这是本设计唯一真正的妥协，必须写进客户对接文档。

---

## 打包层 — Pro 特性中"源码已在 CE、只差启用"的部分

**这些不是特性分支，也没有 `CF_ENABLE_*` 开关。** 它们的代码本来就在 CE 开源仓里，
由上游自己的 settings 门控（不是 `is_pro_version()`）。启用 = 在 bootstrap 里从
`.env` 写上游设置，做法与已落地的 OAuth（`_settings_block_sso`）完全一致。
默认关 = 原生 CE 这条铁律不变，只是这里的开关是**上游的**。全表见
[pro-parity.md](pro-parity.md)。

| # | Pro 特性 | 启用方式 | 状态 |
|---|---|---|---|
| 89 | LDAP/AD 登录 | `CF_LDAP_*` → `ENABLE_LDAP` + `CustomLDAPBackend`（CE 已带） | 🟡 已接 bootstrap；配置片段及必填项门禁已测，待接真实目录验收 |
| 90 | ADFS（SAML）SSO | `CF_ADFS_*` → `ENABLE_ADFS_LOGIN`（`seahub/adfs_auth/`，无 `is_pro`） | 🟡 已接 bootstrap，镜像已含 `xmlsec1`；待 IdP、SP 证书实测 |
| 91 | Shibboleth SSO | `CF_SHIBBOLETH_*` → 远程用户认证路径 | 🟡 已接 bootstrap；默认 Caddy 不是 Shibboleth SP，需可信认证代理后验收 |
| 92 | 角色账号管理 | `CF_*ROLE_PERMISSIONS_JSON` → `seahub/role_permissions/` | ✅ 已接 bootstrap；JSON 增量策略生成并加载已测 |
| 93 | 双因素认证 2FA | `CF_TWO_FACTOR_*` → `ENABLE_TWO_FACTOR_AUTH`（`seahub/two_factor/` 无条件装载） | ✅ 已接 bootstrap；开关与设备记住期限生成并加载已测 |
| 94 | 远程擦除 | 用户、组织管理员、系统管理员前端均传 `wipe_device=true` 到 CE 设备 API | ✅ 已具备；已核对前端入口与后端 `mark_device_to_be_remote_wiped` 调用链 |
| 95 | WebDAV | `seafdav`，已在 CloudFile 构建里 | ✅ 已具备（ACL 读写补丁已测） |

> 这一层应**最先清**：企业准入门槛（LDAP/角色/2FA）几乎零成本就能对齐 Pro，
> 而它一行 `cloudfile_ext` 代码都不用写。它验证时并进现有 `smoke.py` 即可——
> 都是"开关一开，上游功能是否照常工作"，不需要单独的能力门禁。

---

## P2 — 信息管理能力

**簇 D（`feature/metadata`）** —— 38 / 39 / 42 是一条分支，因为它们共享同一张表。
标签是属性的特化；42 是 38/39 的正确性要求，不是独立特性。两个开关
（`CF_ENABLE_METADATA`、`CF_ENABLE_TAGS`），一条分支。

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 38 | 文件属性扩展 | 🟡 | `metadata` profile、上游开关和官方 metadata-server 已接；真实门禁暴露 `seafevents` 包导出阻塞，已在 Server 修复后待重建验收。官方尚无稳定 14.x 镜像，当前只用 `14.0.3-testing` 验证兼容性 |
| 39 | 标签 | 🟡 | 与 38 同表同分支；已接 `CF_ENABLE_TAGS` 依赖校验、标签读写门禁和官方存储服务，待重建后实测 |
| 42 | 移动重命名时元数据关联更新 | ⬜ | 依赖 38/39 验收；投喂走 seafevents 的提交遍历，很可能**不依赖 `file_op` 钩子**——移动/重命名本就在提交流里 |

**簇 E（`feature/search`）** —— 与簇 D **可真并行**，靠第 67 项的过滤契约解耦。

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 40 | 索引与检索 | ⬜ | **完整方案见 [search.md](search.md)。** 默认官方 seasearch（索引/查询后端零新增代码）；P0 精确解除全局搜索接口的 Pro 门（`Search` + `public_repos_search` 两个接口，经 URL 影子子类覆盖 `permission_classes`，**零上游改动**，**不动全局 `is_pro_version()`**）；P1 抽 `SearchBackend`；P2 meilisearch（索引侧走 cf-worker，不 fork seafevents）；P3 元数据组合检索。⚠️ provider 与 seasearch 同配时 `HAS_FILE_SEARCH` 分支优先——见 search.md |
| 41 | 属性 / 标签 / 内容组合检索 | ⬜ | **跨簇（D × E）**。经第 67 项的契约解耦：D 喂字段、E 翻译过滤，各自独立验收；端到端验收属 `dev` 上的集成门禁，不归任一分支 |

Compose 的 `search` profile 与 `cf-worker` 已就位，实现时不需要再动部署。

> **不确定性已消除**：探针 1 与 3 都已完成（[upstream-reuse.md](upstream-reuse.md)），
> P2 从"五个特性从零做"确认缩成"一个兼容服务 + 配置 seasearch"。原文这里写着
> "三个探针各 1～2 天"——探针 1、3 已兑现那句承诺，探针 2（OnlyOffice）属 P3，仍未做。

**AI（自动属性 / 标签 / 摘要）** —— 复用官方 seafile-ai，自动管线依赖簇 D。
完整方案见 [ai.md](ai.md)。

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 97 | AI 按需能力（标签/摘要/描述/OCR） | ⬜ | **📦 打包**：`seahub/ai/` 已带且**无 Pro 门控**（`ENABLE_SEAFILE_AI` env），调官方 `seafileltd/seafile-ai`。启用即用，需自备 LLM 后端。自建即绕开 seafile.com 托管 AI 计费 |
| 98 | AI 自动管线（入库自动生成 + 落元数据） | ⬜ | **🔨 构建**：唯一新代码。CE **没有**自动标签/摘要接线（只有人脸识别是自动的）。cf-worker 消费提交 → 调 seafile-ai → 写元数据。**依赖簇 D**。幂等 + 可控触发。门禁用假 seafile-ai 桩 |
| 99 | 人脸识别 | ⬜ | **📦 打包**：seafevents 已有自动管线（`ENABLE_FACE_RECOGNITION`） |
| 100 | 语义检索 | ⬜ | **🔨 构建**：嵌入 → 检索后端，属 [search.md](search.md) P3，与 98 共用 cf-worker |

> AI 不在官方 Pro vs CE 对比表里（是按量计费的独立维度），但**代码在 CE、无 Pro
> 门控**，可自建。这是"复用官方组件但用自备模型绕开托管计费"的落地。

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

## P4 — 存储扩展与 server 侧管线

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 49 | S3 / 多存储 | ⬜ | **完整方案见 [storage.md](storage.md)。** 核心文件服务只有 FS：Go fileserver 仅 `backend_fs.go`、C 侧仅 `obj-backend-fs.c`（GC/FSCK 也经它）。要补 Go `backend_s3.go` + C `obj-backend-s3.c` + 两侧后端选择与多存储 `storage_id` 路由，覆盖上传/下载/同步/历史/GC/FSCK/迁移。seafobj（Python 读侧）已带 S3/OSS/Swift/Ceph，白捡。沿用官方 `SEAF_SERVER_STORAGE_TYPE`/`S3_*` 变量，不造私有格式。**roadmap 最重的构建项之一** |
| 96 | 反病毒集成（簇 I） | ⬜ | **Pro 对标补入**（[pro-parity.md](pro-parity.md)）。Pro 的"缺失机制"里唯一没归簇的一项：上传/文件扫描在 server/pipeline 侧，**镜像已主动剥离 clamav**。落地前先做门控盘点（同 OnlyOffice 探针 2 的做法），确认哪些是真依赖、哪些只是商业门控 |
| 50 | SMB/NFS 外部资料源 | ⬜ | 零上游改动，但**代价是另起一个入口**——不改上游就进不了原生库列表。见 [EXTENSION-POINTS.md](EXTENSION-POINTS.md) 缺口 3。这是产品决定，不是技术决定 |
| 51 | 外部源增量扫描 | ⬜ | 依赖 50 + `cf-worker` |
| 52 | 虚拟目录挂载 | ⬜ | 依赖 50；融入原生 UI 的问题同 50 |
| 53 | Overlay 标签与属性 | ⬜ | 依赖 50 + 38 |

外部源首版只读，不进入 Seafile 的 repo/commit/block 模型。

---

## 待办与审计发现

按阻塞程度排。

1. 🟠 **在 CI 上跑一次三条门禁**（checks / build-and-e2e / acl-e2e）。本机
   全绿，但 CI 与本机在架构、磁盘配额、PATH 上都有已知差异，而十二次构建失败
   里有六次正是栽在这类边界。**这是目前唯一的未验证面。**

   > **矩阵这一关已经过了（23/23）**，而它的价值在第一次运行就兑现：单元测试
   > （C 62 / Python 87）全绿、静态检查全绿、基线门禁全绿，而第 71 项那个缺陷
   > **一个都没被拦住**——它们证明的是"求解器算得对"，缺陷却在"存进去的东西
   > 根本进不了求解器"。只有把栈起起来、拿另一个用户的 token 去敲每个入口
   > 才会显形。
2. 🔴 **`file_op` 钩子没有生产者**。`register_file_op_hook()` 注册得了，但上游
   没有任何地方调用 `run_file_op_hooks()`——注册了一个永不触发的回调。审计、
   文件属性、标签、元数据跟随、OnlyOffice、文件锁、签入签出，**七个特性依赖它**。
   见 [EXTENSION-POINTS.md](EXTENSION-POINTS.md) 缺口 1。
3. 🟢 **上游 CE 14.0 已带了 P2/P3 的一大半**（`repo_metadata`、`tags`、
   `file_tags`、`repo_tags`、`onlyoffice`、seasearch），且大多**无 Pro 门控**。
   **探针 1、3 已做**（[upstream-reuse.md](upstream-reuse.md)）：属性/标签的
   方向是"写一个协议兼容的 metadata-server + 复用上游全部前端和 API"，检索的
   方向是"配上游已集成的 seasearch，零 CloudFile 代码"。**结论是省下工作量，
   不是待办**——只剩 OnlyOffice（探针 2）未盘点，属 P3。
3.5. 🟢 **打包层是最便宜的 Pro 准入**（第 89–95 项，[pro-parity.md](pro-parity.md)）。
   LDAP/ADFS/Shibboleth 登录、角色管理、2FA、远程擦除的代码**都在 CE 源码里、
   不被 `is_pro_version` 挡**——启用只是在 bootstrap 里从 `.env` 写上游设置，
   零 `cloudfile_ext` 代码、不开分支。**建议在推进构建层之前先清这一层**：
   它几乎无成本地对齐了 Pro 的用户/安全管理，而那正是企业采购的门槛项。
4. 🟡 **MySQL DDL 未对真实 MySQL 执行**（第 19 项），仅验证了语句切分与 SQLite 变体。
5. 🟡 **上游遗留问题**：`seahub/api2/endpoints/repos_batch.py` 的
   `BatchMoveItemsUpdatePath` 完全没有权限校验（上游 docstring 自述
   "all authenticated user can perform this action"）。它只更新路径记录、
   不搬运数据，但允许任何登录用户对任意库提交路径更新。属于上游问题，
   不是 CloudFile 引入的回归，需单独评估。
6. 🟡 **上游 `Seafile CI` 在 fork 上永远失败**：`ci/run.py` 写死
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

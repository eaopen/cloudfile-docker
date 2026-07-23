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

| 层 | 分支 | 内容 | 门禁 |
|---|---|---|---|
| **扩展基线** | `dev` | 扩展点、构建、部署、发布机制 | 构建镜像 + 原生 CE 冒烟 + 扩展点验收 |
| **目录 ACL** | `feature/dir-acl` | 唯一已实现的能力 | 自带六入口矩阵 |

> **当前最大的一块空白**：完整镜像从未成功构建过。所有 🟡 项的共同前提都是它。
> 已知 C 代码可以编译（CI 的 `build-c` job 已通过），但发行包构建仍在修复中。

---

## P0 — CE 兼容基线

| # | 特性 | 状态 | 说明 |
|---|---|---|---|
| 1 | 三仓 fork 与分支模型 | ✅ | `dev` 为主干，`upstream/master` remote-tracking ref 作纯净副本，见 [BRANCHING.md](../BRANCHING.md) |
| 2 | 统一版本号与发布清单 | ✅ | [release.yaml](../release.yaml)，各组件按 commit SHA 锁定 |
| 3 | 功能开关机制（10 个 `CF_ENABLE_*`） | ✅ | 默认全关；配置块重写幂等性已验证 |
| 4 | 扩展注册机制 | ✅ | URL / 菜单 / 权限 / 文件操作 / 索引器 / 外部源 / 周期任务；分发与 seal 行为已验证 |
| 5 | `cloudfile_ext` Django app | ✅ | 通过 `EXTRA_INSTALLED_APPS` 注册，未改 `settings.py` |
| 6 | 上游注入点最小化 | ✅ | Hub 仅 2 处行为改动 + 1 处数据追加；Server 8 个文件；Docker 3 个文件 |
| 7 | 前端骨架与入口注册 | 🟡 | 入口映射已验证可加载；基线页面为能力总览；**从未真正打包** |
| 55 | 前端资源构建接入 | 🟡 | **本轮补齐**。`seafile-build.py` 的 Seahub 阶段只复制源码树，`media/assets` 只存在于上游 dist 分支——原先的构建会产出没有 Web 界面的镜像。已在 `cloudfile-build.sh` 中加入 `npm run build` + `make dist`，并在缺失时直接失败 |
| 56 | CI：快速检查门禁 | 🟡 | 三仓共用 `tools/run-checks.sh`；本地已全绿，**CI 上尚未跑过** |
| 57 | CI：构建 + E2E 门禁 | 🟡 | `build-and-e2e.yml`：构建镜像 → 开关全关冒烟 → 开 ACL 跑六入口矩阵。**尚未在 CI 上执行过** |
| 8 | CE 14.0 镜像 | 🟡 | 与 13.0 CE 镜像的 diff 已核对（仅注释与版本 pin）；**从未构建** |
| 9 | SHA pin 构建脚本 | 🟡 | `bash -n` 与 manifest 读取已验证；**从未执行**（需 Linux） |
| 10 | Compose 一键部署 | 🟡 | `docker compose config` 与 4 个 profile 已验证；**从未启动** |
| 11 | `cf-worker` 后台进程 | 🟡 | 命令已实现；当前无任何周期任务注册，故置于 `worker` profile 而非默认集合 |
| 12 | **原生 CE 回归测试** | 🟡 | `tests/e2e/smoke.py` 已写；**未执行**，需要能跑起来的镜像 |
| 58 | server 侧扩展点 `cf-ext` | 🟡 | 能力注册表 + 权限/列举/子树三个分发钩子；**C 编译已通过 CI**，运行时未验证 |
| 59 | 扩展点装配验收 | 🟡 | `tests/e2e/baseline.py`：证明 `cloudfile_ext` 确实被加载、开关全关、无能力路由、钩子透传。只跑 smoke 无法发现"扩展根本没装上" |
| 60 | 基线与能力分层 | ✅ | ACL 整体剥离到 `feature/dir-acl`；剥离前后三仓上游改动清单**逐字节不变**，证明能力可独立演进而不增加 fork 成本 |

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
| 36 | SSO 登录与用户/组织映射 | ⬜ | 占位，`CF_ENABLE_SSO` |
| 37 | 操作日志 / 审计 | ⬜ | 占位，`CF_ENABLE_AUDIT`；已预留 post 文件操作钩子（吞异常，不影响写入） |

---

## P2 — 信息管理能力

| # | 特性 | 状态 |
|---|---|---|
| 38 | 文件属性扩展 | ⬜ |
| 39 | 标签 | ⬜ |
| 40 | Meilisearch 索引与检索 | ⬜ |
| 41 | 属性 / 标签 / 内容组合检索 | ⬜ |
| 42 | 移动重命名时元数据关联更新 | ⬜ |

Compose 的 `search` profile 与 `cf-worker` 已就位，实现时不需要再动部署。

---

## P3 — 协同与项目流程

| # | 特性 | 状态 |
|---|---|---|
| 43 | OnlyOffice 编辑与回调 | ⬜ |
| 44 | 文件锁定强制校验 | ⬜ |
| 45 | 签入签出流程 | ⬜ |
| 46 | iTeam 流程接口 | ⬜ |
| 47 | 编辑超时与异常解锁 | ⬜ |
| 48 | OnlyOffice 回调幂等 | ⬜ |

Compose 的 `office` profile 已就位。第一阶段只支持 Seafile 主存储文件。

---

## P4 — 存储扩展

| # | 特性 | 状态 |
|---|---|---|
| 49 | S3 类主存储 | ⬜ |
| 50 | SMB/NFS 外部资料源 | ⬜ |
| 51 | 外部源增量扫描 | ⬜ |
| 52 | 虚拟目录挂载 | ⬜ |
| 53 | Overlay 标签与属性 | ⬜ |

外部源首版只读，不进入 Seafile 的 repo/commit/block 模型。

---

## 待办与审计发现

1. **让发行包构建成功并启动一次完整栈**。这是解锁全部 🟡 项的前提。
   已连续修掉两个构建缺陷（前端资源生成、构建期依赖），仍未跑通。
2. **WebDAV 读侧 `invisible` 缺口**（第 31 项）。修复需要改 seafdav。建议在
   `cloudfile-docker/patches/seafdav/` 放补丁由构建脚本 `git apply`，
   避免引入第四个 fork。
3. **上游遗留问题**：`seahub/api2/endpoints/repos_batch.py` 的
   `BatchMoveItemsUpdatePath` 完全没有权限校验（上游 docstring 自述
   "all authenticated user can perform this action"）。它只更新路径记录、
   不搬运数据，但允许任何登录用户对任意库提交路径更新。属于上游问题，
   不是 CloudFile 引入的回归，需单独评估。
4. **MySQL DDL 未对真实 MySQL 执行**（第 19 项），仅验证了语句切分与 SQLite 变体。
5. **三个构建期缺陷已发现并修复**（第 54、55 项及构建期依赖）：目录列举不过滤
   `invisible`、发行包不含前端资源、`collectstatic` 缺少被刻意排除的依赖。
   第一个是静态审查发现的，后两个是 CI 跑出来的——这正是 CI 的价值：
   本地 `bash -n` 全过，真跑起来才暴露 PATH 与 import 链问题。
6. **上游 `Seafile CI` 在 fork 上永远失败**：`ci/run.py` 写死
   `join(TOPDIR, 'seafile-server')`，而仓库名是 `cloudfile-server`。与我们的代码
   无关。已改为从自己的 workflow 里把仓库 checkout 成那个目录名来获得 C 编译
   覆盖；建议把上游那个 workflow 在 fork 里禁用，避免红叉变成噪音。

<!-- generated-by: gsd-doc-writer -->
# CloudFile 三仓分支模型

> **用途**：规定 `cloudfile-server`、`cloudfile-hub`、`cloudfile-docker` 共用的分支、发布和上游同步规则。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效；构建 ref 以 [`release.yaml`](release.yaml) 为准，详细门槛见 [`docs/BRANCHES.md`](docs/BRANCHES.md)。

## 分支类型

| 分支 | 用途 | 生命周期 |
|---|---|---|
| `dev` | 集成基线：扩展点、构建、部署和已验收能力；全部能力开关默认关闭 | 长期 |
| `feature/<name>` | 单个耦合能力簇 | 验收后合回 `dev` 并删除 |
| `fix/<name>` | 独立缺陷修复 | 验证后合回 `dev` 并删除 |
| `sync/upstream-YYYYMMDD` | 三仓同步上游的临时工作分支 | 同步与回归完成后删除 |

长期能力分支只用于不准备进入产品的客户定制、实验或许可证不兼容实现。能力不能长期各自分叉：构建脚本每仓只接受一个 ref，正式组合必须在 `dev` 上通过默认关闭的开关隔离和集成验证。

## 上游基线

未 fork 组件按 `release.yaml` 的 `upstream` SHA 锁定；CloudFile fork 使用 `forks` 下的 URL/ref。上游未发布 CE 14 tag，不能用 Pro tag 代替 CE 基线。

```bash
python3 build/cloudfile_14.0/read-manifest.py release.yaml forks.cloudfile_server.ref
python3 build/cloudfile_14.0/read-manifest.py release.yaml upstream.seafile_server
```

## 跟随上游

1. 三仓各自从 `dev` 创建同名 `sync/upstream-YYYYMMDD`。
2. 获取并合入对应上游分支，逐项处理已登记上游文件的冲突。
3. 更新 `release.yaml` 的上游 SHA。
4. 运行上游改动登记、快速检查、基线门禁和所有受影响能力门禁。
5. 三仓评审通过后合入 `dev`。

```bash
git fetch upstream master
git switch -c sync/upstream-$(date +%Y%m%d) dev
git merge upstream/master
./tools/check-upstream-patches.sh
./tools/run-checks.sh
```

允许修改的上游文件以 [`docs/upstream-patches/`](docs/upstream-patches/) 三份清单为准。脚本报告新增文件时，先确认无法用新增文件或现有扩展点实现，再更新清单和本文件；不能直接补登记来绕过审查。

2026-09-30 CI 修复登记 Hub 的 `tests/seahub/views/file/test_file.py` 与
`.github/workflows/test.yml`：已有审计回归必须改用 `FILE_AUDIT_ENABLED`，否则它们仍
mock 已移除的 Pro 判定并在运行断言前失败；自动调试步骤必须在现有工作流中改为
显式开启 runner debug 后才运行，并限制等待时间。新增测试或另建工作流不能修复
这两处原入口，生产审计端点的行为不变。

`release.yaml` 还有第二个锚点：`ce_anchor`。CloudFile 跟的是 `upstream/master`（同步频繁、
冲突小），但产品自称 CE 14，基线就必须是上游 CE 14 **正式发布的超集**。上游打新的
`v14.0.N-server` 时，把 `ce_anchor` 更新到那次发布的**源码提交**，`./tools/check-ce-anchor.sh`
会断言它已在被验证的 ref 上（`run-checks.sh` 已接入，CI 的 dev 任务 HEAD 即 dev）。

注意 `seahub` 的 `-server` tag 打在 `[dist][CI SKIP] ... CI build` 的产物提交上，不是
`master` 的祖先；`ce_anchor.seahub` 记的是它基于的那个源码提交，直接记 tag 提交会让
断言永远为假。

### 冲突与移植的裁决顺序（2026-09-22 追加）

同步上游、或在两套实现之间取舍时，按下面三条判断。**顺序即优先级，第 3 条让位于前两条。**

**1. 涉及 CE 14 的，以上游为准。**
上游对 CE 14 的运行时依赖、镜像配方、配置默认值、脚本行为，只要有对应实现就跟上游，
不再自建一套平行实现。2026-09 上游已补上 `image/seafile_14.0/`（CE 14 镜像配方）——
本节前提里"上游没有 CE 14 镜像"那句已作废。判断方法是拿上游配方与 CloudFile 的
`image/cloudfile_14.0/Dockerfile.base` 对比，**上游有的 pin 一个都不能少**；CloudFile
多出来的部分要能说出属于第 2 条。

**2. CloudFile 自有的能力、以及从 Pro 迁移过来的东西，按 CloudFile 的逻辑。**
`cloudfile_ext/`、`frontend/src/cloudfile/`、`cf_*` 开关与表、镜像里的编译工具链、
以及为 CE 补齐的原 Pro 能力（审计、OnlyOffice 内网根、SSO 建号回填、全文索引开关等）
是 CloudFile 的产品面，不受第 1 条影响。反过来说，拿不准某个上游删除/简化该不该跟
时，先问它属于"上游给的东西"还是"CloudFile 的产品面"。

**3. `cloudfile-hub` 的代码规则优先跟随上游同类规则。**
上游 `frontend/AGENTS.md`、`seahub/AGENTS.md` 定义的 import 路径、依赖分层、命名和
lint 规则，CloudFile 自有的前端文件同样遵守：跨模块 import 用 `@/` 别名，同一子模块
内部才用相对路径，import 顺序以 `npm run lint` 为准。既有违规按上游要求"不扩大、
触及才迁移"。这条管**写法**，不改第 2 条里的**逻辑**。

三条的共同收口是**开关默认关闭**：第 1 条要跟上游的默认值，第 2 条要保 CloudFile 的
开关语义，冲突时以"新增开关默认 `false`、能力默认不生效"为准。

2026-09-22 废除了原来的那条共同底线「**`CF_ENABLE_*` 全关 = 原生 CE 行为**」，理由
是它在本仓从来就不成立：CloudFile 是 CE 的扩展版，基线里始终有不受开关约束的改动
（登记在 `docs/upstream-patches/` 的兼容与安全补丁，包括 B-1 字节通道按路径判定权限、
标签按目标路径判定等），全关时它们照样生效。现在关闭态只要求**不劣化可用性**，不再
要求与原生 CE 逐字一致；对应地，`smoke.py`/`baseline.py` 从"等同性证明"降为回归检查。

### 上游改动登记（2026-08-15 追加）

`cloudfile-server` 新增登记：

- `fileserver/option/option.go`：为目录 ACL 的同步边界加 `cloudfile.dir_acl_enabled`
  选项。fileserver 只从这里读配置，这是唯一入口，无法用新增文件替代。
- `README.testing.md`、`tests/test_upload/readme.md`：上游测试说明被改写为
  CloudFile 测试指南/工具说明。文档替换是为了保持"先读这个文件"的约定路径单一，
  不制造第二份入口；同步成本为文档级，风险低。

`cloudfile-docker` 新增登记：

- `.dockerignore`：构建上下文排除的唯一入口，必须就地改（否则多 GB 的构建产物
  会随上下文进镜像构建）。
- `README.md`、`build/README.md`：改写为 CloudFile 仓库/构建文档，理由同上。

`cloudfile-hub` 清单移除过期项 `frontend/webpack-stats.pro.json`：与上游已无差异
（构建产物回退），保留只会让清单失真。

### 上游改动登记（2026-09-22 追加）

跟随 `upstream/master` 同步时，登记脚本暴露了 24 个**既有但从未登记**的上游文件改动。
逐个核对后登记 21 个、明确拒绝 3 个。新增登记的都是既有代码，不是本次同步引入的。

`cloudfile-server` 新增登记（3）：

- `server/repo-mgr.c`、`server/repo-mgr.h`：存储类能力给
  `seaf_repo_manager_create_new_repo()` 增加 `storage_id` 参数。这是既有 C 函数的
  签名，调用方必须传新参数，新增文件替代不了。
- `lib/Makefile.am`：`fix(build): serialize Vala source generation` 把
  `seafile-object.h` 的生成折进 `valac` 命令并改用 `${valac_gen}`，消除并行构建下
  `valac` 的竞态。构建规则必须落在原文件。

`cloudfile-hub` 新增登记（13）：

上游这一次重构了前端目录（`components/dir-view-mode/` → `features/library-view/`、
`pages/lib-content-view/` → `pages/app/main-panel/lib-content-view/`、
`utils/seafile-api.js` → `api/seafile-api.js` 等），并把跨模块 import 改成 `@/` 别名。
CloudFile 的改动跟着文件走，登记路径随之改写：

- 路径迁移（11）：`frontend/src/api/seafile-api.js`、
  `frontend/src/components/dirent-operation-menu/menuHandlers.js`、
  `frontend/src/components/repo-info-bar/index.js`、
  `frontend/src/components/repo-info-bar/index.css`、
  `frontend/src/features/library-view/dir-grid-view/index.js`、
  `frontend/src/features/library-view/dir-others/index.js`、
  `frontend/src/features/metadata/components/cell-formatter/file-tags/index.js`、
  `frontend/src/features/tag/hooks/tags.js`、
  `frontend/src/pages/app/main-panel/lib-content-view/lib-content-view.js`、
  `frontend/src/pages/file-history/history-list-view/history-list-item.js`、
  `frontend/src/pages/file-history/history-list-view/history-list-view.js`。
- `frontend/src/pages/file-history-old/index.js`：上游把 `frontend/file-history-old.js`
  从 257 行缩成 6 行引导，实现搬到页面目录。CloudFile 的 `canRevert` 改动随之落到
  新文件，旧路径条目删除。
- `AGENTS.md`：上游新增了自己的根指南，以及 `frontend/AGENTS.md`、
  `seahub/AGENTS.md` 两份局部指南。本仓根 `AGENTS.md` 保持 CloudFile 版本——它是本
  fork 的权威指令文件——并补了一节说明上游那两份局部指南在各自目录内优先。这处冲突
  以后仍会重复出现，登记在案。
- 删除 `frontend/src/tag/utils/file.js` 的登记：上游删掉了这个文件，把 tag 视图接到
  共享的 `getDirentItemMenuList` → `Utils.getDirentOperationList` →
  `getFileOperationList`，其中 `ACCESS_LOG` 只由 `fileAuditEnabled` 控制。CloudFile
  对该文件的改动正是这条 CE 开关，所以接受上游删除即保留了行为，补丁不再需要。

同时清掉 13 条因上述迁移而失效的旧路径条目。

`cloudfile-hub` 的既有能力登记（权限/安全就地收窄、能力挂钩、UI 增强、CE 兼容）
不变，只是路径随上游重构改写；性质说明见本节的分类，此处不重复。

**拒绝登记 3 项**（保持未登记，另行清理——不能用补登记掩盖）：

- `seahub/ai/apis.py`、`seahub/ai/utils.py`：与上游只差尾随空白，不含任何能力。
  应还原为上游内容，让它自然退出清单。
- `frontend/webpack-stats.pro.json`：构建产物，内容随构建漂移。
  2026-08-15 已因同样原因移出清单一次；应改为忽略/不追踪，而不是登记。

同时修正 `release.yaml` 的 CI 比对锚点。`seahub` 原先停在 `da3334e`，比真正的合并基点
落后 52 个上游提交，CI 里两点 diff 会把 219 个文件误报成 CloudFile 改动；先前移到
当时的合并基点 `84eeabf`，再随本次 hub 同步前移到 `957c7c50`。`seafile_server`
（→ `d9ed57e`）与 `seafile_docker`（→ `566b7e5`）随各自同步前移。

## 合并与发布

能力合并前必须在开关开启时通过专项门禁，并确认关闭态没有把可用性弄坏（`smoke.py`）
且能力确实未启用（`baseline.py`）。2026-09-22 起不再要求证明"关闭时走原生 CE 路径"。
跨 Hub/Server 的语义先更新共享规格和用例，再同步实现。

发布时将三个仓库的最终提交写入 `release.yaml` 的 `server_commit`、`hub_commit`、`docker_commit`，
然后在 GitHub Actions 中从 `prod` 分支手动运行 `CloudFile production build`，填写版本并
选择 `incremental` 或 `full`。日常小改用增量路径，正式复核、上游升级或缓存对照用保留的
CE 全量路径；通过后再使用同一版本 tag。普通 push 不触发生产编译；增量构建计划会校验
声明的 Server/Hub 提交与实际解析结果一致。未填写提交的开发清单不能当作可追溯发布记录。

历史分支事故、旧排期和过期文件清单保留在 [`docs/history/`](docs/history/)，不作为当前操作依据。

### OnlyOffice 既有补丁维护（2026-09-30）

`seahub/onlyoffice/views.py` 已在 Hub 上游补丁清单登记。本轮在该原位置修正
下载/上传异常及上传非 200 响应：返回失败并保留会话，不继续删除 doc key 或解锁。
原因是失败被原函数内部吞掉，外层回调守卫无法从返回成功中识别它，且清理已执行；
仅在扩展包增加包装不能修复该错误。增加有限网络超时，不新增上游修改路径。
CloudFile 回调守卫另外要求配置 JWT secret 并绑定受签正文；强锁与 Checkout 不启用。

### 统一锁实现清理（2026-09-30）

普通锁和 Checkout 收敛到 Hub `cloudfile_extensions/editing/`，Server 只读同一
`cf_edit_guard`。删除原型路径锁 RPC 的 C 注册/声明及 Python 客户端方法，均位于
既有上游登记文件；不是新增一组上游扩展点。删除旧本地独占自动写回和重复 Hub
接口，不保留旧表迁移/兼容逻辑。原生发布闭环已通过独立实库验收；完整产品
身份、浏览器和 Agent 联验尚未完成，相关入口继续默认关闭。

## 目录分页扫描状态补丁（2026-09-30）

新增登记 `cloudfile-server/server/repo-perm.c`：在原始窗口扫描循环中记录消费数量和耗尽状态，旧函数保留包装。RPC 之后的列表已丢失被过滤项，扩展文件无法恢复扫描位置，因此需要在这一底层循环采集；不改变目录读取、排序或权限规则。契约与共享用例见 `docs/directory-pagination.md`。

## Legacy Search Permission Transport（2026-09-30）

复用已登记的 Server RPC/header/registration/Python binding/Makefile 接缝，新增
`common/cf-permission-many.*` 与内部 `cf_check_permissions_many`。接缝仅委托有界 JSON
适配器调用原 scalar engine；第一轮和发布前第二轮均保留，未修改权限 writer 或规则。
不新增上游修改路径。契约、结构计数和非 lease 边界见
[`docs/legacy-search-permission-many.md`](docs/legacy-search-permission-many.md)。

## Hub 上游同步（2026-09-30）

Hub 从 `957c7c500` 同步至 `6d2452ba95f52fb99388bae22ba957f1ff764b16`，
纳入 54 个上游提交，包括只读库权限、Wiki 写鉴权和目录统计 SQL 参数化修复。
`check_folder_permission` 先校验原生访问权限，再降为只读，最后执行 CloudFile
权限钩子；两个历史页面迁移到原生 API 后保留下载和恢复权限控制。

跟随上游将构建、基础镜像（含旧 Docker 回退路径）与 Hub 测试 CI 对齐至
Node 24，容器固定 `24.21.0`。日历、SDoc 编辑器及锁文件采用上游版本
`1.0.33`、`3.0.250`；生产构建通过。部署前须重建基础镜像，以免复用旧 Node 20。

新增登记两处测试兼容补丁：`frontend/package.json` 的 Jest 资源转换规则排除
`.cjs`，避免把 Axios 的 CommonJS 入口转换成文件名；
`frontend/src/components/search/search.test.js` 隔离 Webpack 图标加载与编辑器展示
依赖，仅验证真实的访问记录逻辑。Jest 配置和原测试依赖无法通过运行时扩展点
修复，因此在原位置修改；后续上游修复同类测试时复核并移除补丁。

验证：Hub 扩展 635 passed / 5 skipped（含新增只读权限回归 13 项），当前契约
534 passed / 295 skipped / 229 subtests，前端 8 suites / 42 tests、全量 lint、
生产构建通过。本机快速检查的两项 C 测试受缺少 `valac` 与脚本执行位影响；
在隔离 Linux 基础镜像中经 `bash` 执行，并为 Vala 指定源码基目录后，目录分页
8 项、Hub 联动 20 项、批量权限 6 项全部通过，未修改 Server 源码。
其余快速检查通过；未运行完整运行时栈 E2E，未配置外部 S3 测试端点。
补丁登记中的其他既有告警保持可见，本次不批量补登记。

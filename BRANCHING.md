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

三条的共同底线仍是那条铁律：**`CF_ENABLE_*` 全关 = 原生 CE 行为**。第 1 条要跟上游的
默认值，第 2 条要保 CloudFile 的开关语义，两者冲突时以"关掉开关必须与上游一致"收口。

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

能力合并前必须证明开关关闭时仍走原生 CE 路径，并在开关开启时通过专项门禁。跨 Hub/Server 的语义先更新共享规格和用例，再同步实现。

发布时将三个仓库的最终提交写入 `release.yaml` 的 `server_commit`、`hub_commit`、`docker_commit`，
然后在 GitHub Actions 中从 `prod` 分支手动运行 `CloudFile production build`，填写版本并
选择 `incremental` 或 `full`。日常小改用增量路径，正式复核、上游升级或缓存对照用保留的
CE 全量路径；通过后再使用同一版本 tag。普通 push 不触发生产编译；增量构建计划会校验
声明的 Server/Hub 提交与实际解析结果一致。未填写提交的开发清单不能当作可追溯发布记录。

历史分支事故、旧排期和过期文件清单保留在 [`docs/history/`](docs/history/)，不作为当前操作依据。

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

`cloudfile-hub` 新增登记（18），按性质分四类：

- **权限/安全就地收窄**（判定的是上游自己的权限调用点，扩展点覆盖不到）：
  `seahub/api2/endpoints/internal_api.py`（Web 字节通道按目标路径而非根 `/` 判定，
  堵住凭 Cookie 直连 URL 绕过子目录规则）、`seahub/api2/endpoints/file_tag.py`
  （标签按目标真实路径判定，此前只查父目录）、`seahub/api2/endpoints/share_links.py`
  与 `seahub/views/repo.py`（`CF_ENABLE_SHARE_RESTRICT` 不得被旧链接/匿名 token 绕过）。
- **能力挂钩**：`seahub/api2/endpoints/file_access_log.py`（审计后端由 Pro 限定改为
  CloudFile 提供）、`frontend/src/components/dialog/move-dirent-dialog.js`
  （`CF_ENABLE_FILEOPS` 移动前成员影响确认）。
- **UI/交互增强**：`frontend/src/components/dir-view-mode/dir-grid-view.js`、
  `frontend/src/components/dropdown/item.js`、`frontend/src/components/repo-info-bar.js`、
  `frontend/src/css/repo-info-bar.css`、`frontend/src/models/repo-tag.js`、
  `frontend/src/metadata/components/cell-formatter/file-tags/index.js`、
  `frontend/src/pages/lib-content-view/lib-content-view.js`。
- **CE 兼容/部署**：`seahub/api2/endpoints/groups.py`（CE 无群组配额 API）、
  `seahub/oauth/views.py`（SSO 建号后回填 `contact_email`，否则目录同步成员全为
  UnknownSubject）、`seahub/onlyoffice/settings.py`、`seahub/onlyoffice/utils.py`、
  `seahub/onlyoffice/views.py`（Document Server 可达的内部 fileserver 根）。

**拒绝登记 3 项**（保持未登记，另行清理——不能用补登记掩盖）：

- `seahub/ai/apis.py`、`seahub/ai/utils.py`：与上游只差尾随空白，不含任何能力。
  应还原为上游内容，让它自然退出清单。
- `frontend/webpack-stats.pro.json`：构建产物，内容随构建漂移（本次 1060 行）。
  2026-08-15 已因同样原因移出清单一次；应改为忽略/不追踪，而不是登记。

同时修正 `release.yaml` 的 CI 比对锚点：`cloudfile-hub` 的 `seahub` 锚点停在
`da3334e`，比它真正的合并基点落后 52 个上游提交，CI 里两点 diff 会把 219 个文件
误报成 CloudFile 改动；已前移到真实合并基点 `84eeabf`（修正后与本地三点 diff 的
21 项完全一致）。`seafile_server`（→ `d9ed57e`）与 `seafile_docker`（→ `566b7e5`）
随本次同步前移。

## 合并与发布

能力合并前必须证明开关关闭时仍走原生 CE 路径，并在开关开启时通过专项门禁。跨 Hub/Server 的语义先更新共享规格和用例，再同步实现。

发布时将三个仓库的最终提交写入 `release.yaml` 的 `server_commit`、`hub_commit`、`docker_commit`，
然后在 GitHub Actions 中从 `prod` 分支手动运行 `CloudFile production build`，填写版本并
选择 `incremental` 或 `full`。日常小改用增量路径，正式复核、上游升级或缓存对照用保留的
CE 全量路径；通过后再使用同一版本 tag。普通 push 不触发生产编译；增量构建计划会校验
声明的 Server/Hub 提交与实际解析结果一致。未填写提交的开发清单不能当作可追溯发布记录。

历史分支事故、旧排期和过期文件清单保留在 [`docs/history/`](docs/history/)，不作为当前操作依据。

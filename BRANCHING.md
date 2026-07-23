# CloudFile 分支模型

三个仓库（`cloudfile-server`、`cloudfile-hub`、`cloudfile-docker`）使用同一套分支模型。

| 分支 | 用途 |
|---|---|
| `dev` | **CloudFile 主干**，也是三个仓库在 GitHub 上的默认分支 |
| `sync/upstream-YYYYMMDD` | 周期性把上游合并进 `dev` 的工作分支 |
| `feature/*`、`fix/*` | 常规开发，命名对齐 `CF_ENABLE_*`，见 [docs/BRANCHES.md](docs/BRANCHES.md) |

上游的纯净副本**不需要本地分支**，`upstream/master` 这个 remote-tracking ref
本身就是，且不可能被误提交——比维护一个"约定上不许提交"的本地镜像分支更可靠。

`main` 停留在 CloudFile 的第一个提交之前，作为 fork 基线的锚点。不再使用，
确认不需要后可以删掉：

```bash
git branch -D main
```

## remote

```
origin     git@github.com:eaopen/cloudfile-<repo>.git
upstream   https://github.com/haiwen/<upstream-repo>.git
```

## 跟随上游

因为上游 14.0 CE 尚未发布，基线锚点是 **commit SHA 而不是 tag**（见
[release.yaml](release.yaml) 的 `upstream:` 段）。跟随上游的流程：

```bash
git fetch upstream master
git checkout -b sync/upstream-$(date +%Y%m%d) dev
git merge upstream/master
```

冲突集中在 CloudFile 修改过的上游核心文件上。这些文件被刻意限制到最小集合，
每次同步前先确认这份清单没有变长：

**cloudfile-hub**
- `seahub/utils/rooturl.py` — 追加 CloudFile 路由
- `seahub/views/__init__.py` — `check_folder_permission` 委派
- `frontend/config/webpack.entry.js` — 注册 CloudFile 前端入口（纯数据追加，
  往 `entryFiles` 字典里加一个 key，不含逻辑）

前两个是行为改动，需要逐行 review；第三个是数据追加，冲突时直接保留双方的 key 即可。

**cloudfile-server**
- `common/rpc-service.c` — `seafile_check_permission_by_path` 实现 +
  `seafile_cf_find_restricted_path`
- `include/seafile-rpc.h`、`server/seaf-server.c` — 新 RPC 声明与注册
- `server/seafile-session.c` — 启动时 `cf_acl_init()`
- `server/Makefile.am` — 新增源文件
- `fileserver/sync_api.go` — 同步前的子树校验（两处：`checkPermission` 与缓存清理）
- `python/seaserv/api.py` — `is_repo_syncable` / `is_dir_downloadable`
- `python/seafile/rpcclient.py` — 新 RPC 客户端声明

`cf_*` 建表放在**新文件** `scripts/sql/{mysql,sqlite}/cloudfile.sql`，没有动上游的
`seafile.sql`，因此这一块永远不会产生合并冲突。建表由容器每次启动时执行
（`bootstrap.py` 的 `apply_cloudfile_schema`），全部是 `IF NOT EXISTS`——
新装、升级、以及既有 CE 部署切换到 CloudFile 三种路径都能覆盖。

**cloudfile-docker**
- `scripts/scripts_14.0/bootstrap.py` — 写入 CloudFile 配置段与建表
- `scripts/scripts_14.0/start.py` — 每次启动时调用 `write_cloudfile_config()`
- `.gitignore` — 忽略构建产物与部署密钥

其余 CloudFile 代码都在新增文件里（`cloudfile_ext/`、`common/cf-acl.[ch]`、
`build/cloudfile_14.0/`、`image/cloudfile_14.0/`、`deploy/compose/`），不参与合并冲突。

合并前后都跑一次登记检查，确认清单没有变长：

```bash
./tools/check-upstream-patches.sh
```

合并完成后更新 `release.yaml` 的 `upstream:` SHA 并跑一遍
[deploy/compose/README.md](deploy/compose/README.md) 里的原生 CE 回归。

## 发布

三仓打同一个 tag：

```bash
git tag v14.0.0-cf.0 && git push origin v14.0.0-cf.0
```

发布前把三仓的 commit SHA 写回 `release.yaml` 的 `server_commit` /
`hub_commit` / `docker_commit`。

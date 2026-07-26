# CloudFile 分支模型

三个仓库（`cloudfile-server`、`cloudfile-hub`、`cloudfile-docker`）使用同一套分支模型。

| 分支 | 用途 |
|---|---|
| `dev` | **CloudFile 主干** = 扩展基线 + 已验收能力（**全部开关默认关闭**），也是三个仓库在 GitHub 上的默认分支 |
| `sync/upstream-YYYYMMDD` | 周期性把上游合并进 `dev` 的工作分支 |
| `feature/*`、`fix/*` | 开发中的能力，一个耦合簇一条，**验收后合回 `dev` 并删除**，见 [docs/BRANCHES.md](docs/BRANCHES.md) |

**能力不长期分叉。** 构建脚本每个仓库只认一个 ref，所以两个尚未合并的能力
无法一起构建、也就无法一起交付；八个能力各占一条长期分支意味着 2⁸ 种交付组合
全都没验证过。让能力住在 `dev` 上是安全的，因为**"全部开关关闭 = 原生 CE"**
这条铁律保证未启用的能力对部署没有影响。完整论证见
[docs/BRANCHES.md](docs/BRANCHES.md) 第一节。

> ⚠️ **能力分支跟进 `dev` 前，先确认它不是 `dev` 的祖先。**
>
> ```bash
> git merge-base --is-ancestor feature/<能力> dev && echo "危险：merge 会快进"
> ```
>
> 如果是祖先，`git merge dev` 会**快进**而不是合并——分支指针直接跳到 `dev`，
> 该能力的代码被"合并"掉，且 git 不会报任何冲突。三个仓库的
> `feature/dir-acl` 当前正处于这个状态（能力代码是在 `dev` 上被剥离的，
> 分支停在剥离前的那个提交，没有任何独有提交）。
> 正确的恢复步骤见 [docs/BRANCHES.md](docs/BRANCHES.md) 第九节。

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
- `seahub/search/utils.py` — `search_files` 委派给已选中的检索 provider
- `seahub/utils/__init__.py` — `HAS_FILE_SEARCH` 或上"provider 是否已配置"
- `frontend/config/webpack.entry.js` — 注册 CloudFile 前端入口（纯数据追加，
  往 `entryFiles` 字典里加一个 key，不含逻辑）
- `scripts/seaf-fsck.sh` — 修复模式前置校验 seaf-server/fileserver 已停止，
  并把 `run_seaf_fsck` 的退出码传播到脚本自身
- `scripts/seaf-gc.sh` — 把 `run_seaf_gc` 的退出码传播到脚本自身

前两个是行为改动，需要逐行 review。

中间两个是检索扩展点，**必须成对存在**：只改 `search/utils.py` 的话，CE 部署上
六个搜索入口都因为 `HAS_FILE_SEARCH=False` 而根本不会路由过来，provider 永远
不被调用。两处都是加法（或上 / 未选中则回落原生路径），取舍见
[docs/EXTENSION-POINTS.md](docs/EXTENSION-POINTS.md) 第六节。

`frontend/config/webpack.entry.js` 是数据追加，冲突时直接保留双方的 key 即可。

`scripts/seaf-fsck.sh`、`scripts/seaf-gc.sh` 属于离线 S3 维护 wrapper
（见 `feat(storage): add offline S3 maintenance wrappers`）。两个上游脚本原本
不管 `run_seaf_fsck`/`run_seaf_gc` 是否成功，末尾都固定 `echo "Done."` 后以 0
退出，调用方（迁移编排脚本）拿不到失败信号；`seaf-fsck.sh` 还需要在 `-r`/
`--repair` 前确认 `seaf-server`/`fileserver` 均已停止，避免修复期间仍有写入。
这两点都发生在脚本唯一的调用入口上，无法旁路成新文件：整份复制这两个脚本
自己维护，会失去 `check-upstream-patches.sh` 对分叉的检测；保留原脚本可直接
调用，则新加的离线校验形同虚设。跟随上游时这两个文件的冲突面很小（末尾几行
的收尾逻辑），按上面的意图重新应用改动即可。

**cloudfile-server**
- `common/obj-{backend,store}.{c,h}`、`common/block-{backend,mgr}.{c,h}`、
  `common/fs-mgr.{c,h}` — 在 CE 原有构造入口选择 FS、S3 或 multiple，补齐三态存在检查、
  可报告失败的删除与整库复制接口；Commit/FS 与 Block 使用两套上游接口，不能旁路接入。
- `configure.ac` — C S3 客户端使用 libcurl 原生 SigV4，最低版本提高到 7.75。
- `fuse/Makefile.am` — seaf-fuse 与主服务使用同一套 S3/multiple 后端，避免读取路径
  仍固定到本地 FS。
- `common/rpc-service.c` — `seafile_check_permission_by_path` 实现 +
  `seafile_cf_find_restricted_path`
- `include/seafile-rpc.h`、`server/seaf-server.c` — 新 RPC 声明与注册
- `server/seafile-session.c` — 启动时 `cf_acl_init()`
- `server/Makefile.am` — 新增源文件
- `server/gc/{Makefile.am,seafserv-gc.c,seaf-fsck.c,gc-core.c,gc-core.h,fsck.c,repo-mgr.c,repo-mgr.h}`
  — GC/FSCK 通过统一后端遍历并传播枚举、读取、删除和修复失败；新增离线迁移程序在复制并
  回读校验三类对象后事务切换 `RepoStorageId`。
- `fileserver/sync_api.go` — 同步前的子树校验（两处：`checkPermission` 与缓存清理）
- `python/seaserv/api.py` — `is_repo_syncable` / `is_dir_downloadable`
- `python/seafile/rpcclient.py` — 新 RPC 客户端声明
- `python/seaserv/__init__.py` — re-export `REPO_STATUS_*`；seafevents 从包根导入
  这两个既有常量，缺失会让 8889 任务服务在 import 阶段退出，进而阻断元数据初始化
- `fileserver/objstore/objstore.go` — 在既有构造入口选择 FS、S3 或多存储后端；不能改为
  新文件，因为三个对象管理器均从这里创建。
- `fileserver/go.mod`、`fileserver/go.sum` — S3 SDK 的受控模块依赖；Go 的模块校验文件必须
  与声明一起提交。
- `fileserver/objstore/objstore_test.go` — 既有对象存储测试扩展为配置和 MinIO 集成覆盖；保留
  在同一测试包才能验证未导出的后端构造函数。

`cf_*` 建表放在**新文件** `scripts/sql/{mysql,sqlite}/cloudfile.sql`，没有动上游的
`seafile.sql`，因此这一块永远不会产生合并冲突。建表由容器每次启动时执行
（`bootstrap.py` 的 `apply_cloudfile_schema`），全部是 `IF NOT EXISTS`——
新装、升级、以及既有 CE 部署切换到 CloudFile 三种路径都能覆盖。

**cloudfile-docker**
- `scripts/scripts_14.0/bootstrap.py` — 写入 CloudFile 配置段与建表
- `scripts/scripts_14.0/start.py` — 每次启动时调用 `write_cloudfile_config()`
- `.gitignore` — 忽略构建产物与部署密钥

其余 CloudFile 代码都在新增文件里（`cloudfile_ext/`、`common/cf-ext.[ch]`、
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

# 默认按库自动分配本地存储

更新：2026-10-11。**v0.6 复用已实现的 C/Go/Python 路由**，本次只补新安装默认 Compose 配置、契约验证和运维说明，不重做用户已在一套 CloudFile 环境验证的真实库。2026-10-08 原目标仍成立：逐库登记存储类和 bind mount 会使每次建库依赖运维修改部署并重启。一个父目录挂载，后端首次使用时按稳定 key 创建子后端。

## 新安装的开箱即用配置（不改变已有部署）

1. **仅新安装**：在 `deploy/compose/` 内执行 `cp .env.example .env`，新模板默认设置 `COMPOSE_FILE=docker-compose.yml:docker-compose.auto-library-storage.yml`。之后仍使用 `docker compose up -d`；不需要逐个创建库时修改 Compose 或静态存储类。
2. 覆盖文件 `deploy/compose/docker-compose.auto-library-storage.yml` 把 `CF_LIBRARY_STORAGE_HOST_DIR=./data/libraries` **一次性**挂载至主服务及 `cf-worker` 的 `/shared/seafile/library-storage`，该目录必须持久化并包含在运维备份清单内。若调整父目录，只改新装环境这一项，并在部署前确认源目录与权限；**不得把旧库绑定目录当作新的空目录**。
3. 新模板沿用当前多存储引导兼容开关 `CF_ENABLE_S3_STORAGE=true` 与 `SEAF_SERVER_STORAGE_TYPE=multiple`，这是已有代码的历史开关名称，**实际配置为本地文件系统，没有 S3 后端或凭据**。存储类 `legacy-default` 是已有 Seafile 本地对象路径，`auto-local` 为非默认存储类模板，供原生建库绑定到每库子目录。
4. 现有 CloudFile / DEV / PROD 的 `.env` 和持久化 `seafile.conf` **完全不自动变更**。已经启用独立父目录的环境保持原挂载、配置和 `RepoStorageId`。新版本更新文件不会自动覆盖原有 `.env`，但**手工套用新 overlay 就属于存储变更**，必须先核对旧库位置、实例备份与回退，禁止无迁移方案直接切换已有 S3/legacy 实例。
5. 不采用每库独立目录的**全新安装**可把 `.env` 的 `COMPOSE_FILE` 改回 `docker-compose.yml`；特殊 S3/存储类部署沿用已有显式配置及受控存储迁移工具，不与新默认模板叠加。

**仅做配置解析核对（不启动容器、不写库）**：

```bash
cd deploy/compose
docker compose --env-file .env.example config --quiet
# 检查组合配置中的 cloudfile / cf-worker 父目录挂载及两个 storage class
python3 -m unittest discover -s ../../tests -p test_v06_default_library_storage.py -v
```


## 契约

- 宿主机父目录可按环境设置（新装默认为 `./data/libraries`，已有实际部署可采用其他绝对路径），统一挂载为容器内 `/shared/seafile/library-storage`；主服务和 worker 使用同一读写挂载。**每库子目录由存储引擎自行处理，禁止逐库增加 Compose mount。**
- 存储类 JSON 保留既有 `legacy-default`，新增唯一模板 `auto-local`，`is_auto: true`、`is_default: false`，三个 `fs` 后端的 `dir` 均为上述容器父目录。模板不是一个可直接写入的共享后端。
- 新库未显式选择后端时，原生建库在初始 commit 前绑定 `auto-local:<repo UUID>`。CloudFile 建库 API 可提交 `repo_key`，此时绑定 `auto-local:<repo_key>`。默认导入提交已有配置中的 key，不新增部署配置或重启。
- key 为 1–80 个 ASCII 小写字母、数字或连字符，首尾必须为字母或数字。目录为父目录/key；拒绝路径穿越和 key 目录符号链接。
- `cf_library_storage_key` 使用 key 主键、repo UUID 唯一约束，原子保留绑定。永久删除保留绑定记录作为 GC 定位和 key 占用记录，避免旧对象混入同名新库。显示名变更不改变 key。
- 既有未绑定库仍走 `legacy-default`；既有显式本地/S3 存储类继续使用原配置。自定义磁盘通过预登记的例外存储类选择，客户端不能指定任意宿主机路径。
- C、Go fileserver、Python 对象读取器遵守同一 ID 和目录规则，未知存储类仍拒绝回落。虚拟库继承原库绑定。GC 通过保留的 key 记录清理正确子目录，不能依赖进程已缓存该库。

## 验证要求

跨层 key 用例位于 `automatic-local-storage-cases.json`。除单位测试外，须以同一运行镜像验证：不修改 Compose/存储 JSON、不重启容器，连续创建两个不同 key 的库，上传下载及目录/文件搜索，重启后读取，重复 key 拒绝，原有库读取，以及永久删除后的物理对象清理。

普通建库入口未填写 key 时使用 UUID，可保证无需配置即可独立存储；组织命名 key 由受控建库 API 或通用导入配置指定。网页上的专用 key 输入界面不在此变更范围。

## 构建接线

Python 依赖保持锁定上游 SHA，`patches/seafobj/automatic-local-storage.patch` 提供惰性字典及虚拟库原库路由，`cloudfile-build.sh` 对 seafobj 应用补丁，失败即终止构建。C/Go 代码在 server fork 内；本次生产候选基于原生产 `d93b51b` 加存储改动单独构建，避免带入较新开发分支的编辑/RPC 改动。

## 提交门禁

新增 key 保留表对应 `release.yaml` 的 `database_schema: 3`，启动仍以 `IF NOT EXISTS` 增量建表。统一 `tools/run-checks.sh` 执行补丁内 Python 策略、C 共享 key 用例和 Go 对象存储路由测试。C 用例由 Python 读取共享 JSON 并调用真实策略，仅依赖 glib，避免为纯策略测试引入原生 JSON 库。

# 默认按库自动分配本地存储

2026-10-08 修改原因：逐库登记存储类和 bind mount 会使每次建库依赖运维修改部署并重启。默认路径改为一个父目录挂载，后端在首次使用时按稳定 key 构造本地子后端。

## 契约

- 部署只挂载一次宿主机 `/data2/cloudfile/libraries` 到 `/shared/seafile/library-storage`；主服务和 worker 使用同一读写挂载。
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

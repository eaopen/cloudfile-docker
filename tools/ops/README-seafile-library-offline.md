# Seafile 单库离线检查与导出（无需 CloudFile 服务）

本工具只负责**定位某一个** Seafile CE/CloudFile 库的物理对象目录，以及显式调用 Seafile 原生 `seaf-fsck --export` 导出其逻辑文件。无需 Hub、CloudFile Web/API、`cf_library_storage` SQL，也不建立新的存储元数据或同步引擎。

**默认不备份、不复制、不扫描全库内容。** 所有操作都必须传入**完整且唯一的 `repo_id`**，没有 `--all`。此工具也不会通过定时器、Compose 启动脚本自动运行。

## 存储结构

Seafile 原生老库：

```text
<seafile-data>/storage/{commits,fs,blocks}/<repo_id>/...
```

CloudFile V2 每库本地目录：

```text
<library-root>/<repo_key>/storage/{commits,fs,blocks}/<repo_id>/...
```

`repo_key` 可以是与 `repo_id` 不同的受控名称。离线定位只检查一级库目录中的 `storage/commits/<repo_id>`，不需要知道 `cf_library_storage` 内容。如果同一 UUID 同时在原生目录和多个库目录中出现，**拒绝自动选择**，由运维人工核对。这些目录是 Seafile 对象存储，**不是用户文件目录**。

## 1. 只读定位（推荐的第一步）

```sh
python3 tools/ops/seafile-library-offline.py inspect \
  --repo-id <repo-uuid> \
  --seafile-data /shared/seafile/seafile-data \
  --library-root /shared/seafile/library-storage
```

只枚举一级目录并核对 Commit/FS/Block 根，不调用服务、不读数据库、不导出任何字节，不更改文件。**只有旧版 CE 原生库时，可以省略 `--library-root`；一旦显式提供该参数，目录不存在或挂载丢失必须报错，不得静默回退到旧库目录。** 它不是对象哈希完整性检查：完整修复/检查应按照 Seafile 原生工具的约束另行执行。

## 2. 显式导出单个库（耗时、耗磁盘空间）

**操作前确保目标磁盘有足够空间，使用未加密库并明确选择一个 `repo_id` 和全新目标目录。**

```sh
python3 tools/ops/seafile-library-offline.py export \
  --repo-id <repo-uuid> \
  --seafile-data /shared/seafile/seafile-data \
  --library-root /shared/seafile/library-storage \
  --seaf-fsck /opt/seafile/seafile-server-latest/seafile/bin/seaf-fsck \
  --output-dir /mnt/recovery/<repo-uuid>
```

此操作：
1. 先按 Seafile 物理目录确定唯一库，不使用 CloudFile 服务或 SQL。
2. 在目标磁盘创建临时、只用于本次操作的原生 Seafile 配置和对象视图；通过符号链接**引用**该库的 Commit/FS/Block 目录，不复制它们。
3. 调用 **Seafile 原生** `seaf-fsck -d ... -F ... --export ... <repo-id>`。原生工具读取 Commit/FS/Block，生成普通文件。
4. 只有在**全部**条件满足时才发布结果：原生工具退出码为 0、日志中没有 `[WARNING]`/`[ERROR]` 记录、没有已知失败标记（`Failed to export file`、`Failed to mkdir`、`Dir/File ... is missing.` 等）、且恰好产出一个库目录。否则整体失败：不创建/不保留目标目录，返回非零退出码，并在 stderr 附带命中的原生日志行；目标目录已存在时同样拒绝覆盖。

独立的离线临时配置只使用原生 filesystem backend（去掉 `cloudfile_v2` 路由层）；**不修改原来服务器的 `seafile.conf`**。需要可执行的 `seaf-fsck` 以及适合该二进制的动态库环境。**本工具直接执行所给的 `seaf-fsck` 二进制，不经过发行包的 `seaf-fsck.sh` 包装脚本**；与包装脚本一致，它会自动把该二进制同级安装树中的 `seafile/lib`、`seafile/lib64` 前置到 `LD_LIBRARY_PATH`（保留调用方已有值；二进制不在安装树中时保持原环境），因此 14.0.8 这类依赖随包 `libevent` 的镜像也可直接执行。若二进制位于非标准位置或仍有库依赖缺失，需由调用方自行设置 `LD_LIBRARY_PATH`。加密库或损坏库可能无法成功导出；即便返回成功，也不能据此保证所有历史版本都已恢复。Seafile 原生导出读取选出的可用 Commit，而不是完整的数据库备份。

原生导出只在日志里报告**部分**内部失败（C 层 `export_file()` 为 `void`：缺块、目录对象读不到、目标文件无法创建，都可能只留一行日志后继续）。本工具按日志级别与已知失败标记判断，无法保证覆盖未来版本新增的静默失败；**成功导出仍不等于内容完整**，完整性仍需 `verify-export` 与官方 per-repo fsck。

## 3. 显式检查已导出的文件

```sh
python3 tools/ops/seafile-library-offline.py verify-export \
  --repo-id <repo-uuid> \
  --output-dir /mnt/recovery/<repo-uuid>
```

这会读取目录树元数据并计算文件数量/总字节数；如果确有需要再传 `--hash`，逐文件读完整内容生成树校验摘要，可能消耗较长时间。

**检查导出文件 ≠ 证明全部原对象完整**。完整性验收仍可按 Seafile 官方的 per-repo `seaf-fsck` 检查/修复流程进行，涉及库 DB 与对象健康时按其要求执行。官方说明：https://manual.seafile.com/14.0/administration/seafile_fsck/

## 4. 严格限制与独立职责

- 不提供无库 ID 的批量导出；不启动自动备份、定时同步、全盘复制。
- 不直接读写用户逻辑文件到 Seafile 对象目录；导出的文件只能进入单独的新目标目录。
- 不直接修复/变更存储映射；`RepoStorageId` 仍是在线后端路由事实。
- 只支持**本地 filesystem** 的原生布局和 auto-local；S3/RustFS/MinIO 需要其独立工具及配置，绝不猜路径或回退到错误本地目录。
- 现有 `cf_recovery.py` 是**另一个显式调用的、全实例离线备份工具**，不能视为普通的单库导出，也不得加入自动启动/发布路径；如果存在 auto-local/S3，应重新审查其完整备份范围，避免漏数据或误报备份成功。

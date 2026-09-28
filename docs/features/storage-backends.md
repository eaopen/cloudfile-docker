# 多存储与 S3 兼容存储

> 用途：说明 Seafile 原生数据的存储后端、存储类、迁移和运维限制
> 适用版本：Seafile CE 14 参考基线
> 当前状态：多存储后端、按资料库映射和离线迁移 MVP 已完成；新建资料库的自助选择入口持续改进；S3 兼容性只验证 MinIO

本能力存储 Seafile 原生 commit、FS object 和 block。它与面向外部文件系统的
[虚拟目录挂载](external-directory-mount.md)无关。

实现顺序遵循“上游可用能力优先”：先复用 Seafile 已有存储模型、配置语义和
`RepoStorageId`，只为锁定的 CE 14 代码中缺失的后端、配置与运维链路增加扩展。MVP
必须先闭合配置、路由、按库分配、迁移、校验与恢复，再在不改变数据模型的前提下持续
改进管理界面和分配策略。

## 与上游能力的边界

Seafile 14 管理手册定义了 S3 和 multiple storage backends 的配置模型：三类对象后端、
`storage_id`、`RepoStorageId`、默认存储类和离线迁移。CloudFile 沿用这些概念和 Seahub
中已有的存储类数据结构。

但 `release.yaml` 锁定的 `haiwen/seafile-server` CE 提交中不存在
`storage-backend-multi.c`、C/Go S3 backend 或 `seaf-storage-migrate`；这些文件和对应
维护路径由 CloudFile fork 新增。文档因此不得写成“仅打开 CE 14 自带开关”，也不得把
Seafile 的数据模型和 `RepoStorageId` 归为 CloudFile 发明。

官方参考：

- [Multiple Storage Backends](https://manual.seafile.com/14.0/setup/setup_with_multiple_storage_backends/)
- [S3 Backend](https://manual.seafile.com/14.0/setup/setup_with_s3/)

## 当前支持范围

| 模式 | 当前范围 | 状态 |
|---|---|---|
| 本地文件系统 | CE 默认 commit/FS/block 后端 | 已完成 |
| 单一 S3 兼容存储 | 三个 bucket，C 与 Go fileserver 路径 | 已完成；MinIO 优先验证 |
| 多存储 | 每个存储类可分别定义 commit、FS、block 的 `fs` 或 `s3` 后端 | 已完成后端路由与离线迁移 |
| 按资料库选择存储方案 | 通过 `RepoStorageId` 与迁移工具为不同资料库指定 `storage_id` | 已完成管理员分配路径；新建库自助入口待改进 |
| 用户选择/角色/Repo ID 自动分配 UI | Seahub 代码存在但仍受 Pro 判断；CloudFile 未解除或替换 | 未实现，不影响管理员按库分配 |
| 其他后端 | Swift、Ceph、OSS 等不在 CloudFile 当前配置校验范围 | 待确认 |

## 单一 S3 配置

```dotenv
CF_ENABLE_S3_STORAGE=true
SEAF_SERVER_STORAGE_TYPE=s3
S3_COMMIT_BUCKET=cloudfile-commits
S3_FS_BUCKET=cloudfile-fs
S3_BLOCK_BUCKET=cloudfile-blocks
S3_KEY_ID=<access-key>
S3_SECRET_KEY=<secret-key>
S3_HOST=minio.example.internal:9000
S3_AWS_REGION=us-east-1
S3_USE_HTTPS=true
S3_USE_V4_SIGNATURE=true
S3_PATH_STYLE_REQUEST=true
```

生产 bucket 必须预先创建。`s3` profile 的 `minio-init` 只用于本地验证，不应被描述为
通用生产 bucket 生命周期管理。

## 多存储配置与映射

```dotenv
CF_ENABLE_S3_STORAGE=true
SEAF_SERVER_STORAGE_TYPE=multiple
CF_STORAGE_CLASSES_JSON=[...]
```

每个类至少包含唯一 `storage_id`、三类对象配置，并且全局必须有一个
`is_default=true`。bootstrap 将 JSON 写入权限为 `0600` 的
`conf/seafile_storage_classes.json`，同时在 `seafile.conf` 启用 storage classes。

路由规则：

1. `RepoStorageId` 有记录时使用该 `storage_id`；
2. 没有记录时使用默认类；
3. 虚拟资料库跟随原始资料库的存储类；
4. 未知 ID、重复 ID、缺少默认类或缺少对象后端时失败，不跨后端猜测或回退。

CloudFile 支持管理员通过 `RepoStorageId`/迁移工具为不同资料库选择存储方案；普通新资料库
没有显式映射时落到默认类。当前没有解除 Seahub 创建资料库路径中的 Pro 判断，因此不能
把“按库选择”扩大解释为已经提供用户自助选择、角色分配或按 Repo ID 自动均衡。后续应在
CE 可用的独立分配层上补齐新建库入口和 E2E，不改变已验证的路由契约。

## 新建库自助分配：后端 + API 方案（不实现 UI）

自助分配的根因不在前端，而是 CE fork 缺存储类 RPC。已按「后端优先、不实现 UI」落地：

- **C 侧**（`cloudfile-server`，新文件 `common/cf-storage.{c,h}`）：
  - `cf_get_storage_classes_json()` —— 读 `[storage] storage_classes_file`，返回
    `[{"storage_id","storage_name","is_default"},…]` 的 JSON 字符串；
  - `cf_create_repo_json()` —— 收 JSON 请求（`name`/`owner`/`desc`/`passwd`/
    `enc_version`/`storage_id`），在 `seaf_repo_manager_create_new_repo` 里**先写
    `RepoStorageId` 再写初始 commit**，保证新库的根 commit 落在所选后端（否则
    「先建库后改映射」会让根 commit 留在默认类、按映射读不到）。
- **RPC 名**：`cf_get_storage_classes`（`string→string` 返回 JSON）、`cf_create_repo`
  （`string→string`，收 JSON 返回 repo_id）。searpc 无 8 参签名，故建库走 JSON 单参
  而非给上游 `seafile_create_repo` 加第 9 参。
- **Python 透传**：`rpcclient` + `seaserv.get_storage_classes()` / `create_repo_with_storage()`。
- **Seahub API**（`cloudfile_ext/storage/`，`CF_ENABLE_S3_STORAGE` 门控）：
  - `GET  /api/v2.1/cloudfile/storage-classes/` 列出存储类；
  - `POST /api/v2.1/cloudfile/repos/` 建库并按 `storage_id` 固定存储类。
- **不实现前端下拉**；`is_pro_version()` 门控的 `get_library_storages`/`_create_repo` 不解除，
  自助分配走 CloudFile 独立端点，避免上游 patch。

前端下拉、按角色/Repo ID 自动分配，以及配 MinIO 起栈的端到端复验仍待后续；本方案
先闭合「列出存储类 + 按存储类建库」的后端与 API。

## 已有资料库迁移

迁移必须停止 `cloudfile` 服务后执行：

```bash
./seaf-storage-migrate.sh <repo_id> <target_storage_id>
```

工具复制 commit、FS、block 以及关联虚拟资料库 commit，逐对象回读后才在事务中更新
`RepoStorageId`。源对象默认保留，便于人工回滚；清理源对象是单独且不可逆的操作。

> **警告：** 不要在服务运行时迁移，不要在验证和备份完成前删除源对象，也不要给
> commit、FS 或 block bucket 配置按年龄自动删除的生命周期规则。

## 一致性、备份与故障处理

- 资料库是映射单位，但三类对象可指向不同后端；任一后端不可用都可能使资料库不可用。
- 网络、认证、权限、bucket 和 5xx 错误保持为错误，不能当作对象不存在。
- GC 只有完整遍历成功后才能删除；FSCK 修复要求 seaf-server 和 fileserver 已停止。
- 备份必须同时覆盖数据库中的映射和三类对象。只备份 bucket、不备份数据库，或反之，
  都不能保证恢复到一致路由。
- 跨区域复制、版本控制、对象锁、KMS、凭据轮换和灾备切换没有通用自动化；按实际 S3
  产品单独设计并演练。

## 验证范围

`verify-local.sh cap storage` 和 `storage_matrix.py` 覆盖 local + MinIO、跨 block 文件、GC、FSCK、
离线迁移和迁移后读写。C/Go 单测覆盖配置、路由和 S3 对象操作。AWS S3、Ceph RGW、
公有云 S3 兼容服务均不在当前兼容性承诺内；多架构压力、故障注入和大规模迁移也尚无
统一验证结论。公开文档只应写“支持 S3 兼容接口，当前验证对象为 MinIO”。

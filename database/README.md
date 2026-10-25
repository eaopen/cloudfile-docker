# CloudFile V2 当前数据库

CloudFile 尚未正式发布，只有 **五张当前扩展表**。产品不实现旧表升级、旧数据迁移、历史数据追溯或归档流程。

| 表 | 当前数据来源 |
| --- | --- |
| `cf_library_storage` | Seafile CE 原生 `Repo`、`RepoStorageId`（含 RepoTrash/GarbageRepos 状态）重新识别登记 |
| `cf_dir_acl` | 客户 Provider 重新下发库目录 ACL、继承和共享规则 |
| `cf_sso_group_map` | 客户 Provider 重新同步组织/角色到 CE 原生 Group |
| `cf_edit_guard` | 新增独占编辑 Guard，从空表开始 |
| `cf_audit_event` | 从空表开始记录 CE Activity 未覆盖的 Tag/Checkout/Checkin 业务动作 |

原生文件、块、Commit、Repo、RepoStorageId 及 CE 原生 Tag 仍属于 Seafile CE，不是旧 CloudFile 表；不能为了重建扩展表而删除或重新绑定它们。原 CloudFile `cf_tag`、Resource、Session、Intent、Outbox、旧搜索任务等数据一律放弃，绝不在产品里恢复。

## 新装

新 Seafile 数据卷首次启动，从 Server 源码自带的 `cloudfile-v2.sql`、`cloudfile-v2-edit.sql` 和 `cloudfile-v2-audit.sql` 一次性创建全部五表。Guard 的功能启用状态不影响表结构。已有卷启动只验证结构，不自动升级或修补数据库。

## 开发环境重新初始化（仅 DEV，人工执行一次）

1. 停止 CloudFile 文件写入、Hub 和 客户 Provider 同步任务；确认 Agent2 没有正在进行的 Checkout/未完成写入。
2. 由 DEV 数据库管理员清理旧 CloudFile 扩展表并按**当前五表 DDL**重新建立空表。仅处理 CloudFile 扩展表，不删除 CE 的 `Repo`、`RepoStorageId`、`Branch`、`Commit` 或原生 Tag；不读取旧扩展表数据，不生成归档库或迁移台账。
3. 运行现有管理员接口 `POST /api/v2.1/admin/cloudfile/storage/reconcile/`，请求体 `{"repo_ids":[]}`，从实际 Seafile 原生库重新登记 `cf_library_storage`。核对未登记/受阻库，不强行重绑存储、不移动文件。
4. 由 客户 Provider 重新执行目录权限/共享全量下发，以及组织、角色和用户组关系同步。CloudFile `POST /api/v2.1/admin/cloudfile/directory/entities/sync/` 只核对实体与原生组，不代表用户成员关系已经完成；成员关系仍由现有 客户 Provider/SSO 同步链路提供。
5. `cf_edit_guard`、`cf_audit_event` 不回填；开始新测试后产生新锁和新审计事件。验证普通浏览/上传、目录 ACL、客户 Directory 账号/组、本地编辑三模式。

不做增量迁移，不保留旧版本 API/SchemaRunner/Job/Outbox。任何特殊历史恢复均属于产品以外的临时工作，不能进入 CloudFile 日常安装与 CI。

只读五表校验：`python3 /scripts/cloudfile-v2-schema.py check`。未更新到当前五表源码的镜像不能作为本规则的验收对象。

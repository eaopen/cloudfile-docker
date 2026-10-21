# CloudFile V2 数据库（当前开发主线）

当前未正式发布的 V2 产品仅使用五张扩展表：

| 表 | 功能 |
| --- | --- |
| `cf_library_storage` | 库与自动存储绑定 |
| `cf_dir_acl` | 目录 ACL 与目录分享 |
| `cf_sso_group_map` | 外部组织/角色映射到原生 Group |
| `cf_edit_guard` | Agent2 独占编辑（启用 Checkout 才查询） |
| `cf_audit_event` | CE Activity 以外的 Tag、Checkout/Checkin 业务操作日志 |

新卷首次启动由 Server 当前 `cloudfile-v2.sql`、`cloudfile-v2-audit.sql`（及启用 Checkout 时 `cloudfile-v2-edit.sql`）创建当前表结构；已有卷只做结构校验，不自动做任何旧表升级。文件变更历史继续由 CE Activity/Commit 负责。

V0.x、早期 V2 开发数据库的转换不是产品功能。2026-10-21 四表 DEV 一次性转换 SQL 与临时工具已从当前产品源码目录移出，仍可从 Git 历史提交 `b373b8821357d49a664708e1332b76e587ead706` 检索，必要时在产品以外复制使用，不允许通过 Docker 启动或 CI 自动运行。归档目标库统一命名 `cloudfile_legacy_archive`。不要通过恢复旧表、旧 SchemaRunner 或补历史字段解决运行时缺表。

启动结构检查：`python3 /scripts/cloudfile-v2-schema.py check`；只读诊断：`python3 /scripts/cloudfile-v2-schema.py plan`。它们是校验命令，不执行 DDL、数据回填或自动修复。

# CloudFile V2 当前数据库

当前六张扩展表：`cf_repo_feature`（库级能力，默认关闭）、`cf_dir_acl`（目录权限）、`cf_sso_group_map`（身份映射）、`cf_edit_guard`（编辑租约）、`cf_audit_event`（审计）和 `cf_file_protection`（文件保护）。CE 原生 `RepoStorageId` 是存储路由真相；文件、Commit 和原生 Tag 仍由 Seafile 管理。

新卷使用 Server 的四份 `cloudfile-v2*.sql` 一次创建六表。已有卷仅缺 `cf_repo_feature`、其他五表与 DDL 完全一致、无额外 CloudFile 表且没有保护记录或活动租约时，启动在锁内补建空表；其他缺表或结构漂移拒绝启动。

含旧 `cf_library_storage` 的布局必须停写，使用 `tools/migrate/repo-features.py` 先检查再显式执行；工具核验原生路由并将旧表改名为 `retired_library_storage_v2`，归档不是业务 `cf_*` 表。旧能力列表不会自动启用特性；已有保护记录或活动租约若会失去对应能力，必须先进行显式安全处置。不得清空数据或改写原生路由以绕过核验。

只读检查：`python3 /scripts/cloudfile-v2-schema.py check`。迁移步骤参见 [文件保护文档](../docs/file-protection-v1.md)。

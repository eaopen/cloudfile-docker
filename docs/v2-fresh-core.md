# 2026-10-16 历史切片：最初三表与 CE14 干净源码

> **历史档案，不是当前 CloudFile V2 `dev` 构建与 Schema 指引。** 当时只有三表草案以及 `dev2-clean` 构建流程，不得再用本说明执行新装、检查、源代码组装或断言目录 ACL 尚未实现。

当前实际 `dev` 使用 Docker `release.yaml`、`build/cloudfile_14.0/` 当前脚本及固定三仓 SHA 收据；五张扩展表为 `cf_library_storage`、`cf_dir_acl`、`cf_sso_group_map`、`cf_edit_guard`、`cf_audit_event`，不允许旧迁移账本和托管库分类。真正运行的源码/部署/权限事实以 [Docker AGENTS](../AGENTS.md)、[当前权限终判](permission-adjudication-contract.md)、[当前表说明](permission-tables.md) 为准。

旧三表/干净源组装的完整过程仅留在 Git 历史，禁止直接复用旧命令。

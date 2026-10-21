# 历史归档：v0.9 RC 统一权限阶段记录

> **已失效，禁止作为当前 dev 的设计、修复、验收或代码恢复依据。** 本文此前以 `cf_managed_library`、`checkLegacyLibrary()`、`legacyLibraryAllowed()` 等旧“托管库”门禁作为正确性条件，该策略已在当前 V2 移除。旧版本具体过程请查 Git 历史。

## 当前替代规范

CloudFile `dev` 是 V2：没有托管库分类；CE 原生库资格 + `cf_dir_acl` 路径规则/共享根 + Hub Authority + C/Go 最终文件操作检查。不能因为库中存在 ACL 行就整库拒绝。没有路径证明的整库协议可拒绝该操作而不能判定库被托管。

- [当前权限终判契约](permission-adjudication-contract.md)
- [当前权限表](permission-tables.md)
- [当前目录 ACL 语义](acl-semantics.md)

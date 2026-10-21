# 历史归档：v0.9 权限与内部链接草案

> **不再是当前 CloudFile dev 权限规格，也不得从本文件恢复托管库、独立权限表、旧 Guard 或旧测试。** 当前 `dev` 已是 V2，旧内容保留在 Git 历史供追溯。

现行权限由 CE 库资格、V2 目录 ACL/共享目录及统一用户和路径终判组成。文件链接要验证各自的真实目标路径，而非将某个库的任意 ACL 行作为全库拒绝依据。

请仅以 [当前权限终判契约](permission-adjudication-contract.md)、[权限表与身份事实](permission-tables.md) 和 [ACL 语义](acl-semantics.md) 为准。

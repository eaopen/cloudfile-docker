# 历史验收记录：系统管理员与权限修复（2026-10-15）

> **仅供追溯，不属于当前 V2 设计/代码/测试合同。** 当时的“托管库登记后旧上传自动拒绝”等现象，已经被认定为旧错误架构；不能据此阻止有实际路径授权的文件上传、分享链接或恢复 `cf_managed_library` 标记。

当前 V2 按原生 CE 库资格、`cf_dir_acl` 路径规则、独立共享目录资格及 Hub Authority/C-Go 最终提交执行。无关目录存在 ACL 不应拒绝整个库。当前五张扩展表：`cf_library_storage`、`cf_dir_acl`、`cf_sso_group_map`、`cf_edit_guard`、`cf_audit_event`。历史环境实验、身份信息、时间点及结果请在 Git 历史审计，不可复制旧脚本复现过期机制。

[当前 V2 权限契约](permission-adjudication-contract.md) · [当前权限表](permission-tables.md)

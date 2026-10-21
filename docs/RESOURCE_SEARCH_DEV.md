# 历史归档：2026-09-30 资源搜索 DEV 验证

> **不是 CloudFile V2 当前搜索/权限规格。** 旧版要求某库先登记为“托管库”才能搜索的做法已删除，不能重新引入 `cf_managed_library`、旧搜索 Worker 或旧存储表以使历史测试通过。

当前搜索必须使用 Hub `cloudfile_ext/v2/search/` 的同一 `Authority.effective(repo,path,kind)` 和最新主体/目录 ACL 过滤；无整库资格但持有共享目录根的用户只搜索该子树。目录 ACL 的存在不能使库整体不可搜索，授权失败必须拒绝而不是返回未经过滤的结果。

现行五表：`cf_library_storage`、`cf_dir_acl`、`cf_sso_group_map`、`cf_edit_guard`、`cf_audit_event`。旧 DEV 搜索实验细节只保留在 Git 历史。

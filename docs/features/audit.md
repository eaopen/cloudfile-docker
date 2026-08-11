<!-- generated-by: gsd-doc-writer -->
# 操作日志

> **用途**：说明 CloudFile 操作日志的事件链路、查询接口、管理界面和验收范围。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：已实现并有 `audit-e2e.yml` 与 `tests/e2e/audit_matrix.py` 门禁；具体运行结果以对应提交的 CI 记录为准。
> **边界**：CE 的提交活动是事实来源；CloudFile 新增审计投影、API 和管理员界面；外部归档或 SIEM 不在本仓实现范围。

## 事件链路

```
seaf-server / WebDAV / 同步客户端
  → 提交库版本
  → Server 发布 repo-update(repo_id, commit_id)
  → seafevents 比较父提交与新提交
  → Activity（seahub-db）
  → CloudFile 审计 API 与系统管理员页面
```

审计的正确边界是 **提交差异**，而不是 Seahub 的 HTTP endpoint：前者覆盖 Web、
WebDAV、Seafile 客户端与 SeaDrive 等所有最终提交库版本的写入路径。seafevents 已将
差异归一化为 `file` / `dir` 对象及 `create`、`edit`、`delete`、`rename`、`move`、
`recover` 操作，并记录操作者、时间、库、路径、提交和旧路径。

## 接口与界面

- API：`GET /api/v2.1/cloudfile/audit/`
- 页面：`/cloudfile/audit/`
- 权限：系统管理员；`CF_ENABLE_AUDIT=true` 才注册。
- 筛选：`repo_id`、`user`、`op_type`、`obj_type`；每页最多 200 条，按时间倒序。

`Activity` 是 seafevents 的持久化权威表，位于 seahub-db。因此本能力不创建平行
`cf_audit_log` 表，也不消费无生产者的 `file_op` 钩子；两者都会导致只有一部分文件
操作被记录。

## 验收

1. 创建文件和目录、修改文件、重命名、移动、删除。
2. 审计 API 同时返回 file 与 dir 记录，移动/重命名含 `old_path`。
3. 按库、操作者、操作和对象类型筛选的结果正确。
4. 系统管理员可打开页面；普通用户与关闭开关时不能访问。

<!-- generated-by: gsd-doc-writer -->
# 目录/文件操作日志

> **用途**：说明 CloudFile 操作日志的事件链路、查询接口、管理界面和验收范围。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：验证中；查询/API/UI 已实现并有容器门禁，当前 E2E 只覆盖目录创建、文件上传和目录重命名的核心查询。
> **边界**：CE 的提交活动是事实来源；CloudFile 新增只读查询、API 和管理员界面。这是目录/文件的版本化变更日志，不是读取/下载访问日志或合规审计平台。

## 事件链路

```
seaf-server / WebDAV / 同步客户端
  → 提交库版本
  → Server 发布 repo-update(repo_id, commit_id)
  → seafevents 比较父提交与新提交
  → Activity（seahub-db）
  → CloudFile 审计 API 与系统管理员页面
```

操作日志的数据边界是 **提交差异**，而不是 Seahub 的 HTTP endpoint。
这一设计可以统一消费 Web、WebDAV、Seafile 客户端和 SeaDrive 最终生成的资料库版本，但当前自动化验收只从 Web API 写入，还不能声称各协议均已实测。seafevents 将
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

## 当前验收进度

| 范围 | 当前结论 |
|---|---|
| 创建目录、上传文件 | 已验证 API 出现 `dir` 与 `file` 事件 |
| 目录重命名 | 已验证 `rename`、新路径与 `old_path` |
| 按资料库、对象、操作筛选 | 已验证核心筛选；单元测限制合法操作和对象集合 |
| 管理员页面 | 已验证管理员登录后可打开 |
| 文件修改、删除、移动、恢复 | 查询合同已接受，当前 E2E 未逐项产生并核对事件 |
| 目录删除、移动、恢复 | 当前 E2E 未覆盖 |
| WebDAV、同步客户端、SeaDrive | 事件源设计可覆盖提交，但当前未分协议验收 |
| 读取、预览、下载、分享访问 | 不属于 `Activity` 提交差异日志，当前接口不支持 |

## MVP 验收清单

1. 文件和目录分别覆盖 `create`、`edit`（仅文件）、`delete`、`rename`、`move` 和 `recover`，并核对新旧路径。
2. Web、WebDAV 和同步客户端至少各完成一条代表性变更，确认统一事件源。
3. 按库、操作者、操作和对象筻选，验证分页稳定性与时区处理。
4. 系统管理员可访问；普通用户和关闭开关时拒绝访问。
5. 明确保留期、备份/导出、脱敏和外部 SIEM 对接边界；在此之前不声称合规审计等价。

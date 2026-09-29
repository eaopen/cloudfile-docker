# 文件协作与本地应用

当前只推进单文件人工提交。普通文件锁与 Checkout 共用 Hub `cloudfile_extensions/editing/`、Server Barrier、同一 generation 与同一资源占用表，不再保留独立 FileLock/Checkout 服务。

## 实现边界

- 两张表：`cf_edit_guard` 管占用、模式与凭据，`cf_commit_intent` 管提交和回执；`029_editing_core` 直接建表，无历史锁兼容迁移。
- 单文件主流程：Checkout → 暂存意图 → Commit → 查询 → Checkin/Abandon；状态事务与独立实库原生发布已验收，完整产品身份、HTTP 与终端联验待完成。
- 已删除路径 C 锁 RPC、旧 Hub 写入接口、旧本地独占自动写回和占位 checkout 包。普通 file-lock 模式保留；移除的是重复实现。
- OnlyOffice、Agent 独占、第三方、自动上传、多文件、目录迁移等暂不开通，不新增各自的锁状态表。
- Server 读取统一占用，原生 Branch 事务原子发布版本、回执与释放；独立实例已验证连续 Commit、无内容 Checkin 和失败回滚，见[原生验收报告](../../tests/e2e/EDITING_NATIVE_ACCEPTANCE.md)。当前部署全部写入口覆盖仍待验收；根路由仅在显式启用时挂载，开关默认关闭。旧 lock_matrix 使用已删除接口，已移除，不能作为当前发布凭证。

OnlyOffice 下载或发布失败返回错误并保留会话，回调 JWT 必须绑定正文。这是现有回调缺陷修正，不代表已完成在线协作与统一 Commit 集成。

本地普通打开及人工 Web 上传继续沿用现有路径；不将“本地副本可编辑”描述为独占编辑。实现及数据库回归见 Hub `editing/` 与 `tests/test_editing_core.py`。

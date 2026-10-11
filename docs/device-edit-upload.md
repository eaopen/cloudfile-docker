# 设备本地编辑上传协议

状态：开发实现，默认关闭；真实部署验收前不开放产品能力。

Agent 手工捕获不可变快照，沿用原 CommitIntent。设备签名通过后，Hub 签发
60 秒内可开始上传的加密短期凭据（AES-256-GCM，专用派生密钥）。凭据只通过
Authorization 传送，不写 URL，不使用 Cookie；绑定会话、设备版本、资源、
原 Intent、基线、摘要、大小和操作。不同 worker 可使用同一配置密钥验证。

字节入口为同源 `/api/v2.1/cloudfile/extensions/local-edit/v1/agent/commit-upload/`，
复用现有 Hub httptemp 与原生 publish_edit RPC，避免新增 fileserver 授权体系。
最多 128 MiB；原始字节、准确 Content-Length、Idempotency-Key=Intent。
开始接收前验证凭据；流式写入私有临时文件并核验摘要/长度，再调用原生发布。
上传可能超过凭据启动期限；最终原生事务仍重复当前权限、设备、会话、Checkout
有效期和原文件版本校验。凭据不是离线发布授权。

原生事务仅允许 editing + local_commit 的设备写入条件；读用 local_session
永远不能作为写入条件。local_commit 使用服务端生成的设备/会话版本引用，
并校验 exclusive-edit 的真实 guard。提交结果、guard 基线和会话基线在同一
Branch 事务推进；Checkin 同事务结束会话并释放 guard。

仅 cf_commit_intent 中 published 的持久回执可显示成功。超时/丢失响应后，
Agent 用新设备签名查询原 Intent，不能以重新创建 Intent 来重试。查询不返回
路径、凭据或文件字节，允许完成/过期会话查询自己的历史回执；撤销设备拒绝查询。

验收用例：正常 Commit/Checkin、工作文件再修改不影响捕获快照、摘要/大小错误、
跨 Intent 凭据、过期凭据、设备撤销、会话取消、Checkout 过期/替换、版本冲突、
重复请求、发布后响应丢失、同资源其他会话不能读取 Intent。

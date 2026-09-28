# 文件协作与本地应用

> 用途：说明预览、OnlyOffice、锁、签入签出和本地应用的当前边界
> 适用版本：Seafile CE 14 参考基线
> 当前状态：部分完成

## 能力边界

| 能力 | 当前状态 | 来源与边界 |
|---|---|---|
| 原生预览 | 验证中 | Seafile CE 负责渲染；CloudFile 只统一动作选择和兼容接线 |
| OnlyOffice | 部分完成 | CE/OnlyOffice 负责编辑器；CloudFile 增加回调校验、幂等与锁协同 |
| 文件锁 | 部分完成 | CloudFile 的 `cf-lock` 和 Hub API 提供租约与终判；客户端兼容仍需验证 |
| 签入签出 | 部分完成 | Hub 有入口与状态流，`checkout` 包仍无独立完整注册实现 |
| 本地查看/编辑 | 验证中 | 已创建独立项目 `cloudfile-local-agent`、`cloudfile-chrome-extension`，与 Hub 会话接口组成应用链路 |
| 关注、转换/导出 | 部分完成 | 主要复用 CE 与 SeaDoc，CloudFile 提供开关和 UI 接线 |

本页不把外部组件的渲染、Office 兼容或本机软件识别写成 CloudFile 自研。详细本地应用
边界见 `cloudfile-hub/docs/local-professional-software.md`、`cloudfile-local-agent/README.md`
和 `cloudfile-chrome-extension/README.md`。

## 独立项目边界

本地预览与本地编辑不是嵌入 Seahub 进程的桌面执行能力，而是两个已建立的独立项目：

- `cloudfile-local-agent`：本机 Native Messaging Host，负责受控临时目录、应用发现、启动、
  心跳和写回；服务端不能向它下发任意可执行程序路径。
- `cloudfile-chrome-extension`：浏览器与本地 Agent 之间的受限桥接层；不持久化 Seafile
  Cookie、长期 token 或 OAuth client secret。

CloudFile Hub 只签发短时会话并提供下载/写回接口。三个边界先形成可验证的完整 MVP，
再持续补充签名发布、跨平台兼容、升级、冲突恢复和观测能力；独立仓库已经存在不等于
全链路已达到发布状态。

## 安全与一致性

- 前端隐藏按钮不是权限边界；写入必须通过 server 写入生命周期和锁终判。
- OnlyOffice 回调必须验证 JWT 并保证完成保存的重试幂等。
- 本地 Agent 使用一次性短时票据，不接收浏览器 Cookie、长期 Seafile token 或服务端传来的
  可执行程序路径。
- 本地编辑的下载、心跳、写回和冲突恢复需要端到端验收；单元测试不证明跨平台可发布。
- 外部资料源不是 Seafile 对象，当前不支持这些锁、历史或写回语义。

证据：`cloudfile-server/common/cf-fileop*`、`common/cf-lock*`、
`cloudfile-hub/cloudfile_ext/file_actions/`、`cloudfile_ext/office/`。写入生命周期契约见
[`fileop-lifecycle.md`](../fileop-lifecycle.md)。

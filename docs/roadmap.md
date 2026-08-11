# 路线图

> 用途：记录尚未完成的能力和进入下一状态所需证据
> 适用版本：Seafile CE 14 参考基线
> 当前状态：有效；不承诺发布日期

路线图不用于证明功能已实现。当前状态、来源和限制以[功能矩阵](feature-matrix.md)为准。

| 优先方向 | 当前状态 | 下一门槛 |
|---|---|---|
| Authentik 默认企业认证入口 | 部分完成 | 以 Authentik 2026.5.6 和通用 OIDC Authorization Code 完成登录、首次创建、登出、字段变更、故障与本地管理员恢复 E2E；确定组织同步适配 |
| 多存储自助分配 | 验证中 | 在现有按库 `RepoStorageId`/迁移能力上补齐新建库选择、角色和自动分配策略；S3 兼容验收仍只覆盖 MinIO |
| CloudFile 外部资料联邦 | 规划 | 独立项目完成统一文件接口、只读 PoC、安全边界和契约测试，再分别接入 AI 应用与 CloudFile 虚拟目录 |
| 搜索与 ACL 一致性 | 部分完成 | 修复/规避 SeaSearch `invisible` 过滤缺口，完成当前提交容器 E2E 与故障测试 |
| 目录/文件标签闭环 | 验证中 | 补齐文件与目录绑定/反查 E2E，验证重命名、移动、删除/恢复、目录 ACL 与标签更新权限 |
| 目录/文件操作日志完整性 | 验证中 | 逐项覆盖文件/目录创建、修改、删除、重命名、移动、恢复，并从 WebDAV 和同步客户端验证统一事件源 |
| 文件锁、签入签出与 OnlyOffice | 部分完成 | 统一锁语义，覆盖 Web、同步、WebDAV、回调重试和恢复，补生产协议面 E2E |
| 本地应用链路 | 验证中 | 在已建立的 `cloudfile-local-agent`、`cloudfile-chrome-extension` 独立项目中产出签名发布包，完成 Windows/macOS/Linux 与浏览器全链路验收和升级策略 |
| 元数据服务 | 验证中 | 固定可发布的官方镜像或确认替代方案，完成 schema、升级、备份和故障恢复验证 |
| Seafile AI 与外接 LLM | 验证中 | 验证现有 `ai` profile、Metadata Server/Redis 前置、JWT、模型配置和权限裁剪；补外部 LLM 故障、数据外发与审计测试，不另建平行 AI 后端 |
| Hub 上游修改收敛 | 验证中 | 将 ACL 菜单/文案改造成扩展点；确认标签审计 Pro 门禁策略；决定 `webpack-stats.pro.json` 的生成与版本控制规则 |

已放弃或被替代的阶段计划不留在本页；其决策价值保存在[历史版本](history/README.md)。

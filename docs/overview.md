# 项目概览

> 用途：说明 CloudFile 的当前基线、产品边界和事实口径
> 适用版本：Seafile CE 14 参考基线
> 当前状态：有效

CloudFile 是 Seafile Community Edition（CE）扩展版。项目复用 Seafile 的资料库、
提交、对象存储、同步、Web/API 和用户体系，在三个 fork 中增加可关闭的扩展点与能力；
构建、部署和跨仓规格由 `cloudfile-docker` 统一管理。

## 版本基线

`release.yaml` 锁定各上游组件提交和 CloudFile fork 的发布引用。当前上游没有可直接
消费的 Seafile CE 14 正式镜像或 `seafile-server` 14.0 CE tag，因此 CloudFile 从
源码构建 14.0 参考基线。该选择记录在[历史决策索引](history/README.md)。

Seafile 14.0 官方预览提及 AI 对话、Web UI、图片查看器、视频预览、回收站和历史页面等
变化。它们只是上游参考信息；除非[功能矩阵](feature-matrix.md)给出本仓代码、配置或测试
证据，否则不属于 CloudFile 已实现能力。

参考：

- [Seafile 14.0 预览说明](https://bbs.seafile.com/t/topic/22587)
- [Seafile 14.0 管理手册](https://manual.seafile.com/14.0/)

## 产品边界

内部功能矩阵使用三种定位：

- **Pro 平替**：目标能力与 Seafile Pro 已有能力相近。仅代表目标相近，不代表完整兼容、
  运维能力等价或可替换现有 Pro 部署。
- **CE 补强**：改善 CE 的部署、管理、兼容性、可观测性或集成能力。
- **新应用扩展**：在 Seafile 资料库模型之外形成新的入口或场景；必须说明数据、权限和
  故障边界。

外部公开说明使用客观能力名称，不使用“完全替代”“完全兼容”等未经验证的表述。

## 代码来源口径

| 来源 | 含义 | 示例 |
|---|---|---|
| 复用 Seafile CE | 上游仓已有实现，CloudFile 仅启用、配置或接线 | OAuth2/OIDC 登录、元数据前端与 API |
| 扩展版既有代码 | 当前 `dev` 已包含的 CloudFile 实现 | 扩展注册中心、目录 ACL、组织映射 |
| 本项目新增代码 | 相对锁定的上游提交新增或修改 | `cloudfile_ext/`、`cf-*`、S3/多存储实现 |
| 外部开源组件 | 由独立项目提供的服务能力 | Authentik、MinIO、Meilisearch、OnlyOffice |
| 部署集成 | Compose、配置翻译、健康检查或预设 | profile、环境变量、启动时配置块 |

同一能力可以包含多种来源；[功能矩阵](feature-matrix.md)逐项说明边界。

## 当前原则

1. Seafile 已有且可用的模块、协议、数据模型和扩展服务默认优先复用，不维护平行实现。
2. CloudFile 特性通过可关闭的 provider、hook、独立服务或客户端扩展 CE；全部
   `CF_ENABLE_*` 关闭时保持原生 CE 行为。
3. 每项特性先完成入口、权限、数据、配置、故障隔离、运维和验证闭环的 MVP，再持续改进
   界面、兼容范围与自动化。
4. 权限扩展只能收紧权限；安全规则读取失败时拒绝访问。
5. 新增代码优先使用 CloudFile 自有文件和稳定扩展点，减少上游 fork 冲突。
6. 外部服务不进入同步权限终判路径；故障必须可隔离并可观测。
7. 文档状态由当前代码、配置、测试和部署证据决定，不由文件名或计划决定。

## 继续阅读

- [架构](architecture.md)
- [部署](deployment.md)
- [配置](configuration.md)
- [扩展能力矩阵](feature-matrix.md)
- [上游贡献建议](upstream-contribution.md)
- [路线图](roadmap.md)

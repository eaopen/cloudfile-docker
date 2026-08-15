# 开发路线图

> 用途：按能力依赖顺序安排可交付的 MVP；每次只实现一项能力或一个共享语义面
> 适用版本：Seafile CE 14 参考基线
> 当前状态：有效；不承诺发布日期

本页不证明功能已实现；状态、代码来源和限制以[功能矩阵](feature-matrix.md)为准。
已完成的范围是 CE 14 构建扩展基线、扩展注册与开关、组织/组同步、目录级 ACL，以及按资料库选择
本地或 MinIO S3 存储。其余能力必须完成对应的可执行验收后才可改变状态。

## 交付原则

- 每次只推进下表的一行；该行的代码、配置、测试和文档在独立提交中闭环。
- 先完成身份、权限、写入终判、操作事实和元数据闭环，再接入检索、编辑、外部资料或 AI 消费面。
- 默认复用 Seafile CE、OnlyOffice、Authentik 和 Seafile AI 的现有能力；不为接入这些
  组件新建专用协议或平行后端。
- 红色契约、测试文件、Compose 配置或文档草稿都不是完成证据。

## 推荐交付顺序

| 顺序 | 唯一交付目标 | 依赖与范围 | 完成门槛 |
|---|---|---|---|
| 1 | Authentik 通用 OIDC MVP | 复用现有 Authorization Code 配置；不开发 Authentik 专用协议 | Authentik 2026.5.6 容器 E2E 覆盖登录、首次建用户、登出、claim 变更、IdP 故障与本地管理员恢复 |
| 2 | 目录 ACL 终判 MVP（已完成） | 复用 C Server 的单一权限 RPC；Go fileserver 不缓存 ACL 决策，启用后故障 fail closed | Web、同步和 WebDAV 均执行同一决策；规则变更在下一次请求生效并完成容器 E2E（37/37 通过） |
| 3 | 写入生命周期与锁 MVP | 统一 Web、同步和 WebDAV 的写入/租约终判 | `cf-lock`、签入签出和冲突/恢复路径共享同一代际围栏，并有跨协议验收 |
| 4 | 目录/文件操作日志完整性 | 依赖已确认的写入事件源，不建立平行审计流 | 创建、修改、删除、重命名、移动、恢复在 Web、WebDAV、同步客户端可查询为同一提交变更 |
| 5 | 元数据与目录/文件标签闭环 | 复用 CE Metadata Server、`repo_metadata` 和标签 API；受 ACL 约束 | 固定可发布镜像，验证绑定、反查、移动、删除/恢复、权限和升级/备份/故障恢复 |
| 6 | 搜索 ACL 一致性 | 依赖目录 ACL 终判；已在结果层统一裁剪 `invisible`/`none`（复用 acl resolver，fail closed） | 跨用户检索不可观察到无权内容，provider 故障不降级泄露，容器 E2E 通过 |
| 7 | OnlyOffice 安全编辑 MVP | 依赖锁和写入生命周期；Docker 启动配置已验证 | JWT 回调认证、受信下载、重试幂等、锁协同和 Document Server 容器 E2E 均通过 |
| 8 | 本地应用编辑 MVP | 复用现有 Local Agent 与 Chrome Extension；依赖短时会话和写入终判 | 下载—编辑—心跳—写回—冲突恢复 E2E；再分别产出 Windows/macOS/Linux 签名与升级方案 |
| 9 | 既有外部服务的运行验收 | 外部资料源、Seafile AI、转换/导出和多存储自助分配均在既有架构内改进 | 每项分别完成 profile、故障、权限和运维恢复验证；S3 兼容性仍只声明 MinIO |
| 10 | 外部资料联邦独立项目 | 新建 CloudFile 外部资料联邦模块，适配 OpenList/rclone | 先交付统一只读资料接口、安全边界与契约测试，再分别服务 AI 资料库和 CloudFile 虚拟目录 |

第 10 项不是当前 CloudFile 仓库的功能实现；在前九项稳定前不启动其消费端接入。
已放弃或被替代的过程性材料保存在[历史版本](history/README.md)，不作为交付依据。

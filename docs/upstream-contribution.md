# 上游贡献建议

> 用途：评估 CloudFile 改动是否适合向 Seafile 上游提交
> 适用版本：当前三个 `dev` fork 与其 `upstream/master` 差异
> 当前状态：工程与产品策略建议；不是法律结论

判断以可独立复现、通用价值、改动范围、测试完整性和商业边界为准。涉及 Seafile Pro
能力、CloudFile 专属架构或第三方深度产品集成时默认保留内部；缺少上游官方立场的项目
由负责人最终确认。

| 改动 | 上游策略 | 判断依据 | 建议拆分范围 | 风险 |
|---|---|---|---|---|
| 导出 `REPO_STATUS_NORMAL` / `REPO_STATUS_READ_ONLY` | 适合 PR | `cloudfile-server` 提交 `e398c5e` 仅修正 `python/seaserv/__init__.py` 的公共导出，避免 seafevents import 失败，独立于 CloudFile 能力 | 单文件、带 import 回归测试 | 上游可能选择改调用方 import 路径；需先核对最新 master |
| `seaf-fsck.sh` / `seaf-gc.sh` 传播底层退出码 | 适合 PR | 上游脚本当前以最终 `echo` 掩盖失败；修正对所有部署有价值 | 先提交纯退出码传播和 shell 测试 | 脚本兼容 shell 版本与既有调用方对退出码的假设 |
| FSCK repair 运行中服务检查 | 拆分后 PR | 离线修复保护具有通用价值，但当前用 `pgrep` 匹配进程名 | 与退出码 PR 分开；抽象检测或改为文档+显式参数 | 容器/多实例下误报或漏报，不能把进程名检测当绝对锁 |
| Go fileserver 无效配置不静默回退 FS | 拆分后 PR | 提交 `f126e6e` 防止配置解析错误导致错误后端；原则通用 | 从 CloudFile S3/multiple 代码中提取只处理 ini load error 的最小补丁并补上游测试 | 当前补丁上下文包含 CloudFile 后端选择；未经缩小不宜提交 |
| 通用写入生命周期 hook | 拆分后 PR | 文件操作 PREPARE/COMMITTED/ABORTED 对审计、锁和扩展有通用价值 | 去除 `cf_` 产品命名和测试 provider，先提最小 hook API、契约测试与一个调用链 | 调用点多、侵入 C/Go 核心；API 稳定性和维护成本高 |
| 通用权限/搜索 provider 扩展点 | 拆分后 PR | 小型标准扩展点可减少 fork；注册中心本身不必绑定具体能力 | 分别提交最小 hook、默认透传行为和单元测试，不含 ACL/Meilisearch/Authenik | 上游可能不接受长期插件 API；搜索路径涉及 Pro gate，必须剥离 |
| CE 14 源码构建发现的通用构建修正 | 拆分后 PR | Node 版本、前端资源缺失或依赖 pin 漂移若能在纯上游复现，具有通用价值 | 每个可复现问题一个 PR，使用上游分支和最小测试 | 当前 14 CE 无正式发布，复现基线和上游目标需确认 |
| Authentik OIDC 配置示例 | 待确认 | 面向通用 IdP 的文档示例可能有价值；当前无 Authentik E2E | 完成官方 Authentik 验收后，只提交标准 Seahub OIDC 配置文档，不含 CloudFile 组织同步 | 上游文档可能已有同类内容；端点随 Authentik 版本变化 |
| Hub 目录 ACL 菜单与文案入口 | 保留内部并评估扩展点 | `menuHandlers.js`、`text-translation.js` 当前承载 CloudFile ACL 入口，已登记为上游修改 | 先尝试将菜单和文案注册改造成通用前端扩展点，再判断是否单独 PR | 直接提交 ACL 产品能力不合适；扩展点需上游接受长期 API |
| Hub 标签审计入口去除 Pro 判断 | 不适合 PR | `tag/utils/file.js` 改动跨越 Pro 能力门禁，不能作为通用 CE 修正申报 | 保留内部并补回归测试；若发现独立错误，另做最小复现 | 商业边界明确，升级冲突概率高 |
| `webpack-stats.pro.json` 生成资产差异 | 待负责人确认 | 当前文件包含 CloudFile 构建入口并已登记，生成结果还可能携带构建机绝对路径 | 确认是否应由构建流程生成、忽略或保留最小稳定产物 | 不应把未审查的生成资产当作有意上游补丁 |
| 目录 ACL、审计、文件锁/签入签出、搜索 Pro gate | 不适合 PR | 主要目标与 Pro 商业差异化能力接近 | 只提取其中独立 bug fix 或通用 hook | 商业边界与维护利益冲突；不能把判断写成法律结论 |
| S3/多存储 CE 实现和迁移工具 | 不适合 PR | 目标与官方多存储/对象存储产品能力高度重合，改动大且侵入后端 | 独立的错误处理 bug 可另提；能力主体保留内部 | 与 Pro 产品边界冲突、维护面大、后端兼容风险高 |
| Meilisearch、OnlyOffice、Authentik、OpenList/rclone 深度集成 | 不适合 PR | 强依赖 CloudFile 产品选型和部署架构 | 仅提取协议无关 hook 或上游 bug | 第三方耦合、版本漂移、上游不承担运维责任 |
| 本地 Agent/Chrome 扩展和外部资料源 | 不适合 PR | 属 CloudFile 新应用场景，跨独立客户端与宿主机安全边界 | 无；如发现 CE 通用 API bug 单独报告 | 产品专属、跨平台发布和安全模型不同 |

## 提交前门槛

1. 在最新上游提交上独立复现，不依赖 CloudFile Compose 或 `cf_*` 表。
2. 每个 PR 只解决一个问题，补上游风格测试和兼容说明。
3. 不混入 Pro gate 绕过、CloudFile 开关或特定第三方产品名。
4. 更新 `docs/upstream-patches/`，记录已提交、已接受或仍需维护的 fork 差异。
5. 商业边界不明确时由项目负责人确认，不自行把工程建议解释为授权结论。

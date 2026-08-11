<!-- generated-by: gsd-doc-writer -->
# Seafile AI

> 用途：说明 CloudFile 对 Seafile AI 的复用决策、部署接线、安全边界和验证要求
> 适用版本：CloudFile `14.0.0-cf.0`，Seafile CE 14 参考基线
> 当前状态：验证中；镜像、profile 和配置映射已存在，但本仓库没有 AI 端到端门禁或通过结果

## 结论与范围

CloudFile 当前决定**先复用 Seafile 现有 AI 能力，不自行实现 CloudFile AI**。Seafile 14
官方 AI 扩展已经覆盖文件标签、文件和图片摘要、翻译、图片 OCR、写作辅助等按需能力；
CloudFile 只负责把官方组件接入部署，并让运维选择自己的模型后端。只有在官方能力无法满足
已验证的业务需求时，才重新评估 CloudFile 专属的自动入库、模型编排或语义检索实现。

当前范围不包括文件上传后自动生成标签或摘要、CloudFile 自有推理服务、模型托管，也不包括
把外部资料源自动纳入 AI。功能说明和部署前提以
[Seafile 14 AI 官方手册](https://manual.seafile.com/14.0/extension/seafile-ai/)为上游依据；
本仓库的实际接线以 [`docker-compose.yml`](../../deploy/compose/docker-compose.yml) 和
[`deploy/compose/.env.example`](../../deploy/compose/.env.example) 为准。

## 当前部署接线

| 接线 | 当前实现 |
|---|---|
| 服务 profile | `seafile-ai` 位于 `ai` 和 `full` profile；核心 `cloudfile` 服务不依赖 AI 服务 |
| 官方镜像 | `CF_AI_IMAGE` 默认为 `seafileltd/seafile-ai:14.0-latest`，本仓库不重建该镜像 |
| Seahub 开关 | `CF_AI_ENABLED` → `ENABLE_SEAFILE_AI` |
| 服务地址与共享密钥 | `CF_AI_SERVER_URL` → `SEAFILE_AI_SERVER_URL`；`CF_AI_SECRET_KEY` → `SEAFILE_AI_SECRET_KEY` |
| 人脸识别 | `CF_AI_FACE_RECOGNITION_ENABLED` → `ENABLE_FACE_RECOGNITION`，并要求元数据能力开启 |
| 日志级别 | `CF_AI_LOG_LEVEL` → AI 容器的 `SEAFILE_AI_LOG_LEVEL` |
| 数据与配置 | `./data/seafile` 挂载为 AI 容器的 `/shared`；运维从 [`seafile_ai_config.example.yaml`](../../deploy/compose/seafile_ai_config.example.yaml) 创建运行时模型配置 |
| 基础依赖 | AI 容器连接同一 MariaDB 和 Redis；官方手册要求先部署 metadata server，并明确要求 Redis 缓存 |

默认值保持 AI 关闭。试用时至少需要：

1. 在 `.env` 中设置 `CF_ENABLE_METADATA=true`、`CF_AI_ENABLED=true`，并生成强随机的
   `CF_AI_SECRET_KEY`。
2. 复制并填写 [`seafile_ai_config.example.yaml`](../../deploy/compose/seafile_ai_config.example.yaml)
   中的 `LLM_MODELS`，将运行时副本放入 Compose 数据卷的 Seafile 中央配置目录。模型可以
   是外部 OpenAI-compatible API，也可以是运维自行部署的本地兼容服务，例如 Ollama 或
   LM Studio；URL、模型 ID 和 API key 均由部署方提供。
3. 同时启动 metadata 和 AI profile：

   ```bash
   docker compose --profile metadata --profile ai up -d
   ```

仅使用 `--profile ai` 不会启动 `cloudfile-metadata`，因为 Compose 中 AI 服务的
`depends_on` 只列出数据库、Redis 和 `cloudfile`；`full` profile 会同时包含两项服务。
配置文件当前由运维维护，bootstrap 不生成模型配置或模型凭据。

## 权限与数据治理

### AI 与文件权限

AI 请求必须沿用 Seahub 已授权的用户、资料库和文件上下文，AI 服务不能成为绕过资料库
权限、目录 ACL 或分享边界的读取通道。服务间凭据只能证明“调用方是受信服务”，不能代替
最终用户的文件授权判断。当前仓库没有 AI 权限矩阵测试，因此尚不能证明无权限用户无法通过
摘要、标签、对话或错误信息推断其他资料库内容；在门禁完成前，不应把接线状态表述为权限
隔离已验证。

### 外部数据传输

使用外部模型 API 时，为完成摘要、标签、OCR 或对话而构造的文件内容、图片、文件名、提示词
和相关元数据可能离开 CloudFile 的部署边界，传往
[`seafile_ai_config.example.yaml`](../../deploy/compose/seafile_ai_config.example.yaml) 的运行时
副本所指定的模型端点。
部署方必须先确认数据分类、用户告知与同意、服务商留存和训练政策、数据驻留位置及传输加密。
本地模型可以减少第三方外发，但数据仍会在 CloudFile、`seafile-ai` 和本地模型服务之间流动，
同样需要网络隔离和访问控制。

### 凭据

`CF_AI_SECRET_KEY` 是 Seahub 与 Seafile AI 的服务接线凭据，模型 API key 则保存在由
[`seafile_ai_config.example.yaml`](../../deploy/compose/seafile_ai_config.example.yaml) 创建的
运行时副本中；两者用途不同，不能复用。运行时 YAML 位于持久化数据目录，不应提交到 Git、
写入镜像或输出到普通日志，并应限制宿主机文件权限。Compose 注释还记录了一个待验证点：
AI 镜像是否会从共享配置目录自行读取 `JWT_PRIVATE_KEY`，还是需要显式传入环境变量；端到端
验证前不能假定这条共享密钥链已经工作。

### 故障隔离

AI 使用独立容器和可选 profile，且默认开关为 `false`；核心服务不反向依赖 AI 容器，目标是
模型超时、额度耗尽或 AI 容器退出时只让 AI 请求失败，不影响文件上传、下载和共享。当前
Compose 没有为 `seafile-ai` 定义健康检查，本仓库也没有验证超时、重试、熔断、队列积压或
降级提示。上线前应证明模型端点不可达和 metadata/Redis 故障不会拖垮 Seahub 或泄漏内容。

### 审计与配额

官方手册支持通过 `AI_PRICES` 统计 token 用量，并通过 `monthly_ai_credit_per_user` 设置月度
额度；本仓库的 `.env.example` 尚未暴露或验证这些设置。CloudFile 的通用操作审计也不能自动
等同于 AI 审计。生产环境至少应记录调用主体、资料库/文件标识、模型、时间、结果状态、延迟
和 token 数，但避免把原文、提示词、模型响应或密钥写入普通日志；还应定义用户/组织额度、
并发限制、费用告警和管理员查询权限。

## 外部内容联邦的边界

CloudFile 未来可能把 SMB/NFS、OpenList/rclone 或其他外部内容联邦成统一的文件资料库视图，
届时可以再设计同一权限模型下的 AI 入口。但当前
[`external-sources.md`](external-sources.md) 只说明独立的外部资料源路径，外部文件不进入
Seafile commit/block 模型；本仓库没有把外部资料源、统一资料库和 Seafile AI 连接起来的
实现或测试。不能据此宣称 AI 已能读取、索引或总结外部内容。

## 验证门槛

当前证据只证明 Compose 可以解析 `ai`/`metadata` 服务以及所需配置已被打包。要从“验证中”
转为“已完成”，至少需要一条可重复的 AI 能力门禁，覆盖：

- metadata、Redis、Seafile AI 和可控的 OpenAI-compatible 模型桩完整启动；
- 授权用户可以调用代表性能力，无权限用户无法读取或推断其他资料库内容；
- 模型请求只携带完成任务所需的数据，凭据不会出现在响应或日志中；
- 模型、AI 容器、metadata 或 Redis 不可用时，核心文件操作仍正常且错误可观察；
- 用量、额度和 AI 审计事件符合配置，并能按用户或组织追踪。

仓库目前存在 metadata 的容器门禁，但在
[`tests/e2e/`](../../tests/e2e/) 和 [`.github/workflows/`](../../.github/workflows/) 中没有
对应的 AI 用例或工作流，因此 metadata 的通过结果不能替代 AI 全链路验收。

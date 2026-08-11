# 技术栈

**项目：** CloudFile CE Extension
**调研日期：** 2026-08-11
**调研范围：** Seafile CE 14 后续里程碑；仅补强 Authentik/OIDC、Seafile AI 外接 LLM、MinIO 验证基线和跨仓发布来源证明
**总体置信度：** HIGH（版本与接口来自当前官方文档；CloudFile 未完成的端到端行为明确标为待验证）

## 推荐栈

本里程碑不替换现有框架。继续使用 Seafile CE 14 源码组装、CloudFile Hub/Server 扩展、Docker Compose、MariaDB、Redis、Python/Bash 构建工具和 GitHub Actions。新增工作只应把现有外部集成固定为可重复验证的版本与配置，并把一次发布绑定到不可变的跨仓输入和镜像摘要。

### 核心框架

| 技术 | 推荐版本/固定方式 | 用途 | 为什么 |
|---|---|---|---|
| Seafile CE 14 + CloudFile forks | 保留 `14.0.0-cf.0` 参考基线；发布时 Hub、Server、Docker 全部固定为完整 Git commit SHA | 产品运行时 | 当前代码、扩展点、E2E 和运维脚本均围绕该基线；本里程碑没有更换框架的收益 |
| Seahub 通用 OAuth2/OIDC | 当前 Hub 中的 Authorization Code 实现 | Authentik 登录 | authentik 官方已有 Seafile 集成指南；无需 Authentik SDK 或自定义认证协议 |
| authentik | `2026.5.6`，部署镜像再固定到 registry digest | 外部 OpenID Provider | `2026.5` 是当前稳定 release train，官方 release notes 的最新补丁节为 `2026.5.6`；不得使用已废弃且不再更新的 `latest` tag |
| Seafile AI | Seafile 14 发布线，验收后固定 `seafileltd/seafile-ai:14.0-latest` 实际解析出的 digest | 官方 AI 执行层 | Seafile 14 官方接口以 `seafile_ai_config.yaml` 配置模型；`14.0-latest` 是滚动 tag，只能作为发现入口，不能作为发布锁 |
| MinIO Community | Server `RELEASE.2025-10-15T17-29-55Z`；`mc` `RELEASE.2025-08-13T08-35-41Z`；两者均固定镜像 digest | 唯一 S3 兼容验证基线 | Server 版本是官方仓库最后发布的安全修复 release；Community 仓库已于 2026-04-25 归档，因此只能作为明确冻结的兼容性 fixture，不能使用 `latest` 或扩大生产支持声明 |

### 数据库

| 技术 | 版本 | 用途 | 为什么 |
|---|---|---|---|
| MariaDB | 保留当前 Compose `11.4` | Seafile/Seahub/CloudFile 状态 | 当前实现和验证基线，不在本里程碑改动 |
| Redis | 保留当前 `7-alpine` 发布线；发布锁记录实际 digest | Hub 缓存、协调及 Seafile AI 必需缓存 | Seafile AI 14 官方手册明确要求 Redis；不新增第二套缓存 |
| Authentik PostgreSQL | 由独立 Authentik 部署按其官方 Compose 管理 | Authentik 自身状态 | 不并入 CloudFile 数据库；身份系统保持独立生命周期和备份边界 |

### 基础设施

| 技术 | 版本/固定方式 | 用途 | 为什么 |
|---|---|---|---|
| Docker Engine + Compose v2 | 保留当前 | 单机参考部署和能力矩阵 | 已有全部集成和测试围绕 Compose profile |
| OCI image annotations | OCI Image Spec 当前稳定规范 | 在镜像中暴露 source、revision、version、base digest | 标准字段可被 registry 和检查工具直接读取；跨仓字段使用 `io.cloudfile.*` 自定义命名空间 |
| GitHub Actions artifact attestations | `actions/attest` v4 接口；workflow 中固定到完整 action commit SHA | 对发布镜像 digest 生成签名来源证明 | GitHub 官方支持容器镜像 subject digest、registry 推送和 CLI 验证；自动生成 SLSA build provenance |
| SLSA provenance | v1 predicate（当前规范 v1.2） | 表达构建输入、resolved dependencies、builder 和 image subject | 跨仓 Git commit 是实际构建依赖，应以 URI + `gitCommit` digest 记录，而不只是留在日志中 |

### 支撑库与工具

| 库/工具 | 版本 | 用途 | 使用条件 |
|---|---|---|---|
| Python 标准库 `json`、`hashlib`、`subprocess` | Python 3.12 | 生成和验证 `release-lock.json`、哈希 patch 与构建输入 | 复用现有 Python，不引入新的 manifest 框架或 YAML 依赖 |
| `requests-oauthlib` | 保留 Hub 当前 pin | Seahub Authorization Code 客户端 | 继续由上游 OAuth 视图使用，不新增 Authentik 专用 client |
| `minio-go/v7` | 保留 Server 当前 `v7.0.84` | Go fileserver 的 S3 兼容访问 | MinIO 矩阵验证当前 client/server 组合；升级需重新跑完整存储生命周期矩阵 |
| `boto3` | 保留当前 image pin 策略 | Python seafobj S3 路径 | 与 C/Go 数据面一起验证，不单独作为兼容性证明 |
| 可控 OpenAI-compatible 模型桩 | 在测试仓内固定实现和响应契约 | AI E2E 的确定性外部 LLM | CI 不依赖真实付费/联网模型；生产模型另做数据治理和验收 |

## Authentik / OIDC 精确基线

### Authentik 侧

| 设置 | 推荐值 |
|---|---|
| Application / Provider | CloudFile 独立 Application + OAuth2/OpenID Connect Provider |
| 版本 | `2026.5.6`；Server/Worker/Outpost 必须同版本，镜像在发布锁中记录 digest |
| Client | Confidential client，保管独立 client secret |
| Grant types | 显式只启用 Authorization Code；authentik 2026.5 新增可配置 grant types，旧 Provider 为兼容性默认全开，不能沿用该宽松默认 |
| Redirect URI | 类型 `Strict` + `Authorization`，精确值 `https://<cloudfile-host>/oauth/callback/`；禁止 regex/wildcard |
| Issuer mode | 保持推荐的 per-provider/default 模式；用 discovery 文档核对 issuer、JWKS 和端点，但当前 Seahub 仍显式配置三个端点 |
| Scopes | `openid profile email`，不加入 groups/offline_access 或自定义 scope，除非后续需求和测试明确要求 |
| Property mappings | `sub` 为稳定 uid，`name` 为可选显示名，`email` 为联系邮箱/当前 CloudFile 首次建号所需字段 |
| Application bindings | 生产必须显式绑定允许的用户/组/策略；没有 binding 时 authentik 默认允许所有用户访问应用 |

### CloudFile 侧

```dotenv
CF_ENABLE_SSO=true
CF_SSO_OAUTH_CLIENT_ID=<authentik-client-id>
CF_SSO_OAUTH_CLIENT_SECRET=<secret-store-value>
CF_SSO_OAUTH_AUTHORIZATION_URL=https://<authentik-host>/application/o/authorize/
CF_SSO_OAUTH_TOKEN_URL=https://<authentik-host>/application/o/token/
CF_SSO_OAUTH_USER_INFO_URL=https://<authentik-host>/application/o/userinfo/
CF_SSO_OAUTH_SCOPE=openid profile email
CF_SSO_OAUTH_PROVIDER=authentik:<application-slug>
CF_SSO_OAUTH_UID_CLAIM=sub
CF_SSO_OAUTH_EMAIL_CLAIM=email
CF_SSO_OAUTH_NAME_CLAIM=name
CF_SSO_OAUTH_INSECURE=false
```

`CF_SSO_OAUTH_PROVIDER` 是 `SocialAuthUser` 绑定键，发布后不得改名。CloudFile 必须继续从公开 hostname 派生 callback，并验证 `CSRF_TRUSTED_ORIGINS` 与该 origin 一致。`OAUTH_LOGOUT_URL`、`CLIENT_SSO_VIA_LOCAL_BROWSER` 和是否允许首次自动建号目前没有完整 CloudFile 配置面；应作为该阶段的明确补齐项，而不是假定通用登录接线已经覆盖。始终保留一个受保护的本地管理员用于 IdP 故障恢复。

### 必须通过的身份矩阵

- 校验 state、精确 callback、错误 client secret、错误 issuer/endpoint、缺少 `sub`/`email`、重复邮箱和 provider 标识变化。
- 覆盖首次用户、既有绑定用户、字段更新、禁用用户、应用 binding 拒绝、Authentik 不可用和本地管理员恢复。
- 覆盖 Web 登录和 Seafile desktop client 的 system-browser SSO；只有本地 Seahub logout 与 IdP logout 都通过后才宣称单点登出。
- Authentik 升级按 major release train 顺序进行，且 core/outpost 同步升级；升级后重跑完整矩阵。

## Seafile AI 外接 LLM 约束

### 受官方接口确认的配置

| 约束 | 推荐落实 |
|---|---|
| 前置服务 | Metadata Server 必须先部署；`CACHE_PROVIDER=redis`；AI 服务还需 Seahub 内网地址、MariaDB 和共享 JWT/服务密钥 |
| Seafile 14 模型配置 | 唯一来源为 `$SEAFILE_VOLUME/seafile/conf/seafile_ai_config.yaml` 的 `global.LLM_MODELS`；不要沿用 Seafile 13/最新文档中的模型环境变量方案 |
| OpenAI-compatible endpoint | `type: other`，明确填写 `url`、`key`、`model`；一个模型时只保留一项且 `default: true` |
| 多模型 | 通常只能有一个 `default: true`；该默认模型同时服务摘要、翻译、写作等非 chat 功能 |
| 模型能力 | 若要覆盖图片标签/摘要/OCR 等完整能力，默认模型必须支持多模态输入；纯文本模型只能声明验证过的文本能力 |
| 分离部署 | Seahub 主机与 AI 主机都要有一致的 `LLM_MODELS` 配置；Seahub 用它显示 selector，AI 服务用它执行请求 |
| S3 部署 | AI 服务的 storage type、三类 bucket、endpoint、region、signature/path-style 设置必须与 Seafile Server 一致 |

`seafileltd/seafile-ai:14.0-latest` 不可直接成为不可变发布输入。资格认证流程应先解析并记录 digest，再用该 digest完成 metadata + Redis + AI + 模型桩矩阵；只有通过的 digest 才进入 release lock。

### 官方没有替 CloudFile 证明的边界

Seafile 官方手册说明了功能和部署契约，但没有证明 CloudFile 目录 ACL 下的 permission trimming、外部 LLM 最小数据发送、超时/重试/熔断、审计、日志脱敏或供应商留存策略。路线图不能把“AI 容器能启动”视为这些能力完成。AI 阶段必须验证：

- 请求主体只能访问当前有效权限允许的 repo/path；ACL、分享撤销和移动后立即生效。
- 模型端点只收到完成操作所需内容；API key、原文和模型响应不进入普通日志。
- 模型/AI/metadata/Redis 失败只让 AI 请求失败，基础上传、下载、同步和分享继续工作。
- 外部端点采用 TLS、出站 allowlist、短超时和明确的 retention/training/data-residency 决策；本地模型也按独立网络信任边界处理。
- CI 使用确定性模型桩；真实 provider 另建资格矩阵，模型名称或 endpoint 变更不能绕过重新验收。

## MinIO 验证基线

MinIO 仅是本里程碑的 S3 兼容性 fixture，不是新的生产对象存储推荐。官方 Community Server 仓库已经归档；因此推荐冻结最后安全修复 release，而不是跟随 `latest`。

| 项目 | 基线 |
|---|---|
| Server | 从官方 tag `RELEASE.2025-10-15T17-29-55Z` 构建/获取，记录 source commit、镜像 digest 和构建方式 |
| Client/init | `mc` tag `RELEASE.2025-08-13T08-35-41Z`，记录镜像 digest；只用于 readiness 和 bucket 初始化 |
| API | SigV4、path-style、HTTP 仅限隔离 CI 网络；生产式验收增加 TLS |
| Buckets | 独立 commits、fs、blocks bucket，禁止把单 bucket CRUD 结果外推为 Seafile 兼容 |
| 支持声明 | 只写“当前以 MinIO 基线通过”；AWS S3、Ceph RGW 等没有各自矩阵前不在支持范围 |

最低验收必须包括多 block 上传/下载字节一致、list/pagination、缺失/拒绝/超时错误映射、重启持久化、GC dry-run、FSCK 完整遍历与在线 repair 拒绝、local↔MinIO 离线迁移、迁移后继续读写、源对象保留与回滚证据。`cf-s3` 因未设置 endpoint 而 skip 必须显示为 SKIP，不能计为 PASS。每次 MinIO tag/digest、`minio-go`、boto3、C S3 client 或对象布局变化都需重跑完整矩阵。

## 不可变跨仓发布来源

### 推荐发布锁

保留 `release.yaml` 作为开发/候选清单，新增由 Python 标准库生成的 `release-lock.json` 作为正式发布的唯一构建输入。Release 模式不得接受 branch ref、空的 `server_commit`/`hub_commit`/`docker_commit`、环境 ref override 或未固定 digest 的外部镜像。

`release-lock.json` 至少包含：

- schema、product、database schema、extension API 和目标 platform；
- CloudFile Docker/Hub/Server 的 repository URL + 完整 commit SHA；
- 所有未 fork upstream repository URL + commit SHA；
- 每个 maintained patch 的路径和 SHA-256；
- Dockerfile、Node/toolchain 版本、基础镜像及所有可选服务镜像 digest；
- Authentik、Seafile AI、MinIO/`mc` 的资格认证版本、digest 和对应 E2E run URL/ID；
- 锁文件自身 SHA-256、构建 invocation ID、最终 OCI image digest。

### 发布流水线

1. 从候选 refs 解析 commit，生成 canonical JSON lock；检查三个 CloudFile commit 可获取且工作区无未记录 patch。
2. 仅以 lock 构建一次 distribution/image；所有能力矩阵复用同一 image digest，不再各自解析移动的 `dev`。
3. 将完整 lock 和其 SHA-256 写入 distribution，并复制到镜像只读路径；保留现有文本 build info 作为人类摘要。
4. 添加 OCI annotations：`org.opencontainers.image.source`、`version`、`revision`、`base.name`、`base.digest`，以及 `io.cloudfile.release-lock.sha256`、`io.cloudfile.hub.revision`、`io.cloudfile.server.revision`。
5. 推送镜像后以 digest 为 subject 运行 GitHub `actions/attest` v4；workflow 引用必须固定完整 SHA，并把 attestation 推到 registry。
6. 发布 image digest、lock、checksums、attestation URL 和全部 gate run IDs；部署只接受 digest，并用 `gh attestation verify` 加 lock/hash 检查验证。

自动 GitHub provenance 会证明 workflow、Docker 仓 commit 和 image digest；跨仓 Hub/Server 与外部镜像必须另外通过 release lock、OCI 自定义 labels 和锁文件哈希绑定。后续若生成自定义 SLSA predicate，应把这些输入放入 `buildDefinition.resolvedDependencies`，而不是只写入自由文本日志。

## 备选方案审查

| 类别 | 推荐 | 未采用的替代 | 为什么不采用 |
|---|---|---|---|
| 身份 | Seahub 通用 OIDC + Authentik 2026.5.6 | Authentik 专用 adapter、自定义 token 协议 | 重复上游能力并扩大认证攻击面 |
| AI | 官方 Seafile AI + `seafile_ai_config.yaml` 外接 LLM | CloudFile 自建 AI backend | 违反既定边界并重复权限/索引架构 |
| S3 验证 | 冻结 MinIO Community fixture | 直接宣称所有 S3 provider 兼容 | S3 实现差异必须按 provider 验证；当前没有证据 |
| 发布锁格式 | Python 标准库生成 canonical JSON | 新增复杂 release framework | 现有脚本已是 Bash/Python；JSON 可哈希、可嵌入且无需依赖 |
| 来源证明 | release lock + OCI labels + GitHub attestation | 只保存 build log 或 image tag | 日志/tag 不能不可变地绑定跨仓输入与产物 digest |

## 应用与验证命令

```bash
# 现有开发构建保持不变；正式发布构建应改为显式 lock 模式。
python3 tools/release-lock.py resolve --manifest release.yaml --output release-lock.json
python3 tools/release-lock.py verify release-lock.json

CF_RELEASE_LOCK=release-lock.json \
  ./build/cloudfile_14.0/cloudfile-build.sh 14.0.0-cf.0
CF_RELEASE_LOCK=release-lock.json \
  ./image/cloudfile_14.0/docker-build.sh 14.0.0-cf.0

# 发布后按 digest 验证签名来源；OWNER/IMAGE/DIGEST 由发布结果提供。
gh attestation verify "oci://ghcr.io/OWNER/IMAGE@sha256:DIGEST" --owner OWNER
```

这些命令描述目标接口，`tools/release-lock.py` 尚未实现；路线图应先完成锁格式与 fail-closed 构建，再接 registry attestation。

## 置信度

| 区域 | 置信度 | 说明 |
|---|---|---|
| Authentik 版本和端点 | HIGH | 当前官方 release notes、OAuth provider 文档和官方 Seafile 集成指南一致 |
| Seafile AI 配置契约 | HIGH | Seafile 14 官方手册明确列出 YAML、依赖、模型和分离部署契约 |
| AI 权限/故障/数据治理 | MEDIUM | 风险来自当前代码边界和官方未覆盖项；必须由 CloudFile E2E 提升置信度 |
| MinIO 版本基线 | HIGH | 官方 GitHub release/归档状态可核验；作为长期生产方案的置信度 LOW，因此只推荐为冻结 fixture |
| 发布来源方案 | HIGH | OCI、SLSA 与 GitHub attest 官方规范支持；具体 workflow 尚待实现和验证 |

## 来源

- [authentik Release 2026.5](https://docs.goauthentik.io/releases/2026.5/) — HIGH；最新补丁节为 2026.5.6，含 grant types 与升级约束
- [authentik OAuth 2.0 provider](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/) — HIGH；端点、issuer mode、redirect URI 与 Authorization Code 行为
- [authentik: Integrate with Seafile](https://integrations.goauthentik.io/media/seafile/) — MEDIUM/HIGH；官方站点的 Community 支持级别指南，精确 callback 和 Seahub 设置
- [authentik First steps](https://docs.goauthentik.io/install-config/first-steps/) — HIGH；版本 tag 与 application binding 行为
- [Seafile 14 AI extension](https://manual.seafile.com/14.0/extension/seafile-ai/) — HIGH；metadata/Redis 前置、`seafile_ai_config.yaml`、外接 LLM 和分离部署
- [Seafile 14 Docker upgrade](https://manual.seafile.com/14.0/upgrade/upgrade_docker/) — HIGH；14.0 AI image release line 与 YAML 配置迁移
- [MinIO Server releases](https://github.com/minio/minio/releases) — HIGH；最后 Community security release 和仓库归档状态
- [MinIO Client releases](https://github.com/minio/mc/releases) — HIGH；最后 `mc` release 与签名资产
- [OCI Image annotations](https://github.com/opencontainers/image-spec/blob/main/annotations.md) — HIGH；标准 source/revision/version/base digest 字段
- [SLSA v1.2 Build Provenance](https://slsa.dev/spec/v1.2/build-provenance) — HIGH；subject、buildDefinition、resolvedDependencies 和 builder 模型
- [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations) — HIGH；容器 image digest attestation 与验证流程
- [`actions/attest`](https://github.com/actions/attest) — HIGH；v4 provenance/SBOM/custom modes、registry 推送和 subject digest 接口

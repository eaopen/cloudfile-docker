# 配置

> 用途：说明当前配置入口、通用开关和敏感值管理
> 适用版本：Seafile CE 14 参考基线
> 当前状态：有效；具体变量以 `deploy/compose/.env.example` 为准

## 配置来源

| 来源 | 职责 |
|---|---|
| `deploy/compose/.env` | 运维输入；不得提交 |
| `deploy/compose/.env.example` | 当前变量全集、默认值和注释 |
| `deploy/compose/docker-compose.yml` | 变量传递、服务和 profile |
| `scripts/scripts_14.0/bootstrap.py` | 生成 `seahub_settings.py`、`seafile.conf` 和持久化 `.env` |
| `cloudfile-hub/cloudfile_ext/settings_defaults.py` | Hub 侧安全默认值 |

默认值见下表。不依赖第三方/外部服务的旧能力通常默认打开
（AUDIT、METADATA、TAGS、FILE_PREVIEW、FAVORITES_ID、WATCH、FILEOPS、SHARE_RESTRICT）；
旧版 DIR_ACL、FILE_LOCK、CHECKOUT 与当前版本化表结构不兼容，默认关闭。
依赖第三方服务、宿主机挂载或客户端安装的能力也默认关闭
（SSO、SEARCH、ONLYOFFICE、CONVERT_EXPORT—S3_STORAGE、EXTERNAL_SOURCES、LOCAL_APP）。
关闭 CloudFile 开关时，bootstrap 不应覆盖运维自行设置的同名上游能力；新增开关必须同时更新 `.env.example`、Compose、bootstrap 和 Hub 清单。

## 功能开关

当前代码登记 18 个开关（同步自 `bootstrap.py` 的 `CF_FEATURE_SWITCHES`）：

| 开关 | 默认值 | 默认开关的原因 / 默认关闭的依赖 |
|---|---:|---|
| `CF_ENABLE_DIR_ACL` | `false` | 旧版 ACL 入口使用 v0.1 表结构；当前 ACL 由版本化迁移与授权服务承接 |
| `CF_ENABLE_AUDIT` | `true` | 复用 seafevents `Activity`，无外部服务 |
| `CF_ENABLE_METADATA` | `true` | 依赖官方 `seafile-md-server`；该服务已进默认 compose 栈 |
| `CF_ENABLE_TAGS` | `true` | 与 METADATA 同一栈（bootstrap 强制 TAGS⇒METADATA）|
| `CF_ENABLE_FILE_PREVIEW` | `true` | 复用 CE 原生预览渲染器 |
| `CF_ENABLE_FILE_LOCK` | `false` | 原生基础已验收；当前部署完整写入口与产品联验待完成 |
| `CF_ENABLE_CHECKOUT` | `false` | 单文件受控发布仍需端到端验收 |
| `CF_ENABLE_FAVORITES_ID` | `true` | `obj_id` 化收藏，纯 CE 表结构改造 |
| `CF_ENABLE_WATCH` | `true` | 复用 CE monitored-repos、放开非 Pro gate |
| `CF_ENABLE_FILEOPS` | `true` | 复制/移动统一预检查，Hub 影子端点 |
| `CF_ENABLE_SHARE_RESTRICT` | `true` | 外部分享管控，复用 CE 外链表与端点 |
| `CF_ENABLE_SSO` | `false` | 依赖第三方 IdP（Authentik/OIDC/SAML/LDAP）|
| `CF_ENABLE_SEARCH` | `false` | 依赖 SeaSearch/Elasticsearch/Meilisearch 容器与索引 |
| `CF_ENABLE_ONLYOFFICE` | `false` | 依赖第三方 Document Server |
| `CF_ENABLE_CONVERT_EXPORT` | `false` | 依赖 SeaDoc 容器 + `JWT_PRIVATE_KEY` |
| `CF_ENABLE_S3_STORAGE` | `false` | 依赖 S3 端点（默认 RustFS，兼容 MinIO；自动本地 overlay 也复用此开关） |
| `CF_ENABLE_EXTERNAL_SOURCES` | `false` | 依赖宿主机挂载的本地目录（v1 只读；协议转换归运维）|
| `CF_ENABLE_LOCAL_APP` | `false` | 依赖用户机 Chrome 扩展 + Local Agent |

`CLOUDFILE_EDITING_ENABLED` 是统一 Checkout API 的独立宿主开关，默认 `false`；启用要求 OIDC、资源权限运行时、版本化编辑表、`CF_ENABLE_FILE_LOCK=true` 和 `CF_LOCK_BACKEND=cloudfile` 同时就绪。当前仅提供单文件人工 Checkout、手动上传 Commit/Checkin，其他编辑模式保持关闭。

> 修改说明（2026-09-22）：原表只列了 15 个开关（漏 `FAVORITES_ID`/`FILEOPS`/`SHARE_RESTRICT`）
> 且未给出默认值。现以 `bootstrap.py` 的 `CF_FEATURE_SWITCHES` 为准逐项列出。

开关表示装配意图，不单独证明能力可用。依赖、验证范围和限制见
[功能矩阵](feature-matrix.md)。

## Provider 选择

- `CF_PROVIDER_SEARCH=`：留空走 Seafile/SeaSearch 路径；`meilisearch` 走 CloudFile
  provider 和 `cf-worker` 索引。
- `CF_PROVIDER_SSO_DIRECTORY=`：留空不做组织同步；当前实现支持 `static` 和
  `external-service`。Authentik 登录不等于自动选择目录 provider。
- 外部资料源按记录的 `source_type` 选择 provider；当前只有 `local-path`，不是全局
  `CF_PROVIDER_*` 二选一。

未知 provider 应显式失败，不得回落为空结果。

## 认证配置

默认企业身份入口定义为 Authentik，但当前仓只提供通用 OAuth2/OIDC 参数：

```dotenv
CF_ENABLE_SSO=true
CF_SSO_OAUTH_CLIENT_ID=
CF_SSO_OAUTH_CLIENT_SECRET=
CF_SSO_OAUTH_AUTHORIZATION_URL=
CF_SSO_OAUTH_TOKEN_URL=
CF_SSO_OAUTH_USER_INFO_URL=
CF_SSO_OAUTH_LOGOUT_URL=
CF_SSO_OAUTH_SCOPE=openid email profile
CF_SSO_OAUTH_PROVIDER=
CF_SSO_OAUTH_UID_CLAIM=sub
CF_SSO_OAUTH_EMAIL_CLAIM=email
CF_SSO_OAUTH_NAME_CLAIM=name
CF_SSO_OAUTH_CREATE_UNKNOWN_USER=true
```

`CF_SSO_OAUTH_UID_CLAIM` 是必需的稳定身份主键；`CF_SSO_OAUTH_EMAIL_CLAIM` 仅是可选联系资料，
没有邮箱的账号也可通过稳定 UID 登录。回调地址由站点协议和主机名生成：`<scheme>://<host>/oauth/callback/`。完整字段映射、
首次登录和恢复边界见 [Authentik 与企业认证](features/sso-authentik.md)。配置 client ID 后，
secret、三个 OAuth 端点和 provider 均为启动必填项；默认仅接受 HTTPS。`LOGOUT_URL` 为
可选的 RP 发起登出端点，`CREATE_UNKNOWN_USER=false` 要求管理员预先创建用户。

## 存储配置

单一 S3 与多存储都受 `CF_ENABLE_S3_STORAGE` 控制。核心变量包括
`SEAF_SERVER_STORAGE_TYPE`、三个 bucket、S3 endpoint/凭据，以及多存储所需的
`CF_STORAGE_CLASSES_JSON`。只填写变量不会创建生产 bucket，也不会迁移已有资料库；
详见[多存储与 S3](features/storage-backends.md)。

存储的回退边界（2026-10-15 明确）：

| 情况 | 行为 |
| --- | --- |
| 未提供多存储 overlay、`SEAF_SERVER_STORAGE_TYPE` 为空 | 使用原生本地磁盘；`CF_ENABLE_S3_STORAGE=true` 但未指定后端时只告警，不再阻断启动 |
| 新建库、临时数据，没有明确的存储类绑定 | 使用本地磁盘（默认存储类指向 `seafile-data`） |
| 已绑定存储类/目录的库，映射不可用（未知存储类、父挂载缺失） | 报明确存储错误，**不**回退到 `seafile-data`、也不新建目录 |

不需要新的 fallback 开关：**是否存在有效的存储绑定**就是选择依据。C、Go fileserver
与 seafobj 三层都只在"没有绑定记录"时取默认类；一旦有绑定而类不可解析就拒绝
（`storage-backend-multi.c` / `backend_multi.go` / `seafobj/auto_local.py`）。
`CF_STORAGE_CLASSES_JSON` 缺失/非法或后端值未知仍然 fail closed——那是运维明确声明的
映射，半套配置比不启动更危险。

## 外部资料源配置

`CF_ENABLE_EXTERNAL_SOURCES` 启用当前 `local-path` 外部资料源入口，
`CF_EXTERNAL_SOURCES_ROOTS` 限制容器可登记的根目录。**v1 只支持只读挂载本地目录**
（2026-09-22 明确）：SMB/NFS、OpenList、rclone 等一切外部形态都由运维在宿主机转换成本地
目录，再以只读 bind mount 暴露给容器；CloudFile **不做直接 SMB**（原 `smb` provider 已取消）、
不做直接 NFS、不做 OpenList/rclone 适配器。CloudFile 外部资料联邦尚无可用变量，见
[规划说明](features/external-directory-mount.md)。

## 密钥与证书

- `deploy/compose/.env`、`data/`、证书私钥和真实 provider 凭据不得提交。
- `JWT_PRIVATE_KEY` 首次生成后必须跨重启保持一致；OnlyOffice、SeaDoc、metadata-server
  等依赖方须使用相同信任材料。
- Authentik client secret、LDAP bind password、SAML SP private key 和 S3 secret 均应由
  外部密钥管理或受限文件注入；当前 Compose 示例不是密钥管理系统。
- `bootstrap.py` 生成的敏感配置文件权限为 `0600`；日志和故障报告不得回显真实值。

## 配置验证

```bash
cd deploy/compose
cp .env.example .env
docker compose config --quiet
rm .env
```

仓库门禁还会比较三处开关清单、执行 bootstrap 配置生成测试，并检查 profile 引用。
修改变量时同步更新本页引用的功能文档；不要在多处复制完整变量表。


## v0.4 preview and formal library repo-root embedding

- CF_PREVIEW_PROVIDER=eap-fileview selects external preview when configured; native preserves CE native preview.
- CF_PREVIEW_PUBLIC_URL is empty until independent eap-fileview is available. Private example: https://files.example.net/fileview
- CF_FORMAL_EMBED_RESOURCES={} maps resource keys to trusted repo roots. Example JSON: {"research":{"repo_id":"11111111-1111-4111-8111-111111111111","root_path":"/"}}
- Initial embed supports only repository root /, not arbitrary subtree confinement. A plain iframe is not a file access security boundary.
- Source URLs are per-user Seafile read tokens; the viewer must reach fileserver and restrict trusted source hosts and logs.
- These settings do not deploy the viewer or Filestash. Filestash stays optional.


## HTTP / HTTPS — intranet CloudFile standard compatibility (v0.7)

CloudFile supports both HTTP and HTTPS for business access, OIDC browser
redirects, signed pairing/claim, Web upload, Agent full/CDC, Checkout,
native guarded file reads, and cryptographically signed update sources.
No separate HTTP enable flag or server-origin allowlist is needed.
The canonical Scheme/Host/Port must match the browser, OIDC redirect,
and paired Agent; there is never automatic TLS downgrade.

For intranet HTTP, set public origin and CLOUDFILE_OIDC_CONFIG_JSON to the
actual registered HTTP URLs. On HTTP the OIDC session and CSRF cookies use
Secure=false and browser binding cookies omit the __Host- prefix; on HTTPS
the original Secure/__Host- attributes remain. Device P-256 proof,
one-use tickets, current ACL, CSRF, baseline file IDs, Branch CAS and
Checkout fencing all remain mandatory.

HTTP transmits sessions, credentials and document bytes in cleartext.
Restrict it to appropriately secured internal networks/VPNs and use HTTPS
where feasible. External IdPs may independently require HTTPS callbacks.
Do not open a new Chrome native operation to foreign page origins.

### Cookie 的 Secure 归属（2026-10-15）

`SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` 只由**部署实际使用的公共访问入口**决定，
不再由新启用的原生 OIDC callback 单独推断（`cloudfile_extensions/identity/configuration.py`
的 `public_browser_scheme()`）。原因：Etech 用 Authentik 旧 OAuth 走 HTTP，而原生 OIDC
可能注册为 HTTPS；若按 callback 把 Cookie 置为 Secure，HTTP 浏览器会直接丢弃
`sessionid`/`csrftoken`，表现为登录后立刻掉线。

选择顺序：`CLOUDFILE_PUBLIC_URL`（显式声明，原样校验为 Scheme/Host[/Port]，不接受路径）
→ 否则 `OAUTH_REDIRECT_URL` 与 OIDC `redirect_uri` 必须同为一种 scheme → 两者不一致时
采用旧 OAuth 入口并打 warning（就是现有用户已经在用的入口）。两种登录入口都在 `SITE_ROOT`
之下，共用同一条 Cookie 路径；HttpOnly、SameSite 与 CSRF 校验保持不变。

`CLOUDFILE_PUBLIC_URL` 未声明时，生成的 `OAUTH_REDIRECT_URL` 必须与部署协议一致：由
`SEAFILE_SERVER_PROTOCOL`（未设置时看 `SEAFILE_SERVER_LETSENCRYPT`，都没有则为 HTTP）
与 `SEAFILE_SERVER_HOSTNAME` 派生，与 `bootstrap.get_proto()` 同一套规则。Authentik 预设的
默认协议此前多写了一个 HTTPS（`cloudfile.py`），会把 HTTP 部署的跳转写成 HTTPS。

HTTP 部署不需要额外开关即可使用该预设：redirect 指向的就是部署自己的公共入口，其协议已由
`SEAFILE_SERVER_PROTOCOL`（或显式 `CLOUDFILE_AUTHENTIK_REDIRECT_URL`）声明；`CLOUDFILE_AUTHENTIK_ALLOW_INSECURE`
只继续管**面向 IdP 的 URL**，两者是不同的信任边界。仅当部署声明为 HTTPS 却给出 HTTP redirect
时才拒绝。Authentik 身份提供方自身是 HTTPS 不受影响：部署 HTTP + IdP HTTPS 是受支持组合。

## 目录机器认证默认 v2（2026-10-14）

修改原因：Hub 的 SSO_DIRECTORY 请求、镜像启动配置生成、主服务与 worker 的 Compose 默认值统一为 `v2`，避免省略变量时恢复旧 Token。v2 使用 Bearer HS256，要求与 EAP 对应环境一致的 key-id、32 字节以上共享密钥和 service-id；认证失败直接报错，不自动降级。

`CF_SERVICE_SSO_DIRECTORY_AUTH_MODE=legacy` 仍可显式连接旧接收端；其他外部服务的默认协议不受影响。当前先在 DEV 验证，PROD 镜像与运行配置尚未更新，须等 DEV 验收后发布。

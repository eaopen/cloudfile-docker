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
| `CF_ENABLE_FILE_LOCK` | `false` | 旧版锁入口使用 v0.1 表结构；待 v0.3 当前锁链验收 |
| `CF_ENABLE_CHECKOUT` | `false` | 旧版签入签出依赖旧锁和本地会话表 |
| `CF_ENABLE_FAVORITES_ID` | `true` | `obj_id` 化收藏，纯 CE 表结构改造 |
| `CF_ENABLE_WATCH` | `true` | 复用 CE monitored-repos、放开非 Pro gate |
| `CF_ENABLE_FILEOPS` | `true` | 复制/移动统一预检查，Hub 影子端点 |
| `CF_ENABLE_SHARE_RESTRICT` | `true` | 外部分享管控，复用 CE 外链表与端点 |
| `CF_ENABLE_SSO` | `false` | 依赖第三方 IdP（Authentik/OIDC/SAML/LDAP）|
| `CF_ENABLE_SEARCH` | `false` | 依赖 SeaSearch/Elasticsearch/Meilisearch 容器与索引 |
| `CF_ENABLE_ONLYOFFICE` | `false` | 依赖第三方 Document Server |
| `CF_ENABLE_CONVERT_EXPORT` | `false` | 依赖 SeaDoc 容器 + `JWT_PRIVATE_KEY` |
| `CF_ENABLE_S3_STORAGE` | `false` | 依赖第三方 S3/MinIO 端点 |
| `CF_ENABLE_EXTERNAL_SOURCES` | `false` | 依赖宿主机挂载的本地目录（v1 只读；协议转换归运维）|
| `CF_ENABLE_LOCAL_APP` | `false` | 依赖用户机 Chrome 扩展 + Local Agent |

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

回调地址由站点协议和主机名生成：`<scheme>://<host>/oauth/callback/`。完整字段映射、
首次登录和恢复边界见 [Authentik 与企业认证](features/sso-authentik.md)。配置 client ID 后，
secret、三个 OAuth 端点和 provider 均为启动必填项；默认仅接受 HTTPS。`LOGOUT_URL` 为
可选的 RP 发起登出端点，`CREATE_UNKNOWN_USER=false` 要求管理员预先创建用户。

## 存储配置

单一 S3 与多存储都受 `CF_ENABLE_S3_STORAGE` 控制。核心变量包括
`SEAF_SERVER_STORAGE_TYPE`、三个 bucket、S3 endpoint/凭据，以及多存储所需的
`CF_STORAGE_CLASSES_JSON`。只填写变量不会创建生产 bucket，也不会迁移已有资料库；
详见[多存储与 S3](features/storage-backends.md)。

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

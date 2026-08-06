# CloudFile Compose 部署

## 快速开始

```bash
cp .env.example .env
```

编辑 `.env`，至少改掉 `SEAFILE_SERVER_HOSTNAME` 和四个密码，然后：

```bash
docker compose up -d
```

首次启动会创建数据库、初始化 Seafile 并建立管理员账号，需要一两分钟。

```bash
docker compose logs -f cloudfile
```

## 可选组件

```bash
docker compose --profile search up -d
```
```bash
docker compose --profile office up -d
```
```bash
docker compose --profile convert up -d
```
```bash
docker compose --profile full up -d
```

| profile | 服务 | 说明 |
|---|---|---|
| （默认） | `cloudfile`、`db`、`cache`、`proxy` | 核心栈 |
| `search` | `meilisearch` | 全文与属性检索 |
| `office` | `onlyoffice` | Word/Excel/PPT 协同编辑 |
| `convert` | `seadoc` | 文件转换与导出 |
| `worker` | `cf-worker` | 后台任务 |
| `metadata` | `cloudfile-metadata` | 文件属性、标签与多视图的上游元数据服务 |
| `full` | 全部 | |

`cf-worker` 不在默认集合里。启用 SSO 后，它会按 `CF_SSO_SYNC_INTERVAL`
执行目录同步；后续的搜索、审计等周期任务也使用同一 worker。它与主服务通过共享的
Seafile RPC socket 通信，必须始终通过本 Compose 文件启动。

## 功能开关

`.env` 里所有 `CF_ENABLE_*` 默认为 `false`。**全部关闭时，这套部署的行为与原生
Seafile CE 完全一致**——这是 P0 的核心验收项，也是跟随上游成本可控的前提。

改完开关直接：

```bash
docker compose up -d
```

配置在**每次启动时**重写（`scripts_14.0/start.py` → `write_cloudfile_config`），
不需要删数据重装。写入的是 `conf/seahub_settings.py` 和 `conf/seafile.conf` 里
一段带标记的区块，你在这两个文件里的其它改动不会被动到。

### 目录级 ACL

```bash
CF_ENABLE_DIR_ACL=true docker compose up -d
```

同一个环境变量会同时写进 Seahub 和 seaf-server 两处配置，二者不会漂移。Seahub 那份
只决定界面显示什么，seaf-server 那份才是强制校验。覆盖范围与已知缺口见
[../../docs/acl-semantics.md](../../docs/acl-semantics.md)。

规则通过 REST API 或管理后台配置：

```bash
curl -X POST -H "Authorization: Token $TOKEN" \
  -F path=/受限 -F subject_type=user -F subject=b@example.com \
  -F permission=r \
  https://cloudfile.example.com/api/v2.1/cloudfile/repos/$REPO_ID/dir-acl/
```

排查"为什么某人打不开某个目录"：

```bash
curl -H "Authorization: Token $TOKEN" \
  "https://cloudfile.example.com/api/v2.1/cloudfile/repos/$REPO_ID/dir-acl/effective/?path=/受限&user=b@example.com"
```

### 已打包的 CE 企业设置

LDAP/AD、ADFS/SAML、Shibboleth、角色权限和 2FA 都是 Seafile CE 已有能力；CloudFile
只把它们变成可重建的 `.env` 配置。变量说明和安全前提在
[.env.example](.env.example)，每次启动都会重新写入上游的 `seahub_settings.py`。

- LDAP/AD：设 `CF_LDAP_ENABLED=true`，并填写五个 LDAP 连接参数；缺一项即失败，避免服务
  在看似正常时悄悄跳过 LDAP。
- ADFS/SAML：设 `CF_ADFS_ENABLED=true`，填写元数据 URL 和 JSON 属性映射；把 `sp.key`、`sp.crt`
  放在 `data/seafile/seahub-data/certs/`。镜像已包含 `xmlsec1`。
- Shibboleth：默认 Caddy 不提供 Shibboleth SP，不能直接打开。必须换成/扩展为可信认证代理，先剥离
  客户端伪造的身份头，再向 CloudFile 写入 `CF_SHIBBOLETH_REMOTE_USER_HEADER` 指定的头。
- 角色/2FA：角色 JSON 是对 CE 默认策略的增量覆盖；`CF_TWO_FACTOR_ENABLED=true` 开启用户自助 2FA。

### 文件属性与标签

启用属性和标签需要官方元数据组件，它保存/查询元数据；Hub 前端、REST API 与 `seafevents`
增量投喂仍使用 CE 自带代码。

```bash
CF_ENABLE_METADATA=true CF_ENABLE_TAGS=true docker compose --profile metadata up -d
```

`cloudfile-metadata` 会在主服务健康后从共享的 `conf/.env` 读取同一把
`JWT_PRIVATE_KEY`，而不是把密钥复制到 Compose `.env`。目前上游 Docker Hub 尚未发布稳定
14.x metadata-server tag，示例默认仅用于兼容验证的官方 `14.0.3-testing`；生产启用前必须
在 `CF_METADATA_IMAGE` 固定经过验收的官方镜像。关闭 `CF_ENABLE_METADATA` 时服务不在默认
profile，CE 行为不变。

### 文件锁、关注与转换导出

原生菜单分别由独立开关控制，关闭时仍走 CE 默认行为：

```bash
CF_ENABLE_FILE_LOCK=true CF_ENABLE_WATCH=true docker compose up -d
```

文件锁写入 `cf_lock_lease`，同步、WebDAV 和 HTTP 写路径使用同一终判点；关注复用
Seahub 的 `UserMonitoredRepos` 和文件更新邮件任务，邮件投递仍要求站点已配置 SMTP。

转换/导出使用官方 SeaDoc 2.0 服务。先在 `.env` 固定一次 `JWT_PRIVATE_KEY`
（`openssl rand -hex 32`），再启动对应 profile：

```bash
CF_ENABLE_CONVERT_EXPORT=true docker compose --profile convert up -d
```

启动时会拒绝空 JWT 或与既有 Seafile 持久化密钥不一致的配置，避免 SeaDoc 看似启动、
实际无法读取文件。

## TLS

`CADDY_TLS=internal` 签发自签证书，适合内网和试用。填邮箱地址则申请 Let's Encrypt
正式证书，前提是 `SEAFILE_SERVER_HOSTNAME` 已解析到本机且 80/443 可从公网访问。

## 数据

全部落在 `./data/` 下：

```
data/
├── db/            MariaDB
├── redis/         缓存
├── seafile/       资料库、配置、日志（容器内 /shared）
├── caddy/         证书
├── meilisearch/   索引（search profile）
└── onlyoffice/    文档服务数据（office profile）
```

备份 `data/db` 和 `data/seafile` 即可覆盖全部业务数据。备份前先
`docker compose stop cloudfile`，避免拿到写到一半的资料库。

## 原生 CE 回归

P0 的核心验收项。把 `.env` 里所有 `CF_ENABLE_*` 设为 `false`，然后逐项确认行为与
同 SHA 的原生 CE 镜像一致：

- 登录、建库、上传下载
- 分享链接（下载与上传）
- WebDAV（`/seafdav`）
- 桌面客户端同步
- 在线预览

```bash
cd ../../../cloudfile-hub && python3 -m pytest cloudfile_ext/
```
```bash
cd ../../../cloudfile-server && ./tests/cf-acl/run.sh
```

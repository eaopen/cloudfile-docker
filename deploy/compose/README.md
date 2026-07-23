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
docker compose --profile full up -d
```

| profile | 服务 | 说明 |
|---|---|---|
| （默认） | `cloudfile`、`db`、`cache`、`proxy` | 核心栈 |
| `search` | `meilisearch` | 全文与属性检索 |
| `office` | `onlyoffice` | Word/Excel/PPT 协同编辑 |
| `worker` | `cf-worker` | 后台任务 |
| `full` | 全部 | |

`cf-worker` 不在默认集合里：目前还没有任何能力注册周期任务（都在 P2 及以后），
启动它只会立即退出。等打开需要它的开关后再加 `--profile worker`。

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

# v0.2 业务入口

该 profile 为当前应用镜像外的独立 TLS Nginx 入口，不改变 CE/native 镜像或权限代码。
默认只允许 Golden Path。后端应用必须位于专用私网，使用 `cloudfile` 网络别名；
**不得同时发布后端 80/8000/8082/8080 等端口**，否则外部可以绕过本白名单。
管理及 CF02-07 离线导入只从维护私网进行，不向业务用户公开维护入口。

部署前在当前后端完成已有 OIDC/policy/worker 配置，固定回调 HTTPS 域名并启用
受管库标记与 ACL。服务内部 Nginx/Gunicorn/native 保持既有本地代理信任链；
不要把 Gunicorn forwarded_allow_ips 或 native trusted_tls_proxies 设为任意来源。
本入口终止 TLS 并覆盖来源/协议头，后端只能从可信私网访问。

设置实际证书、私钥绝对路径及已有私网名称，再启动侧车：

```sh
export CLOUDFILE_TLS_CERT=/absolute/path/cloudfile.crt
export CLOUDFILE_TLS_KEY=/absolute/path/cloudfile.key
export CLOUDFILE_PRIVATE_NETWORK=cloudfile-v02
# 默认只在本机 443 监听；企业入口地址按实际网卡明确配置。
export CLOUDFILE_HTTPS_BIND=127.0.0.1
export CLOUDFILE_IMAGE=cloudfile/cloudfile:14.0.8-v0.2-rc-app
docker compose -f deploy/v0.2/compose.ingress.yml config -q
docker compose -f deploy/v0.2/compose.ingress.yml up -d
```

本轮只在隔离无发布端口的夹具验证，未修改用户现有服务，也不宣称生产部署完成。
镜像来源与 ID 见 CF02-08 assembly 证据；上线使用已核对制品。证书、私钥不入 Git。
只读容器的临时目录全部在 tmpfs；启动日志走 stderr，不写只读日志目录。

| 分类 | 路径/方法 | 边界 |
| --- | --- | --- |
| OPEN | `/`、`/libraries/`、`/library/<uuid>/...` GET/HEAD | CE 页面；ACL 仍由实际 API/业务入口执行 |
| OPEN | `/media/` GET/HEAD | 公开静态资产，禁止写 |
| OPEN | `/api/v2.1/repos/` 与 `<uuid>/dir/` GET/HEAD | 当前库/目录 ACL 过滤；禁止普通新建/目录写操作 |
| OPEN | `/api2/account/info/` GET/HEAD | 当前账户基础信息 |
| OPEN | identity `begin/callback/logout/return` GET；`pending` GET/POST | 固定 OIDC 流程；pending POST 的 CSRF 仍由应用验证 |
| OPEN | identity `logout/logout/idp/logout/backchannel/read-tickets/manual-upload/manual-update` POST | 既有登录、签名通知或 CSRF/会话/当前权限检查；功能未启用仍由应用拒绝 |
| OPEN | authorization `delegations`、transfer `delegated-read-tickets` POST | 原有 machine/current-user 委托验证，不放宽授权 |
| OPEN | `/seafhttp/cloudfile/read` GET/HEAD | 增强 Bearer/current ACL；Range 透传 |
| CLOSED | 普通 `/api2/repos`/原生文件票据、普通 `/seafhttp` download/upload/update/sync、WebDAV、分享、历史、回收站、ZIP、搜索、admin、迁移 API及其它未列路径 | 默认 403；不能标为 TODO BUT ENABLED |
| CLOSED | 已列路径的其它方法、普通账号 login POST/logout GET | 禁止平行普通入口；`/accounts/login/` GET 固定跳转 OIDC begin，忽略 next |
| DEFERRED | 非主流程功能内部改造、额外 CE API、完整 UI 外围功能 | 不因登记 deferred 而开放网络入口 |

独立代理不会改写 body、Cookie、Authorization、CSRF 或 Range；业务权限/签名检查
继续由已有应用执行。对于代理归一化的极端 URI/低频组合，本轮不追加穷举验证。
浏览器真实常用流程与生产部署/证书/网络验收仍是 CF02-08 后续 gate；若浏览器发现
必需的外围请求被关闭，先证明属于主流程，再加最小精确路由，不能开放整个 API 前缀。

最小验证：`python3 tests/verify.py changed --plan`，
`python3 tests/ingress_runtime.py --image cloudfile/cloudfile:14.0.8-v0.2-rc-app`。
探针运行实际只读 Nginx 与校验证书的 HTTPS，使用透明响应夹具核对路由/方法/
请求体/头/Range。它不冒充新的 CE 身份、文件权限或真实 eTech 联验。

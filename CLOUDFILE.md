# CloudFile v0.2 容器集成

本仓库从 `build/seafile_14.0/release.json` 锁定 CloudFile 与上游 Seafile 14.0.8 源码，避免构建时重新落到未定制的上游 Seahub。`seafile-build.sh` 可不传版本；如传入版本，必须与清单一致。

日常构建使用 `build/seafile_14.0/build-in-docker.sh`，复用 v0.1 Docker `51f4e6520f84ef3551e222c024bfdcbeffbcec1c` 的预制工具链/架构门禁/持久缓存方案。默认已有 `cloudfile-build-base:ce14-v2`，按宿主 arm64/amd64 原生运行；基础镜像架构不符拒绝。通过 `CF_BASE_IMAGE`、`CF_PLATFORM`、`CF_BUILD_JOBS`、`CF_CACHE_DIR` 覆盖。若当前工作区保留 `.v0.1-local/cloudfile-docker/cloudfile_14.0/.cache`，默认直接复用其中 ccache/Go/pip 缓存；否则用本仓库忽略的 `.cache`。缓存不是来源证明，所有源码与最终包仍执行完整 pin/摘要校验。

```sh
build/seafile_14.0/build-in-docker.sh
build/seafile_14.0/build-local-image.sh cloudfile/cloudfile:14.0.8-v0.2-rc-work
```

预制工具链入口跳过 APT，已有相同 SHA checkout 不重复 fetch。Python thirdpart 安装缓存只在需求清单、Python/架构及工具链 image ID 相同且完成标记存在时复用；改依赖或 `CF_FORCE_THIRDPART_REFRESH=true` 重装，失败保留上个完整目录。编译缓存持久化并不代表每个新临时构建目录均命中，具体命中率需实际构建统计；本轮不将语法/缓存单测冒充完整 native 增量构建提速实测。

尚未由人工推送的本地提交可通过 `CLOUDFILE_SERVER_SOURCE`、`CLOUDFILE_HUB_SOURCE` 提供给构建容器。两个值必须是绝对路径，且工作区干净、HEAD 与 `release.json` 的 40 位提交完全一致；构建器会复制 Git 对象后再构建，不修改来源仓库。未设置时继续只从清单中的 HTTPS 远端构建。例如在构建容器中把两个仓库只读挂载到 `/sources/cloudfile-server`、`/sources/cloudfile-hub`，并把对应环境变量设为这些容器内路径。该覆盖只用于本地已提交但尚未推送的 CloudFile 源码，不能绕过 release pin。

全部七个构建来源均锁定 40 位提交。构建开始时核对实际 checkout HEAD 与清单、拒绝修改或未跟踪文件；只在完整包成功生成后写入 `cloudfile-build.json`，记录清单、实际提交与全部安装文件/目录/执行权限/符号链接摘要。每次在新临时目录构建，成功校验后保留旧包并替换，失败不覆盖上一个包。

源码包成功生成后，运行 `build/seafile_14.0/build-local-image.sh [镜像标签]`。脚本校验原包及复制后的临时 Docker context，缺来源记录、源码 pin 不符或内容改变均拒绝；不能给旧包补写新来源记录。镜像标签含产品版本、Seafile 版本、Hub/Server 精确提交和 `com.cloudfile.package.sha256`；它只构建本地镜像，不执行 push。

运行依赖与应用镜像分层：`Dockerfile.runtime-base` 延续 CE14 的 Ubuntu/Python/系统依赖，`cloudfile/runtime-base:14.0.8-local` 首次需要时生成；日常应用 Dockerfile 只复制脚本和发行包，没有 APT/pip。记录基础镜像 ID，并用对应内容标识本地 tag 构建。`CLOUDFILE_RUNTIME_BASE` 可指定已经生成的同 CE 版本依赖镜像；`CLOUDFILE_REFRESH_RUNTIME_BASE=true` 显式重新运行基础镜像构建。该重新构建仍使用 BuildKit 缓存；维护依赖版本/安全更新时需明确更新基础定义并验证，不把这个参数当作自动更新所有通配版本依赖。

## 隔离运行验收

复用 CE14 新装流程与原生 API，使用 Docker 私有内部网络、随机测试账号、临时 MariaDB/缓存与 tmpfs 数据。没有发布端口、宿主数据卷或外部数据库参数；结束时自动删除本次容器/网络。预先准备 `mariadb:10.11`、`memcached:1.6-alpine`，扩展回归另需 `mysql:8`、`redis:7-alpine`。

```sh
python3 tests/smoke_ce14_runtime.py --image cloudfile/cloudfile:14.0.8-v0.2-rc-work
python3 tests/smoke_ce14_runtime.py --image cloudfile/cloudfile:14.0.8-v0.2-rc-work --native-regression --extensions-regression
python3 tests/smoke_ce14_runtime.py --image cloudfile/cloudfile:14.0.8-v0.2-rc-work --identity-runtime
```

基础验收明确使用 `ENABLE_GO_FILESERVER=true`，覆盖初始化、能力关闭态、本地管理员登录、建库、真实上传/下载字节、Range、显式更新及匿名拒绝。`--native-regression` 在实际 Seahub 配置运行 download actor 回归；`--extensions-regression` 使用另一个独立 SQL/Redis，复用既有扩展测试，报告通过/跳过/失败数量。扩展回归需同级 `eap-cloudfile/contracts` 两份共享 JSON 样本，复制到临时容器；原生 actor 自动在单独完整 Django 进程执行，其余 HTTP 单元夹具保留最小 settings，报告分别计数。报告不含密码或令牌。该夹具不证明真实 Authentik/eTech、HTTPS 委托授权、全入口权限、迁移恢复或 RC 完成。

`--identity-runtime` 复用当前镜像，不重编译 C/Go 或执行全量扩展回归；真实 TLS 的本机测试 IdP/Directory 与原生 CE RPC/SQL、实际 cf schema、完整 Django Client 链验证管理员受控预绑定、RS256/JWKS/state/nonce/PKCE、冷缓存组织/角色投影且保留非托管组、持久会话/索引、重载及 CSRF 本地退出，以及身份冲突/原生停用/目录停用/目录故障拒绝。Django Client 显式模拟浏览器删除过期 cookie，不放宽服务器守卫。测试账号通过 CE RPC 创建，仅用于已有预绑定路径，不证明 JIT worker、RP/backchannel、真实 Authentik/eTech 或浏览器 TLS 入口已验收。

验证分层：改配置/缓存先跑 Docker 单测（Linux `python3 -m unittest discover -s tests`，39 项）；仅改身份夹具跑 `--identity-runtime`；C/Go 改动执行相应 native 回归后重建制品；合并阶段或影响跨域边界再执行 `--extensions-regression`。保留通过证据，只因新变化、失败或未解决边界重复全量，避免用完整构建/全量测试调试路径与 fixture。

## 扩展配置

容器每次启动都会幂等更新 `seahub_settings.py` 中的 CloudFile 配置块，并保留块外的本地配置。

- `CLOUDFILE_EXTENSION_APPS`：额外 Django 应用，逗号分隔。
- `CLOUDFILE_EXTENSION_URLCONFS_JSON`：扩展名到 URLConf 模块的 JSON 对象。
- `CLOUDFILE_CAPABILITIES_JSON`：请求启用已注册实现；公开字段仅限 `enabled`、`version`、`provider`，配置不能开启缺失实现或绕过依赖。
- `CLOUDFILE_WEBDAV_ENABLED`：声明已配置启用 WebDAV，默认 `false`；它不代替 WebDAV 服务本身的启停配置。
- `CLOUDFILE_AUTHORIZATION_ENABLED`：挂载内建 authorization v1 路由，默认 `false`；必须同时启用 post-fork policy worker，并配置真实目录、主体刷新和委托发行运行时。该开关不自动声明 capability 已交付。
- `CLOUDFILE_POLICY_CONFIG_JSON`：严格 JSON 的可信 worker 配置；包含数据库、专属 Redis、Directory Adapter、C ACL 库、机器凭证范围、刷新 provider grant 与独立委托签名键。`CLOUDFILE_AUTHORIZATION_ENABLED=true` 时必须同时设置它和 `CLOUDFILE_POLICY_WORKER_HOOKS=true`，重复字段或不完整安全配置拒绝启动。
- `CLOUDFILE_LOCAL_EDIT_ENABLED`：挂载内建 local-edit URL，默认 `false`；只有同时配置 post-fork policy worker、资源生命周期读取器、本地编辑版本读取器和固定 HTTPS 实例 origin 后才可设为 `true`，该开关本身不声明能力已交付。
- `CLOUDFILE_TRANSFER_ENABLED`：挂载 cookie-free 的 `transfer/v1/delegated-read-tickets/`，默认 `false`；必须同时设置 `ENABLE_GO_FILESERVER=true`、启用 post-fork policy worker，并由完整 `CLOUDFILE_POLICY_CONFIG_JSON` 构造独立委托验签键、共享撤销存储与 native ticket RPC。C 文件服务没有增强下载路由，选择它时拒绝启用委托传输。该开关不挂载 OIDC 会话票据，也不自动声明 `transfer.web` 已交付。

部署 URLConf 不得占用 directory、authorization、library-policy、directory-acl、annotations、audit、search、locks、local-edit、migration、transfer、identity 核心域。自有能力由受信 Python 启动代码注册，配置 JSON 不能注册实现。

authorization/transfer 的 `CLOUDFILE_POLICY_CONFIG_JSON` 最小结构如下；示例值必须由部署密钥系统替换，机器凭证密钥与委托签名密钥不得相同：

```json
{
  "database": {"host":"db","port":3306,"user":"cloudfile","name":"seafile_db","password":"replace-me"},
  "redis": {"host":"redis","port":6379,"password":"replace-me"},
  "provider":"etech",
  "native_schema":"ccnet_db",
  "identity_schema":"seahub_db",
  "directory_url":"https://etech.example.com/eap/cloudDrive/directory/v2",
  "directory_bearer_token":"replace-me",
  "attribute_allowlist":[],
  "core_library":"/opt/seafile/seafile-server-latest/seafile/lib/libcloudfile_acl.so.1",
  "cloud_mode":false,
  "service_credentials":{"login-v1":{"service_id":"etech-login","issuer":"etech-login","audience":"cloudfile-authorization","secret":"replace-with-machine-secret-32-bytes-min","scopes":["subject.refresh","user.delegation.issue"],"maximum_ttl":120}},
  "refresh_provider_grants":{"etech-login":["etech"]},
  "delegation_signing_keys":{"etech-login":{"kid":"delegation-v1","issuer":"cloudfile","audience":"cloudfile-download","secret":"replace-with-distinct-signing-secret-32-bytes-min"}}
}
```

上述 JSON 只在 Gunicorn worker fork 后构造 Redis 撤销存储、机器 verifier 和委托 signer；URLConf/preload master 不持有连接。生产环境应限制生成的 `seahub_settings.py` 读取权限，并通过编排系统注入秘密，不能把实际值提交到源码仓库。

## 完整 OIDC 的显式部署接线

v0.2 的完整 OIDC 使用既有签名校验、登录资源、原生 session backend 和 guarded session middleware，默认关闭。先部署 schema、预绑定账号、真实目录与权限配置，再显式设置：

```dotenv
CLOUDFILE_OIDC_ENABLED=true
CLOUDFILE_POLICY_WORKER_HOOKS=true
CLOUDFILE_OIDC_JIT_ENABLED=false
CLOUDFILE_AUTHENTIK_ENABLED=false
```

同时提供 `CLOUDFILE_POLICY_CONFIG_JSON` 和严格 `CLOUDFILE_OIDC_CONFIG_JSON`，例如：

```json
{
  "issuer":"https://auth.example.com/application/o/cloudfile/",
  "client_id":"cloudfile",
  "client_secret":"replace-through-deployment-secret-store",
  "redirect_uri":"https://files.example.com/api/v2.1/cloudfile/extensions/identity/v1/callback/",
  "authorization_url":"https://auth.example.com/application/o/authorize/",
  "token_url":"https://auth.example.com/application/o/token/",
  "userinfo_url":"https://auth.example.com/application/o/userinfo/",
  "jwks_url":"https://auth.example.com/application/o/cloudfile/jwks/",
  "user_id_claim":"userId"
}
```

issuer/JWKS 等必须取实际 provider 配置并精确注册 callback；示例不替代 IdP 联验。可选 `ca_bundle` 指向可信容器内 CA 文件；RP logout 的 `end_session_url` 与 `post_logout_redirect_uri` 必须同时配置，后者固定为同 origin 的 `identity/v1/logout/return/`。SITE_ROOT 非 `/` 时 callback/return URI 必须含相同前缀。

Django app 启动先把原始配置校验为既有 `OIDCConfig`；只替换原位置的 SessionMiddleware，保留本地恢复认证 backend，追加 CloudFile backend，并要求数据库 session。legacy `ENABLE_OAUTH`、多个 session middleware、另一套 login resource owner、回调路径不符或配置不完整均拒绝，不输出秘密。启用后 session/CSRF cookie 为 Secure，session 为 HttpOnly。反向代理须按真实信任边界提供 HTTPS，不能对任意客户端信任转发头。

内建路径为 `identity/v1/begin/`、`callback/`、`pending/`、`logout/`、`logout/idp/`、`logout/return/`。URLConf 不在 preload master 创建连接；请求和会话保护通过当前 post-fork PolicyHost 获取资源。未初始化、排空或缺资源返回 503，worker 配置失败拒绝启动。`CLOUDFILE_OIDC_ENABLED` 不自动声明 `auth.oidc` capability，也不自动启动 JIT worker或安装 backchannel logout；这些须各自取得完整运行证据。

首次部署可从已预绑定账号闭环，JIT 保持关闭。升级前先显式执行现有迁移，不在请求或 app ready 自动 DDL。回退时先排空/冻结受管入口并恢复匹配配置/数据库，不得把受保护 OIDC session 改为普通 session middleware 继续提供访问。

## 旧 Authentik OAuth 配置预设

CloudFile 内建的是 Authentik 的首选 OIDC 配置，不在本容器中捆绑 Authentik 服务。必填变量：

```dotenv
CLOUDFILE_AUTHENTIK_ENABLED=true
CLOUDFILE_AUTHENTIK_URL=https://auth.example.com
CLOUDFILE_AUTHENTIK_CLIENT_ID=cloudfile
CLOUDFILE_AUTHENTIK_CLIENT_SECRET=replace-me
SEAFILE_SERVER_PROTOCOL=https
SEAFILE_SERVER_HOSTNAME=files.example.com
```

默认回调地址为 `https://<SEAFILE_SERVER_HOSTNAME>/oauth/callback/`，也可用 `CLOUDFILE_AUTHENTIK_REDIRECT_URL` 覆盖。预设将 OIDC `sub` 映射为 CE OAuth `uid`，将 `preferred_username` 映射为 CE `login_id`；`sub` 是认证绑定键，不替代业务主体 `userId`。如果业务 `userId` 不等于 `preferred_username`，必须在部署验收前完成可信 claim 的映射调整和目录对账；当前预设本身不保证两者相同。

未知用户默认不自动创建、不自动激活，SSO 用户默认禁止本地密码登录。先预绑定业务身份并验收停用/撤权；显式开启自动建号也不等于实现受控 JIT。仅本地开发可显式设置 `CLOUDFILE_AUTHENTIK_ALLOW_INSECURE=true`。

该预设复用 CE OAuth 授权码/UserInfo 回调，不应单凭 `openid` scope 声称完整 OIDC 已验收。ID Token 签名、issuer/audience/有效期/nonce、UserInfo sub 一致性与退出流程须按产品身份特性单独实现和验证。

v0.2 目标方案采用受控 JIT，而不是当前预设的无条件建号：仅可信 userId 已在目录存在且启用、无绑定冲突、provider 获准时创建新用户；已有用户复用或预绑定。持久身份沿用 CE 用户/原生绑定，动态主体只缓存 CF 专属 Redis，缓存过期刷新最新目录。详见 `eap-cloudfile/docs/features/identity-directory.md`；这些流程尚未实现，不能通过打开当前自动建号变量替代。

基础认证继续用于本地账户。WebDAV 不复用浏览器 OIDC 会话，应使用独立的 WebDAV 应用密码。CloudFile 不扩展客户端及同步功能。

产品规划与上线设计在 `eap-cloudfile` 仓库；本文件仅说明当前容器配置，不代表目录 ACL、审计、搜索、标签、锁、本地编辑或迁移 API 已实现。

## 开发验证与完整验收分层

复用 v0.1 的分层验证方式，新增 `tests/verify.py`。日常 Python 修改直接挂载当前 Hub 源码到既有 CE14 依赖镜像，不生成发布包、不重新编译 C/Go、不启动 Seahub/native 服务。组件测试使用自己的 MySQL8/Redis7 内部网络，真实数据库/C ACL 用例不跳过。此证据明确标为 `development-source-overlay`，不能替代锁定制品验收。

```bash
# 先看选择；默认包含各仓 HEAD 后的工作区、暂存区和未跟踪改动。
python3 tests/verify.py changed --plan
# 可用 --base 指定四仓均存在的 Git ref，加入 BASE...HEAD 已提交改动。
python3 tests/verify.py changed --warm
python3 tests/verify.py identity --warm
python3 tests/verify.py authorization --warm
python3 tests/verify.py transfer --warm
python3 tests/verify.py docker

# 按需管理本工作区独占的开发 SQL/Redis；没有发布端口或宿主数据卷。
python3 tests/verify.py warm --warm-action status
python3 tests/verify.py warm --warm-action up
python3 tests/verify.py warm --warm-action down

# 显式新装验收：不使用 warm 服务或挂载的开发源码。
python3 tests/verify.py runtime
python3 tests/verify.py identity-runtime
python3 tests/verify.py full
```

`--image` 可指定本地镜像。`changed` 以生产模块/测试夹具的反向 Python import 闭包选择关联测试；身份修改另列 identity runtime 门禁。显式 `identity/authorization/transfer` 则运行整个组件依赖闭包，包含必要的暂存域消费者回归，不启动 v0.3 产品服务。schema/common/jobs/根接线、原生修改和未知路径保守要求完整门禁；动态导入不保证能由 AST 完全识别，提交/RC 前仍必须显式全量验收。`--changed-file repository/path` 仅用于明确指定范围或检查映射，不能冒充自动检测全部改动。

契约门禁使用安装了 `eap-cloudfile/tools/design-requirements.txt` 的开发 Python；已有环境直接用 `--contract-python /path/to/venv/bin/python`，默认当前解释器。依赖缺失返回失败，不自动修改运行镜像、重新下载依赖或静默跳过。

退出码：0 为所选测试通过且无待执行门禁，1 为失败，2 为所选测试通过但报告中的运行/全量门禁尚待执行。报告记录模块集合、测试数量、跳过/错误、耗时、镜像 ID、源码 HEAD/dirty 与扩展源码摘要；执行期间源码变化拒绝通过。源码挂载只支持 Python 开发；Server dirty 或镜像 Server SHA 不匹配时拒绝组件集成，须先生成匹配 native 制品。`full` 先检查清单、干净 Hub/Server 与镜像来源一致，再执行全新 CE14、全部扩展回归和身份夹具；仍不代表真实 Authentik/eTech/浏览器 TLS 或全部 RC 场景已通过。

warm 仅保留本工作区带 ownership label 的 MySQL/Redis，测试仍创建/删除随机 schema。Redis 夹具可能 flush 自己的测试库，因此跨进程加锁，不能并发跑同一 warm 服务；错标签、外部网络、发布端口、停止/换镜像的服务拒绝复用。不主动重启或删除其他容器。默认不带 `--warm` 时成功/失败均清理，runner 超时也清理。warm tmpfs 不是持久数据库，显式 down 后数据消失。

当前没有把带账号/组/会话副作用的 CE14 身份夹具直接改成长驻环境；需先补幂等数据重置与 worker 生命周期后再复用。IdP 夹具继续单独标注范围，保持测试行为验证与真实部署 E2E 分开。本轮实测 `identity/runtime.py` 关联 78 项：warm 5.344 秒、fresh core 10.975 秒；显式 identity 388 项 warm 22.606 秒，均零失败/跳过。耗时仅为本机当前镜像/用例，非通用性能承诺。

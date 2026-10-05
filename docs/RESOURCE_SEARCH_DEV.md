# v0.3 资源搜索与审计 Dev 验证

更新：2026-09-30。新资源搜索入口与旧 `CF_ENABLE_SEARCH` / SeaSearch / `cloudfile_ext.search` 分开；本文只配置 `cloudfile_extensions.search`。默认关闭，未宣称新镜像已发布或 CloudFile dev 已部署。

## 搜索接入

在 dev 的受信 `seahub_settings.py` 中显式开启 `CLOUDFILE_RESOURCE_SEARCH_ENABLED = True`。必须已有实际 OIDC、authorization、post-fork policy hooks、至少 32 字节的 `CLOUDFILE_RESOURCE_SECRET` 与 `NativeResourceReader`。`CLOUDFILE_RESOURCE_SEARCH_CONFIG` 只接受以下六项，不能由 HTTP 请求选择：

```python
CLOUDFILE_RESOURCE_SEARCH_CONFIG = {
    'endpoint': 'http://meilisearch:7700',
    'index': 'resources_dev_20260930_01',
    'generation': 'dev-20260930-01',
    'read_key': '<固定私网查询密钥>',
    'write_key': '<固定私网写入密钥>',
    'cursor_secret': b'<至少32字节的独立固定游标签名密钥>',
}
```

密钥从受控配置注入，不提交仓库，不发给浏览器。当前支持已登记 `cf_managed_library` 的库；不得为了搜索批量登记已有库。Meilisearch 使用 Compose 的私网服务，不发布其端口。

查询为 `POST /api/v2.1/cloudfile/extensions/search/v1/query/`，HTTPS、当前 OIDC 会话、CSRF、`X-CloudFile-Expected-Subject` 与当前 CE/C 读取权限按实际宿主校验。JSON 示例：`{"q":"drawing","repo_id":"资料库UUID","path":"/","kind":"file","tag_ids":[],"limit":50}`。每页最多 100 个候选，不返回未授权 total/facets/highlight；有权且仍存在的资源才进入结果。标签过滤再次核对当前绑定和启用状态，旧索引标签不能继续命中。没有正文抽取或隐式 fallback。

## 独立 Worker

2026-09-30 范围优化：新资源索引新增 `dirs` 祖先目录过滤字段，path/kind 在候选排名与分页前生效。必须使用新 generation/物理 index 并全量重建；仅更新设置后复用旧文档会遗漏目录内命中，不能作为 ready。旧兼容索引已有 dirs，与新资源索引不混用。范围、非递归降级和后续底层路径直查方案见 [补充设计](../../eap-cloudfile/docs/features/search-path-prefix.md)。

在已初始化的应用容器内、以相同服务账号运行以下入口；它读取同一受信 Django 配置、同库 SQL/Redis 和原生 RPC socket。不是 Web 进程内线程，不自动注册周期任务或启动 supervisor。

```sh
python3 /scripts/cloudfile-search-worker.py initialize
python3 /scripts/cloudfile-search-worker.py rebuild --repo-id <资料库UUID>
python3 /scripts/cloudfile-search-worker.py consume
```

`initialize` 持久登记 generation、创建实际物理索引、确认 Meili 异步任务及固定设置，随后在全局生产者屏障下捕获标签定义边界；必须先于任何库扫描。`rebuild` 每步最多 100 条、1MiB，扫描当前不可变 commit、读取真实稀疏属性/标签，持久追平后才发布。`consume` 处理属性、用户/系统标签绑定及定义 fanout，确认异步 task succeeded 才推进。三种操作支持 `--once`；轮询范围 1–30 秒，SIGTERM/SIGINT 排空当前步骤后退出。只输出状态，不输出文档、密钥和 cursor。

当前字节提交的同事务事件桥尚未完成。Branch head 与发布的扫描版本不一致时查询返回 `503/SEARCH_REBUILD_PENDING`，不能复用旧代次或把旧内容当作 ready。此时配置全新的 generation 和物理 index，初始化、重建、追平后验证；新代次不得复用旧物理名称。未知提交/失败任务保留持久恢复状态，不删任务、重置整个流或自动采用已有索引。

新接口仍处于显式 dev 验证阶段，`search.resources` 公共能力发现保持关闭，待字节增量桥、状态/恢复和产品入口收口后再开启。旧名称搜索开关不能代替这项验收。

## 审计接入与验证

查询已有独立开关 `CLOUDFILE_AUDIT_QUERY_ENABLED`；导出另需 `CLOUDFILE_AUDIT_EXPORT_ENABLED`、至少 32 字节固定 `CLOUDFILE_AUDIT_CURSOR_SECRET` 与预建的服务账号专有 0700 `CLOUDFILE_AUDIT_RESULT_ROOT`。独立入口为 `python3 /scripts/cloudfile-audit-worker.py`。结果目录不放入静态文件根，不允许符号链接。

本轮修复整库查询在事务 finalize 之前清空管理权限 epoch 的缺陷。已有 Web 手动上传/更新事实、受管票据访问事实、属性/标签、CloudFile ACL/管理/共享与身份/任务事实可按已覆盖来源查询；共享链接、WebDAV、普通 CE 原生提交等未覆盖入口单独记缺口。Hub 的 `succeeded` 是原生完成应答，不冒称字节提交与审计同事务，也不把 attempted 当成功。

## Dev 交付核对

先在 Linux 构建并记录此次 Hub/Server/Docker 的实际源码 SHA、镜像 digest，再更新 dev 的镜像引用与配置；发布 manifest 保持原已验版本，不能用 Python overlay 更新其验证状态。现已定位：minio157 的 `/data/etech-infra/cloudfile-dev`，应用/worker 为 `cloudfile-dev` / `cloudfile-worker-dev`，用户入口为 `http://10.9.8.162:6111/`（dev162 eTech-EAP）。2026-09-30 发布前实测运行镜像 `14.0.0-cf.20260930` 的 Hub/Server 仍为 `c7ff8afb` / `6a79b265`，未包含独立 search worker，不能按镜像日期判断当前源码已部署。

dev 验证需使用两个真实业务用户：名称/描述/标签命中、撤销共享或隐藏 ACL 后裁剪、错误主体/CSRF 拒绝、属性/标签事件消费、文件更新后明确拒绝旧代次及新代次重建；审计检查非空分类查询、非空 CSV、导出下载撤权拒绝和过期文件实际清理。记录部署前后镜像 digest、源码 SHA、启用项及测试结果，不能只记录开关已开启。

受控隔离回归入口：

```sh
python3 tests/smoke_ce14_runtime.py --image <已验证CE14镜像> --identity-runtime --identity-scenario search --development-worker-overlay
python3 tests/smoke_ce14_runtime.py --image <已验证CE14镜像> --identity-runtime --identity-scenario audit --development-worker-overlay
```

上述命令使用独立临时容器、真实 Meili/SQL/CE14 与 OIDC fixture；开发 overlay 不等于 dev 部署、外部 IdP/eTech 联验或当前发布制品验收。

### 当前 eTech 搜索检查（2026-09-30）

本轮兼容修复源码新增 Hub `GET /api/v2.1/cloudfile/search/`（仍受 `CF_ENABLE_SEARCH` 控制），优先旧 Meili 文件索引，故障仅读一页当前目录的直属文件和文件夹名称，不使用递归原生搜索。eTech 新界面经 `GET /libraries/{repoId}/search/page` 接分页/降级信息，旧 `/search` 保留列表响应并拒绝无法表达的范围缩小，旧标签路由改为索引查询并拒绝名称降级。部署顺序为 Hub → Java → Web；这些兼容修复不代表新 OIDC 资源搜索已开启，也不解决旧索引覆盖缺失。新资源索引路径优化仍按独立 generation 重建。

`etech01` 名称查询实际代理原生 `api/v2.1/search-file/`，英文/中文/无匹配与 PDF 预览通过，但耗时 6.8–13.3 秒。标签查询代理 `cloudDrive/tags/search`，逐资源调用 CloudFile 标签接口，两个查询均约 60 秒后 504；超时后仍可观察到标签读取。旧 Meili Activity 游标虽追平，90 个真实文件有界抽查仍缺失 75 个索引文档，不能直接切换至旧索引。新资源查询与 OIDC 能力未开启，仍需当前制品和契约接入；本次只使用 admin，不算权限隔离验收。详见 EAP 的 [实测证据](../../eap-cloudfile/docs/releases/evidence/cf03-search-etech-dev-2026-09-30.json)。

2026-09-30 保守权限优化：兼容搜索读取有界的新鲜主体、CF 与原生文件夹权限快照，分别解算权限，检查配置过的祖先边界及每个候选本身；不把 invisible 配置当作全局前缀黑名单。允许结果仅在请求内复用，返回前复核账号、库资格、成员、规则与已允许路径；变化或读取失败拒绝整页，游标绑定权限快照。不递归补满结果。隔离 CE14 + 原生 SQL/RPC + Meili 运行验证已覆盖个人 r 覆盖群组 invisible、撤销个人授权后隐藏及库共享撤权；使用 development overlay，不代表 dev 已部署或字节事件桥已完成。

## 2026-09-30 Dev 镜像发布完成

dev162 的 `tools/release-dev162.sh 14.0.0-cf.20260930-search1 all` 已完成完整编译、产物字节校验和 Nexus 推送；镜像 digest 为 `sha256:ffdeec23b8097c578ed997c5e5761a884a058b631daa5d9aa56d5efa3a786107`。minio157 的 `cloudfile-dev` 与 `cloudfile-worker-dev` 同时更新到该制品，应用 healthy、worker running、重启计数均为 0；源码为 Hub `a9c16167c`、Server `d104150b`、Docker `08ccdff`。未使用开发 overlay。

实际 `etech01` 兼容入口的只读验证通过：新鲜账号/权限快照，Meili 查询 200 且非降级，强制直属名称降级 200，匿名入口与 HTTP 请求均 403。使用既有原生库拥有者，不代表普通业务用户权限隔离验收或 eTech 浏览器联验；Java/Web 本次未部署，旧索引覆盖缺口和公共新资源能力继续保留原发布门槛。配置、旧镜像信息、schema/ACL 备份及更新日志保留在 dev 的 `rollback-20260930-search1/`；完整 [发布证据](../../eap-cloudfile/docs/releases/evidence/cf-dev-deployment-2026-09-30.json) 记录制品和验证边界。

## 2026-10-06 Dev 运行环境只读复核

在 minio157 对 dev 栈做只读核查（未改配置、未重启、未重跑索引）：

- dev 运行镜像为 `10.12.1.138:8041/cloudfile/cloudfile:14.0.0-cf.20260930-9f77a3b`，image id `sha256:adff8690…`，来源 Server `d104150b` / Hub `447e00e0b` / Docker `9f77a3b`，容器 `cloudfile-dev`（healthy）、`cloudfile-worker-dev`（running）。
- 兼容索引 `cloudfile_files` 共 **410,993** 文档 = 409,324 `file` + **1,669 `dir`**。目录量级与既有观察（约 1,668–1,669）一致，**目录回填按现状已基本完成**。
- 但 `etech01`（`4f09f8a8-40c0-4ded-bec9-6c42691034f5`）原生 `RepoFileCount` 为 **862,177**，索引文档仅 **410,937**，覆盖约 **47.7%**。另有 5 个测试库（一机一档/THome/STP资料库/STWC资料库/角色权限资料库）共 56 个文档。
- 新资源搜索仍未在本机初始化：`cf_search_generation` 等 generation 表不存在，Meili 中也没有 `resources_*` 索引；`search.resources` 保持关闭。`cf_search_index_state` 的 `meilisearch` 水位为 140390。
- dev 上 eTech 两端已部署：`dev-etech-eap`（`etech-eap:2.1-dev`）与 `dev-eap-web`（`etech-web:dev`，入口 6111）。

结论：**目录完成不等于文件覆盖完成**，兼容索引的文件覆盖是本版首要技术阻塞。下一步必须先定位历史文件未入索引的根因（Activity 事件覆盖 vs 全量扫描），再建立文件级全量核验与补索引，最后才谈切换新资源索引。证据见 [环境实测记录](../../eap-cloudfile/docs/releases/evidence/cf-environments-2026-10-06.json)。


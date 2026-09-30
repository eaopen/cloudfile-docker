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

先在 Linux 构建并记录此次 Hub/Server/Docker 的实际源码 SHA、镜像 digest，再更新 dev 的镜像引用与配置；发布 manifest 保持原已验版本，不能用 Python overlay 更新其验证状态。现已定位：minio157 的 `/data/etech-infra/cloudfile-dev`，应用/worker 为 `cloudfile-dev` / `cloudfile-worker-dev`，用户入口为 `http://10.9.8.162:6111/`（dev162 eTech-EAP）。2026-09-30 实测运行镜像 `14.0.0-cf.20260930` 的 Hub/Server 仍为 `c7ff8afb` / `6a79b265`，未包含独立 search worker，不能按镜像日期判断当前源码已部署。

dev 验证需使用两个真实业务用户：名称/描述/标签命中、撤销共享或隐藏 ACL 后裁剪、错误主体/CSRF 拒绝、属性/标签事件消费、文件更新后明确拒绝旧代次及新代次重建；审计检查非空分类查询、非空 CSV、导出下载撤权拒绝和过期文件实际清理。记录部署前后镜像 digest、源码 SHA、启用项及测试结果，不能只记录开关已开启。

受控隔离回归入口：

```sh
python3 tests/smoke_ce14_runtime.py --image <已验证CE14镜像> --identity-runtime --identity-scenario search --development-worker-overlay
python3 tests/smoke_ce14_runtime.py --image <已验证CE14镜像> --identity-runtime --identity-scenario audit --development-worker-overlay
```

上述命令使用独立临时容器、真实 Meili/SQL/CE14 与 OIDC fixture；开发 overlay 不等于 dev 部署、外部 IdP/eTech 联验或当前发布制品验收。

### 当前 eTech 搜索检查（2026-09-30）

`etech01` 名称查询实际代理原生 `api/v2.1/search-file/`，英文/中文/无匹配与 PDF 预览通过，但耗时 6.8–13.3 秒。标签查询代理 `cloudDrive/tags/search`，逐资源调用 CloudFile 标签接口，两个查询均约 60 秒后 504；超时后仍可观察到标签读取。旧 Meili Activity 游标虽追平，90 个真实文件有界抽查仍缺失 75 个索引文档，不能直接切换至旧索引。新资源查询与 OIDC 能力未开启，仍需当前制品和契约接入；本次只使用 admin，不算权限隔离验收。详见 EAP 的 [实测证据](../../eap-cloudfile/docs/releases/evidence/cf03-search-etech-dev-2026-09-30.json)。

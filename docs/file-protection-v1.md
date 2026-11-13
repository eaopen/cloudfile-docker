# 文件保护 V1 配套安装与联验

Server #51、Hub #100 与 Docker #53 已合并至 dev；尚未部署，仍待业务验收。文件原件可读、可复制；写入、删除、移动、改名和影响原件的上级目录操作拒绝。目录改名自动迁移不在 V1 内。

## 配置

Compose 各应用实例设置同一 `CF_PROTECTION_REPOS`，值为逗号分隔的小写标准 Repo UUID；缺省为空，不开启任何库。启动生成共享 `seafile.conf` 的 `[cloudfile] protection_repo_ids`，C/Go/Hub 读取同一份配置。此范围独立于 Checkout，不改变租约。

配置变更后所有 Server、Hub、后台工作进程必须同步重启。不得从范围移除仍有保护记录的资料库，也不得运行不包含保护屏障的旧版本。保护范围内整库删除一律拒绝。

## 数据库

新卷一次安装六表。已有卷启动只校验，缺保护表即拒绝启动，不自动补表。五表升级使用本仓 `tools/migrate/file-protection-v1.py`，读取匹配发行包内的四份 DDL 以及 Hub `FreshSchema`；先验证五张既有表精确结构，再只创建保护表，不改业务行和 CE 原生表，不引入迁移台账。

在独立维护进程中提供既有 `SEAFILE_MYSQL_DB_*` 环境变量，先检查：

```sh
python3 tools/migrate/file-protection-v1.py --installdir /path/to/seafile-server
```

检查会使用连接级协调锁和临时表比较 DDL，不修改持久表。管理员确认全部写入已停止后显式执行：

```sh
python3 tools/migrate/file-protection-v1.py --installdir /path/to/seafile-server --apply --writers-stopped
```

`--writers-stopped` 是维护人员的明确声明，不代替真实停写。DDL 在 MySQL 自动提交；中断后重跑会校验既有六表并返回无需修改。异常结构拒绝执行，不自动 DROP/ALTER。失败后保持停写，检查结构，禁止绕过校验启动旧版。存在保护记录时不得降级；解除保护、移除范围和回退须另行维护评审。

## 配套构建

沿用 `release.yaml` 默认 dev，不永久将产品源码指向功能分支。本轮修复尚未合并，联验时对 Server/Hub 选择 `fix/virtual-file-protection`，Docker 选择已推送的验收分支，由已有入口一次解析为固定 SHA 收据：

```sh
CF_SERVER_REF=fix/virtual-file-protection CF_HUB_REF=fix/virtual-file-protection \
CF_DOCKER_REF=fix/file-protection-acceptance CF_BUILD_JOBS=2 \
bash build/cloudfile_14.0/build-in-docker.sh 14.0.8-virtual-protection-fix
```

工作树须已提交、推送且干净；复用既有基础镜像和缓存。构建结果不等于部署验收。

## 发布前验收

- 六表新装、五表显式升级、重复执行、结构异常拒绝和启动只读校验。
- C/Go 与 Hub 共用 MariaDB：定版与上传双向竞争，检查实际 Branch 行锁等待。
- 覆盖、历史恢复、父目录删除/移动/改名、旧 Agent2 票据均拒绝；读取和复制到新路径可用，副本可编辑。
- 普通库零 Protection SQL；选定库大批量提交基准和 SQL 故障拒绝。
- Etech 真实用户 Web/API/Agent2 验收另行完成；DEV/PROD 不在本次修改范围。

## 2026-11-13 隔离验证结果

以下为本机 Linux ARM64 + 临时 MariaDB 11.4 验证，不是 DEV/PROD 或 Etech 真实身份验收。

| 构建输入 | 固定 SHA |
| --- | --- |
| Server | `88a95ac9e9f5c8612d3d3027fa6b558789a00237` |
| Hub | `c0f37682e653c2264d393522df2ddc58f40a6dc0` |
| Docker 运行配方 | `e4be0e173dc7fe01f855a952a502d086bdbe63de` |

完整 C/Go/Web 编译、发行包校验、本地应用镜像组装通过；收据中的 local_storage、objstore 专项通过。本地镜像 `cloudfile/cloudfile:14.0.8-protection-v1-test`，ARM64 image config ID 为 `sha256:b7f1a8feeab9794357abe83a99a51b78381ca6dcf5f54a3a0e58fab635e9f95a`。未推送 Registry，这不是远端 manifest digest。后续探针与本文记录提交不改变该镜像的运行配方 SHA。

- Docker 30 项定向 Python 检查、bootstrap 设置检查、六表跨仓 SQL 契约通过；Hub 5 项保护单测及 1 项 Schema 序列值回归通过；Server 独立 cf-lock 夹具修复后通过。
- 真实 MariaDB 验证六表新装、五表启动/自动新装拒绝、显式升级、重复执行、前缀索引漂移拒绝。审计表已有数据时的自增序列比较误判已修复。
- Hub 真实 SQL 验证定版、批量状态、幂等、解除和审计失败原子回滚；Go 最终屏障与 Hub HEAD CAS 分别验证两种竞争顺序，均观察到实际 Branch 行锁等待。此组 SQL 探针的身份/原生元数据是测试替身，不代表完整并发上传验收。
- `tests/e2e/full/file_protection_native.py` 直接使用匹配发行包的 C/Go/Hub 与随机临时数据库：16 项原生场景通过，包括真实定版、原件读取、旧独占票据 Checkout 拒绝、旧普通编辑票据发布拒绝、C 覆盖/删除/移动/改名/父目录删除改名/文件及整库历史恢复拒绝、整库删除拒绝，以及副本可编辑/恢复/改名/移动/删除。解除后同一普通编辑票据可成功发布，C 写入恢复。
- 原生探针复用真实 ACL 计算与 CE 用户，仅以测试 `native-local` 主体和管理员对象替代登录/SSO；旧票据由测试密钥按真实协议签发，不是实际 Agent2 客户端操作。

原生探针必须在一次性容器中运行，显式设置 `CF_TEST_FILE_PROTECTION=1` 与 `CF_NATIVE_TEST_PACKAGE`；数据库主机 `db`、root 密码 `isolated-protection-test` 仅用于独立测试网络，不暴露宿主端口，不挂载业务卷。探针创建随机数据库并在 finally 清理，不能指向 DEV/PROD；Python 不允许 `-O`。`PYTHONPATH` 使用发行包的 `seahub`、`seahub/thirdpart`、`seafile/lib/python3/site-packages`，`LD_LIBRARY_PATH` 指向 `seafile/lib`。

仍未完成：Etech UI/真实用户集成、浏览器 Web/API 与实际 Agent2 客户端验收、WebDAV/同步入口矩阵、跨库/虚拟库边界完整验收、真实上传双向竞争、受保护大库性能基准及 AMD64 发布验收。这些是历史测试的覆盖缺口；三个核心 PR 已合并，不代表已部署或已完成业务验收。最新组合回归另见后续验收记录。


## 最新 dev 组合验收（2026-11-13）

本轮 ARM64 发行包重新固定 Server `5fef361a9a237d52908dafffef378cff1cb2faa9`、Hub `3ec2ecf869f7761ec89d2087c45c6c156c7a3519`、Docker 运行配方 `9b4ec99b3cb38f92a753a50c183b0f147a3b227f`。完整构建与发行包校验通过；新增测试代码独立记录版本，不将旧镜像冒充最新组合。

通过现有入口构建后运行：

```sh
bash tests/e2e/full/run-file-protection.sh 14.0.8-protection-acceptance
```

工具只创建一次性 Docker 网络、MariaDB 10.11 容器和随机数据库，无宿主数据库端口、无业务卷。退出清理自己创建的容器及网络。证据位于 `build/cloudfile_14.0/test-results/protection/<run>/`，包含结果 JSON、C/Go 日志、测试版本、基础镜像架构及源码收据。既有手动 `prod.yml` 在 AMD64 编译及镜像组装后运行相同矩阵；失败保持红色，不自动发布。

- 真实 HTTP `upload-api` 覆盖、`update-api`、混合多文件提交及同步 Commit/HEAD 发布：受保护写入拒绝，普通库对照成功；失败后验证 Branch 和文件 ID。
- 打包 WebDAV provider 经 HTTP 验证 GET/COPY、PUT/DELETE/MOVE 和可编辑副本。Basic 身份及 WSGI 容器为测试适配，不是生产登录、反向代理或实际桌面客户端验收。
- 跨库复制及副本编辑通过；跨库移动拒绝并保留原件，但原生移动可能已在目标库留下副本，不能声称跨库移动具有原子回滚。
- 真实 HTTP 更新与 Hub 定版分别抢先，重复三轮，共六次；观察实际 MariaDB Branch 记录锁等待。定版先完成则更新拒绝；更新先完成则定版返回 `FILE_VERSION_CHANGED`，不会记录过时版本。
- MariaDB general log 证明普通库 HTTP 上传无 Protection SQL。1,000 个真实原生文件逐个定版后，20 次更新采样的普通库 P95 为 8.3 ms、保护库为 13.4 ms；500 文件一次提交约 225 ms。默认工程回归预算为保护库 P95 ≤ max(普通库 P95 × 3, 普通库 P95 + 100 ms)、批量提交 ≤ 10 秒。这不是生产 SLA；可用 `CF_PROTECTION_PERF_ROWS=10000` 扩大规模。

**历史发布阻断：虚拟库写入未继承源库保护。** 在保护源库 `/acceptance/original` 后，对对应虚拟库 `/original` 发起真实 `update-api` 返回 200，虚拟库 Branch 和文件 ID 已改变，而响应后采样时源库 Branch/文件保持原值（不将此即时采样当作异步合并最终安全的证明）。矩阵对此明确失败，不跳过、不放宽断言。正式发布前必须修复原生虚拟库写入边界并重新联验；AMD64 构建成功也不能解除此阻断。Etech/Windows Agent2、DEV/PROD 验收仍另行完成。

补充规模验证：相同 ARM64 运行组合、测试代码 `547f89d` 在 10,000 个真实受保护文件下，普通小库更新 P95 12.0 ms、保护库 P95 46.6 ms，500 文件批量提交 472.8 ms，均通过前述工程预算。两个目录规模不同，差值包含原生大目录处理成本，不能归因于保护 SQL 本身；普通库零 Protection SQL 另有数据库日志证据。该轮仍因虚拟库写入返回 200 而整体失败。

AMD64 首轮流程 `43405168313` 已完成 C/Go/Web 编译，但暴露已有夹具问题：只读源码目录下的 Go TestMain 写入失败，容器原子写出的收据权限为 0600 导致镜像阶段读取及证据上传失败。`547f89d` 将挂载测试编译为测试二进制，在独立临时目录执行，并将非敏感来源收据设为 0644；保留源码只读挂载。修复后的 ARM64/AMD64 backend、repository、shard 挂载测试与证据上传通过。一次性 MariaDB 匿名卷随所属测试容器一并清理，不清理其他卷。


## AMD64 修复前验收记录（历史失败）

[第三轮完整流程 43408619032](https://github.com/eaopen/cloudfile-docker/actions/runs/43408619032) 固定 Server `5fef361a9a237d52908dafffef378cff1cb2faa9`、Hub `3ec2ecf869f7761ec89d2087c45c6c156c7a3519`、Docker `263a1466a632aa498852b05a89171ab59e74d7b4`。后续本文记录提交不改变这次构建输入。

- Ubuntu 24.04 原生 AMD64 完整 C/Go/Web 编译、发行包校验、镜像组装、local_storage、objstore 与三项 bind-mount 检查通过。构建结束将 `test-results` 归还宿主用户，协议测试和证据上传均实际执行成功。
- 九组新增非虚拟库验收通过，包括 Web 上传/更新、混合批量原子性、同步 Commit/HEAD、跨库复制与移动拒绝、WebDAV、六轮双向真实上传竞争、普通库零 Protection SQL 和性能预算。
- AMD64 的 1,000 个受保护文件基准：普通小库更新 P95 9.3 ms，保护库 P95 15.4 ms，500 文件提交 509.2 ms；仍仅为隔离工程预算。
- **整体验收失败**：虚拟库更新返回 200，虚拟 Branch 与文件 ID 改变。与 ARM64 结果一致，收据 `tests.file_protection.status` 为 `failed`，未豁免失败用例。

Runner 内构建标签 `cloudfile/cloudfile:14.0.8-protection-amd64-20261113-r3`，本地 image config ID `sha256:8f3089295505359f8cea48458425c02731395d08c7dd5460d050033bfd7d70ee`。它不是 Registry manifest digest；镜像未推送，runner 镜像不是可直接部署的持久交付件。

[完整验收证据](https://github.com/eaopen/cloudfile-docker/actions/runs/43408619032/artifacts/14029740165) 包含三仓收据、九组通过结果、虚拟库失败前后文件/Branch、性能结果和 C/Go 日志。下一步先修复 Server 虚拟库到源库路径的保护判断及原子并发边界，再使用新的固定三仓 SHA 重跑；此前不进行正式发布或 DEV/PROD 部署。


## 虚拟库保护修复候选（2026-11-13）

Server [#52](https://github.com/eaopen/cloudfile-server/pull/52)、Hub [#102](https://github.com/eaopen/cloudfile-hub/pull/102) 与 Docker [#55](https://github.com/eaopen/cloudfile-docker/pull/55) 提供本轮修复及验收，尚未合并、发布或部署。历史失败记录保留，不能将旧 dev 或旧镜像视为已修复。

C/Go 最终提交屏障使用原生 VirtualRepo 映射，把变更路径映射到源库，在源库 Branch 行锁下重新检查映射和保护版本；删除、覆盖及父目录操作均拒绝。副本仍可编辑，原生回同步仅在保留受保护 File ID 时允许。Hub 定版时检查相关虚拟视图的不可变提交；已有虚拟写入尚未同步到源库时返回 `409 VIRTUAL_REPO_SYNC_PENDING`，避免定版过时原件。无新增数据表、缓存层或 Checkout 租约变化。

本轮固定 Server `2df0ba1a9645da519177000fb573d1d504388adb`、Hub `1a7415b674dea5cb16cba32777ea045762a1ebf4`。ARM64 发行包构建配方为 Docker `bd20724`，后续验收代码固定为 `4cba65f2ea9c325c7a40a9061c13604335bc8563`。完整 C/Go/Web 构建通过；Go 保护/Guard 定向测试、C cf-lock 夹具、Hub 六项保护单测及两个源码快速检查通过。

ARM64 最终矩阵通过 16 项基础原生场景和 11 组扩展验收，包含真实 Go HTTP、C RPC、同步 Commit/HEAD、WebDAV、虚拟库父目录操作、历史恢复及可编辑副本。六个源库和十二个虚拟库并发场景均观察实际 Branch 锁等待，覆盖定版与写入的两种顺序。虚拟库拒绝写入后，源库与虚拟库的 Branch/File ID 均保持不变。

10,000 个真实受保护文件下，普通库更新 P95 13.7 ms、保护库 P95 47.0 ms，500 文件批量提交 447.1 ms，均满足既有隔离工程预算。普通库零 Protection SQL 由 MariaDB general log 独立验证；采样前等待上一轮原生虚拟库合并完成，避免把其后台 SQL 误归因于普通库上传。此数据不代表业务 SLA。


[AMD64 修复后完整流程 43414000985](https://github.com/eaopen/cloudfile-docker/actions/runs/43414000985) 已全部通过，收据固定上述 Server/Hub SHA 和 Docker `4cba65f2ea9c325c7a40a9061c13604335bc8563`。C/Go/Web 编译、发行包校验、镜像组装、local_storage、objstore、三项 bind-mount 检查及同一文件保护矩阵均成功，`tests.file_protection.status=passed`。AMD64 默认 1,000 文件规模：普通库 P95 8.6 ms、保护库 P95 15.3 ms，500 文件提交 663.5 ms。万文件规模的数值来自前述 ARM64 独立运行，不混作 AMD64 数据。

Runner 本地标签 `cloudfile/cloudfile:14.0.8-virtual-protection-fix-amd64`，image config ID 为 `sha256:40ecb363898605940ceb0fdcc6ca8dce66f885af351c59fe6c7da82860beb74f`；Registry digest 为空，未发布镜像。收据及 JSON/日志已上传为该流程的 `full-build-evidence`，来源锁与挂载证据另行上传。后续纯文档提交不改变本次已验证构建组合。

结论：本轮固定修复组合已消除已复现的虚拟写入绕过和定版竞争问题，具备合并审查及后续 AMD64 发布准备依据。通用原生上传拒绝仍沿用现有 HTTP 500 错误映射，验收同时检查不可变 Branch/File ID，未将错误码本身视为安全证明。Etech/SSO、实际 Windows Agent2 与 DEV/PROD 业务验收仍未完成；不得将候选 PR、CI 镜像或隔离测试写成已上线。

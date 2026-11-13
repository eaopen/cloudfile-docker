# 文件保护 V1 配套安装与联验

此组合仍为 Draft，禁止单仓合并或部署。文件原件可读、可复制；写入、删除、移动、改名和影响原件的上级目录操作拒绝。目录改名自动迁移不在 V1 内。

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

沿用 `release.yaml` 默认 dev，不永久将产品源码指向功能分支。联验时对三仓选择 `feat/file-protection-v1`，由已有入口一次解析为固定 SHA 收据：

```sh
CF_SERVER_REF=feat/file-protection-v1 CF_HUB_REF=feat/file-protection-v1 \
CF_DOCKER_REF=feat/file-protection-v1 CF_BUILD_JOBS=2 \
bash build/cloudfile_14.0/build-in-docker.sh 14.0.8-protection-v1-test
```

工作树须已提交、推送且干净；复用既有基础镜像和缓存。构建结果不等于部署验收。

## 合并前验收

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

仍未完成：Etech UI/真实用户集成、浏览器 Web/API 与实际 Agent2 客户端验收、WebDAV/同步入口矩阵、跨库/虚拟库边界完整验收、真实上传双向竞争、受保护大库性能基准及 AMD64 发布验收。因此三仓保持 Draft，不合并、不部署。

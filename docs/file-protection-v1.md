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

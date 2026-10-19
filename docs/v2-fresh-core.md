# V2 独立三表与 CE14 源码组装

本切片交付独立新装 DDL、原生 UID 绑定/单用户 GroupUser TTL 适配器、自动每库存储路由及干净源码组装工具。**尚非完整 M1/MVP**：没有接通 OIDC Web 登录、目录 ACL 的 C/Go 终判或无库权限共享根；不能将本切片作为这些能力已可用的镜像部署。

## 干净源码

需要 Python 3.12 或更新版本，三个代码仓同级放置。`tools/prepare-v2-source.py` 从 `build/v2/source-set.json` 固定的 2026-10-16 CE14 测试源码（Server `b6179eb3`、Hub `15ec1aa7`）导出源码，再加入已提交的扩展白名单；不复制 fork HEAD 的原生文件修改或旧包。

```bash
python3 tools/prepare-v2-source.py --workspace .. --output /tmp/cfv2-clean
```

输出保留 `v2-source-receipt.json`，记录原生提交、扩展提交及每个扩展文件 SHA256。普通 overlay 禁止覆盖原生文件；实际执行所需的修改必须逐文件列在 `native_patches`，仅允许固定上游已经存在的单一文件，并记录修改前后 SHA256。扩展仍不得越出 V2 包或引用旧注册中心/任务框架。旧分支历史仍在 Git 内，构建输入只取这份显式源码集。现有 `cloudfile_14.0` 构建器属于旧组装路径，不能用其结果证明此干净基线。

## 新装三表

唯一 DDL 是 Server 的 `scripts/sql/mysql/cloudfile-v2.sql`，不读取旧 `cloudfile.sql` 或 001–042 迁移：

| 表 | 最小字段职责 |
| --- | --- |
| `cf_library_storage` | repo_key、repo_id、reserved/active/retired；Key 唯一且保留退役占位，不复制 RepoStorageId 的 storage_id |
| `cf_sso_group_map` | provider、org/role、namespace、external_id → 原生 group_id；不存名称、父级或成员副本 |
| `cf_dir_acl` | Repo/路径/主体、访问权限、继承、共享资格及 revision；拒绝规则及库根不得携带内部共享资格 |

DDL 中不创建第四张持久表。安装程序使用数据库命名锁与临时预期表校验真实定义，不另建迁移账本；可重试中断的新装，发现旧扩展表或结构漂移则停止，不做转换、清表或旧权限恢复。

在组装后的 `seahub` 目录配置 `CF_V2_DB_HOST/PORT/USER/PASSWORD/NAME` 后执行：

```bash
python3 -m cloudfile_ext.v2 install --ddl ../seafile-server/scripts/sql/mysql/cloudfile-v2.sql
python3 -m cloudfile_ext.v2 check --ddl ../seafile-server/scripts/sql/mysql/cloudfile-v2.sql
```

需 PyMySQL。数据库用户需要安装/校验涉及的表及临时表权限；密码使用环境配置，不放在命令行。Seafile 原生数据库先使用 CE 自身的新装流程初始化。

## 身份适配边界

`NativeIdentity.bind` 接收**已经认证并与可信 Directory 比对过**的 issuer/sub/UID/login_name；它不是 HTTP 认证接口。账号创建委派原生 API，绑定保存在原生 Profile/SocialAuthUser；登录名改变不换账号，UID/sub 冲突拒绝。原生账号创建与 Profile 事务分离时，失败可以遗留未绑定账号，但不产生成功登录或组权限。

`GroupCatalog` 通过原生 API 新建组并记录映射，不按名称接管手工组，不重映射已有组。当前按平面 CE Group 投影外部组织/角色，有效祖先由可信 Directory 快照明确给出。

`Memberships.ensure` 仅更新当前用户在当前 provider 拥有的 GroupUser；保留其他组和原生管理成员。Redis 就绪记录仅在 SQL 提交后写入，默认 TTL 1800 秒；过期刷新失败返回不可用，不把旧 GroupUser 当成新鲜证明。尚需在全部真实文件入口接入此证明，不能仅凭此适配器宣称旧票据和最终 Commit 已受保护。

## 可复现验证

`tools/check-v2-fresh.py --source /tmp/cfv2-clean` 需要隔离 MariaDB/Redis 的 `CF_TEST_DB_PORT`、`CF_TEST_REDIS_PORT`。测试直接使用组装后的 CE 原生 SQL，且任一跳过均判失败。

Linux CE14 构建环境执行 `bash build/v2/build-native.sh /tmp/cfv2-clean /tmp/cfv2-prefix`，固定 libsearpc/libevhtp 来源，编译原生 C 和 Go；不运行旧 bootstrap。`tests/v2/native_runtime.py` 在隔离数据库上启动真实服务，通过原生 RPC 建号/建组/建库/共享，并验证 HTTP 上传、Branch 变化、下载、Range、改名和删除。

默认运行验证原生 CE 文件通道与新身份/组适配器可共存。设置 `CF_V2_AUTO_STORAGE=1` 后，同一测试先创建普通原生库，再重启启用自动库存储，验证旧库不改绑、C/Go 文件字节、跨文件系统复制、损坏绑定/缺表拒绝、回收站恢复和冷 GC。自动存储测试使用 `/dev/shm` 与默认数据目录分属不同设备，不用同一磁盘上的两个目录冒充跨设备复制。两种模式均需通过；CI 每次重新编译 C/Go，并执行 Go 后端 race 测试。**这些不是 OIDC、扩展目录权限或 Etech Web/BPM 验收**。当前不自动挂载 V2 ACL 发布接口。

## 自动每库存储配置

Server、Go Fileserver 和 GC 共用 `seafile.conf`：

```ini
[cloudfile_v2]
auto_local_root=/srv/cloudfile-libraries
```

缺省不启用。根目录必须预先创建且由部署方管理；缺失挂载、符号链接 key、未知/损坏路由或缺表均拒绝 I/O。新库在第一份 Commit 写入前，将 UUID key 和原生 `RepoStorageId` 在同一事务内保留。`cf_library_storage` 不复制 storage_id，永久删除后保留 retired key 和原生绑定供冷 GC 定位，不自动认领、移动或重建旧库。块暂存位于目标文件系统，支持 key 目录分别挂载的部署方式。完整契约见 Server `doc/cloudfile-v2-clean.md`。该配置暂未接入镜像 bootstrap；本批不交付产品镜像。

## dev2-clean 来源锁定

本工作分支来自 upstream Docker `822c24c9`（2026-10-12）；Server/Hub 的上游基线分别为 `b6179eb3`（2026-10-15）与 `15ec1aa7`（2026-10-16）。三仓已有 `archive/dev2-m1-20261016` 保存上一版全部成果，`dev2-clean` 只含上游源码和显式移植的少量文件。

`source-set.json` 的 `overlay_commit` 锁定实际 Server/Hub 提交；组装时强制校验锁定 SHA，后续移植必须显式同步更新，CI checkout 使用同一来源。`ce_version` 表示测试源码组，不是声称 Seafile 官方发布了同名发行版。此工作树尚未构建 2.0 镜像或完成真实 Etech 端到端验收。

## First native runtime evidence (2026-10-16)

[Actions run 38865151544](https://github.com/eaopen/cloudfile-docker/actions/runs/38865151544), sourced from Docker commit `ee652a1dd0fadd6af625aaa4e34912760c995a6e`, reports both `native-and-schema` and `native-ce14-runtime` **success**. The latter actually builds `seaf-server` and Go `fileserver` using `build/v2/build-native.sh`, starts them with isolated MariaDB/Redis, then runs `tests/v2/native_runtime.py`. The JSON proof reports `http_upload_bytes=184320`, `http_download_bytes=184320`, `branch_commit_changed=true`, `http_range=true`, and real create/group-share/rename/delete. It also explicitly reports `oidc_login_verified=false` and `directory_acl_verified=false`. No Seahub Web process, application session, Etech DEV UI, storage backend-routing or CloudFile ACL byte final-authorization was verified. The two missing product milestones remain open.

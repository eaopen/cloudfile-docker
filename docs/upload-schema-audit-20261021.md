# 普通上传故障与新增表 SQL 审查（2026-10-21）

## 原则与源码基线

普通文件上传、下载不创建、不续租、不提交 Checkout/Checkin 会话。已有锁定文件仍须在最终 Branch 事务中防止被无票据覆盖，不能通过删除锁表或忽略查询错误恢复上传。

本次四个独立工作区重新拉取 GitHub dev 并核对祖先关系：Server `06efc4dea43c5200eea5dd2341f581536ad0838c`、Hub `fc9e89c53636432e2a6da824a8758d1b0a374316`、Docker `0b47da4a811a8c3e240545f3ec6203526792b4d3`、EAP `876e7a7f8d4e6ef2ba588b11f27a58b214ff1c51`。DEV 容器实际 Server/Hub/Docker 分别为 `366f5db742dbd8b8bf08add300b14068d9cfe193`、`f8a396a46a2a14cbac5da9e6fed9319c52d57a20`、`38be08c71e6ff7847b75ebdb35040ba986f65612`；不能把本地最新分支当成已部署版本。

## 已确认上传根因及修复

DEV cf_edit_guard 是 16 字段的 resource_uid 主键布局，索引 PRIMARY、guard_identity；Go 最终提交却按另一套 path/lease_expires_at 布局强制读取 cf_edit_guard_active 索引。只检查表存在导致 SQL 1176，错误又被当作并发冲突重试 10 次。原生日志已有 stop updating repo after 10 retries，故不是文件体积或 Checkout 会话缺失。

Server 修复按实际字段区分已安装布局，并在同一 Branch 事务中查询。资源锁通过 cf_resource 解析路径；孤立资源、生命周期错配、未知/混合结构、SQL 或差异计算失败均拒绝，不跳过已有锁。空锁集合允许普通提交。仅 Branch 头变化返回并发重试，Guard/结构失败直接报错。原生修改 fileop.go 已在 upstream-patches/cloudfile-server.txt 登记；该原生最终提交点不可由上层预检替代。common/cf-v2-edit-fence.c 同样含旧路径查询，但本次源码中只有声明/定义，没有调用点，Makefile 未编入 C 源，记录为未启用历史实现，不能据此声称 C 终判已迁移。

Hub 原先仅查表存在即开放可选 Rust/path Checkout，已改为核对列集合和完整必要索引；已安装 resource 布局不会冒充 path 能力。普通 local-view/optimistic-edit 不因缺少 path Checkout 被强制签出。

EAP 修复只有 200/201 加完整原生单文件回执才能报成功，并核对名称、字节数、文件 ID；错误页、异步任务和重定向均拒绝。同名编号按实际文件名记账。失败终止后续批次，不记成功日志；批量上传不提供事务回滚。未增加 Checkout API 调用。

## SQL 审查与其他风险

检查 3 份 Server SQL 和 42 份 Hub 迁移，共 45 份输入、47 条 CREATE、44 个表名。发现三类同名不兼容布局：

| 表 | 隔离 fresh SQL | 现有 DEV 迁移布局 | 处理 |
| --- | --- | --- | --- |
| cf_edit_guard | path_hash/path、lease_expires_at、15 字段 | resource_uid/lifecycle_ref、lease_until/hard_expire_at、16 字段 | 已修复 Go/Hub 对布局的误判；不修改现有表 |
| cf_dir_acl | 11 字段、复合主键、BINARY(32) path_hash | 008 建 13 字段，042 再加 share_mode/lifecycle_ref，总 15 字段；id/subject_hash/kind、CHAR(64) path_hash | 禁止把 fresh DDL 套入当前卷；当前原生 cloudfile-policy.c 使用统一迁移布局 |
| cf_sso_group_map | 5 字段、复合主键、group_id BIGINT | 006 的 10 字段，id 自增，name 非空无默认值、group_id INT | 新建映射必须使用与该布局匹配的写入契约 |

额外静态风险：cloudfile_ext/v2/memberships.py 的 GroupCatalog 新建映射仅写 5 字段，在现有 006 表布局下未提供必填 name；创建原生组 RPC 先于映射 INSERT，可能留下无映射组。cloudfile_ext/v2/acl_store.py 的内部 mutate 使用 fresh 11 字段及二进制 path_hash，不能直接写现有 15 字段统一 ACL 表（缺少 id/kind/subject_hash 等）。已有映射查询不等于新增写入已验证。此次未在 DEV 创建业务组或新增授权以触发这些风险，故不称为线上复现；它们不是普通文件上传故障根因。

推荐后续方案：现有实例维持 42 项迁移布局为事实源，分别为组目录和 ACL 写入补齐完整类型/必填列/唯一键/读回契约，先确认具体运行调用路径，再决定统一写入适配；不要用补默认空 name、删列、重建表或整枝复制旧实现掩盖不一致。ACL 还必须保持原生 Branch 事务、权限及生命周期终判。已应用迁移不可改写；确需变更用新增迁移并做显式版本验证。当前发现的两项额外风险未纳入本次上传补丁，不应把 SQL 门禁通过等同于所有业务写入兼容。

release.yaml 的 database_schema: 3 是旧发布元数据，不等于当前迁移版本。已有持久卷不会仅因新镜像执行 initialize_fresh_schema 的整套版本迁移，但 write_cloudfile_config → apply_cloudfile_schema 仍在每次启动执行 cloudfile.sql 的 CREATE IF NOT EXISTS，并执行多项 compatibility 建表/改列逻辑；不能把新安装标记测试通过理解成已有卷启动完全不写 DDL。fresh schema 是独立新库合同，不是现有卷的升级脚本。

## 新增防回归门禁

Docker tools/check-sql-contracts.py 只读检查同名 CREATE 冲突以及 Hub Checkout 读取合同与 Server DDL 的字段/索引一致性；tools/reviewed-sql-contracts.json 固定全部 45 份已检查输入的摘要，涵盖字段类型、默认值、约束、ALTER/DROP 和索引 SQL 的变化。已知同名表并非允许任意变化的白名单。更新/新增/删除迁移或 DDL 必须重新审查并显式更新基线，不提供自动刷新基线命令；摘要门禁不能代替 SQL 语义和调用方审查。两项检查接入 tools/run-checks.sh。

## 验证证据及未完成事项

- DEV 只读抓取：50 张 cf_* 表，42 项迁移均 applied，无未完成步骤。
- 使用最新 Hub 源码 SchemaRunner.require_current()，连接包装器仅允许 SELECT，42 项迁移校验和、实际 verify SQL、目录布局及索引契约全部通过。没有执行 DDL/DML。
- 资源锁替代 SQL 已在 DEV EXPLAIN 和只读事务查询通过，当前锁记录为 0；事务立即结束。不能代替真实并发锁行为验收。
- Go 上传/已有锁/托管库写保护定向测试通过；Hub 结构识别 4 项、Docker SQL 漂移 5 项通过；EAP JDK17 定向测试 95 项通过。脚本语法及差异空白检查通过。
- 未全量构建、替换镜像、重启服务或修改 DEV 环境变量。尚不能声称上传已恢复。后续须确认构建/DEV 部署，再验收普通上传→目录可见→下载字节一致、已有锁阻止覆盖、无锁文件正常传输及失败不报成功。

## 本次修复提交

- etech-eap-upload-result: `14a1792eacae16546baddadc6c6a88b727953070`
- cloudfile-upload-guard: `578d9fd51c73b5a70d4a3ebdbe0f627e710ead76`
- cloudfile-upload-guard-hub: `b3fa0b2d256d5a7286a3ee85da54fd9a97a7e11c`

Docker 门禁及本报告随同一审查提交交付；均尚未部署。

## 方案对比补充

参见 [跨方案对比与补充计划](upload-plan-comparison-20261021.md)。补充了实际参与编译的 common/cf-lock.c、存储绑定两表共存、bootstrap 启动 DDL 边界，以及 EXDEV 和离线迁移验收；与尚未接入的 common/cf-v2-edit-fence.c 区分。

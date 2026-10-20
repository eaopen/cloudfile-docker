# DEV V2 四表修复执行记录（2026-10-21）

## 授权、目标和源码

用户明确要求“按照新的数据库表设计，直接修复 dev 环境中 cloudfile dev 中 v2 新增的 4 张 cf_* 表”。本次连接 minio157 的 cloudfile-dev 容器和 seafile_db，核对容器为运行中且未共享宿主 PID。没有操作 PROD、改环境变量、构建镜像、自动回滚或删除无关表。

采用 GitHub 最新 dev：Server 06efc4dea43c5200eea5dd2341f581536ad0838c 的 cloudfile-v2.sql 与 cloudfile-v2-edit.sql；Hub fc9e89c53636432e2a6da824a8758d1b0a374316 的 FreshSchema 进行精确复核。Docker 源码基线 0b47da4a811a8c3e240545f3ec6203526792b4d3。目标 DDL SHA256：`07565ddf1bce244d800135d81e085211970dc8bb145a71f0eea4f1824874270d`。

## 执行结果

| 表 | 新版结构 | 保留记录数 |
| --- | --- | --- |
| cf_library_storage | repo_key 主键、repo_id 唯一键、state 状态约束 | 102（active 74、retired 28） |
| cf_sso_group_map | provider/subject_type/namespace/external_id 复合主键、group_id BIGINT 且唯一 | 1143 |
| cf_dir_acl | 复合主键、BINARY(32) path_hash、共享主体索引及权限/继承/分享约束 | 3 |
| cf_edit_guard | repo_id/path_hash 主键、15 字段、cf_edit_guard_active 等必要索引和活跃行约束 | 0 |

先检查四表无外键依赖，组映射字段长度/类型可容纳、ACL 原始 SHA256 文本与路径匹配，Guard 为空。三个 ACL 均为目录规则，可映射新版；没有把文件 ACL 静默提升为目录授权。ACL 中一条含旧 lifecycle_ref；该旧元数据随原表及独立备份保留，新表按已授权新版的路径语义转换，不伪造生命周期或版本。

转换保留所有存储状态、原生组 ID、规则主体、路径、权限、继承、分享模式和 revision。path_hash 从十六进制文本转换为对应的 32 字节二进制。组名称等新版不再存储的旧字段完整留在受控备份及旧表；新表不再保留临时 DEFAULT 空 name 的旧结构补丁。

工具 tools/repair-v2-four-tables.py 是显式一次性 DEV 转换器，不是启动钩子：先导出四表 DDL/全部记录，再创建候选表；短暂停住容器内 DB 写入服务，重新核对源 DDL/数据摘要，复制并核验全部目标记录，最后一条 RENAME TABLE 原子切换四个名称。任何源变化或 Guard 变为非空均拒绝切换。原进程在 finally 恢复；不自动回滚数据库，不自动重放旧迁移。

## 备份与变更边界

- 独立备份：容器内 `/shared/schema-backups/four-tables-20261020T174028Z_636083.json`，权限 0600；同目录有 receipt，权限 0600。目录权限 0700。内容包含业务映射，禁止提交备份文件。
- 原表保留：`cfv2_old_20261020T174028Z_636083_library_storage`、`cfv2_old_20261020T174028Z_636083_sso_group_map`、`cfv2_old_20261020T174028Z_636083_dir_acl`、`cfv2_old_20261020T174028Z_636083_edit_guard`。
- 时间标识使用 UTC；20261020T174028Z 对应北京时间 2026-10-21 01:40:28。
- cf_resource、cf_commit_intent、cf_edit_session、cf_managed_library、cf_library_storage_key、cf_schema_migration 等均未删除或篡改。保留旧表不表示继续让旧代码按原布局写入四张新表。
- 数据切换后不应再用旧 029/042 校验或重新执行旧迁移恢复旧字段；历史 ledger 是旧迁移事实，不能作为新四表契约通过的证明。完整实例仍包含其它 cf_* 表，此次不声称全库已经变成只有四表的全新安装。

## 已完成验证

- 修复前后全部四表目标投影的行数和数据摘要一致；备份中的源摘要已保留。
- 用最新 FreshSchema._verify_one 逐表验证 SHOW CREATE TABLE，字段类型、长度、NULL/默认值、字符集/排序规则、索引及 CHECK 约束全部与目标 DDL 一致。
- 原生 path Guard 查询 EXPLAIN 通过，原 cf_edit_guard_active 缺失导致的 SQL 1176 不再存在。
- 没有遗留暂停的文件服务或 Python/Gunicorn 写入进程；普通上传后 cf_edit_guard 仍为 0。
- 实际浏览器直传链路创建上传会话、传输及上传完成提交成功；1600 字节唯一测试文件目录可见，通过 EAP 下载票据回读为 HTTP 200，内容逐字节相同，SHA256 `63cdc6faac70060f4bcd1061a93fb5567da981eee2d5f08121bac4d60fc03dd9`。
- EAP 中转上传实测 0B、1B、中文文件名 1KB 三例均返回 code=0/data=true，目录实际条目与大小匹配，下载票据回读 HTTP 200 且内容逐字节一致，排除了仅返回成功但未落盘的假成功。
- 旧测试脚本把原生签名 URL 改写到旧反代路径，最后下载曾得到 404；正确 EAP 票据路径回读通过。单独的原生 URL 反代路径问题不以本次四表变更替代修复。
- 转换工具 6 项定向测试通过，现有跨仓 SQL 门禁通过；新增转换测试接入 tools/run-checks.sh。测试过程不调用 Checkout/Checkin；普通上传会话是文件传输会话，并非编辑签出会话。

## 后续兼容事项

四表实际修复不代表所有旧调用者已经迁移。Docker 的 bootstrap 每次启动仍含集成 DDL，旧版本化 SchemaRunner 仍识别 resource/统一 ACL 结构；已编译 C cf-lock.c/cloudfile-policy.c 的部分路径及旧目录同步写入也仍有旧字段依赖。启动 Schema Owner、旧入口退出及所有原生锁/ACL 写入消费者需按 [方案对比](upload-plan-comparison-20261021.md)继续统一，发布或重启前必须覆盖相关测试。不能靠重新加旧字段、补默认值或清除真实锁来掩盖新旧代码不一致。


### 后续源码修复状态

启动已取消自动扩展 DDL；Docker 四表运行时不再加载旧 PolicyHost。原生 C 锁屏障/普通写终判已直接使用 V2 Guard，Hub 旧控制面路由已退出，V2 读取别名不再进入旧 NativeRead。现有 DEV 的历史表及同库备份仍须按独立 SQL 审核归档后再部署；本轮没有操作现有 DEV 表、环境变量或容器。详见 [运行依赖收敛](../database/v2/20261021-four-table-baseline/README.md)。

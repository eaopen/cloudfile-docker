# 四表开发基线 SQL 包

适用：Server `06efc4dea43c5200eea5dd2341f581536ad0838c` 的四表 DDL、Hub `fc9e89c53636432e2a6da824a8758d1b0a374316` 的对应 V2 读写合同。Docker 启动只读校验的配套提交随本包交付。配套修复将原生锁屏障切换至 V2 Guard，Hub 根路由退出旧 Resource/Intent 控制面；SQL 包通过不表示这些已退役功能重新可用。

## 文件与执行顺序

| 文件 | 数据库 | 用途 |
| --- | --- | --- |
| `00-create.sql` | Seafile 原生库 | 仅空的新安装，创建已确认四表；不用 IF NOT EXISTS 掩盖同名旧表 |
| `01-preflight.sql` | Seafile 原生库 | 只读查看实际结构、索引、记录数、Guard 状态 |
| `05-archive-legacy.sql` | Seafile 原生库 | 只读列出历史表与归档 SQL，审核后人工移到独立备份库 |
| `10-upgrade-029-042.sql` | Seafile 原生库 | 仅 3 列存储表、10 列组映射、15 列统一 ACL、16 列资源 Guard 的既有组合 |
| `20-seahub-compat.sql` | Seahub 原生库 | 显式补齐当前 CE14 模型兼容字段，按所发布模型审核后执行；不新增 cf_* 业务表 |
| `50-verify.sql` | Seafile 原生库 | 检查目标字段类型、长度、NULL、字符集/排序规则、必要索引和 CHECK 名称；失败抛错 |
| `checksums.json` | 不连接数据库 | 固定交付 SQL 的 SHA256；发布前核对 |

新安装使用 `00 → 50`；已有规定旧结构使用 `01 → 10 → 审核执行 05 生成的归档 SQL → 50`。**DEV 已在 2026-10-21 完成四表转换，不再执行 00 或 10，只做校验。** 20 对应移出 bootstrap 的原生表字段修复，不属于四表建表动作；只为明确依赖这些字段的代码执行，不能把遗留扩展功能当成新版需求。其他历史集成表不随本包创建。

升级前显式创建受控独立归档库，并设置 `@cf_upgrade_archive_database`。升级脚本将原表移入该独立库，名称为 `backup_20261021_cf_*`，先创建 `stage_20261021_cf_*`、复制并核对所有行及原生组 ID/ACL 字段，再原子切换。ACL 文本 SHA256 转换成 BINARY(32)；组名称等不再属于新表的旧元数据留在原表/外部备份。存储状态及 repo_key、repo_id 均保留。

以下情况拒绝执行：未确认停写、外键依赖、源结构不符或已升级、候选/备份已存在、任意 Guard 记录、文件级 ACL、长度/哈希不符、数据复制不一致。非空生命周期 ACL 必须先确认路径语义转换，不能暗中放宽生命周期约束。没有通用的活跃锁转换 SQL；有实际锁或待办 Intent 时先单独设计迁移。

## 手动执行示例

先备份数据库和持久存储，停止所有 Hub/Server/后台写入者，核对数据库与实际源结构。下例的受控客户端配置文件由运维预先管理，密码不放命令参数、Git 或 SQL。不要使用 `--force`。

```sh
mariadb --defaults-extra-file=/secure/cloudfile-client.cnf --database=seafile_db --batch \
  < database/v2/20261021-four-table-baseline/01-preflight.sql

mariadb --defaults-extra-file=/secure/cloudfile-client.cnf --database=seafile_db --batch <<'SQL'
SET @cf_upgrade_writers_stopped=1;
SET @cf_upgrade_archive_database='cloudfile_legacy_archive'; -- DBA must create/back up this separate DB first
-- Only after reviewing existing lifecycle ACL semantics, if applicable:
-- SET @cf_upgrade_accept_path_acl=1;
SOURCE database/v2/20261021-four-table-baseline/10-upgrade-029-042.sql;
SQL

mariadb --defaults-extra-file=/secure/cloudfile-client.cnf --database=seafile_db --batch \
  < database/v2/20261021-four-table-baseline/50-verify.sql
```

`@cf_upgrade_writers_stopped` 是操作者声明，不会替你停止进程。10 和 50 使用短暂存储过程提供明确 SIGNAL，执行账号需有相应权限；它们不是业务表或新的迁移台账。短过程 DDL 的权限也应单独审核。无存储过程权限时须由 DBA 以等价、同样可中止的方式执行，不可直接删掉检查。

脚本中断不会自动恢复原表。查看 `stage_*`/`backup_*`、原表名称及实际结构，确认是否完成切换后再决定下一步。客户端必须遇错中止；中断后遗留的同名辅助过程会在下次显式执行时清理，但业务表与备份不会自动删除。

## 验证和 DEV → PROD

已在隔离 MariaDB 11.4 容器验证：新建与验收、旧结构迁移及组身份/ACL 二进制保持、重复执行拒绝、缺索引拒绝、非空 Guard 的 generation 保留、生命周期转换确认、Seahub 兼容 SQL 重放，以及只读启动检查。MySQL 8 及其它数据库版本须在该目标版本另行验证，不以 MariaDB 成功代替。

复现（已有镜像，不下载、不连接现有 DEV 数据库）：

```sh
python3 tests/test_manual_sql_integration.py --hub /path/to/cloudfile-hub
# Or use a dedicated test host with an existing mariadb:11.4 image:
python3 tests/test_manual_sql_integration.py --hub /path/to/cloudfile-hub --ssh-host test-host
```

DEV/PROD 都应记录 SQL 校验和、三仓源码 SHA、目标数据库版本、备份位置、前后结构/数量、执行人及时间。验收至少包含普通上传→目录可见→下载哈希一致、0B/1B/中文文件名、已有锁保护及新旧实例重启不改表。50 和启动校验会拒绝混入历史 cf 表。现有 DEV 尚保留历史表及备份，部署前须审核执行 05 生成的归档 SQL；不得为了通过启动校验删除数据或恢复旧表。四表启动不再接入旧 PolicyHost，显式启用旧入口的配置会在启动时被拒绝并列出变量名。本次不修改现有 DEV 数据库或部署镜像。

目标结构验收还需核对完整 SHOW CREATE（包括默认值与 CHECK 内容），50 不能代替所有业务语义和原生消费者测试。


## 运行依赖收敛（2026-10-21）

- 普通上传、下载、目录 ACL 与 Etech 目录同步使用现有 V2 入口；关闭 Checkout 时，C/Go/Hub 均不查询 Guard。
- C fileop 锁屏障与普通写入事务只读 path-keyed Guard，不再关联 `cf_resource` 或查询 029 台账。活动租约阻止无受控凭据的写入（包括租约所有者）；SQL 故障拒绝写入。
- Docker 不再为四表运行时安装旧 PolicyHost Gunicorn hooks，仅删除自己管理的旧 hook 块，保留操作者其它 hook。`CLOUDFILE_*` 的旧 OIDC/授权/编辑/传输/注释/审计/搜索入口若显式开启，启动拒绝；不会自动修改环境变量。原生 OAuth、`/oidc/` 和 V2 API 不属于该旧入口。
- Hub 根路由只保留当前原生文件/库接口、原生库配置、V2 兼容只读别名及部署扩展；不再挂载旧 SchemaRunner 管理、同步、会话、Intent 和 capabilities 入口。管理使用 `/api/v2.1/cloudfile/authorization/v1/directory-rules/`，组同步使用 `/api/v2.1/admin/cloudfile/directory/entities/sync/`。旧只读别名采用现有 V2 的参数和回执，不保留历史字段。
- 兼容读取：`extensions/authorization/v1/{effective-permission,shared-directories,directory-entries}/` 直接使用 V2 视图；旧 `directory-address`、`library-rules`、`directory-shares` 等历史路由不再提供。不能用保留历史表来恢复它们。

本轮：配置/只读启动/SQL 契约 46 项；Hub 28 项及 7 个子用例；原生 C 锁屏障及最终事务 12 项；隔离 MariaDB 9 组场景（含从生产 C 抽取的空/活动/过期 Guard 查询）通过。未全量构建、部署或调整 DEV 环境；当前 DEV 历史表归档仍是部署前人工 SQL 步骤，不是启动时升级。

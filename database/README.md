# CloudFile 开发期数据库交付

2026-10-21 决策：CloudFile 仍处于开发阶段，数据库结构升级和数据迁移使用**独立、人工执行的 SQL**。DEV 验证与 PROD 发布使用同一份固定 SQL 包；成熟版本之间才允许另行设计、审核自动升级机制。开发分支、构建成功或标签变化都不自动取得迁移资格。

## 当前产品 4+1 表

当前 V2 是唯一产品基线，四张核心表加一张低频业务操作补充日志表：

| 表 | 作用 |
| --- | --- |
| `cf_library_storage` | 库与存储绑定 |
| `cf_dir_acl` | 目录权限及分享属性 |
| `cf_sso_group_map` | 外部身份与原生组映射 |
| `cf_edit_guard` | 编辑 Guard；普通上传下载不创建 Checkout/Checkin |
| `cf_audit_event` | 补充 CE Activity 无法直接表达的 Tag、Checkout/Checkin 等业务操作 |

其它 `cf_*` 名称属于历史实现或待确认依赖，仅用于备份或数据迁移，不属于新版运行库或运行依赖。不得因旧源码、JSON 迁移、旧开关或当前数据库存在便将其带入新版。不得将旧迁移链、`cloudfile.sql` 或 Django 的自动迁移直接作为新版初始化入口，也不据此删除现有表和数据。扩展审计只保留这一张表，不恢复旧 Outbox/Job/审计事件迁移台账；CE 原生 Activity 负责文件和目录变化。SQL 的候选表、归档表使用 `stage_`/`backup_` 前缀，属于受控运维产物，不能作为新业务模型。

## SQL 包与执行规则

当前包：[20261021-four-table-baseline](v2/20261021-four-table-baseline/README.md)。每个包说明源结构、目标结构、适用的 Server/Hub/Docker 提交、数据转换限制、执行顺序、验收与故障处理，并固定 SQL SHA256。

- 新安装执行独立建表 SQL；已有实例按精确源结构选择升级 SQL。发现缺表、未知结构或非空 Guard 时停止并审查，不自动猜测映射。
- **空卷首次启动会按镜像内随 Server 发行的 reviewed DDL 建表一次**（`/opt/seafile/seafile-server-*/sql/mysql/cloudfile-v2.sql`、`cloudfile-v2-audit.sql`，启用 Checkout 时再加 `cloudfile-v2-edit.sql`），成功后删除 `/shared/seafile/.cloudfile-schema-init-pending` 意图文件；失败保留该文件，下次启动重试。
- 初始化 ≠ 升级：只有"没有 `seafile-data` 的新卷"才会拿到意图文件，已有卷永远只做校验；应用重启不会因新代码、表名存在或旧台账而自动升级，也不执行回填、旧迁移链或兼容 DDL。结构不匹配就停止并给出手动 SQL 提示。
- 应用启动/重启检查运行库不混入历史 CloudFile 表；基础三表和扩展审计表必须匹配，Guard 仅在显式启用 Checkout 时检查。
- 发布前备份、停止所有写入者；DEV 验证后将同一份 SQL 及校验和用于对应源结构的 PROD，不能把 DEV 业务数据覆盖 PROD。两环境结构不同则另写并审核迁移。
- 数据库结构与业务数据迁移分别写清，禁止静默截断、猜测身份、重置真实锁 generation 或依赖 HTTP 200 作为落盘证明。业务对象引用须可核验。
- 默认不自动回滚。MySQL/MariaDB DDL 可能隐式提交，中断后先查看候选表、归档表及数据；停止写入后由人工决定修复或恢复。不能仅因脚本失败就重跑或删除备份。
- 已交付并执行的 SQL 不改写；后续修正用新包记录。以脚本校验和、实际表结构和执行记录为依据，不伪造旧 `cf_schema_migration` 的成功状态。

成熟版本自动升级必须另外给出明确的源/目标版本范围、完整依赖表清单、并发/停机边界、备份与中断恢复证据、全量数据转换验收以及发布审批；不能默认遍历历史迁移目录。上游成熟 Seafile 版本的原有升级流程与 CloudFile 开发期扩展 SQL 分开管理。

历史 `cloudfile-directory-schema.py`、`SchemaRunner.apply()` 与 `tools/repair-v2-four-tables.py` 保留用于追溯，不作为新版开发期发布入口。已运行的容器仍使用旧启动代码，代码变更须随匹配版本发布后才能生效；此次规范和 SQL 交付不意味着已经替换 DEV 镜像或执行 PROD 升级。

## 只读结构盘点（发布/排障前）

启动校验只回答“能否起服务”，不说明“当前装的是哪套结构”。选 SQL 或排障前先运行只读盘点（`information_schema` 查询，不执行 DDL、不读取业务数据）：

```bash
python3 /scripts/cloudfile-v2-schema.py plan   # JSON：current/missing/legacy/incompatible/mixed + 额外 cf_* 表
python3 /scripts/cloudfile-v2-schema.py check  # 非 current 退出码为 2，可直接作为发布门禁
```

`check` 依据 `CF_ENABLE_CHECKOUT` 决定是否要求 `cf_edit_guard`：关闭 Checkout 时该表标记为 `optional-disabled`，不阻塞普通文件服务；启用时按 V2 列/索引契约判定，旧 029 结构归类为 `legacy`，不自动修复。

## V2 当前审计规则

- 文件/目录新建、修改、重命名、移动、删除、恢复等沿用 Seafile CE `Activity`；不再复制 Commit 事件。
- `cf_audit_event` 只保存 Tag 变更、Checkout/Checkin 等 CE 未覆盖的有争议操作；Etech 权限设置及权限日志仍由 Etech 管理。
- 无历史升级框架。此前 `20261021-four-table-baseline` 包是 DEV 一次性转换材料，不能充当当前新安装的审计 DDL；新安装以 Server 的当前 V2 DDL 为准。
- 下载/查看、浏览、搜索不作为当前操作日志采集目标；不引入 Outbox 或异步审计任务表。

# CloudFile V2 — 原生 Seafile 历史库原位升级

## 前提（先确认再切流量）

- 本流程只认**运行中所连接的 Seafile 原数据库** `Repo`、`Branch`、`RepoStorageId`，以及原文件/块物理目录。不能根据 Etech 的库名称重建 Repo，也不能把旧 UUID 只登记到空数据库。
- 升级前分别备份 Seafile/ccnet/Seahub DB 与数据卷；确认新进程使用原始 DB host/schema、原 `seafile-data/storage` 挂载、Seahub SECRET_KEY。
- 旧库 Repo UUID、版本、共享/权限、文件物理路径不改动；V2 自动存储新库继续单独目录。不跨存储类型“自动搬家”。

## 自动机制

- Docker V2 启动时，在三张 V2 扩展表完成原位建表/校验后执行发现和幂等登记，重复启动不再生成新记录。
- 对 `Repo` 存在、`RepoStorageId` 不存在且 `cf_library_storage` 尚无记录的历史原生库，新增 `repo_key=native-<repo UUID>`、`state=active`；它是**原生路径标记**，不是目录或新的 storage ID。
- 原生读写 C/Go 对该标记继续访问 `seafile-data/storage/{commits,fs,blocks}/<repo UUID>`；退休标记仍保留路径供冷 GC。现有记录、原有非默认存储映射、异常/冲突记录都不覆盖。
- CloudFile 只通过管理员读接口 `GET /api/v2.1/admin/cloudfile/native-libraries/?page=1&per_page=100` 枚举**已登记且仍活跃、存储路由为原生的历史库**。新建 V2 定向库存储不在此清单。
- Etech 管理页与同步轮询自动发现清单中尚未纳入的 UUID，添加 `webdisk_library` 业务配置，默认 `active=0`、`sync_status=BLOCKED`、`migrationReviewRequired=true`；已有 Etech 绑定不覆盖。
- Etech 管理员可以在“历史库 · 待启用”中核对原库和权限后明确启用。禁用状态强制发布也被后端拒绝；**首次强制同步会覆盖受管授权，需在核对历史权限后执行**。

## 可重复核查和故障处理

通过 Hub/Server 包内 V2 CLI（使用运行实例已有数据库环境，不在命令行放密码）：

```bash
python -m cloudfile_ext.v2 install --ddl /opt/cloudfile-v2/source/seafile-server/scripts/sql/mysql/cloudfile-v2.sql
python -m cloudfile_ext.v2 discover --ddl /opt/cloudfile-v2/source/seafile-server/scripts/sql/mysql/cloudfile-v2.sql
python -m cloudfile_ext.v2 inspect --ddl /opt/cloudfile-v2/source/seafile-server/scripts/sql/mysql/cloudfile-v2.sql --repo-id <原Repo UUID>
python -m cloudfile_ext.v2 reconcile --ddl /opt/cloudfile-v2/source/seafile-server/scripts/sql/mysql/cloudfile-v2.sql
```

| 状态 | 含义 | 处理 |
|---|---|---|
| NATIVE_UNREGISTERED | Repo 在当前原生 DB，V2 尚未登记 | 重试 reconcile；不新建 Repo |
| NATIVE_REGISTERED | 已原位登记且原生路径仍生效 | 可进入 Etech 管理候选 |
| NATIVE_RESOURCE_MISSING | 当前 Seafile DB 里没有该 UUID | 检查是否连接了旧数据库，必要时先执行有备份的原生数据库和文件恢复；不可仅补登记 |
| EXTERNAL_STORAGE_REQUIRES_REVIEW | 原生仓库已有别的存储路由 | 维持原配置，先人工核对物理后端 |
| STORAGE_BINDING_CONFLICT / STORAGE_BINDING_INCOMPLETE | 记录冲突或破损 | 停止自动修复，核对 RepoStorageId 与物理路径 |

`NATIVE_REGISTERED` 只证明数据库登记正确，不取代文件内容完整性、权限或 FSCK 验证；切换流量前必须抽样验证原库上传/下载、旧授权和文件版本。

**etech01 仅存在于旧数据库时**：在新数据库里无法“发现”出它。先将 CloudFile 接回含 `etech01` 的旧原生库数据库和文件卷，或执行受控原生恢复，再启动发现。Etech 侧不能根据旧业务配置凭空造相同 UUID 的新 Repo。
## V2 双向库存对账（2026-10-17）

CloudFile 每次启动均运行 NativeLibraryDiscovery.reconcile()：只给真实 Repo 且非 VirtualRepo 的旧库幂等补 cf_library_storage。已有配置不修改；发现 cf_library_storage 对应资源不在 Repo、RepoTrash、GarbageRepos 时只记录运维警告，不自动退役或删库。

管理员只读接口 GET /api/v2.1/admin/cloudfile/storage-libraries/?page=1&per_page=100 枚举库存登记；GET 同一路径带 repo_id=<UUID> 可区分缺少登记与原 Repo 缺失。只有 READY 且原生 Repo 可读的库允许导入 Etech；RESERVED、RETIRED、IN_TRASH、GC_PENDING、VIRTUAL_REPO、BINDING_ERROR、RESOURCE_UNREADABLE 均只报告状态。READY 不证明全部文件块完整，需额外 FSCK 与读写验收。

Etech 管理员 POST /eap/cloudDrive/config/libraries/storage-check 对比 cf_library_storage 与 webdisk_library 全量集合。CloudFile 多出的 READY 库自动加入 Etech 待启用管理记录（active=0、PROVISIONING、BLOCKED），不更改 Seafile 原有权限，普通 Etech 用户列表不显示。已存在业务配置不覆盖；Etech 独有 UUID 通过单库原生资源诊断后显示缺登记/缺 Repo/回收站等处理建议。存在未完成 Etech 建库时不自动认领新的 V2 定向库，以避免新库发布回填竞态。

Etech 的 active=0 仅控制业务可见性与发布，并不是 Seafile ACL 拒绝。确实丢失的旧 Repo 不复用 UUID 创建新库，应由运维恢复旧数据库和文件，或由业务人员确认新建独立库。首次强制发布可能覆盖原生受管授权，必须人工核对。

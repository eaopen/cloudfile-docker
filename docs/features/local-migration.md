# 本地文件迁移与大资料库评估

## v0.2 离线管理员单库导入

CF02-07 MVP 复用 v0.1 `a963c177e9e6e5e122c2e088620b2cc2bb63c2b1` 的
`image/migration/` 和已构建 `cloudfile/seaf-cli-migration:9.0.21`。当前目录映射封装
使用 `cloudfile/seaf-cli-migration:9.0.21-cf2`，仍内含官方 CLI 9.0.21，须重新构建镜像。
当前是维护操作，不是开放的 Web/eTech migration API。

仅导入到新建、空、尚未开放给业务用户的 **UNMANAGED** 库。维护网络只允许管理员
和迁移容器访问；禁止连接现有受管库，禁止为迁移关闭受管入口守卫。
核验完成后停止 CLI、轮换 token，再设置持久受管状态和正式 ACL，才交付用户。
该交付配置属于 CF02-08；本轮没有宣称验证受管库 sync 或生产反向代理。

原目录保持只读并在导入期间冻结。使用已有 SourceScanner(content_hash=True)、
WorkingCopyBuilder、WorkingCopyVerifier 生成和核验独立副本；CLI 是双向客户端，
只能挂载副本，绝不能挂载原目录。manifest/逐文件核验报告与客户端状态单独保留。

镜像脚本固定使用：

- `/migration/source`：独立、可读写的暂存副本；
- `/migration/state`：该库专用持久客户端状态；
- `/migration/control`：所有迁移共用的持久排他锁目录；
- `/run/secrets/cf_migration_token`：只读私有 API token 文件；
- `CF_MIGRATION_SERVER_URL`、`CF_MIGRATION_REPO_ID`、`CF_MIGRATION_USER`、
  `CF_MIGRATION_SOURCE_HOST`：管理员固定配置，不接受业务请求传入。

运行时使用 `--platform linux/amd64`，上述四处分别 bind mount（token 只读），
配置四个环境变量，再运行该镜像。当前封装按
`docker build -f image/migration/Dockerfile -t cloudfile/seaf-cli-migration:9.0.21-cf2 .` 构建；
旧 `9.0.21` 镜像不识别准备树，不能用于目录映射导入。
受控维护地址的 TLS/网络限制在部署验收中落实，夹具 HTTP 仅在 Docker internal 网络。

中断使用 Docker stop（脚本捕获 SIGTERM，停止 daemon，退出 143）；恢复沿用同一
库 UUID、暂存路径和 state/control 目录启动，脚本复用已有绑定。不要清空状态或
覆盖暂存副本来掩盖失败。无自动取消后删数据、无目录删除/增量同步/并行迁移支持。

完成必须核对目标实际目录/文件集合、大小，并下载所有小目录文件比较 SHA-256，
输出每文件 path/bytes/sha256/result 的报告。CLI idle/done/status 不能替代内容核验。
该 MVP 不证明源目录全局一致快照、TB 规模吞吐或强杀/多重故障恢复。
旧 CLI 首次绑定需 `-T`，token 短暂存在容器进程参数；沿用 v0.1 限制，管理员专用
隔离运行、禁止日志记录凭据、完成轮换。密封 FD 接线不在本轮扩展。

定向验收复用已有 CE14 隔离入口，跳过其它业务回归：

```sh
python3 tests/verify.py changed --plan
python3 tests/smoke_ce14_runtime.py --image cloudfile/cloudfile:14.0.8-v0.2-rc-work --migration-runtime
python3 tests/verify.py docker
```

实际报告见 eap-cloudfile `docs/releases/evidence/cf02-import-2026-09-27.json`。

## Compose 单库迁移

`migration` profile 提供独立的 `cf-migration` 容器，内含官方 Seafile CLI 9.0.21。
它只接收已经复制到本机的目录，不负责挂载或复制 SMB；同步客户端是**双向**的，
因此必须使用可读写的专用暂存副本，并预先建立一个**空的**目标资料库。
不要把原始 SMB 目录直接作为 `/migration/source`。
暂存目录还需为空间充足的本地文件系统；客户端状态目录会保存同步索引和缓存，
应与源文件、服务端存储一起计入容量规划。迁移期间不要修改暂存目录。

在 `deploy/compose/.env` 为本次迁移设置：

- `CF_MIGRATION_SOURCE_DIR`：本机完整、静止的资料库暂存目录；
- `CF_MIGRATION_STATE_DIR`：本资料库专用、持久化的客户端状态目录；同一资料库中断续传时保持不变；
- `CF_MIGRATION_REPO_ID`：目标资料库 UUID；
- `CF_MIGRATION_USER`：有目标资料库写权限的账户邮箱；
- `CF_MIGRATION_TOKEN_FILE`：该账户的 Seafile API token 文件，禁止提交到 Git；
- `CF_MIGRATION_SERVER_URL`：容器可访问的 CloudFile 地址，默认 `http://cloudfile`。

### 指定目录与库内路径

若只导入部分目录，先在冻结、只读的源副本上创建映射文件。`source` 相对
`--source-root`，`target` 是目标库内的绝对目录；下面只导入两个目录，并分别放入
`/历史资料/设计` 和 `/历史资料/合同`。目标库仍须是新建空库：映射仅改变 CLI 暂存树，
不改变 Seafile CLI 的双向同步语义。

```json
{"version":1,"mappings":[
  {"source":"设计/2024","target":"/历史资料/设计"},
  {"source":"合同/归档","target":"/历史资料/合同"}
]}
```

```bash
python3 tools/prepare-migration.py \
  --source-root /srv/frozen-source \
  --mapping-file /srv/migration-map.json \
  --output-root /srv/migration-attempt-001
```

命令在相邻临时目录中准备完成后才发布新的 `output-root`，从不覆盖已有暂存。
`output-root/data/` 是独立可写 CLI 工作树；`.cf-migration/` 保存源/目标映射、
逐文件 SHA-256 清单和选择 ID，
不进入资料库。把 `CF_MIGRATION_SOURCE_DIR` 设为 **`/srv/migration-attempt-001`**，
不要设为其 `data/`：容器会校验清单并只将 `data/` 交给 CLI。恢复时保持原路径、
状态目录与映射结果不变；不同选择 ID 会被拒绝。选择 ID 绑定准备时的清单，
容器启动时不重读 80 万个文件来证明工作树内容仍相同；暂存除专用 CLI 外必须保持冻结，
目标内容仍需最终核验。

准备失败会留下 `*.incomplete-*` 取证目录，不会发布可导入的 `output-root`。
准备工具逐文件只读一次源并在复制时计算摘要，不会再完整扫描、哈希同一原目录。
默认逐文件 `fsync`；大量小文件且使用独立 Linux 暂存卷时，可实测
`--durability volume`，它在发布完整选择前以一次 `syncfs` 刷新该文件系统，
减少逐文件刷盘次数。该选项会刷新同卷的其他脏数据，须计入资源预算。
大量小文件和大小文件混合场景应分别记录
准备耗时、CLI 索引/上传速率、状态盘 I/O 与目标核验耗时，再针对实际瓶颈调优。
目标验收仍按映射后的库内路径核对清单、大小和必要的内容摘要；CLI 状态不代替核验。
首次绑定前容器通过只读 API 检查目标库根目录为空，读取失败或非空均拒绝；
检查和随后 CLI 绑定并非同一个事务，维护期间仍须禁止其他写入。
当前工具不自动宣布导入完成，也不支持导入既有业务库。

推荐先用一个小资料库试运行。`data/migration/control` 中的锁会拒绝第二个并行实例；
已有状态也会拒绝绑定不同 UUID 或目录。依次运行：

```bash
cd deploy/compose
docker compose --profile migration build cf-migration
docker compose --profile migration up -d cf-migration
docker compose logs -f cf-migration
```

容器每 60 秒输出一次 `seaf-cli status --json`；它不会凭状态自动宣布迁移完成。
确认状态没有同步错误、服务端文件数和总大小与原目录一致，并对抽样大文件做哈希校验后，
运行 `docker compose --profile migration stop cf-migration`。需继续同一资料库时，
沿用原状态和暂存目录后再次启动。迁下一个资料库前，先停止当前容器，
更换 UUID、暂存目录、token 和**新的**状态目录；不要清空旧状态以掩盖未完成的任务。

官方 CLI AppImage 目前仅采用 x86-64 发行包，所以容器固定 `linux/amd64`；
ARM 主机依赖模拟，百万文件规模应使用原生 x86-64 节点。
token 虽通过 Compose secret 提供，但 `seaf-cli sync -T` 会在首次绑定时短暂将其置于进程参数；
须限制主机和 Docker 管理权限，迁移后轮换 token。

## Metadata 容量判断

Seafile 14.0 官方 Metadata Server 的 `MD_FILE_COUNT_LIMIT` 默认是**每资料库 100,000 个文件**，
不是单个文件的字节大小限制。超限资料库无法启用元数据管理；启用后达到上限时，
后续文件的元数据不会继续写入。当前 Compose 同时把 `CF_METADATA_FILE_COUNT_LIMIT`
传给主服务和 Metadata Server，默认 `100000`。`MD_MAX_CACHE_SIZE`（默认 1GB）
只是内存缓存上限，调大它不能解除文件数限制。

**仅当该大资料库需要启用官方高级元数据**（Table/Kanban/Gallery/AI 等）时，
才考虑在两侧一致地提高 `CF_METADATA_FILE_COUNT_LIMIT`，并先以代表性资料库验证
初始化/追赶、资源占用和恢复；数值调高不是性能保证。CloudFile 核心标签和少量业务属性
拟按[解耦方案](cloudfile-tags-properties-decoupling.md)走 Seahub 稀疏存储，
不以放宽官方阈值作为长期前提；但此方案尚未实施，当前 `CF_ENABLE_TAGS` 仍依赖
`CF_ENABLE_METADATA`，不能按规划直接关闭 Metadata Server。
同步传输与元数据管理是两个独立链路；如同步出现 `fs-id-list` 超时，
还需检查服务端 fileserver、反向代理的请求时限，而不是继续调高 metadata 阈值。

Meilisearch 只承担 CloudFile 的搜索投影，不能替代官方 Metadata Server 的
列、链接、视图和 AI 数据；两套能力应保持明确边界。

参考：[Seafile 14 Metadata Server 配置](https://manual.seafile.com/14.0/extension/metadata-server/)、
[Linux CLI 使用说明](https://help.seafile.com/syncing_client/linux-cli/)。

# 本地文件迁移与大资料库评估

## 单资料库迁移

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

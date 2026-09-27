# v0.2 离线管理员单库导入

CF02-07 MVP 复用 v0.1 `a963c177e9e6e5e122c2e088620b2cc2bb63c2b1` 的
`image/migration/` 和已构建 `cloudfile/seaf-cli-migration:9.0.21`，不另建同步器。
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
配置四个环境变量，再运行该镜像。已存在镜像无需 build；首次部署可按
`docker build -f image/migration/Dockerfile -t cloudfile/seaf-cli-migration:9.0.21 .` 构建。
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

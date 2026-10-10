# V05-05 local Compose 离线备份与隔离恢复（开发工具）

适用：`deploy/compose/docker-compose.yml` 的本机绑定数据目录 `data/db` (MariaDB) 和 `data/seafile`（正式文件块与配置）；若存在本地 `data/minio` 一并备份。**不支持外部数据库、外部 S3/MinIO、远端挂载/其他 Compose 覆盖文件中的额外数据卷**；这些模式需要单独的数据资产清单和一致备份，不得将当前脚本当作完整备份。

工具：`tools/cf_recovery.py`（Python 3 标准库）。仅作为已停机本地文件快照/完整性检查/复制到新目录的工具。它不负责停机、不操作在线生产实例、不恢复 Seafile 用户会话、不自动启动或连接数据库，也不声称复制完成就已完成业务恢复。

## 人工操作步骤

1. 运维先核对部署实际 bind mount 和外部存储，完成维护窗口通告与停写，停止主 Web、所有 worker、索引消费进程、MariaDB 和本地 MinIO 等相关写入服务；自行确认没有其他节点或进程写这些目录。
2. 使用实际 Compose 目录（以下只是路径示例，不要替换当前环境参数）执行：`python3 tools/cf_recovery.py backup --compose-root /absolute/path/to/deploy/compose --output /separate/secure-volume/snapshot-YYYYMMDD --ack-writers-stopped`。脚本额外检查该 Compose 项目没有 running 容器；无法查询 Docker 时保守拒绝。快照目录必须事先不存在、不能放到源码/数据目录内部。
3. 在**隔离主机/新目录**先执行 `python3 tools/cf_recovery.py verify --snapshot /secure-volume/snapshot-YYYYMMDD`，再执行 `python3 tools/cf_recovery.py restore --snapshot /secure-volume/snapshot-YYYYMMDD --destination /isolated/cloudfile-compose-data --ack-isolated-destination`。只允许创建全新目标目录，不覆盖现有服务数据；恢复后快照再次核验哈希。
4. 运维在隔离环境中准备与备份版本完全相符的 Compose 配置、镜像和密钥依赖，重建/启动服务；再逐项检验**真实**数据库可启动、文件字节摘要、历史版本、目录 ACL、撤权/身份、审计事实及后台任务。对旧会话、票据、未决 worker 必须按新环境重新授权或使其失效；搜索索引可按既有工具重建。此业务级检验**本工具尚未自动化**。
5. 全部证据与操作命令应保留在私有运维台账，快照包含数据库与认证配置，不能公开上传或放入 Git。新环境测试结束后按真实运营要求管理数据销毁；不要在生产环境直接试恢复。

## 验证现状（2026-10-11）

本地 `python3 -m unittest discover -s tests -p test_cf_recovery.py -v`：4 项通过，使用合成数据，覆盖离线复制/校验/隔离恢复、数据篡改、符号链接、容器仍运行及路径重叠拒绝。**不等于真实 Seafile+MariaDB 恢复验收**。v0.5 W4 必须补真实隔离容器中一组小样本恢复及文件版本、ACL 和权限检查结果，方可将 V05-05 标为 P0 完成。

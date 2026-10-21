# 按库自动分配本地存储

更新：2026-10-20。当前 `dev` 使用 V2 本地路由，物理对象布局保持
`<root>/<key>/storage/<commits|fs|blocks>/<repo_id>`。不搬数据、不改 Repo ID 或对象格式。
Seafile 原生 `RepoStorageId` 是库路由事实来源；不读取、转换或清理旧表
`cf_library_storage_key`，该表原样保留。

## 新安装

1. 从 `deploy/compose/.env.example` 创建 `.env`，新模板明确设置
   `CF_LIBRARY_STORAGE=auto`，并选择 `docker-compose.auto-library-storage.yml`。
2. 运维先创建宿主机 `CF_LIBRARY_STORAGE_HOST_DIR` 指定的真实目录，并设置服务读写权限；
   默认是 `deploy/compose/data/libraries`。Compose 使用 `create_host_path: false`，
   不会悄悄创建缺失的挂载源。不要把旧对象目录替换成空目录。
3. 主服务和 worker 一次性挂载同一个父目录，容器内统一为
   `/shared/seafile/library-storage`。启动时还会拒绝根或任一级祖先为符号链接、
   根不存在或不是目录；不会自动创建存储根。
4. bootstrap 写 `[cloudfile_v2] auto_local_root=/shared/seafile/library-storage`，
   `[storage] enable_storage_classes=false`，三个对象后端均使用 `name=filesystem`。
   新模式不生成 multi 类，也不依赖 `CF_ENABLE_S3_STORAGE`。现有 V2 Server 在首个
   commit 前预留库目录，并使用已有 active/retired 生命周期；此配置不重写路由实现。

直接运行 bootstrap 的新装也默认 auto，但显式选择旧 S3/multiple 变量的安装保留旧模式。
只有新装判断能使用默认值；不能用“环境变量缺失”判定现有实例需要切换。

## 已有安装与显式切换

已有 `.env`、Seafile 对象目录和存储类继续使用原配置。**升级镜像、更新 Compose 文件、
或者没有设置 `CF_LIBRARY_STORAGE` 都不会自行切换旧实例。** 旧组合
`CF_ENABLE_S3_STORAGE=true`、`SEAF_SERVER_STORAGE_TYPE=multiple` 和 auto-local 模板
继续按旧方式运行。旧 overlay 的环境默认值被移除后，bootstrap 仍保留已落盘的旧后端段。
已有 V2 `auto_local_root` 的实例在重启时保持 V2，并仍执行预检。

切换需要运维显式设置 `CF_LIBRARY_STORAGE=auto`，并保留正确的父目录挂载。在改写
`seafile.conf` 前，bootstrap 用临时候选配置执行 Hub 当前的统一 CLI；候选配置保留原
`[storage]`、原存储类 JSON 文件以及原数据库，只有 V2 root 补成上述固定位置。
不会使用独立 `cfv2_*` 数据库。连接信息通过环境变量传递，不放入命令参数。

```text
python -m cloudfile_ext.v2 storage-reconcile \
  --seafile-conf <candidate-seafile.conf> --seafile-data <existing-seafile-data> --dry-run
```

- CLI 输出完整 JSON 报告，bootstrap 原样输出；`BLOCKED`、执行失败或报告格式异常均拒绝启动。
- `NATIVE_CLASS_PINNED` 也会阻止切换。它表示原生默认类仍被 `RepoStorageId` 引用，
  不能直接关闭存储类。运维须检查报告，再针对选定 ID 显式执行
  `storage-reconcile --apply --normalize-native-class <id>`，bootstrap 不自动选择类或删除路由。
- 预检通过后，bootstrap 再执行同一 CLI 的 `--apply`，仅补齐受支持原生库和自动库的
  `cf_library_storage` 登记，之后才原子替换为 filesystem 配置。
- dry-run/apply 任一步失败，原 `seafile.conf` 保持原样。apply 以每库事务执行，跨库部分
  成功可能已经登记，重试幂等；不会以配置回滚掩盖未完成的预检。
- 不支持的 S3/其他后端、非法 key、缺失/符号链接目录及路由冲突均需处理后重新预检。
  `ORPHAN_DIRECTORY` 只报告，不登记、不删除。

CLI 使用 `CF_V2_DB_HOST/PORT/USER/PASSWORD/NAME`；bootstrap 从现有
`SEAFILE_MYSQL_DB_*` 变量传入，保持实例原数据库。
Compose 的 cloudfile/cf-worker 运行环境均明确设置
`SEAFILE_DATA_DIR=/shared/seafile/seafile-data` 与
`SEAFILE_CENTRAL_CONF_DIR=/shared/seafile/conf`，Hub 运行时和预检读取同一原生实例。
CLI 的这两个变量也显式设为当前实例真实原生目录，
覆盖陈旧环境值，避免 Seafile Python 初始化读到其他实例。dry-run 严格只读；首次缺表仅报告 `SCHEMA_MISSING`，不是业务 BLOCKED。
预检无异常后，apply 才幂等建立当前合同的 `cf_library_storage`，不读取旧表。
`STATE_DRIFT` 仅报告、不阻断启动、不更新生命周期；保留 Server 的 reserved/active/retired 终判。以上不是自动数据迁移；切换执行及 DEV/生产发布需按环境审批。

## 验证与边界

```bash
python3 -m unittest discover -s tests -p test_library_storage_config.py -v
python3 -m unittest discover -s tests -p test_settings_block_order.py -v
python3 -m unittest discover -s tests -p test_v06_default_library_storage.py -v
python3 tools/test-bootstrap-settings.py
cd deploy/compose
# 只解析配置，不启动容器或创建目录。
docker compose --env-file .env.example config --quiet
```

专项检查覆盖新装、旧环境保留、显式切换、根校验、原配置库存预检、BLOCKED/PINNED 拒绝、
apply 失败配置不变及重启幂等。生成配置块保留原位置，避免本地别名或覆盖变量在重启时失效。
原生 CE 的 `seafile-data` 链接会只读解析为真实目录后传给 CLI；托管库 root 仍禁止符号链接。
真实旧库、跨挂载上传下载、历史版本、恢复、GC 和 fsck 仍需匹配 Server/Hub 镜像及数据副本验证；
配置测试不代表 DEV/生产验收完成。

原生配置合同还可用当前 Server 的真实 C guard 直接核验：

```bash
python3 tests/check_storage_config_native.py /path/to/cloudfile-server
```

该检查编译并执行生产 guard，接受生成的 `filesystem`，确认错误的 `fs` 被拒绝；
存储类 JSON 中已有的 `backend: fs` 格式不变。

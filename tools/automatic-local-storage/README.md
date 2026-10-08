# 自动本地存储生产补丁构建

修改原因：生产默认建库需要独立目录，逐库挂载和静态 class 会增加维护和重启次数。此工具保留当前运行镜像的员工 OAuth、搜索及前端，仅替换同一原生基线上的存储改动。

规范见 `docs/features/automatic-local-storage.md`；正常完整构建直接使用 server/hub 源码及 `patches/seafobj/automatic-local-storage.patch`，无需此生产补丁工具。

构建上下文包含本目录 Dockerfile，以及 `payload/`：本目录 `apply.py`、验证 manifest、同一生产原生基线编译的 `seaf-server`、`fileserver`、`seafserv-gc`、`seaf-fsck`、`seaf-storage-migrate`、`seaf-fuse`，相应共享 SQL 和 Python 路由。不能只替换主服务而保留旧 GC/fsck 对象路由。

manifest 记录原生基线提交、未打补丁的 seafobj factory SHA-256、各输入 SHA-256 和原生二进制列表。应用时逐项核对，拒绝未知已修改依赖、混合源码版本或非 ELF 产物。

先以隔离数据库、父目录和 Meilisearch 验证镜像；再备份生产配置和数据库，将同一镜像应用到主服务及 worker，部署一次父目录和自动模板。启动检查及实测通过后才能声明生效。未来使用最新开发基线完整构建时，须保留现有数据绑定并重跑跨层用例。

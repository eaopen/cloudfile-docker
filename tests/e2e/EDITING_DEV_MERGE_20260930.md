# Editing Core 开发合并回归

日期：2026-09-30。范围：Hub/Server 的 `feature/lock-checkout-v06` 合入 `dev`，保留当前 .NET Agent，后续 Agent2（Go）复用服务端公共契约。合并开发源码不等于发布镜像或启用 v0.6。

## 修复与兼容

- `editing` 纳入保留域，项目扩展不能覆盖唯一 Editing Core。
- 当前 .NET 的八个设备/读取路由保持不变，编辑开关开启或关闭均保留；Go 编辑适配的八个生命周期路由仅显式启用时挂载。未认证编辑请求拒绝，关闭后返回 404。
- 开发检查隔离 Python 依赖，覆盖旧扩展与当前契约；公共验收向量随 Hub 固定版本，CI 不读取私有 EAP 仓库，EAP 导出脚本校验规范同步。构建配方漂移改为比较 `release.yaml` 锁定的不可变上游 Git 内容。
- 下载主体测试加载实际 User 类和会话常量，隔离原生进程依赖；无效主体仍不得进入 backend/profile 查询。未放宽生产认证。

## 验证证据

| 验证 | 结果与边界 |
| --- | --- |
| `bash tools/run-checks.sh` | 全部通过；旧 Hub 扩展 473 passed，当前契约 500 passed / 281 skipped；C ACL 84、fileop 159 checks 与 50 调用点检查，Server Go build/vet/契约、Compose、配置、发布清单与配方漂移通过。未配置外部 S3 端点，其集成测试跳过 |
| Linux MySQL/Redis/C ABI 契约 | 781 用例首轮 775 passed；6 项失败仅来自缺少 EAP 共享文件挂载和主体测试原生导入依赖，修正后定向复验 7 passed / 20 subtests，无未解决失败。使用专用测试数据库，未执行历史数据迁移 |
| 当前 Hub 原生单文件回归 | 两次 Commit、无内容 Checkin、HTTP 实际字节下载、普通写拒绝、陈旧证明、错误目标、回执 SQL 故障回滚、普通锁 native owner 判定通过 |
| .NET Agent 核心测试 | Docker .NET SDK 8 下全部核心测试通过，16 项 opt-in 通过；Windows ACL/句柄/快照实机组跳过 |
| Go 编辑适配与扩展 | `go test ./...` 与 `go test -count=1 -race ./internal/editing` 通过；浏览器扩展 URI 测试 2 项通过 |

本机快速检查日志：`/tmp/cloudfile-merge-checks-final-20260930.log`。当前 Hub 的原生回归证据：`/tmp/cloudfile-merge-native-20260930/native-result.json`、`build-info.txt`、`test.log`；本次测试库 `46b54bc2-ffad-4828-be6b-0366a17be8c1`。已编译 Server 快照 `ffa9171e9f47aa60d64178feac7fbfba911f1a3c` 的全部受跟踪文件内容与合并前 Server `d104150` 一致，Hub 使用本次工作区源码；没有以旧 Hub 快照代替当前验证。

数据库首轮与定向复验日志分别是 `/tmp/cloudfile-merge-linux-contracts-20260930.log`、`/tmp/cloudfile-merge-linux-recheck-20260930.log`；不将分两次完成的验证描述为单次全绿。

## 数据与开放边界

按未上线范围验收新建隔离数据库的 `029_editing_core`，不提供旧 `029_lock_leases` 历史迁移。SchemaRunner 对未知迁移仍拒绝，不清除现有迁移账本或修改部署数据。

`CLOUDFILE_EDITING_ENABLED`、FILE_LOCK、CHECKOUT 保持默认关闭；EAP 发布实现 pin 不因合并自动更新。真实 HTTPS/OIDC、完整策略/资源运行时、设备 broker、Go CLI/Native Messaging 接线与 Windows Office/CAD 保存恢复仍待验收，不能用路由、库或原生夹具测试替代。

# Editing Native 验收报告

2026-09-30：真实单文件原生闭环通过，建议 **Editing Core Foundation = READY TO FREEZE**。这是原生事务基础的验收结论；本地编辑功能仍默认关闭，不代表可以正式开放完整产品功能。

## 1. 修改文件

本轮继续阶段修复根目标拼接、固定 native owner、补 Checkout 的已有 managed-library 最终门禁，并建立独立原生验收脚本。与并行本地编辑任务共享其 snapshot/size 和历史 checked_in 回执改动，没有重新设计 Editing Core 或新增生产表。

| 文件 | 本轮修改 |
| --- | --- |
| `cloudfile-server/server/repo-op.c` | 使用现有 cf_path_join，避免原生根目录为空时丢失绝对路径 `/` |
| `cloudfile-server/common/branch-mgr.c` | 普通条件写最终两次检查均传 canonical native_username，避免混用业务 userId |
| `cloudfile-server/server/cloudfile-policy.h` | 明确 native owner 参数和已退役 lease proof 的拒绝语义 |
| `cloudfile-hub/cloudfile_extensions/editing/store.py` | 验证既有 owner_native_user 字段，拒绝缺失/变更的绑定；不改变表结构 |
| `cloudfile-hub/cloudfile_extensions/editing/service.py` | 当前权限事务中重新解析 native principal；Acquire/Resume/Prepare 等操作拒绝复用其他 native 绑定的 guard；Checkout 在 Branch 前登记既有 managed marker |
| `cloudfile-hub/cloudfile_extensions/tests/test_editing_core.py`、`test_editing_contract.py` | 补充业务/native 身份分离及调用方 username 注入拒绝测试 |
| `cloudfile-docker/tests/e2e/native_editing.sh`、`native_editing_bootstrap.py`、`native_editing_e2e.py` | 专用实例、真实存储/原生 RPC/HTTP 下载、失败和回包丢失注入、保存证据 |
| `cloudfile-docker/tests/e2e/EDITING_SINGLE_FILE.md`、本报告 | 区分 native 与产品 HTTP E2E，提供复现入口 |
| `eap-cloudfile/docs/features/file-lock-checkout-checkin.md`、`docs/coding/lock-runtime.md` | 更新 owner 契约、原生验收状态和开放边界 |

原生发布路径同时依赖已经实现的 `common/rpc-service.c`、`server/cloudfile-policy.c`、RPC 头/注册和 Python RPC client；Hub 上传路径为 `editing/upload.py`。这些文件里的 snapshot、size、release generation 和上传适配变更与本地编辑任务协调维护。

## 2. 原生事务边界

内容发布只调用 `seafile_cloudfile_publish_edit`；无新内容 Checkin 只调用 `seafile_cloudfile_checkin_edit`。两者进入同一 Branch 原生最终事务：锁定真实 head，复核权限/身份/精确 repo-resource-path、guard/generation/credential_epoch/proof/基线和未决意图，原子发布可见 Branch、CommitIntent receipt、guard baseline，并在 Checkin 时释放。无内容 Checkin 读取 Branch 所指的不可变 commit，核对真实文件 ID 等于 baseline，再记录 receipt/release；不生成新版本。

Hub Prepare 的 SQL 事务及 OIDC guard 已退出后才调用原生 publisher。需要跨 Branch/editing 的顺序为 authority scopes、账号/当前映射及 repo、managed marker、GC（如适用）、Branch、resource/guard/intent。Checkout enrollment 在生命周期读取器锁 Branch 前执行，与旧普通发布的 marker→Branch 顺序一致。未持有 Hub editing 行锁跨原生 RPC。

block/fs/commit object 可以在失败后成为不可达对象，由后续 GC 清理。回执 SQL 失败注入已证明本次可见 Branch、baseline、receipt 不会分裂；没有为物理对象增加回滚机制。缺配置/schema/RPC/条件时拒绝，不恢复 Python TransactionPublisher，不降级普通上传。

## 3. Owner 与 Barrier

`cf_edit_guard.owner` 是当前 CloudFile 业务 userId，用于认证主体及完整 Checkout proof 的绑定。`owner_native_user` 是从当前 `profile_profile.login_id → profile_profile.user` 映射取得、与活跃 Seafile `EmailUser.email` 精确一致的 canonical native username；Server 普通锁 owner 判断统一使用它。OIDC subject/hash 不是普通锁 owner。既有 local device/session 的 `owner_user_id` 仍是业务 userId，不能当作 native username；没有因字段命名重构表。

生产入口不接受调用方 actor/username/native_user。权限事务锁定当前账号和双向身份绑定，Acquire/Resume/Prepare 再解析当前 principal，并与 guard 的 native 绑定核对。原生最终事务再次锁定真实账号/映射；native username 不能代替 holder/token、guard/generation/credential_epoch 或 expected baseline。

Checkout 拒绝同 owner 和他人的普通写入；只有完整当前 proof 的受控 Commit/Checkin 可以发布。生产 Checkout 登记现有 managed marker 后，旧普通写协议最终拒绝该库，CloudFile 的条件写路径继续受保护。File-lock 的普通 CloudFile 条件写允许当前 native owner、拒绝他人；它不携带 Checkout baseline。父目录结构操作仍按当前保守门禁处理，本轮不增加迁移/官方客户端兼容支持。

## 4. 构建与测试

独立 Docker 构建目录：`/tmp/cf-edit-build-69317/docker`。完整 native backend C/Go 编译成功，版本 `14.0.8-cf.0-edit-native-final`，Server 源快照 `ffa9171e9f47aa60d64178feac7fbfba911f1a3c`，libsearpc `23d5df62815fb3b7825bf4e1a28b29af701e8cb2`。这是 backend 编译，不声称已构建和部署完整 Hub/frontend 生产镜像。

Hub editing + schema：32 passed；配置：27 passed；C fileop：159 checks / 0 failures，50 个调用点 type-check。Python compileall、shell 语法、各仓库 diff whitespace 检查通过。pytest 有一项未加载 pytest-django 时的 `DJANGO_SETTINGS_MODULE` 配置提示，不影响这些独立数据库测试结果。

## 5. 真实 Native E2E

正式脚本：`bash tests/e2e/native_editing.sh`，指定 `CF_NATIVE_BACKEND` 和新的 `CF_NATIVE_REPORT_DIR`。专用 MySQL/Redis/C Server/Go Fileserver 使用真实文件对象，HTTP `/cloudfile/read` 下载与源内容逐字节比较。身份、subject、OIDC session 记录为受信测试夹具；没有登录真实 OIDC provider。

最终证据：`/tmp/cf-native-final-evidence-69317/native-result.json`、`build-info.txt`、`test.log`。测试库 `0586e965-c5d6-4e9b-84dd-0b4db9225bdf`，资源 `4bb4cb9c-14d8-47ab-8b44-277cf4d13d66`；运行结束移除了专用容器，JSON/日志和原生对象文件保留在报告目录。

| 阶段 | file_id | Branch commit | guard/intent |
| --- | --- | --- | --- |
| Checkout F1 | `ab3ef42fb91a32ef0953833a66e8d731e83178dc` | `b31575aa71a737402a328432312c13f25a2d700e` | checkout，baseline=F1 |
| Commit S2 | `e756817fd3be3e07f2d339a93b8ca0e0ab7ee798` | `2293d75f65ab0bee90b63731bdb9b7fc5f091d1e` | published，baseline=F2，继续 checkout |
| Commit S3 | `9b7673aaa7b7ee040d4aace1ccedd70bafe0ea5b` | `9af4eee5caeb76058dcff028e266c401432a3765` | published，baseline=F3，继续 checkout |
| 无内容 Checkin | F3 | 保持第三版本 commit | published/checked_in=true，guard/pending=NULL，generation 保持 |

`published` 是现有 COMMITTED 成功语义，无需增加另一套状态名称。两次 Commit 均核对真实下载、SQL Branch、实际 file_id、snapshot JSON/size、持锁基线和 receipt；最终下载仍为 S3。

失败矩阵通过：同 owner/他人普通写拒绝；缺少/不匹配 path、repo、resource 拒绝；陈旧 head/file proof 保留 checkout/未决 intent/本地内容；无内容 baseline 漂移不释放；普通锁允许 native owner（与业务 ID 不同）及最终条件写，拒绝他人；临时 SQL trigger 阻断 receipt 更新时 Branch/baseline/receipt 原子回滚。临时 trigger 仅在专用夹具 DB 中使用。

S3 Commit 和无内容 Checkin 的真实成功 RPC reply，在 pysearpc 返回给应用解码前被注入 ConnectionError；后续查询恢复原 SQL receipt/checked_in。重复查询没有生成第二版本。Hub 历史成功重试“不再次调用 publisher”的行为另有接口专项测试；真实浏览器/HTTP 断网重试不属于本次 native 证据。

## 6. 尚未验证

HTTPS/OIDC 登录与登出、真实 CloudFile policy/resource runtime 全链、公开 HTTP 上传重试、浏览器/Agent、当前正式部署所有启用写入口的产品集成及压力/长时间死锁验证尚未完成。生产 Checkout enrollment 的服务级真实 RPC/下载接线由并行本地编辑任务补测通过，但使用另一固定 backend 快照，不能替代完整产品 E2E。

没有开放保存检测、自动上传、iTeam、OnlyOffice 多人、Seafile 客户端锁协议、多文件工程或父目录锁迁移。pending content 的真实本地持久快照/恢复由本地编辑适配承担；native 验收只证明事务拒绝后既有本地内容与 prepared intent 保留。

## 7. 冻结判断

建议 **READY TO FREEZE**：本轮单文件原生事务、owner/proof 契约及已有状态模型具有真实 native 证据。完整产品开放门槛尚未达到，`CLOUDFILE_EDITING_ENABLED` 继续默认关闭。后续适配共用现有 Core，不新增并行锁或 Checkout 服务。

# v0.9 目录 API 验证记录（2026-10-13）

## 统一共享 ACL 验证（2026-10-14）

此节替代历史记录中“独立共享表、无共享 ACL 可独立提供资格”的语义。当前共享与访问权限统一存入 cf_dir_acl，版本化升级直接删除 cf_dir_share，不做数据转换，不保留或恢复独立共享表。

- Hub：83 项 SQL/C/Schema 回归、35 项 HTTP/服务/登录/票据测试通过。SQL 验证使用临时 MariaDB 隔离库；新增覆盖共享开关、统一版本冲突、不继承共享、历史转换测试（现已按直接删除语义更新），以及 DROP 前后中断重试不重建旧表。pytest 有既有 DJANGO_SETTINGS_MODULE 配置项警告，本组测试自行配置 Django。
- Server：Linux 完整 Server 编译链接通过，纯 C 核心严格编译通过，13 项权限测试通过；Hub 与 Server 消费同一份更新后的权限矩阵。统一语义要求 scoped ABI 2，旧普通库入口 ABI 不变。
- 原生字节链路：17 项通过，覆盖共享 r/rw、普通库入口隔离、真实读取/写入/创建、Range、拒绝、删除 ACL 同时撤销共享、关闭共享后旧票据失效、陈旧生命周期拒绝、无共享正向 ACL 拒绝、重新开启共享、账户停用和库只读。身份/OIDC 会话仍为可信夹具。
- 前端：5 项管理面板测试及定向 ESLint 通过；同一列表编辑权限、继承与共享开关，新建非根目录默认开启共享，根目录不允许共享。Docker 配置/升级命令/存储类 37 项及 18 个子用例通过，Compose 配置与脚本语法检查通过。

旧独立共享功能从未启用，040 表数据不构成授权资格；042 直接 DROP，绝不导入 ACL。上线须使用匹配的 Hub/Server、停止目录读写后执行离线迁移。本次未修改现有部署或业务数据库；真实登录 HTTP、制品发布和结构操作验收仍不在本轮完成范围内。

本轮范围为 API 与原生终判，不包含 Hub 页面；未部署或发布制品，不能将 v0.9 全部标记完成。

## 实现

- Server `264921d`：原生无库成员继续 scoped 裁决；共享历史校验、ACL、库只读在最终事务复核。
- Hub `a653429be`：目录分页、管理范围查询、显式原子批量撤销；Web 取流和单文件创建/更新预检查接入目录资格。
- Docker：生命周期 reader 不再依赖开启编辑功能，按授权/OIDC/取流技术依赖装配。

## 证据

| 检查 | 结果与边界 |
| --- | --- |
| Linux Server 编译链接 | 当前源码在 cloudfile-build-base:ce14-v2 完整 Server 构建成功 |
| Hub SQL/C + HTTP 定向回归 | 52 项通过（26 项 API/HTTP，25 项原管理/访问，1 项新增管理员批量越界）；MariaDB 隔离库，目录分页 RPC 为夹具 |
| 原生字节链路 | 13 项通过；真实 SQL、RPC、文件历史、fileserver 字节和 Range；主体和 OIDC 会话为可信夹具 |
| 配置定向回归 | CloudFileSettingsTest 19 项通过；授权开启、编辑关闭仍装配 reader |
| 配置完整回归 | 27 项中已有 OIDC issuer 测试失败，测试要求拒绝 http，但 HEAD 实现接受 http/https；使用 git HEAD 原源码已复现相同失败，本轮未修改其策略 |
| diff 检查 | 修改仓库 git diff --check 通过 |

原生脚本：`tests/e2e/native_directory.sh` 与 `native_directory_e2e.py`。本机证据目录 `/tmp/cloudfile-v09-directory-native-final/`，JSON 为 `directory-result.json`；构建日志 `/tmp/cloudfile-v09-native-build/build.log`。测试容器退出销毁，现有部署未修改。

原生用例：共享默认 r、兄弟拒绝、共享不能写、ACL rw 更新和创建、Range、显式拒绝及旧票据拒绝、删 ACL 回落 r、撤销共享后新票据/旧票据/后续 Range 拒绝、过期生命周期拒绝、独立 ACL、账户停用、库只读。ACL 拒绝测试使用当前 head 签发票据，避免版本变化掩盖权限结果。

## 未完成验收

结构操作 mkdir/delete/rename/move/copy 的受控原子发布及源/目标联合鉴权、ACL/管理授权生命周期联动、撤权并发和传输中停止边界、真实身份 HTTP、镜像/升级及完整跨入口回归尚未完成。当前旧结构入口对管理库保持拒绝，不以新 rw 权限宣称这些操作已开放。共享 stale birth 测试覆盖不匹配证据，但不替代真实目录删除/重建联验。

## 入口隔离修改与验证（2026-10-13）

最新决定：管理 API 机制及正常库用户 API 保持原行为，目录共享/地址访问通过独立用户入口接入同一后台权限机制。

- 既有 PolicyServiceFactory 恢复 DirectoryManagement；新增显式 directory factory，不再由 lifecycle_reader 是否存在切换既有管理权限。
- 旧 OIDC 下载/上传/更新恢复 ContentReadAuthority/ContentMetadataWriteAuthority；新增 identity/v1/directory-access/read-tickets、manual-upload、manual-update 路由。请求不能选择内部权限模式。
- 原生旧入口继续要求库资格；新增入口允许当前目录资格。RPC 条件解析、签发/消费和 Branch 终判保持路径/身份/屏障校验。普通 local_session 入口恢复原库资格要求。
- 本批 HTTP/票据/路由/能力测试 47 项通过，真实隔离 SQL/C 目录测试 38 项通过，Linux Server 构建通过。原生文件字节与入口对照 16 项通过，其中新增旧入口无库拒绝、正常库成员读取及库撤权、旧写入入口无库拒绝；新目录入口仍通过 ACL/共享裁决。
- 本机证据：`/tmp/cloudfile-v09-entry-native-final/directory-result.json` 和 `/tmp/cloudfile-v09-native-build/entry-build.log`。身份与 OIDC 会话仍为可信夹具；未部署制品，完整真实登录 HTTP 验收仍待完成。

本批代码提交：Hub `b05356702`、Server `44f7745`。另补原有 resource/delegation/local-edit host 生命周期回归 14 项通过；仅验证入口隔离与本批受控访问，不将 v0.9 全部标记完成。

## dev 合并验证（2026-10-14）

本次在独立工作树合并 Hub、Server 与 Docker 的目录访问分支，保留原工作区未提交内容，未部署或发布。

- Hub：100 项定向回归通过，覆盖隔离 MariaDB、权限核心、目录管理/访问/共享、Schema 升级、HTTP 与票据。pytest 提示未安装 pytest-django 的配置项警告；本组测试自行配置 Django。
- 前端：4 项目录权限面板测试通过。修复分页请求未完成时切换目录导致 busy 状态残留的问题，并增加延迟响应回归。
- Server：权限 C 核心以严格编译选项通过；13 项权限测试与共享矩阵 84 项检查通过。本次未重新运行完整 Linux Server 构建和原生字节链路。
- Docker：配置、目录升级命令和存储类 37 项测试（另含 18 个子用例）通过；Compose 配置校验通过。旧 OIDC 测试调整为拒绝 ftp，并明确覆盖 dev 已支持的 http/https，不改变运行时策略。

这些证据支持本次分支集成，不替代前述完整 v0.9 验收，尤其真实登录 HTTP、结构操作和部署联验仍待完成。

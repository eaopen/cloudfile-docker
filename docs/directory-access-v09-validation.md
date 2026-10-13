# v0.9 目录 API 验证记录（2026-10-13）

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

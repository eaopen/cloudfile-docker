# 外部资料源与虚拟目录挂载（v1：只读本地目录）

> 用途：说明外部资料源 v1 的支持范围、实现和限制
> 适用版本：Seafile CE 14 参考基线
> 当前状态：部分完成；只读数据面、影子入口与扫描已有，生产挂载运维待验证

## v1 支持范围（2026-09-22 明确）

**v1 只有一种形态：只读挂载本地目录。** `local-path` 是唯一 `source_type`；CloudFile
看到的始终是一个普通本地目录，挂载方式、挂载点与只读性由运维持有。

**其他一切外部形态都先转换成本地目录再登记**，包括 SMB/CIFS、NFS、OpenList、rclone、
WebDAV 或任何第三方网盘：由运维在**宿主机**完成转换（协议挂载或只读 bind mount），
再把该目录暴露进容器。CloudFile 不实现、不支持、也不再规划任何协议级接入：

- **不做直接 SMB（已取消）**：原计划的用户态 `smb` provider（`smbprotocol`）**不再排期**。
  它要求在 CloudFile 内保存 NAS 凭据，而本产品没有密钥管理层——这正是它一直未落地的
  原因；而宿主机与协议栈早已覆盖同一能力，在产品内重做只会得到第二个真值。
- **不做直接 NFS**：没有可靠的纯 Python NFS 客户端；宿主机挂载 + 本地目录已完全覆盖。
- **不做 OpenList/rclone 适配器**：归入独立的[外部资料联邦](external-directory-mount.md)
  规划，**不属于虚拟目录 v1**（当前仓无该模块的任何实现、配置或测试）。

这条边界的收益是：协议差异与协议凭据**都不进入产品**。CloudFile 侧只剩一个安全边界
（路径包含）和一处授权终判，因此"本地目录"与"经宿主机挂载的 SMB 共享"对它不可区分——
上层浏览、影子入口、Overlay 与扫描无需任何协议分支。

```text
SMB / NFS / OpenList / 第三方网盘
        │  运维在宿主机转换（CloudFile 不参与）
        ▼
   本地目录挂载（只读）
        │  只读 bind mount 进容器
        ▼
   local-path provider → CloudFile UI / API
```

CloudFile 不执行 `mount -t cifs/nfs`，不保存协议凭据，也不实现任何协议。挂载掉线、
权限变化和网络故障由宿主机与远端服务负责；CloudFile 必须把不可达报告为错误，
不能显示成空目录。

> 验收说明：`cap external_sources_real` 用真实 Samba + 容器内 CIFS 挂载来跑同一套
> 矩阵，它证明的是"经宿主机挂载后的共享与本地目录行为一致"，**是这条边界的证据，
> 不是 SMB 支持**。真实挂载由门禁脚本自己建立并在结束时卸载。

## 与原生资料库的区别

外部文件不进入 Seafile commit、FS object 和 block 模型。合成 repo ID 只用于入口和
路由，不表示已经转换为原生资料库。因此当前不支持桌面同步、WebDAV、目录打包、历史、
回收站、加密资料库、文件锁或原生版本语义。

## 当前与未完成范围

- 已有：管理员登记/授权、根路径包含校验、只读浏览/下载、自有页面、部分原生读取端点
  影子路由、Overlay API、Meilisearch 扫描代码及能力门禁。
- 未确认：长期运行的挂载恢复、超大目录、凭据轮换、生产性能、不同 NAS 行为。
- 未实现：原生读写、同步和 Seafile 版本历史。
- **不做**：直接 SMB/NFS/OpenList 等协议接入（见上节 v1 支持范围）。

这项能力与计划中的 [CloudFile 外部资料联邦与虚拟目录挂载](external-directory-mount.md)分开管理；
不能用当前 `local-path` 的实现状态推断后者已经存在，反之亦然。

证据：`cloudfile-hub/cloudfile_ext/external_sources/`、
`cloudfile-server/scripts/sql/*/cloudfile.sql`、`tests/e2e/external_sources_matrix.py` 和
`./tools/verify-local.sh cap external_sources`。

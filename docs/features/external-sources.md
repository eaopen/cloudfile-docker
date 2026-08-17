# SMB/NFS 外部资料源

> 用途：说明当前 `local-path` 外部资料源实现和限制
> 适用版本：Seafile CE 14 参考基线
> 当前状态：部分完成；只读数据面和影子入口已有，生产挂载运维待验证

当前实现面向企业已有的 SMB/NFS 文件服务器。宿主机先完成协议挂载，再把允许的根目录
bind mount 到容器；CloudFile 的 `local-path` provider 负责路径约束、授权、浏览、单文件
下载、影子资料库入口、可选扫描与 Overlay 元数据。

```text
SMB/NFS 服务 → 宿主机挂载 → 容器只读 bind mount → local-path provider → CloudFile UI/API
```

CloudFile 不执行 `mount -t cifs/nfs`，不保存协议凭据，也不实现 SMB/NFS 协议。挂载掉线、
权限变化和网络故障由宿主机与远端服务负责；CloudFile 必须把不可达报告为错误，不能显示成
空目录。

## 与原生资料库的区别

外部文件不进入 Seafile commit、FS object 和 block 模型。合成 repo ID 只用于入口和
路由，不表示已经转换为原生资料库。因此当前不支持桌面同步、WebDAV、目录打包、历史、
回收站、加密资料库、文件锁或原生版本语义。

## 当前与未完成范围

- 已有：管理员登记/授权、根路径包含校验、只读浏览/下载、自有页面、部分原生读取端点
  影子路由、Overlay API、Meilisearch 扫描代码及能力门禁。
- 未确认：长期运行的挂载恢复、超大目录、凭据轮换、生产性能、不同 NAS 行为。
- 未实现：用户态 SMB provider、原生读写、同步和 Seafile 版本历史。

这项能力与计划中的 [CloudFile 外部资料联邦与虚拟目录挂载](external-directory-mount.md)分开管理；
不能用当前 `local-path` 的实现状态推断后者已经存在。

证据：`cloudfile-hub/cloudfile_ext/external_sources/`、
`cloudfile-server/scripts/sql/*/cloudfile.sql`、`tests/e2e/external_sources_matrix.py` 和
`./tools/verify-local.sh cap external_sources`。

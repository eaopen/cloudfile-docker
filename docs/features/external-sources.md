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

## 权限（v1 现状：只有源级授权）

- **源级 grant 是 v1 唯一的授权入口**：`cf_external_source_grant` 按 `user` / `group`
  授予只读（`r`），**没有 path 维度**；未获授权的用户**在列表里看不到该源**（是 404，
  不是 403）；系统管理员恒可读。
- **源内目录级 ACL：判定路径可用，写路径不可用。**（2026-09-23 由源码定案）
  - **判定通**：`service.permission_for` 把合成 repo_id 交给权限链，ACL 求解只查
    `cf_dir_acl`、不调 `seafile_api`，所以**若表里已有规则会生效**；
  - **写不通**：`AdminDirACLView`（`acl/admin_apis.py`）与 `DirACLView`（`acl/apis.py`）
    写入前都校验 `seafile_api.get_repo(repo_id)`，合成 id 必然 404 →
    **当前没有任何 API 能创建这样的规则**（`AdminDirACLMigrateView` 只搬移既有规则）。
  - ⚠️ 因此消费方**不要**按"源级 grant 定资格 + 目录级 dir-acl 定细化"设计；v1 只有源级。
    此前 `cf_external_source.repo_id` 的注释与 `models.create_source` 的 docstring 声称
    "写规则无需新代码"，**该说法与实现矛盾，已于 2026-09-23 更正**。
- **待办（未实现，需先有容器测试环境）**：三项**加法式**改动，全在 Hub，真实库路径不变 ——
  ① `AdminDirACLView` 改判「真实库 or 已启用的外部源」；② `probes.path_kind` 对外部源改问
  provider（`path_kind` 现在对合成 id 兜底返回 `'dir'`，会把真实文件路径误判为目录）；
  ③ `probes.subject_eligible` 对外部源改判「已有源级 grant」（否则一律落 `False` →
  400「不具备库级资格」）。**必须先有 E2E 覆盖再放行**：ACL 模块有"逻辑不可测导致同一
  缺陷发布两次"的前例。

## 前端契约（原生库列表的展示依赖）

v1 的主要展示面是**原生资料库列表**：影子层把合成库注入原生列表，所以影子返回的字段
必须与原生端点同形。不一致不会报错——原生 React 侧的 `catch` 只清一个 loading 标志，
症状是界面静默失效。

| 字段 / 参数 | 原生约定 | 为什么必须一致 |
|---|---|---|
| `parent_dir` | 非根路径带尾斜杠（`/a/b/`），根为 `/` | 侧栏目录树按 `parentDir === '/' ? '/' : parentDir.slice(0, -1)` 反推节点 key；不带尾斜杠会算出 `/a/`，`getNodeByPath` 返回 null，树在 `node.isLoaded` 上抛错并被 promise 的 `catch` 吞掉 |
| `with_parents=1` | 一次返回 `/`、`/a`、`/a/b` 各级目录的条目，**祖先在前**，每条自带 `parent_dir` | 树按 `parent_dir` 分组、逐级填充节点；只返回目标目录会让所有祖先节点永远停在未加载状态 |
| `permission` / `user_perm` | `r` | 原生界面据此隐藏上传、新建、拖拽等写操作；外部源只读 |
| `recursive=1` | 明确 400 拒绝 | 递归列举属于 `commit/fs/block` 语义，外部源没有 |
| `GET /repo-tags/` | 原生返回 `{"repo_tags": [...]}` | **列表加载必经**（`loadDirData`）。上游对合成 id 返回 404，前端的 `.catch` 会弹红色错误提示；影子回空集 |
| `GET /file-tags/` | `{"file_tags": [...]}` | 预览路径 `showFile` 必经；同上，回空集 |
| `GET /dir/detail/` | `{"name", "mtime", "permission"}` | 目录详情面板据此渲染；影子按 provider `stat` 返回同三字段 |
| `id` | 空串（**刻意**） | 外部文件没有内容寻址的 obj_id，返回空值可防止调用方把它当成 block 使用 |

`with_parents` 的祖先展开**只在调用者能读该祖先时进行**：目录 ACL 隐藏了 `/a`，就不能
因为请求 `/a/b` 而被旁路；只要有一个祖先不可读，就退回"只返回目标目录"，即旧行为，
不会多泄露任何东西。

- 单元测试（纯函数、不依赖 Django）：`cloudfile-hub/cloudfile_ext/external_sources/tests/test_service.py`
- 容器门禁：`tests/e2e/external_sources_matrix.py` 的「影子目录 parent_dir 用原生格式」
  与「影子目录 with_parents 返回祖先链」

## 当前与未完成范围

- 已有：管理员登记/授权、根路径包含校验、只读浏览/下载、自有页面、部分原生读取端点
  影子路由、Overlay API、Meilisearch 扫描代码及能力门禁。
- 未确认：长期运行的挂载恢复、超大目录、凭据轮换、生产性能、不同 NAS 行为。
- 未实现：原生读写、同步和 Seafile 版本历史。
- **不做**：直接 SMB/NFS/OpenList 等协议接入（见上节 v1 支持范围）。
- **入口（当前）**：v1 的日常入口是**原生资料库列表**（影子注入，进入即可读）。两个 CloudFile
  自有页面已注册路由、可直接访问：`/cloudfile/external-sources/`（登记/授权/只读浏览器）与
  `/cloudfile/admin/`（能力开关总览，供运维核对部署实际开了哪些 `CF_ENABLE_*`）；URL 与用法见
[部署说明](../../deploy/compose/README.md)。
- **入口（后续项）**：前端目前没有渲染 `registry.menu` 的宿主，菜单项因此不会自动出现。
  计划由集成侧（etech 网盘管理页）挂一个入口指向上述 URL —— 与既有“网盘管理界面配置到
  ETECH”的做法一致，且**不需要再改任何上游文件**。

这项能力与计划中的 [CloudFile 外部资料联邦与虚拟目录挂载](external-directory-mount.md)分开管理；
不能用当前 `local-path` 的实现状态推断后者已经存在，反之亦然。

证据：`cloudfile-hub/cloudfile_ext/external_sources/`、
`cloudfile-server/scripts/sql/*/cloudfile.sql`、`tests/e2e/external_sources_matrix.py` 和
`./tools/verify-local.sh cap external_sources`。

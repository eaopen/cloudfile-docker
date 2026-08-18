# CloudFile 权限表与权限模型规格

> **用途**：统一登记 CloudFile 系统中所有权限相关表及其字段语义，给出设计合理性结论、
> 口径决策与后续收敛路线。求解算法见 [acl-semantics.md](acl-semantics.md)，角色口径见
> [roles-semantics.md](roles-semantics.md)。
> **适用版本**：Seafile CE 14 参考基线，CloudFile `dev`。
> **状态**：当前有效决策（2026-08-18 更新）；V3.1 已落地（PermissionService 门面 +
> 等价性测试），V3.2/V3.3 待排期。

---

## 1. 权限表清单与字段说明

权限存储分三层：CE 库级（seafile-db，C 端 enforce）、Seahub 层（seahub-db，Hub 判定）、
CloudFile 扩展（seafile-db，`cloudfile.sql`）。

### 1.1 Seafile CE 原生（库级，seafile-db）

| 表 | 字段 | 语义 |
|---|---|---|
| `RepoOwner` | `repo_id`、`owner_id`(email 或 `group_id@seafile_group`) | 库唯一所有者；owner 权限为 `rw`+管理 |
| `SharedRepo` | `repo_id`、`from_email`(共享发起者)、`to_email`(接收者)、`permission`(`r`/`rw`) | 个人共享，库级 |
| `RepoGroup` | `repo_id`、`group_id`、`user_name`(操作者)、`permission`(`r`/`rw`) | 组共享，库级 |
| `InnerPubRepo` | `repo_id`、`permission`(`r`/`rw`) | 内网公开库，库级 |
| `VirtualRepo` | `repo_id`(新库 id)、`origin_repo`、`path`、`base_commit` | 子目录共享成的虚拟库；owner 记在 `RepoOwner` |
| `RepoUserToken` | `repo_id`、`email`、`token` | 同步客户端鉴权 token，非权限位 |
| `OrgRepo` / `OrgSharedRepo` / `OrgGroupRepo` / `OrgInnerPubRepo` | 同上各表 + `org_id` | 组织命名空间下各共享的变体 |

### 1.2 Seahub 层（seahub-db）

| 表 | 字段 | 语义 |
|---|---|---|
| `ExtraSharePermission` | `repo_id`、`share_to`、`permission`(`admin`) | 指定库管理员；叠加在底层 `rw` 之上 |
| `ExtraGroupsSharePermission` | `repo_id`、`group_id`、`permission`(`admin`) | 组库管理员 |
| `FileShare` | `username`、`repo_id`、`path`、`token`、`permission`、`s_type`(f/d)、`password`、`expire_date`、`user_scope`、`authed_details` | 分享链接（外链）；`permission` ∈ `view_download`/`view_only`/`edit_download`/`edit_only`/`view_download_upload` |
| `UploadLinkShare` | `repo_id`、`path`、`token`、`password`、`expire_date` | 上传链接 |
| `PrivateFileDirShare` | `repo_id`、`path`、`token`、`permission`(`r`/`rw`)、`s_type` | 内部私密链接 |
| `CustomSharePermissions` | `repo_id`、`name`、`description`、`permission`(JSON) | Pro 自定义权限档案 |

### 1.3 CloudFile 扩展（seafile-db，`cloudfile.sql`）

| 表 | 字段 | 语义 |
|---|---|---|
| `cf_dir_acl` | `repo_id`、`path`、`path_hash`(sha1)、`subject_type`(user/dept/group)、`subject`、`permission`(r/rw/none/invisible)、`inherit`、`ctime`、`mtime` | 目录/文件级**内容** ACL；唯一键 `(repo_id, path_hash, subject_type, subject)` |
| `cf_dir_admin` | `repo_id`、`path`、`path_hash`、`subject_type`、`subject`、`inherit`、`ctime`、`mtime` | 目录级**管理**授权；无 permission 列（授权即 admin）；唯一键同上 |
| `cf_external_source_grant` | `source_id`、`subject_type`、`subject`、`permission`(仅`r`) | 外部资料源只读授权 |
| `cf_sso_group_map` | `provider`、`external_id`、`group_id`、`name` | SSO 身份 → Seafile 组映射（喂 ccnet，非直接权限） |
| `cf_lock_lease` / `cf_edit_session` | … | 文件锁 / 本地编辑会话，访问控制侧车，非权限位 |

---

## 2. 权限值空间（谁存、谁 enforce）

| 值 | 含义 | 存储 | enforce 层 | 状态 |
|---|---|---|---|---|
| `admin`（库级） | 库管理 | `RepoOwner` / `ExtraSharePermission` / `ExtraGroupsSharePermission` | Hub `is_repo_admin` | CE 已有 |
| `rw` / `r`（库级） | 库读写/只读 | `SharedRepo`/`RepoGroup`/`InnerPubRepo` | C `seaf_repo_manager_check_permission` | CE 已有 |
| `invisible` / `none` / `r` / `rw`（目录/文件级） | 目录内容 | `cf_dir_acl` | C `cf_acl_resolve` + Hub `resolver.resolve` | 已实现 |
| `admin`（目录级） | 目录管理 | `cf_dir_admin` | Hub `can_manage` | 已实现（V2） |
| `preview` / `cloud-edit` / `custom-*` | 细粒度（不可下载/不可下载编辑/自定义） | Hub 层档案（见 §4.3），**不进 `cf_dir_acl`** | Hub `PermissionService` | 规划（V3.2/V3.3） |

---

## 3. 设计合理性检查

### 3.1 合理之处（保持）

1. **分层真源清晰**：库级由 C 端 enforce（WebDAV/同步绕不开）；目录级由 `cf_dir_acl` 双实现；
   admin 存 Seahub 表（C 只认 `r/rw`）。每层一个真源。
2. **admin 与内容位分离**：`SharedRepo` 只存 `r/rw`、admin 在 `ExtraSharePermission`，从根上避免
   C 端理解 admin；`cf_dir_admin` 无 permission 列是同一思想的延伸。
3. **`path_hash` 冗余必要**：MySQL 无法索引 1000 字符 utf8mb4，sha1 索引 + 读取比对 `path` 是标准做法。
4. **`subject` 经 `subjects.resolve()` 统一到 enforcement 身份**：正确处理 Seafile 14
   「登录 email ≠ 内部身份」的坑。

### 3.2 问题

| 编号 | 问题 | 影响 |
|---|---|---|
| P1 | 权限位枚举不统一（库级 `r/rw`、目录级 `invisible/none/r/rw`、外链五档、admin 游离） | 每个消费入口各自翻译，平行权限语义 |
| P2 | 「谁是库 admin」跨 `RepoOwner`+`ExtraSharePermission`+组/部门 才算得出 | 库级管理判定未收敛到单一入口，与目录级 `can_manage` 不对称 |
| P3 | 子目录共享两套机制重叠（`VirtualRepo` vs `invisible`） | 结果近似但语义不同，产品口径空白 |
| P4 | 组织三层概念并存（org 命名空间 / ccnet 部门树 / `cf_sso_group_map`） | `dept` 主体只认 ccnet 部门树，跨概念易失配 |
| P5 | Hub 缓存 30s + C 无缓存的撤权时效差异 | 界面滞后 ≤30s、数据面即时；方向正确但需文档说明 |

---

## 4. 推荐方案（CE 兼容 + 参考 Pro + 稳定优先）

### 4.1 三条落地原则

1. **开关全关 = 原生 CE**：权限值空间是 CE 超集，但默认路径逐字等于 CE（P0 铁律）。
2. **C 只做粗粒度全序链**：C 端（WebDAV/同步/下载 token）只理解可全序比较的
   `invisible<none<r<rw`；细粒度在 Hub。这正是 Pro 的分层——Pro 的 C 端也只认 `r/rw/admin`。
3. **单一 PermissionService 门面**：所有入口只调 `effective_perm()` + `can_manage()`，不各自判。

### 4.2 不自造 9 位掩码（稳定性红线）

- **fail-open 陷阱（已核实）**：`cf-acl.c` 装载规则时对未知 permission 返回 `UNKNOWN` 并**跳过该行**。
  若往 `cf_dir_acl` 塞新值（如 `view_only`），C 端静默忽略 → 回落 native → **权限放宽**，是安全漏洞。
- **Pro 已有标准答案**：`CustomSharePermissions`（`name`+`description`+`permission` JSON）就是
  「命名能力档案」；想要的 9 位/3 preset 本质是 Pro 的 custom profile，不必发明位掩码。
- **漂移面**：位掩码要在 C+Python 各写一份「bit→能力」求解，正是要避免的平行实现。

**结论：`cf_dir_acl` 永远只有 4 个值，不再加值。**

### 4.3 细粒度 preset 的 Pro 式落地（存储决策：B）

- **存储**：新建 `cf_permission_profile`（`name`、`description`、`capabilities` JSON），
  单一真源。不复用 Pro 的 `custom_share_permission`（避免与 Pro 门控的上游表纠缠，
  符合「cf_* 表在 seafile-db、managed=False」的既有约定）。
- **引用**：目录规则仍存 4 值之一；需要细粒度时 Hub 层把档案名映射为能力集。
- **判定**：`PermissionService.can(user, repo, path, capability)` 单点——先取 `effective_perm()`
  再叠加档案能力集。
- **enforce 边界**：`preview`/`cloud-edit` 由 Hub 下载/编辑端点 + OnlyOffice 回调守卫执行，
  **不进 C 内容链**（与 Pro 一致；WebDAV/同步不感知「不可下载」，须在文档写明）。
- **三个 preset 映射**：`VIEW_ONLY→view-only`（preview，无 download）、
  `UPLOAD_ONLY→upload-only`（create/upload）、`EDIT_NO_DELETE→edit-nodelete`（rw 减 delete）。

### 4.4 库级收敛：PermissionService 门面（已实现，2026-08-18）

单一入口，关闭 P1/P2 的消费侧风险。纯门面，**不改任何表、不改 C**：

```python
# cloudfile_ext/permissions.py（已实现）
class PermissionService:
    @staticmethod
    def effective_perm(username, repo_id, path, native) -> str | None:
        # native 必须是 path-aware 的 C 判定（check_permission_by_path 的结果），
        # 不是 repo 级 check_permission——否则丢掉 C 层目录 ACL 收紧。
        return service.apply_dir_acl(username, repo_id, path, native)  # Hub 再收紧（幂等）

    @staticmethod
    def can_manage(username, repo_id, path) -> bool:
        return service.can_manage(username, repo_id, path)

    # V3.2 追加：def can(username, repo_id, path, capability) -> bool
```

- **落地方式（S1/S2/S4）**：门面是 `_cf_check_permission` → `registry.apply_permission_checks`
  链路的**目标**（钩子注册 `PermissionService.effective_perm`）；`check_folder_permission` 本体
  与 351 个调用点**零改动**；`effective_perm` 接受 path-aware native 入参、委托 `apply_dir_acl`，
  绝不自算 repo 级判定；`can_manage` 委托 `service.can_manage`。等价性 characterization 测试
  （`cloudfile_ext/tests/test_permissions.py`）冻结门面与既有判定的转发/行为一致性，防止
  门面日后被改成"调 repo 级判定"而不被察觉。
- **性能与缓存（S3）**：Hub 侧 `_load_rules`/`_load_subjects` 已有 30s 缓存且无规则短路；
  最大剩余成本在 C 层 `cf_acl_load_rules`——每次 `check_permission_by_path` 全量拉取规则、
  **无缓存**。这是"即时撤权、fail-closed 优先数据面"的刻意权衡，**维持现状、不引入 C 缓存**。

---

## 5. V3 分阶段路线（成本/风险升序）

| 阶段 | 内容 | 改动面 | 风险 |
|---|---|---|---|
| **V3.1（已完成，2026-08-18）** | 库级收敛 `PermissionService` 门面（§4.4）+ 本文档口径决策 | 纯 Python + 文档，无 schema、无 C | 低 |
| **V3.2** | `cf_permission_profile` 表 + 3 个 preset + `can(capability)` 单点 | 新表 + Hub 逻辑 + 下载/编辑端点接入 | 中 |
| **V3.3** | `preview`/`cloud-edit` 真正 enforce（签名下载 token） | Hub 下载/OnlyOffice，Pro 同类逻辑 | 高（真实需求出现再做） |
| 明确不做 | 位掩码列、细粒度塞进 `cf_dir_acl`、给 C 加自定义权限求解 | — | 避免 fail-open 与漂移 |

---

## 6. 口径决策（P3 / P4 / P5）

| 项 | 决策 |
|---|---|
| P3 `VirtualRepo` vs `invisible` | **给外部同步/独立库 → `VirtualRepo`；给已有库成员做库内隐藏 → `invisible`**。两者并存、不合并 |
| P4 org/dept 两套 | `cf_dir_acl` 的 `dept` 只映射 ccnet 部门树（已实现）；org 命名空间不进入目录 ACL |
| P5 缓存时效 | 维持 Hub 30s 缓存 + C 无缓存（fail-closed 方向正确）；界面滞后 ≤30s、数据面即时，写入文档 |

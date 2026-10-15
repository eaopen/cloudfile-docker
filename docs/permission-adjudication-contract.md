# 权限终判契约（冻结）

> **用途**：把"谁有权判、判到什么范围、哪条链不能当终判"一次写清，避免后续开发
> 再实现出第二条授权链。
> **状态**：契约已冻结（2026-10-15）。第 6 节的实现项尚未完成。
> **权威规格**：[acl-semantics.md](acl-semantics.md)（求解语义）、
> [roles-semantics.md](roles-semantics.md)（角色换算）、
> [directory-access-v09.md](directory-access-v09.md)（v0.9 目录资格）、
> [EXTENSION-POINTS.md](EXTENSION-POINTS.md)（扩展点边界）。

---

## 1. 唯一权威：v0.9 scoped 终判

内容权限的终判只有一处实现：

| 入口 | 用途 |
|---|---|
| `cf_policy_check_read()` | 文件/目录读 |
| `cf_policy_check_write()` | 文件/目录写 |
| `cf_policy_check_create()` | 新建（父目录写 + 新对象策略） |
| `cf_acl_evaluate_scoped()` | 纯策略内核，被上面三个调用 |

它们在**同一次事务**内建立原生主体、barrier、库资格与目标存在性，再求解。契约见
`cloudfile-server/server/cloudfile-policy.h`。

### 1.1 取值语义：可取更高者，不是"只能收紧"

终判结果取自 CE 库级权限与目录规则/共享中**更强者**。目录规则可以把库级 `r` 在具体
路径**提升**为 `rw`——v2 的"只能收紧"上限已于 2026-08-28 撤销
（[acl-semantics.md](acl-semantics.md)「决策 2026-08-28」）。

**`cf_ext_check_permission()` 不是终判，也不能改造为终判。** 两点：

1. `native_perm` 为 NULL 时它**根本不调用 provider**，原样返回 NULL
   （`common/cf-ext.c:90-91`）；链上任一 provider 返回 NULL 即终止，后续无法放宽
   （`:106-107`）。所以它**结构上无法**为 CE 未授权的用户创造资格。
2. "只能收紧"对它只是文档约定——`cf-ext.c` 不校验返回值 ≤ 传入值。该约定对 v0.9
   不再成立，不要再用它论证收敛性。

它保留为**收紧型兼容入口**（旧 RPC / WebDAV / 同步边界），语义是"在 CE 已授予的范围内
再收紧"，**不承担** v0.9 的授权职责。

### 1.2 「无整库权限 + 目录资格」的唯一通路

`cf_policy_check_read()` 以 `ce_permission=0` 表示**合法非成员**，scoped core 依据适用的
目录 ACL/共享授予资格（`server/cloudfile-policy.h:48-56`）。这是 `share_mode` 语义的落点，
也是旧 Hook 无法表达的形态。**给旧 Hook 补列、补 SQL 永远得不到这个效果。**

---

## 2. 受管库边界：不静默降级

`cf_managed_library` 是 **opt-in 且单调**的边界（`server/cloudfile-policy.h:7-15`）：

| 库状态 | 行为 |
|---|---|
| 未受管（`guard` 关闭） | 沿用 Seafile 原生访问，行为与普通 CE 库一致 |
| 已受管 | 策略/库资格/结构故障**一律拒绝**；schema 缺失或漂移同样拒绝 |
| 已安装扩展但未显式 opt-in | 边界**仍然生效**——注册表缺失不能重开一个已安装的部署 |

**非受管库继续使用普通 CE 行为；受管库在新版策略不可用时拒绝访问，不静默退回更宽的
原生权限。** 这是安全底线，不是可调项。

---

## 3. 权限取值格冻结：暂不扩枚举

内容链固定为 `invisible < none < r < rw`（[roles-semantics.md](roles-semantics.md) §2）。

Seafile PRO 的 `preview` / `cloud-edit` / `custom-*` **不入链**，只能被
`invisible`/`none` 一票否决，不参与求解。**不为了对齐 PRO 提前引入权限格**；出现真实
业务需求时再单独设计操作能力（download / preview / edit），并同步 C、Hub 与用例集三处。

---

## 4. 与 Seafile 原生能力的关系

**保留 Virtual Repo / 原生文件夹共享，两条路并行，互不替代。**

| 模式 | 适用场景 |
|---|---|
| 原生文件夹共享 / Virtual Repo | 标准 Seafile 客户端、同步、普通文件协作 |
| CloudFile 原位目录资格（`share_mode`） | 企业业务知识库、目录直达、按组织身份裁决的 API |

原生机制**已在运行时保留并有实现覆盖**：`VirtualRepo` 表（[permission-tables.md](permission-tables.md)）、
虚拟库移动/合并（[fileop-lifecycle.md](fileop-lifecycle.md)）、虚拟库 origin 路由
（[features/automatic-local-storage.md](features/automatic-local-storage.md)）。
**不要移除或绕过它。**

### 4.1 同步边界：不承诺立即支持

原位目录资格的**当前边界是 Web / API**。原因是协议约束，不是工期：

- `cf_find_restricted_path` 服务同步与打包下载，只表达"子树可达/不可达"，表达不了
  "某身份在某目录有资格"。
- `invisible` 目录在传统同步客户端上的支持与 SeaDrive 不同，不能对未修改的客户端
  承诺等价行为。

未来要支持原生同步，须**单独验证** Virtual Repo 路径、客户端协议与受管库终判，
而不是简单放开旧同步入口。未验证前，同步侧保持现有拒绝语义（fail closed）。

---

## 5. 长期定位与上游成本

CloudFile 的定位是 **基于 Seafile CE 的企业文件与目录授权增强系统**，
不是 Seafile PRO 的开源替代版。继续复用 CE 的存储、版本、同步与客户端能力。

**最大长期技术债是上游改动量**：截至同步到 `d9ed57e`（2026-09-22），已有
**42 个已跟踪上游文件被修改、51 个文件新增**（`cloudfile-server/AGENTS.md`）。
坚持既有原则：

- 上游代码只保留必要接缝，新能力放 `cf-*` / `cf_*` / 独立 Python 模块。
- **不新增平行的权限算法**（本文件第 1 节）。
- 每次上游同步先处理补丁冲突，不做全面重构。

**不把直接切换 PRO 作为目标。** CE→PRO 的官方迁移只覆盖官方支持的数据与部署，不保证
CloudFile 扩展继续生效；PRO 许可限制创建衍生作品，长期应视 PRO 为可选存储后端或参考
实现。当前**不为可能的 PRO 预建第二套 Server 适配器**。

---

## 5.1 「不可用」不是权限结论（2026-10-15）

`cf_ext_check_permission` 的旧入口只有两个输出：权限字符串或 NULL。受管库走旧入口是
**故意拒绝**，而策略运行时读不到权威数据（`cf_managed_library` schema 缺失/漂移、SQL/事务失败）
也是拒绝——两者同一个 NULL，客户端因此把存储故障显示成「当前用户无权限」。

现在的契约：

| 层 | 行为 |
|---|---|
| provider（`cf_acl_apply`） | 拒绝时若原因是读不到权威数据，置 `gboolean *unavailable`；故意拒绝不置 |
| `cf_policy_check_legacy_access_reason()` | 把「受管库边界」与「schema/SQL 不可用」分开报告；旧的无 out-param 版本保持原语义 |
| `cf_ext_check_permission(..., unavailable)` | 入口清零并透传；仅当返回 NULL 且置位时由调用方转成明确错误 |
| `seafile_check_permission_by_path` | NULL + unavailable → `g_set_error(SEAF_ERR_GENERAL)`，让 Hub 拿到 SearpcError 而不是空权限 |
| Hub `check_folder_permission` | 仍然 fail closed 返回 None，只在请求上打标记 |
| `cloudfile_extensions.permission_middleware` | 带标记请求的 403 改写为 `503 {"code":"POLICY_UNAVAILABLE"}` |

这不是放宽权限：两条路径都仍然拒绝，改的只是对外可区分的错误。旧入口的 4 参数调用方、
`cf_policy_check_legacy_access()` 的既有调用方和普通 CE 路径行为不变（登记表未注册任何
provider 时 `cf_ext_check_permission` 仍是 `g_strdup(@native_perm)` 的透传）。

---

## 6. 待实现（进入 P0）

| # | 项 | 完成标准 |
|---|---|---|
| 1 | 退役 v0.8 读取器（Hub `cloudfile_ext/acl/` 求解加载段；C `cf_acl_apply` 的存储加载段） | 运行时不再查询已删除的 `subject` 列；`cf_find_restricted_path` 等 RPC 契约不变 |
| 2 | 旧 RPC / WebDAV / Hub / 管理授权 / 目录列举接入 v0.9 终判 | 各入口结论一致；**不得只移除旧 Hook**——那会让链回落到原生权限而放宽 |
| 3 | 搬迁 v0.9 缺失的两项旧能力 | `acl-path-migration`（目录改名/移动后规则迁移，须在受控事务内同步 `revision`/生命周期）、`acl_rule_source`（规则源插件） |
| 4 | 开关真值表与测试 | `CF_ENABLE_DIR_ACL` × `CLOUDFILE_AUTHORIZATION_ENABLED` 组合行为有明确预期，不再由两套读取器各自决定 |

**验收要求**：新增场景测试须在同一部署配置下覆盖"v0.9 库 + 旧入口"的组合，尤其是
无库权限但有目录共享、`none`/`invisible` 撤权、目录改名后规则保留、
关闭旧读取器后**不能**回退到更宽的原生权限。

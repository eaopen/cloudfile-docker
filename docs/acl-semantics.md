<!-- generated-by: gsd-doc-writer -->
# CloudFile 目录级 ACL 语义规格

> **用途**：规定目录 ACL 的数据模型、求解算法、权限合并和入口一致性。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效规格；核心入口已有自动化矩阵验证，正文保留未完成的浏览器实操等边界。
> **边界**：库级/父目录分享提供基础访问资格；目录规则按 Pro 兼容语义在资格范围内细化（可升可降，§5）；
> 外部规则服务不得进入同步权限热路径。
> **决策（2026-08-17，方案 v2）**：MANAGE 并入 admin（管理维度独立于内容链，§7）；同类型合并取最高
> （`none`/`invisible` 否决仍生效，§4.1）；文件级规则优先于目录规则（§4.3）；无规则默认回落 CE 库级
> 权限（§4.4）。规格、`acl-cases.json` v2 与 C/Python 实现已同步，V2 时期两端套件全绿
> （Python 78 用例、C 67 检查为该时期快照；该计数已被 V3 用例集取代，见下条）；
> 目录级委托管理（V2）已实现（§7.2）。
>
> **决策（2026-08-28，方案 v3 —— Seafile Pro 兼容语义）**：按
> `eap-cloudfile/docs/review/cloudfile_decision_20260827.md` §7，求解顺序改为：
> ① 个人规则在整个祖先链上优先于部门/群组规则（跨层，不只同层）；
> ② 目录规则可把库级 `r` 在具体路径**提升**为 `rw`（撤销 v2 的"只能收紧"上限）；
> ③ 个人显式可见权限可覆盖群组 `invisible`；
> ④ `none`/`invisible` 仍一票否决，个人 `none`/`invisible` 压过任何群组授予。
> v2 的"最深路径任意类型规则无条件覆盖 + 目录规则永不高于库权限"作废。
> 与目标 Seafile Pro 版本的差异以黑盒基准为准（决策文档 §7.2 第 8 条）；
> 规格、`acl-cases.json` **v3**（29 cases / 70 checks）与 C/Python 实现三处同步修改。

本文件是 **规范**。求解逻辑只有 **两份实现**，必须与它逐字一致：

| 层 | 实现 | 覆盖入口 |
|---|---|---|
| Hub (Python) | `cloudfile-hub/cloudfile_ext/acl/resolver.py` | Web UI、REST API、缩略图、元数据 |
| Server (C) | `cloudfile-server/common/cf-acl-resolve.c` | `check_permission_by_path` RPC → WebDAV 写、Hub 兜底、Web 下载 token |

Go fileserver **不再实现第三份求解逻辑**，而是通过 `cf_find_restricted_path`
RPC 向 seaf-server 提问（`cloudfile-server/fileserver/cf_acl.go`）。同步客户端
是唯一绕开 Hub 和 `check_permission_by_path` 的入口，但它的协议交换的是 commit、
fs 对象和 block，**不带路径**，因此无法在传输过程中做逐文件校验；能做的只有在
同步开始前判断"这个库里是否存在该用户不可读的内容"。少一份实现 = 少一处可能
与规范漂移的地方。

C 侧刻意拆成两个文件：`cf-acl-resolve.c` 只依赖 glib，装纯策略；`cf-acl.c` 装
配置、数据库和群组查询。这样纯策略可以脱离整个 seafile 构建单独编译测试。

配套用例集 [`acl-cases.json`](acl-cases.json) 由 Python 和 C 两端测试共同加载，
是这份规格的可执行形式：

```bash
cd cloudfile-hub && python3 -m pytest cloudfile_ext/acl/tests/
```
```bash
cd cloudfile-server && ./tests/cf-acl/run.sh
```

改语义 = 同时改本文件、`acl-cases.json` 和两处实现，缺一不可。

---

## 1. 数据模型

一条 ACL 规则（表 `cf_dir_acl`，建在 **seafile-db**，三层共享）：

| 字段 | 说明 |
|---|---|
| `repo_id` | 资料库 ID |
| `path` | 规范化后的目录或文件路径（文件规则见 §4.3） |
| `path_hash` | `sha1(path.encode('utf-8'))` 的十六进制小写，用于绕开 MySQL 索引长度限制 |
| `subject_type` | `user` / `dept` / `group` |
| `subject` | `user` 为邮箱；`dept` / `group` 为 group id 的十进制字符串 |
| `permission` | `rw` / `r` / `none` / `invisible` |
| `inherit` | `1` = 规则向下继承到所有子路径；`0` = 只作用于 `path` 自身 |

### 路径规范化

所有实现在写入和查询前都必须做同样的规范化：

1. 空路径视为 `/`。
2. 统一为 `/` 分隔，折叠连续分隔符。
3. 保证前导 `/`。
4. 去掉尾部 `/`，但根路径保持为单个 `/`。
5. **不做** Unicode 归一化、不做大小写折叠 —— Seafile 的路径是字节敏感的。

规范化后 `/a/b/`、`//a//b`、`/a/b` 三者等价，`path_hash` 相同。

---

## 2. 权限格

CF 规则的取值构成一条**全序链**，从严到松：

```
invisible  <  none  <  r  <  rw
```

`invisible` 与 `none` 都拒绝访问；区别在于 `invisible` 额外要求目录在列表中不可见。

Seahub 还存在 `preview`、`cloud-edit`、`admin` 以及 `custom-*` 权限
（见 `seahub/constants.py`）。它们不在这条链上，处理规则见 §5。
链上取值只用于**内容维度**；`admin` 属于**管理维度**（§7），不作为目录 ACL 规则取值。

---

## 3. 主体集合

用户 `U` 在某次判定中的主体集合是：

```
{ ("user", U.email) }
  ∪ { ("group", gid) | gid ∈ U 所属的普通群组 }
  ∪ { ("dept",  gid) | gid ∈ U 所属的部门及其所有祖先部门 }
```

部门是 Seafile 中带父子关系的群组。**祖先部门也计入**——挂在
`/研发中心` 部门上的规则对 `/研发中心/前端组` 的成员同样生效。

只有主体集合命中的规则参与判定，其余规则一律忽略。

---

## 4. 求解算法

输入：`user`、`repo_id`、`path`、`native`（原生 repo 共享权限）。
输出：最终权限，或 `None`（无访问）。

v3（Pro 兼容）求解分两条独立轨道，最后合并：

```
resolve(user, repo_id, path, native):
    if not cf_enabled:            return native          # 开关关闭 = 零行为变化
    if native is None:            return None            # 原生就没权限，无资格可言

    path   = normalize(path)
    levels = ancestors(path)      # ['/', '/a', '/a/b'] —— 从根到自身，含自身

    # 轨道一：个人规则。取该用户最深（沿祖先链）的命中层，
    # 同层内按 §4.1 取舍。个人规则一旦存在，整体覆盖群组/部门轨道——跨层生效。
    user_decision = None
    for level in levels:                                 # 从根向下
        applicable = [rules_at(repo_id, level, subject_type='user')
                      if rule.subject == user
                      and (rule.inherit == 1 or level == path)]
        if applicable:
            user_decision = pick(applicable)             # 深层覆盖浅层（同主体）

    # 轨道二：部门/群组规则。同样取最深命中层；无任何命中时回落 native。
    group_decision = None
    for level in levels:
        applicable = [rules_at(repo_id, level, subject_type in ('dept','group'))
                      and (rule.inherit == 1 or level == path)]
        if applicable:
            group_decision = pick(applicable)

    decision = user_decision if user_decision is not None else group_decision
    if decision is None:          return native          # 全程无规则 → 原样返回
    return tighten(native, decision)
```

要点：

- **个人优先是跨层属性**：父目录上的个人 `r` 依然压过子目录上的群组 `rw`
  （v2 的"最深任意类型规则无条件覆盖"作废）。这正对应 Pro 官方语义
  "即使个人规则来自父目录继承，仍优先于子目录群组规则"。
- 两条轨道内部仍是"最深命中层胜出"，与 v2 一致；轨道间才是 v3 的新分层。
- 同一主体自己的深层规则覆盖自己的浅层规则（`父目录个人 rw，子目录个人 r`
  → 子目录 `r`），个人与群组皆然。

### 4.1 `pick` —— 同一轨道、同一层内的取舍

同一层可能命中多条规则。分两步：

1. **主体类型优先级**（仅群组轨道内）：`dept` > `group`。
   取存在规则的最高优先级类型，**忽略**较低优先级类型的规则。
2. **同类型内**：`none`/`invisible` 一票否决；否则取最高（`rw` > `r`）。

> 第 1 步保证显式个人授权与部门默认互不干扰：个人走轨道一，部门/群组走轨道二，
> 主体分层（§3 的优先级）只在轨道二内部消解 dept 与 group 的冲突。
> 第 2 步对齐 CE 组内合并：`repo-perm.c` 的 `check_group_permission_by_user`
> 在多个组权限里遇到 `rw` 立即取 `rw`。`none`/`invisible` 是硬否决，优先于
> 任何正向授予；"明确禁止"与"允许"相遇时禁止胜出（沿用 CE `none` 语义）。
> **个人轨道存在 `none`/`invisible` 时同样整体压过群组轨道**——用户被个人规则
> 禁止就是禁止，不会被任何群组授予放大。
>
> **已同步（2026-08-28）**：C/Python 实现与 `acl-cases.json` v3 一致
> （个人轨道跨层优先、同轨道否决优先否则取最高），两套件全绿。

### 4.2 `ancestors` 与 `inherit`

`ancestors('/a/b')` = `['/', '/a', '/a/b']`。

`inherit = 0` 的规则只在 `level == path` 时参与，也就是只作用于规则自身所在目录，
不影响其子目录。`inherit = 1`（默认）时规则向下贯穿。

注意循环是**从根向下**且每层覆盖前一层的 `decision`，因此
**最深的、有命中规则的那一层胜出**。中间层没有任何命中规则时，
沿用更浅层的决定（这就是"继承"）。

### 4.3 文件级规则

`path` 可以是文件自身路径。文件的求解层 = 目录祖先层 + 文件自身层，
文件自身层是最深层，因此**文件规则优先于任何目录规则**（最深命中层胜出）。

- 文件规则与其父目录规则并存时，文件规则胜出；兄弟文件仍受目录规则约束。
- 文件没有子路径，`inherit` 对文件规则无实际意义（写入侧可恒为 `0`）。
- 求解算法无需特判文件：`ancestors()` 已把文件自身路径作为最深一层。

### 4.4 默认（无规则）回落

全程无命中规则时返回 `native`（CE 库级共享权限），与原生 CE 行为一致——
**默认不是 NONE**。这保证"开关全关 = 原生 CE"与"无规则 = CE 默认"两层等价。

---

## 5. `tighten` —— 与原生权限合并

v3 起，目录规则的作用是**在基础访问资格内细化权限**（Pro 兼容），
不再以"只能收紧"为不变量：

- 基础资格仍由 `native` 决定：`native is None` ⇒ 无资格 ⇒ 恒为 `None`。
  目录规则不能为没有任何库级/父目录分享的用户创造访问（决策 §7.1）。
- 有资格（`native ∈ {r, rw}`）时，目录规则可升可降：
  库级 `r` 的用户可在具体子目录获得 `rw`（Pro 的 r → rw 提升），
  也可从 `rw` 降为 `r`。
- `admin` native 收紧到规则值——管理维度（§7）另行判定，内容维度遵循目录规则。

```
tighten(native, decision):
    if native is None:                return None         # 无基础资格，规则不创造访问
    if decision in ('invisible', 'none'):
        return None                                       # 一票否决

    if native in ('rw', 'r'):
        return decision                                   # 规则覆盖库级，可升（r→rw）可降
    if native == 'admin':
        return decision                                   # admin 收紧到 decision
    # preview / cloud-edit / custom-* 不在全序链上：
    return native                         # 只能被 invisible/none 否决，否则原样保留
```

最后一类（`preview` 等）保持 v2 保守处理：这些权限与 `r`/`rw` 不可比
（`preview` 能看不能下载，`cloud-edit` 能编辑不能下载），强行排序会在某个
方向上放大能力，故仅否决、不换算。

最后一条是刻意保守：这些权限与 `r` / `rw` 不可比（`preview` 能看不能下载，
`cloud-edit` 能编辑不能下载），强行排序会在某个方向上放宽权限。
一票否决保证了安全边界，其余情况保持原生行为。

> **本节只约束内容维度。** 管理角色 admin（§7）不经过 `tighten`：目录级委托管理
> 可以授予库级内容权限只有 `rw` 的用户，这是管理维度的独立判定，不是放宽内容权限。

---

## 6. `invisible` 的可见性要求

`decision == 'invisible'` 时，除了拒绝所有操作，还要求：

- Hub 的目录列举把该条目**整条剔除**，而不是标记为不可访问。

### 整棵子树一次性交付的操作

同步和打包下载都是**把整棵子树一次性交给客户端**，开始之后没有逐文件的授权点。
因此规则是：**子树内只要存在一个该用户完全不可访问（`invisible` 或 `none`）的
路径，整个操作就在开始前被拒绝**。

由 `cf_acl_find_restricted` 实现：只有规则所在路径才可能改变结果，所以扫描
"规则路径 ∪ 根路径"就够了，不需要遍历真实目录树。返回值按字典序取第一个，
保证同样的请求每次报出同一个路径。

三个消费方：

| 消费方 | 入口 |
|---|---|
| 桌面同步客户端（Hub 提示） | `is_repo_syncable` → RPC |
| 桌面同步客户端（实际拦截） | Go fileserver `checkPermission` → RPC |
| 目录打包下载 | `is_dir_downloadable` → RPC，返回 `undownloadable_path` |

Go fileserver 那一处才是真正的强制点：`is_repo_syncable` 只是让官方客户端能显示
一条有意义的错误，改过的客户端可以直接跳过它。

上游 CE 把 `is_repo_syncable` 和 `is_dir_downloadable` 写死为恒真，这两个桩函数
在 `cloudfile-server/python/seaserv/api.py` 中被替换为透传 RPC。RPC 调用失败时
（上游 CE 构建，或开关关闭）一律按"无限制"处理，保证原生行为不变。

WebDAV 读侧：seafdav 的目录列举与 GET 原生不经过 `check_permission_by_path`，
本项目的构建补丁 `patches/seafdav/0001-enforce-dir-acl-on-read-paths.patch` 已把
读路径接入该 RPC（invisible/none → 条目不列出、直接访问 404，fail-closed）；
**部署约束：未应用该补丁的裸 upstream seafdav 读侧仍不受 ACL 约束**，故 compose
栈默认不部署 seafdav（见 deploy/compose/README.md「WebDAV 与目录 ACL」）。读侧回归
断言见 `tests/e2e/acl_matrix.py` check_webdav。

---

## 7. 管理维度（admin 与 can_manage）

管理维度与内容维度正交，回答"某用户能否在某个作用域内管理成员与权限"。
权限相关表的完整清单与字段语义见 [permission-tables.md](permission-tables.md)。

### 7.1 角色

单一管理角色 **admin**（MANAGE 已并入，见 `roles-semantics.md` §0）：

| 角色 | 内容维度 | 管理维度 | 所有权附加 |
|---|---|---|---|
| Owner | `rw`（库级） | 库级天然为真 | 删库、转让、改库属性 |
| admin | 至少 `rw` | 可授予，scope ∈ {库, 目录} | 无 |
| edit | `rw` | 否 | — |
| read | `r` | 否 | — |

### 7.2 判定

`can_manage(user, repo, path)` → 布尔。所有管理类入口（分享、成员、改权限、
目录 ACL 本身）只调用这一个判定，不许各模块自行判断。

- **库级（已实现）**：`can_manage` = `is_repo_admin(user, repo)`（owner /
  `ExtraSharePermission='admin'` / 组 admin）。
- **目录级（已实现，2026-08-17）**：授权存 `cf_dir_admin`（独立于内容链的新表，
  无 permission 列——授权即 admin 角色本身）；管理权沿目录继承（`inherit` 与内容
  规则同语义）；授予边界 = 库 owner 或最近祖先目录 admin（即 `can_manage` 在目标
  路径为真）；自锁保护沿用现有设计（管理接口用原生权限判定，不经内容 ACL 过滤）。
- **范围边界**：目录级 admin 当前作用于目录 ACL 内容规则与目录 admin 授权的管理；
  CE 的分享/成员管理端点仍按 `is_repo_admin` 判定（接入需改上游分享授权面，未做）。

### 7.3 与内容链的关系

admin 不进入 `pick`/`tighten`，也不作为 `cf_dir_acl` 规则取值（§2）。
目录级 admin 可以授予库级内容权限只有 `r` 的用户目录规则 `rw`——这是 v3
Pro 兼容语义的正常行为（§5），管理维度与内容维度正交。

## 8. 开关

- Hub：`CF_ENABLE_DIR_ACL`（`seahub_settings.py`，由 compose 的 `.env` 注入）
- Server：`seafile.conf` 的 `[cloudfile] dir_acl_enabled`

两者都关闭时，三层都必须走原生代码路径，行为与同 SHA 的原生 CE 完全一致。
这是 P0 的核心验收项。

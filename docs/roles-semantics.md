# CloudFile 角色与权限口径规格与决策

> **用途**：规定 CloudFile 的角色模型（Owner / admin / edit / read）、内容维度与管理维度的
> 划分，以及它们与 CE 权限位的关系；固化下游 P2-03 权限裁剪、P2-06 权限变化提示、
> P2-07 标签权限共同遵守的口径。
> **适用版本**：CloudFile `dev`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效决策（2026-08-17 更新）；评审清单 `couldfile_review20260814.md` 的
> 「五级角色」项维持「不采纳」，替代模型见 §0。
> **边界**：本文件只决定权限**口径**与角色映射，不新增内容权限位；求解算法、继承与
> 收紧规则见 [acl-semantics.md](acl-semantics.md)。

---

## 0. 决策摘要（2026-08-17 更新）

**采用 Owner / admin / edit / read 四角色；MANAGE 并入 admin。**

- 角色是**授权与展示层**的概念；内容终判真源仍是 CE 权限位（`r` / `rw` / `admin`）加
  目录 ACL 收紧链，角色不进入求解热路径。
- **MANAGE 并入 admin**：不存在独立的管理角色。admin 是唯一可授予的管理角色，作用域为
  库或目录（管理维度，见 acl-semantics.md §7）。
- 评审建议的五级角色维持**不采纳**：查看者=下载者=read、编辑者=内容管理员=edit、
  空间管理员=admin，仅为换算关系，不新增权限位。
- 下游口径不变：内容终判只产生 CE perm；管理判定只产生 `can_manage` 布尔。

---

## 1. 为什么先做这个决策

P2-03（搜索结果权限裁剪）、P2-06（移动前权限影响提示）、P2-07（标签权限）都要回答同一个
问题：**"某用户对某对象能做什么"以什么为口径？** 如果三处各自发明一套"角色"，就会在同一
权限语义上出现第二、第三份实现——而 AGENTS.md 的铁律是跨层语义只有一份真源，漂移在权限
系统里意味着安全漏洞。

所以先定死口径：**内容终判只有 CE perm 一份 + 目录 ACL 收紧**；角色只做授权与展示；
管理维度只有 `can_manage` 一个布尔判定。

---

## 2. CE 现有权限模型（内容维度唯一真源）

Seahub 的仓库/文件夹权限常量（`seahub/constants.py`）：

| 常量 | 值 | 含义 | CE 是否可用 |
|---|---|---|---|
| `PERMISSION_READ` | `r` | 读：浏览、搜索、下载 | 是 |
| `PERMISSION_READ_WRITE` | `rw` | 读写：读 + 上传/新建/编辑/重命名/移动/删除 | 是 |
| `PERMISSION_ADMIN` | `admin` | 库所有者/管理员：管理成员与权限 | 是 |
| `PERMISSION_PREVIEW` | `preview` | 仅网页预览，不可下载 | 否（Pro） |
| `PERMISSION_PREVIEW_EDIT` | `cloud-edit` | 仅网页预览+编辑，不可下载 | 否（Pro） |
| `PERMISSION_INVISIBLE` | `invisible` | 目录列举时整条剔除 | CloudFile dir_acl 扩展 |
| `CUSTOM_PERMISSION_PREFIX` | `custom*` | 自定义权限 | 否（Pro） |

`admin` 的真实形态（全部库级、无 path）：库 owner（`get_repo_owner`），或指定管理员
（`ExtraSharePermission` / `ExtraGroupsSharePermission` 的 `permission='admin'`），
统一经 `is_repo_admin()` 判定。目录级 admin 是管理维度的扩展（acl-semantics.md §7 V2）。

两条硬约束，见 [acl-semantics.md](acl-semantics.md)：

1. **CE 的库级权限是内容维度上限**；目录 ACL 只能收紧，绝不放宽。
2. dir_acl 取值构成内容链 `invisible < none < r < rw`，`preview`/`cloud-edit`/`custom-*`
   不在这条链上，只能被 `invisible`/`none` 一票否决。

---

## 3. 四角色 → CE perm 换算

| 角色 | 内容维度 | 管理维度 | 对应 CE | 说明 |
|---|---|---|---|---|
| Owner | `rw` | 是（库级天然） | owner | 另含删库/转让/改库属性 |
| admin | `rw` | 是（可授予，库或目录） | `ExtraSharePermission='admin'` | 分享/加减成员/改权限 |
| edit | `rw` | 否 | `rw` | 读 + 建/传/改/改名/移/删 |
| read | `r` | 否 | `r` | 浏览/搜索/下载/复制出 |

评审五级角色的换算（信息性，不落地）：查看者 = 下载者 = read；编辑者 = 内容管理员 =
edit；空间管理员 = admin。

---

## 4. 继承与优先级

1. **库级**：repo 共享权限（`r`/`rw`/`admin`）作用于整个库，是内容维度上限。
2. **目录级**：dir_acl 规则从根向下逐层求解，深层命中覆盖浅层；中间层无命中规则时继承
   最近祖先决定；**文件规则优先于目录规则**（acl-semantics.md §4.3）。
3. **默认**：全程无命中规则回落 CE 库级权限，与原生 CE 行为一致（acl-semantics.md §4.4）。
4. **收紧不变量**：内容终判 ⊆ native；管理维度独立判定，不参与收紧（acl-semantics.md §7.3）。

---

## 5. 决策理由

1. **复用 CE 是铁律。** 内容真源仍是 CE `r`/`rw`/`admin`，没有平行权限位。
2. **角色壳不进入求解。** Owner/admin/edit/read 是授权与展示层；求解只产 CE perm 与
   `can_manage` 布尔，C/Python 两端各一份实现、共享用例集，漂移面没有扩大。
3. **管理必须独立维度。** 目录级委托管理在内容收紧链上无法表达——给库级只有 `rw` 的
   用户授目录 admin，不是"放宽内容权限"，而是管理维度的新事实；独立成维度才不破坏
   "扩展只能收紧"。
4. **五级角色仍不采纳。** CE 没有"能看不能下载"（`preview` 是 Pro）、"能编辑不能移动"
   对应的内容位；这些不是当前交付范围，为它们新增内容位不值——留待能力位预设
   （acl-semantics.md §7 / V2 预留位）。

---

## 6. 对下游 P2-03 / P2-06 / P2-07 的口径

- **P2-03 权限裁剪**：搜索/自动补全/数量统计只按 `resolve(user, repo, path)` 的终判结果
  过滤，返回值只有 CE perm（`r`/`rw`/`admin`/`none`/`invisible`），**不产生角色名**。
- **P2-06 权限变化提示**：移动前后分别对源、目标计算"哪些主体还能读/写"，用 CE perm 差
  值表达（例如"N 名成员由 `rw` 降为不可访问"），**不引用角色名**。
- **P2-07 标签权限**：系统标签变更仅 admin 可用、用户标签编辑需 `rw` 及以上——此处
  admin 指 `is_repo_admin()`，与角色模型中的 admin 是同一概念。

---

## 7. 评审清单标注

| 条目 | 处置 |
|---|---|
| 五级角色（查看者/下载者/编辑者/内容管理员/空间管理员） | **不采纳** —— 采用四角色 Owner/admin/edit/read（2026-08-17 决策），换算见 §3 |
| 角色→能力映射表 | 不采纳为权限模型；保留为 UI 展示换算 |
| 角色级用例 | 删除（不进入 P2-02 用例集） |
| MANAGE 角色（后续方案） | **并入 admin**（2026-08-17 决策），管理维度见 acl-semantics.md §7 |

标签模型（系统/用户标签、只读/可编辑、锁形图标、折叠与点击行为）**保留**，其权限判定按
§6 P2-07 口径，用 CE 权限位表达。

<!-- generated-by: gsd-doc-writer -->
# CloudFile 目录级 ACL 语义规格

> **用途**：规定目录 ACL 的数据模型、求解算法、权限合并和入口一致性。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效规格；核心入口已有自动化矩阵验证，正文保留未完成的浏览器实操等边界。
> **边界**：CE 的库级权限是上限；CloudFile 只做本地、可收紧的目录终判；外部规则服务不得进入同步权限热路径。

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
| `path` | 规范化后的目录路径 |
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

```
resolve(user, repo_id, path, native):
    if not cf_enabled:            return native          # 开关关闭 = 零行为变化
    if native is None:            return None            # 原生就没权限，不必再看 CF

    path   = normalize(path)
    levels = ancestors(path)      # ['/', '/a', '/a/b'] —— 从根到自身，含自身

    decision = None
    for level in levels:                                 # 从根向下，深层覆盖浅层
        applicable = [rule for rule in rules_at(repo_id, level)
                      if rule.subject in subjects(user)
                      and (rule.inherit == 1 or level == path)]
        if not applicable:
            continue                                     # 该层无规则 → 继承上层决定
        decision = pick(applicable)

    if decision is None:          return native          # 全程无规则 → 原样返回
    return tighten(native, decision)
```

### 4.1 `pick` —— 同一层内的取舍

同一层可能命中多条规则。分两步：

1. **主体类型优先级**：`user` > `dept` > `group`。
   取存在规则的最高优先级类型，**忽略**较低优先级类型的规则。
2. **同类型内取最严**：按 §2 的全序取最小值。

> 第 1 步是对"同级多主体取最严"的必要修正。若不分主体类型一律取最严，
> 那么给"全员"群组挂一条 `r` 会让任何针对个人的 `rw` 显式授权失效，
> 显式授权将永远无法生效。分层之后，"取最严"仍然在真正等价的主体之间成立
> （比如一个人同时属于两个群组），而更具体的授权可以覆盖更宽泛的默认值。

### 4.2 `ancestors` 与 `inherit`

`ancestors('/a/b')` = `['/', '/a', '/a/b']`。

`inherit = 0` 的规则只在 `level == path` 时参与，也就是只作用于规则自身所在目录，
不影响其子目录。`inherit = 1`（默认）时规则向下贯穿。

注意循环是**从根向下**且每层覆盖前一层的 `decision`，因此
**最深的、有命中规则的那一层胜出**。中间层没有任何命中规则时，
沿用更浅层的决定（这就是"继承"）。

---

## 5. `tighten` —— 与原生权限合并

**安全不变量：扩展只能收紧，绝不能放宽。**
对任意 `(user, repo, path)`，最终权限必须 ⊆ 原生权限。

```
tighten(native, decision):
    if decision in ('invisible', 'none'):
        return None                       # 一票否决，与 native 类型无关

    if native in ('rw', 'r'):
        return min(native, decision)      # 按 §2 的全序
    if native == 'admin':
        return decision                   # admin 是最高权限，收紧到 decision
    # preview / cloud-edit / custom-* 不在全序链上：
    return native                         # 只能被 invisible/none 否决，否则原样保留
```

最后一条是刻意保守：这些权限与 `r` / `rw` 不可比（`preview` 能看不能下载，
`cloud-edit` 能编辑不能下载），强行排序会在某个方向上放宽权限。
一票否决保证了安全边界，其余情况保持原生行为。

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

已知缺口：seafdav 的目录列举与 GET 不经过 `check_permission_by_path`，
因此 `invisible` 在 **WebDAV 读路径上不生效**（写路径生效）。见
[BRANCHING.md](../BRANCHING.md) 与 compose README 的限制说明。

---

## 7. 开关

- Hub：`CF_ENABLE_DIR_ACL`（`seahub_settings.py`，由 compose 的 `.env` 注入）
- Server：`seafile.conf` 的 `[cloudfile] dir_acl_enabled`

两者都关闭时，三层都必须走原生代码路径，行为与同 SHA 的原生 CE 完全一致。
这是 P0 的核心验收项。

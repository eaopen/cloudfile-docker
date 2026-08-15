<!-- generated-by: gsd-doc-writer -->
# 统一写入生命周期契约

> **用途**：规定所有写入口共享的 PREPARE、COMMITTED、ABORTED 三相契约和错误语义。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：已实现、待整机验收；单元与跨语言契约测试已覆盖，`fileop-e2e.yml` 已存在但文档记录尚无成功跑次。
> **边界**：CE 写路径保留为生产者；CloudFile 新增统一 veto/事实扩展点；外部 provider 不得绕过同步终判或建立第二事实源。

CloudFile 的**写入扩展点**规格。本文件是**规范**：C、Go 两处实现和后续每一个
provider 都必须与它逐字一致。

配套文档：

- [EXTENSION-POINTS.md](EXTENSION-POINTS.md)：这个扩展点补的是缺口 1
- [文件协作与本地应用](features/file-collaboration.md)：锁、签入签出与 OnlyOffice 消费者
- [acl-semantics.md](acl-semantics.md)：路径规范化与子树包含语义的先例

配套用例集 [`fileop-cases.json`](fileop-cases.json) 是这份规格的可执行形式，
由 C 与 Go 两端测试共同加载：

```bash
cd cloudfile-server && ./tests/cf-fileop/run.sh
```
```bash
cd cloudfile-server/fileserver && go test ./... -run CfFileOp
```

改语义 = 同时改本文件、`fileop-cases.json` 和两处实现，缺一不可。

---

## 一、这个扩展点为什么必须先于文件锁存在

`register_file_op_hook()` 在 Hub 侧注册得了，但**上游没有任何地方调用它**；
server 侧的 `cf-ext` 只有权限、列举、子树三个**读侧**钩子。于是六个特性
（文件锁、签入签出、OnlyOffice 写回、文件属性、标签、移动重命名元数据跟随）
全都卡在同一件事上：**没有地方在写入发生前说"不行"，也没有地方在写入成功后
说"发生了什么"。**

先做锁再补钩子，会造出两套东西：锁的 veto 点和 `file_op` 的事件源各走各的，
而它们要覆盖的是同一批写入口。所以顺序固定为**先契约、后能力**。

---

## 二、三相语义

| 相 | 时机 | 能否否决 | 保证 |
|---|---|---:|---|
| `PREPARE` | 提交前，任何持久化写入之前 | **能** | 任一 provider 拒绝则整个操作终止，且尚未产生任何文件变更 |
| `COMMITTED` | 提交成功后 | 否 | 不可变事实。一次成功操作**恰好一次** |
| `ABORTED` | 操作失败后 | 否 | **尽力而为**，见下 |

### PREPARE 是同步 veto

语义与 `CfPermFunc` 的先例相同：串行执行全部 provider，**任何一个拒绝就终止**，
后续 provider 不再执行。拒绝必须带 `GError`，错误码进入调用方的返回码。

PREPARE **不预留任何资源**。它是一次纯判断：问"当前状态下这次写入允许吗"。
这条约束是 ABORTED 可以退化为尽力而为的前提。

### COMMITTED 恰好一次

一次成功的写入操作产生**一个** COMMITTED，不多不少：

- 批量操作（`batch_del_files`、`post_multi_files`、`move_multiple_files`）
  产生一个 COMMITTED，携带全部受影响路径，**不是每个文件一个**。
- 内部为了并发重试而重复执行的 `gen_new_commit`（`post_file` 的
  `SEAF_ERR_CONCURRENT_UPLOAD` 重试路径）只在最终成功那次发出。
- 失败的操作**永远不产生** COMMITTED。

> 为什么不把 COMMITTED 挂在 `gen_new_commit()` 上——它是 C 侧唯一的提交咽喉，
> 看起来是最省事的位置。因为它**只知道 root_id 和一句 desc**，不知道 operation，
> 也不知道路径。挂在那里得到的是"有个提交发生了"，而消费者要的是
> "谁把哪个文件怎么了"。从 desc 字符串反解操作类型是把人类可读文案变成协议，
> 上游改一次文案就全线失效。

### 嵌套是真的，而且是对的

有几处操作会在内部触发第二次写入，于是 provider 会看到嵌套的事件：

- 父目录不存在时 `revert-file` / `revert-dir` 先调 `mkdir_with_parents`。
- 虚拟库与 origin 之间的移动会先 `put_dirent_and_commit` 再 `del_file`。
- 每次提交后的 `merge_virtual_repo` 会在 origin 库上产生 `update-dir`。

这些**都不是重复计数**：每一条都对应一个真实的、独立的提交。provider 要按
`repo_id` + 路径去理解事件，不能假设"一次用户操作 = 一个 COMMITTED"。

### ABORTED 是尽力而为，provider 不得依赖它

**保证**：ABORTED 只在 PREPARE 已通过、且该操作最终没有成功时发出。
不会出现"PREPARE 没跑过却收到 ABORTED"。

**不保证**：进程崩溃、断电、`SIGKILL` 之后不会有 ABORTED。

所以任何需要"预留 → 释放"语义的 provider **必须自己带租约和超时**，
不能把 ABORTED 当成释放信号。文件锁正是这么设计的（心跳 + `lease_until` +
`hard_expire_at`，见 [文件协作与本地应用](features/file-collaboration.md)），
这不是巧合——**契约里做不到的保证，就不要让能力去依赖**。

ABORTED 的正当用途只有两个：资源回收（provider 自己在 PREPARE 里建的临时状态）
和可观测性（失败率指标）。

---

## 三、operation 词汇表

operation 是**稳定字符串**，不是枚举序号——它要跨 C、Go、RPC 和将来的 Python
consumer，序号在任何一处错位都是静默的语义错误。

| operation | 语义 | 目标 | 源 |
|---|---|---|---|
| `create-file` | 新建文件（含空文件、分块提交产生的新文件） | 文件路径 | — |
| `update-file` | 覆盖已存在的文件 | 文件路径 | — |
| `delete` | 删除文件或目录 | 一或多个路径 | — |
| `mkdir` | 新建目录（含逐级创建父目录） | 目录路径 | — |
| `rename` | 同目录内改名 | 新路径 | 旧路径 |
| `move` | 移动，可能跨库 | 目标路径 | 源路径 |
| `copy` | 复制，可能跨库 | 目标路径 | 源路径 |
| `revert-file` | 把文件恢复到历史版本 | 文件路径 | — |
| `revert-dir` | 把目录恢复到历史版本 | 目录路径 | — |
| `revert-repo` | 把整库恢复到某个提交 | `/` | — |
| `update-dir` | 直接把某个目录替换为指定 dir 对象 | 目录路径 | — |
| `upload-blocks` | 只上传 block、不产生提交 | 无路径 | — |
| `sync-update` | 同步客户端推送的分支更新 | `/` | — |

三条容易判错的归类：

1. **`copy` 的源是读、目标是写。** PREPARE 只针对目标；源侧的可读性由 ACL
   负责，不在这个扩展点里重判。但 `src_repo_id`/`src_path` 必须填——锁的
   "跨库移动含锁子树默认拒绝"需要它。
2. **`rename` 不是 `move` 的特例。** Pro 兼容语义里两者对锁的处理不同
   （同库改名保持锁跟随，跨库移动拒绝），归成一类就没法区分。
3. **分块提交的 create/update 是意图，不是核实过的存在性。** `commit_file_blocks`
   （C 与 Go 两侧）按调用方的 `replace_existed` 标志报 `update-file` 或
   `create-file`，**没有**去查这个路径当前是否真有文件——那要在每次分块上传时
   多做一次目录查找，而没有消费者需要这个区分：锁对两者一视同仁，审计的事实来自
   `repo-update`。`post_file` / `put_file` 两个入口不受影响，它们本来就无歧义。
4. **`upload-blocks` 没有路径。** 它只把 block 写进对象库，不进入任何目录树。
   provider 要么忽略它，要么只按配额/病毒扫描这类与路径无关的规则判断。
   **锁 provider 必须忽略它**——没有路径就没有锁对象，在这里拒绝等于随机拒绝。
   真正的终判发生在随后的 `create-file` / `update-file`。

`sync-update` 是唯一一个目标路径为 `/` 的写操作：同步协议交换的是 commit、
fs 对象和 block，**不带路径**，所以没有逐文件的授权点。这与 ACL 当年面对的
是同一个事实（见 [acl-semantics.md](acl-semantics.md) 开头），处理方式也一样：
能问的只有库级问题。**这是本契约已知的、结构性的粗粒度点，不是首版限制。**

---

## 四、上下文字段

```text
CfFileOp {
  op                 operation 词汇表中的一个
  repo_id            目标库
  dir                父目录；对 mkdir / revert-dir / update-dir 就是对象本身
  name               dir 下的条目名；为空表示 dir 就是对象
  names              批量操作的全部条目名；单对象操作为空
  src_repo_id        copy / move 的源库；其余为空
  src_dir            源父目录
  src_name           源条目名
  src_names          批量 move 的全部源条目名
  user               操作者身份（Seafile 身份，不是邮箱，见下）
  client             会话/客户端标识，可空
  expect_commit_id   调用方声明的源版本，可空
  commit_id          结果提交 ID —— 仅 COMMITTED
  file_id            结果内容对象 ID —— 仅 COMMITTED，且仅单文件操作
}
```

**存的是"目录 + 条目名"而不是拼好的路径**，因为调用点手里就是这两截，而拼接和
规范化要花一次分配。分配发生在 dispatcher 里、`cf_fileop_active()` 之后，
所以没有 provider 时一次都不发生——这就是"基线零成本"落到实处的地方。
provider 拿完整路径用 `cf_fileop_subject_path()` / `cf_fileop_subject_paths()`
和 `cf_fileop_source_paths()`。

**`src_*` 对 move 和 rename 不是参考信息。** 一次移动写的是两端：条目从源目录
消失。所以源上有锁必须拒绝，不只是目标上有锁才拒绝。`copy` 是唯一源侧只读的，
它填 `src_*` 是为了让锁能区分同库和跨库。

**`user` 是身份不是邮箱。** Seafile 14 把账号主键（`<hex>@auth.local`）与登录
邮箱拆开了，而写入口拿到的是身份。这一条已经在 ACL 上付过一次代价：按邮箱下发
的规则永远匹配不上，且不报错、不记日志、接口返回 200
（当前状态见[扩展能力矩阵](feature-matrix.md)）。provider 若要与人类可读的邮箱比较，
必须自己经 `cloudfile_ext/identity.py` 的映射，**不能假设这个字段是邮箱**。

**`expect_commit_id` 在 P0.5 只做透传。** C 的 `put_file` / `update_dir` 已有
`head_id` 参数，填进来即可；其余入口为空。乐观并发的终判（源版本 CAS）属于
P1，本契约只负责把这个值送到 provider 面前。

**`client` 在 P0.5 恒为空。** 会话与 generation 是 P1 的概念，字段先留好，
避免 P1 再改一次契约签名。

### 路径规范化

与 ACL 逐字相同（[acl-semantics.md](acl-semantics.md) §1）：

1. 空路径视为 `/`。
2. 统一 `/` 分隔，折叠连续分隔符。
3. 保证前导 `/`。
4. 去掉尾部 `/`，根路径保持单个 `/`。
5. **不做** Unicode 归一化、不做大小写折叠——Seafile 的路径是字节敏感的。

**不复用第二套实现**：规范化只有一份，`common/cf-path.c` 的
`cf_path_normalize()` / `cf_path_join()`。它原本长在 `cf-acl-resolve.c` 里，
这次下沉到基线，ACL 侧留一层薄转发（既有用例逐字未改）。理由和身份解析下沉
（当前状态见[扩展能力矩阵](feature-matrix.md)）一样：ACL 按路径存规则、锁按路径存租约，
两者必须逐字节一致，否则 `/a/b` 的规则和 `/a/b/` 的锁说的是两个对象；
而且留在能力里会让基线 seam 在运行时 import 能力，并让 ACL 的开关决定路径
能不能被规范化。

**Go 不做规范化**，它把原样的 dir/name 交给 RPC，由 C 完成。两处各写一遍 =
两处会漂移，而在权限系统里漂移意味着漏洞。

---

## 五、谁在什么位置产生这些事件

```text
Seahub / REST ──┐
seafdav ────────┼──→ seafile_api RPC ──→ common/rpc-service.c ──┐
桌面客户端(锁API)─┘                                              │
                                                                ▼
                                              server/repo-op.c  ← 权威产生点
                                                                ▲
Go fileserver ──→ fileserver/cf_fileop.go ──RPC──→ cf_fileop_* ─┘
（上传/更新/分块/同步）
```

| 层 | 角色 | 理由 |
|---|---|---|
| `server/repo-op.c` | **唯一权威产生点** | 所有 C 写入最终都经过这里 |
| `common/rpc-service.c` | 只暴露 RPC，不产生事件 | 它只覆盖 Seahub/REST 进来的调用 |
| `fileserver/cf_fileop.go` | 经 RPC 问 C，不做第二份判断 | 同 `cf_ext.go` 的先例 |
| seafdav | 不重复实现校验（见下） | 写路径全部走 `seafile_api.*` → RPC → `repo-op.c`；只补拒绝状态码 423 翻译 |
| Hub `register_file_op_hook` | 只补 IP / User-Agent / session | 不是文件事实的主路径 |

### 为什么 C 的 seam 放 `repo-op.c` 而不是 `rpc-service.c`

`common/rpc-service.c` 已经在上游改动登记清单里，放那儿边际成本为零，很诱人。
但它**只覆盖经 RPC 进来的调用**：`server/upload-file.c`（`go_fileserver`
关闭时的 C 文件服务）、虚拟库合并、`copy-mgr` 的异步复制都直接调用
`seaf_repo_manager_*`，从旁边绕过去。

**终判点不能有绕行路。** 一个漏掉的入口不会报错、不会记日志，只会在某天变成
"锁明明在，文件却被改了"。为此接受上游改动从 33 涨到 35。

### 为什么 seafdav 不重复实现校验（只补状态码翻译）

`patches/seafdav/0001` 的注释里已经写明："every write path in this file already
goes through check_permission_by_path"——seafdav 的写全部是 `seafile_api.post_file`
这类调用，落在 `repo-op.c` 上。再写一份 Python 校验会得到**第二个真值**，
而它与 C 的差异只会在生产上暴露。WebDAV 的验收因此是**验证它继承了 C 的结论**，
不是验证它自己实现对了。

唯一需要补的是一层**状态码翻译**：上游 seafdav 把所有 `SearpcError` 都翻成
500，于是 C 的锁拒绝到了 WebDAV 客户端会变成"服务坏了"。`patches/seafdav/0002`
在 write 路径上把 `CF_ERR_FILE_LOCKED`(600) 映射成 423 Locked，其余仍回落到
500——它**不判断该不该锁**，只把 C 的结论用正确的 HTTP 码说出来。

### Go 的成本与那个刻意不做的缓存

Go fileserver 自己完成分块、写对象、生成提交、更新分支，**整条路不经过 C**，
所以它必须有自己的 seam。它不重新实现判断，而是经 RPC 问 C。

`cf_ext.go` 的先例是"TTL 缓存 + RPC 失败视为放行"，因为它问的是一个变化很慢的
库级问题。**这里刻意不那样做**：缓存"当前没有 provider"这个否定结论，会在
运维打开某个能力并重启 seaf-server 之后留下一个 TTL 长度的窗口，窗口里所有
上传都绕过锁。一个会自己消失的安全漏洞是最难排查的那种。

所以 Go **每次写操作都调一次 `cf_fileop_prepare`**，判决从不缓存。缓存的只有
"我们处在哪个世界"，而且只用来决定**失败模式**：

| 状态 | 含义 | RPC 打不通时 |
|---|---|---|
| `unsupported` | 没有这个 RPC，即上游 seaf-server | 完全跳过，零成本 |
| `inactive` | 有 RPC，没有 provider 注册 | **放行** |
| `active` | 有 provider 注册 | **拒绝**（503） |

`inactive` 放行不是偷懒：那时没有任何东西可执行，而让基线部署在 seaf-server
抖一下的时候上传失败，是对原生 CE 的回归。`active` 拒绝则是第三条铁律——
读不到规则时 fail closed。

`unsupported` 每 300 秒重探一次，而不是缓存到进程结束：Go fileserver 可能比
seaf-server 先起来，一次输掉的启动竞争不该把 seam 关掉一整个进程生命周期。

代价说清楚：CloudFile 基线（有 RPC、无 provider）上，每次写多一次 unix socket
往返，C 侧只读一个全局布尔就返回。**它不是数据库查询**，基线门禁
"开关全关不增加数据库查询"仍然成立；但它确实不是零成本，这里写明而不是藏起来。

---

## 六、错误码

PREPARE 拒绝时 provider 填 `GError`。契约定义三个域内错误码，其余按
`SEAF_ERR_GENERAL` 处理：

| 错误码 | 值 | 含义 | HTTP | 谁会用 |
|---|---:|---|---:|---|
| `CF_ERR_FILE_LOCKED` | 600 | 对象被其他会话锁定 | 423 | 文件锁 |
| `CF_ERR_VERSION_MISMATCH` | 601 | 源版本与调用方声明的不一致 | 409 | 文件锁、OnlyOffice |
| `SEAF_ERR_GENERAL` | 500 | 其余拒绝 | 403 | 任意 provider |

两个新码定义在 `common/cf-fileop.h`，从 600 起，**不加进
`include/seafile-error.h`**——那是一个我们至今没改过的上游文件，而每多改一个
上游文件都要在每次同步时再付一次。上游停在 522，600 给它留足了空间。
它们和上游的码进同一个 `SEAFILE_DOMAIN`，C 的 searpc server 照常把它编进
`err_code`。Python 侧上游 `pysearpc` 的 `_fret_*` 却只保留 `err_msg`、丢掉
`err_code`——`cloudfile-server/python/seafile/rpcclient.py` 在导入期把它们包成
`SearpcError(msg, code)`，让 600 能一路传到 Seahub/WebDAV 并映射成 423；这是
本契约"跨协议拒绝统一"那条验收的一半。

**错误消息会到达终端用户**，所以它必须能解释"为什么不行"（谁持有锁、还剩多久），
不能只是 `Permission denied`。这是从 ACL 学到的：一个不解释原因的拒绝会变成
支持工单，而工单里没有任何可用于定位的信息。

调用方**不得**把 PREPARE 的拒绝翻译成"文件不存在"。存在性泄露的方向在这里是
反的：隐藏一个被锁定的文件不会提高安全性，只会让用户以为文件丢了。

---

## 七、铁律

**1. 没有 provider 注册 = 原生 CE 行为。**

`cf_fileop_active()` 为假时，每个调用点都是一次全局布尔读取后立即返回。
不构造上下文、不规范化路径、不查数据库、不改变任何返回码。

**2. PREPARE 只能拒绝，不能改写。**

provider 拿到的上下文是**只读**的。它不能改路径、不能改 operation、不能把
`update-file` 变成 `create-file`。能改写就意味着两个 provider 的顺序会决定结果，
而顺序不是任何人有意设计过的东西。

**3. 读不出规则时 fail closed。**

沿用 `cf-ext` 的第三条铁律。注意区分"没有规则"（放行）与"读不出规则"（拒绝）。

**4. COMMITTED 不能否决，也不能抛异常打断调用方。**

它在提交之后发出，那时文件已经变了。一个在 COMMITTED 里失败的 provider 只能
记日志，不能让已经成功的写入返回失败——那会让客户端重试一次已经生效的操作。

---

## 七之二、门禁用的假 provider

`cloudfile-server/common/cf-fileop-test.c`。它记 journal，并拒绝任何路径里含有
标记组件的操作。

**为什么需要它**：退出条件写的是"锁 provider 尚未实现时，假 provider 已能在所有
写入口统一 veto"。没有可注册的东西，seam 通了的唯一证据就是"没有出现症状"——
而目录 ACL 已经证明那不值钱：62 项 C 检查和 87 项 Python 检查全绿，而存进去的
规则永远匹配不上、接口还返回 200。

它也不只在 P1 之前有用：锁的拒绝理由取决于锁的状态，那让它成为一个很差的
"这个调用点到底有没有被走到"的探针。

**为什么用运行时开关而不是编译期剔除**：编译期剔除意味着门禁跑的镜像不是发出去的
那个镜像，而这个项目已经为此付过一次代价——一份手写的 `seahub_settings.py`
fixture 通过了测试，而真正生成的文件抛 `NameError`、把整个文件的 CloudFile 配置
一起丢掉，服务看起来还是正常起来的。**测发出去的那个。**

代价是一个绝不能在生产里打开的开关。它：

- 默认关闭，只有 `[cloudfile] fileop_test_provider_enabled = true` 才注册；
- **不在 `CF_ENABLE_*` 清单里**——那份清单里的每一项都是运维可以合理打开的产品
  能力，这个不是，而且列进去会让它出现在管理页和 features 接口上；
- 注册时打一条明说"不要在生产里跑"的警告，那条警告同时是门禁用来证明
  `cf_ext_init()` 真的走到这里的唯一证据（配置写对了但代码没注册是完全静默的）。

**标记按路径组件比较**（`cf_path_has_component`），不是子串也不是前缀：子串会让
标记 `secret` 命中 `notes-secret.txt`，于是一条只针对某个对象的规则悄悄覆盖了
别的；前缀则根本没法播种，因为播种要先创建那个被标记的目录，而创建正是被测操作
之一。空标记不匹配任何东西——那是"没配标记"的写法，绝不能退化成"匹配一切"。

配置项（`[cloudfile]` 段，由 `CF_FILEOP_TEST_*` 生成）：

| 键 | 含义 |
|---|---|
| `fileop_test_provider_enabled` | 非 true 则完全不注册 |
| `fileop_test_refuse_token` | 拒绝含该组件的路径；**显式留空 = 只观察不拒绝** |
| `fileop_test_journal` | 事件追加到这个绝对路径；留空则不记 |

journal 一行一个事件，字段固定顺序、空值写 `-`：

```text
<phase> <op> <repo_id> <subjects> <sources> <user> <commit_id>
```

字段永不消失是有意的：一个"空值就不写"的格式会让缺字段读成移位字段。

## 八、验收

门禁：`.github/workflows/fileop-e2e.yml`、`tools/verify-local.sh cap fileop`、
矩阵 `tests/e2e/fileop_matrix.py`（两阶段）。

### 8.1 全入口统一 veto

用第七之二节那个假 provider，逐入口确认拒绝确实发生且没有产生提交：

| 入口 | 覆盖的 operation |
|---|---|
| Seahub REST | create-file、update-file、delete、mkdir、rename、move、copy、revert-file、revert-dir |
| WebDAV | create-file、update-file、delete、mkdir、move |
| Go fileserver 上传 | create-file、update-file、upload-blocks |
| Go fileserver 分块提交 | create-file、update-file |
| 桌面同步 | sync-update |
| 目录替换 | update-dir |

### 8.2 事实的唯一性

| 场景 | 预期 |
|---|---|
| 单文件上传成功 | 恰好一个 COMMITTED，`op=create-file` |
| 覆盖已有文件 | 恰好一个 COMMITTED，`op=update-file` |
| 并发冲突重试后成功 | 仍然只有一个 COMMITTED |
| 批量删除 5 个文件 | 一个 COMMITTED，`paths` 长度为 5 |
| 上传失败（配额/校验） | 零个 COMMITTED |
| PREPARE 拒绝 | 零个 COMMITTED，零个 ABORTED |
| PREPARE 通过但提交失败 | 零个 COMMITTED，一个 ABORTED |

### 8.3 三层一致

同一份 `fileop-cases.json` 分别驱动 C 与 Go 的 operation 归类、路径规范化和
组件匹配，两端结论必须逐条相同。WebDAV 不单独验证归类（它经 C），但要验证
**拒绝确实传导到了 WebDAV 客户端，而且不是以 500 的形式**。

后半句是重点。上游 CE 的锁接口就是这么坏的：`check_file_lock()` 恒返回 false，
随后调用不存在的 `seafile_api.lock_file` 抛 `AttributeError`，代码只捕获
`SearpcError`，于是普通 rw 用户就能触发 500（旧问题记录见
[历史功能清单](history/FEATURES-旧版.md)第 6 条）。被吞成 500 的拒绝对用户是
“服务坏了”，对监控是噪声，对排查毫无信息。

### 8.4 基线关闭

- 无 provider 注册时，C 的调用点不构造上下文（用计数器断言构造次数为 0）。
- 原生 CE 冒烟 12/12 不变。
- Go `go build ./... && go vet ./...` 干净。
- **整机**：关掉 provider 重启后再跑一遍冒烟（建库、建目录、上传、删库，全是
  写操作），journal 一行都不该长。这是"没有 provider 注册 = 原生 CE 行为"这条
  铁律在整机上的形式——比"没看到异常"强得多。

### 8.5 为什么矩阵必须两个阶段

- **夹具只能在观察模式下建。** 拒绝一开，创建被标记的路径本身就被拒，而那恰好
  是被测操作之一。
- **反向对照必须跑在同一个栈上。** 一个把所有写入都拒掉的 provider——或者一个
  坏掉的服务——会让"每个入口都拒绝"平凡成立。没有对照，这份矩阵证明的是服务坏了。
- **重启这一步本身就是被测对象。** 配置每次启动重写（`write_cloudfile_config`），
  改了 `.env` 却不生效是这套部署踩过的坑。

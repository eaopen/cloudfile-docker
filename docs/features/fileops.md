<!-- generated-by: gsd-doc-writer -->
# 复制/移动统一预检查、权限变化提示、幂等与失败清单（P2-06）

> **用途**：把评审清单「复制」「移动」的批量操作流程（预检查—确认—异步执行—结果报告）
> 落到 CloudFile 的 Hub API 层，并说明与 CE 原生复制/移动的边界。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：已实现、待整机验收；纯策略单测本地可跑，容器 E2E 由
> `review-copy-e2e.yml` / `review-move-e2e.yml` 在开启 `CF_ENABLE_FILEOPS` 时执行。
> **边界**：只改 Hub API（影子端点）；写入本身仍走 `seafile_api.copy_file` / `move_file`
> → repo-op.c，权限终判仍是 CE perm（`r`/`rw`/`admin`），见
> [roles-semantics.md](../roles-semantics.md)。

## 一、为什么影子端点而不是改上游

复制/移动的原生入口有三处：单对象 `api2/repos/{repo}/fileops/{copy,move}/`（旧
`OpCopyView`/`OpMoveView`）、现代前端的批量 `v2.1/repos/{sync,async}-batch-{copy,move}-item/`、
以及 `v2.1/copy-move-task/`。评审清单的可执行契约（[review-copy-cases.json](../review-copy-cases.json)、
[review-move-cases.json](../review-move-cases.json)）逐字驱动的是第一个入口，且带的是
`operation + src_repo_id + dst_repo_id + dirent_type` 的 JSON 载荷。

因此 P2-06 用既有的「影子端点」机制（`seahub/utils/rooturl.py` 把
`cloudfile_ext.urls` 前置到 Seahub 自身 pattern 之前，见
[EXTENSION-POINTS.md](../EXTENSION-POINTS.md) 缺口 3）把这两个 URL 换成
`cloudfile_ext/fileops/` 的实现，**零上游改动**：

- 请求不是该 JSON 契约（即旧 UI 的 form 形态）时，逐字委托回上游视图；
- `CF_ENABLE_FILEOPS` 关闭时不注册任何路由，两个 URL 完全由上游处理。

## 二、统一预检查

`evaluate()` 先做整请求级否决，再把请求里的每个对象拆成「可执行」与「失败」两份：

| 检查 | 级别 | 失败时 |
|---|---|---|
| 来源权限：复制需读（`r`/`rw`/`admin`），移动需写（`rw`/`admin`） | 整请求 | 403 |
| 目标权限：需 `rw`/`admin`（新建权限） | 整请求 | 403 |
| 跨空间移动：`owner(src) != owner(dst)` 且非源库 admin | 整请求 | 403 |
| 循环/退化移动：移入自身或自己的子树，或源目录=目标目录 | 整请求 | 400 |
| 对象数量 `CF_FILEOP_MAX_ITEM_COUNT` | 整请求 | 400 |
| 单次总大小 `CF_FILEOP_MAX_BATCH_SIZE` | 整请求 | 400 |
| 配额（复制，或跨 owner 移动） | 整请求 | 443 |
| 单文件大小 `CF_FILEOP_MAX_FILE_SIZE` | 逐项 | 进失败清单 |
| 文件夹层级 `CF_FILEOP_MAX_FOLDER_DEPTH` | 逐项 | 进失败清单 |
| 同名冲突（策略 `skip` 时） | 逐项 | 进失败清单 |
| 对象不存在 | 逐项 | 进失败清单 |

同名冲突策略：`rename`（默认，保留两者，自动加 `(n)`）、`skip`（跳过并进失败清单）、
`overwrite`（仅移动支持，`replace=True`；复制在 CE 无 overwrite 语义，请求
`overwrite` 会被拒）。默认 `rename` 正是「绝不静默覆盖」这条验收的落点。

所有限制都以 `0 = 无限` 表示，因此只开开关、不调任何限制，行为仍与原生 CE 一致。

## 三、移动权限变化提示

移动确认需要提示「移动后继承目标目录权限，N 名成员可能失去访问」。`evaluate()`
对移动返回 `affected_members`：枚举源库的共享成员（用户 + 组成员），用 C 侧权威
`seafile_api.check_permission_by_path` 分别求该成员在**源父目录**与**目标父目录**的
有效权限，统计「现在可读、移动后不可读」的人数。口径只表达 CE perm 差值，不引用
角色名（[roles-semantics.md](../roles-semantics.md) §6 P2-06）。

## 四、任务 ID 幂等

幂等键 = `sha256(username | operation | src_repo | src_parent | 排序后的源名 |
dst_repo | dst_parent)`，存进 `cf_fileop_task`（seafile-db，见
`cloudfile-server/scripts/sql/*/cloudfile.sql`）。提交时先 `claim()`（对
`(username, idempotency_key)` 唯一索引 `get_or_create`），**拿到已存在行就返回原
task_id、不再调用 `seafile_api`**——重复点击不会产生第二份副本。只有
`created=True` 的那次才真正发起 copy/move。

## 五、失败清单

预检查后 `failures` 是一个逐项列表 `[{name, reason}]`，`reason` 取值见
`cloudfile_ext/fileops/policy.py`。全部失败时不创建任务、直接返回清单；部分失败时
其余对象照常执行，清单随 `task_id` 一起返回。执行期失败（`seafile_api` 抛错）把任务
标为 `failed`，不静默吞掉。

## 六、开关与配置

| 项 | 默认 | 说明 |
|---|---|---|
| `CF_ENABLE_FILEOPS` | false | 总开关，关闭 = 原生 CE |
| `CF_FILEOP_MAX_FILE_SIZE` | 0 | 单文件大小上限（字节），逐项 |
| `CF_FILEOP_MAX_FOLDER_DEPTH` | 0 | 文件夹层级上限，逐项 |
| `CF_FILEOP_MAX_ITEM_COUNT` | 0 | 单批对象数上限，整请求 |
| `CF_FILEOP_MAX_BATCH_SIZE` | 0 | 单批总大小上限（字节），整请求 |

## 七、验证与边界

- **单元**：`cloudfile-hub/cloudfile_ext/fileops/tests/test_policy.py`（纯策略，本地可跑）。
- **容器 E2E**：`review_copy_matrix.py` / `review_move_matrix.py`（开启
  `CF_ENABLE_FILEOPS`），由 `review-copy-e2e.yml` / `review-move-e2e.yml` 执行。
- **未覆盖**：浏览器里的移动确认框（权限变化提示的 UI）仍待前端套件；现代前端
  批量入口 `v2.1/repos/{sync,async}-batch-{copy,move}-item/` 未接本契约——本能力只
  让评审契约指向的入口转绿，把同一预检查接到批量入口是后续工作，复用同一
  `service.evaluate()`/`submit()` 即可。

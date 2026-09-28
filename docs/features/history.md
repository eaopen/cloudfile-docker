# 操作历史：文件/文件夹历史增强（P2-10）

> **用途**：说明评审清单「操作历史」模块的 API 落地面（review-history-cases.json
> 的 history-002/003/004/006/007）。实现是**加性参数**：不传任何新参数时，
> `file/history` 与 `repo/history` 的行为与 Seafile CE 完全一致，不需要开关。
> **适用版本**：CloudFile `dev`，Seafile CE 14 参考基线。
> **状态**：验证中；容器 E2E 由
> `./tools/verify-local.sh cap review-history` 运行
> [`review_history_matrix.py`](../../tests/e2e/review_history_matrix.py)，
> 2026-08-20 于 dev 全量镜像复验 api 7/7 通过（history-001～007）。

## 范围

评审清单「文件历史支持来源/搜索/筛选/分页/详情、文件夹历史直属下一级与
仅当前文件夹」共 7 条。CE 原生已绿：history-001（修订列表含创建人，即评审口径的
「来源」）与 history-005（修订详情含 ctime 等元数据）。P2-10 补绿 5 条：

| 用例 | 接口 | 语义 |
|---|---|---|
| history-002 搜索 | `GET /api2/repos/{repo_id}/file/history/?p=…&q=…` | `q` 对提交 desc 与创建人做不区分大小写子串匹配，只返回命中的修订 |
| history-003 筛选 | 同上传参 `operator=`（别名 `source=`） | 按创建人邮箱精确过滤。协议级来源（Web/桌面/移动）不在提交对象上，Hub 无法细分，`source` 以提交创建人近似——与 audit 的既有口径一致 |
| history-004 分页 | 同上传参 `page=`/`per_page=` | 过滤后分页，`per_page+1` 前瞻返回 `page_next`；页间不重叠、并集完整 |
| history-006 直属下一级 | `GET /api2/repos/{repo_id}/history/?path=/docs` | 只返回改动到该文件夹自身或其**直属子级**（一层以内）的提交，不递归更深层 |
| history-007 仅当前文件夹 | 同上传参 `current_folder_only=1` | 连直属子级也排除，只保留文件夹自身改动（新建/删除/改名）的提交 |

实现位置：`seahub/api2/views.py` 的 `FileHistory.get()` 与 `RepoHistory.get()`，
以及新增的 `_commit_touches_folder()` 辅助函数（每个提交与其父提交 diff，
按改动路径深度判定范围）。该文件是已登记的上游改动文件，新增改动块不需要更新
`docs/upstream-patches/cloudfile-hub.txt`。

## 语义细节

- 文件夹范围判定：diff 条目路径去尾 `/` 后，等于 `path` → 文件夹自身；
  以 `path/` 开头且剩余部分不含 `/` → 直属子级（默认模式计入）；
  剩余部分含 `/` → 更深层，两种模式都不计。
- 重命名（`mov`）同时检查旧路径 `name` 与新路径 `new_name`：移入或移出当前
  范围都算命中。
- 分页与范围的关系：`repo/history` 先按 repo 提交流分页，再按范围过滤——
  文件夹历史的分页不在评审用例内，`page_next` 仍是 repo 级前瞻。
- 全部为可选参数；CE 前端不传参，行为逐字节不变（仅响应多一个 `page_next` 键，
  对 CE 调用方无害）。

## 验证

```bash
# 起栈后（默认 .env，无开关）：
python3 tests/e2e/review_history_matrix.py --url https://127.0.0.1 --insecure \
    --admin admin@example.com --admin-password xxx
```

场景与期望：admin 建 f.txt 两版、/docs 及 /docs/a.txt、/docs/sub、/docs/sub/b.txt，
rw 用户再改 f.txt 一版。repo 提交 7 条，`path=/docs` 默认范围 3 条（/docs、
a.txt、sub），`current_folder_only=1` 1 条（/docs 自身）。

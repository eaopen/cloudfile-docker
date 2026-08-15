# 评审清单 9 模块用例集（P2-02）

> **用途**：把评审清单 `couldfile_review20260814.md` 的树/图标/复制/移动/标签/搜索/
> 操作历史/回收站/外部分享九个模块，从"设计描述"转成机器可读、可计数的用例，并给每个
> 模块配一套可执行的 E2E 门禁。
> **状态**：契约先行（先红后绿）。当前只定义"要测什么"，P2-03/P2-06/P2-07 再把它做成绿。
> **权限口径**：沿用 CE perm（`r`/`rw`/`admin`），五级角色不落地，见
> [roles-semantics.md](roles-semantics.md)。

---

## 1. 三元组

每个模块一套，照搬目录 ACL 的 cases.json + matrix.py + e2e.yml 结构：

| 层 | 文件 | 作用 |
|---|---|---|
| 用例集 | `docs/review-<模块>-cases.json` | 机器可读、可计数的用例契约（本目录 9 份） |
| 矩阵 | `tests/e2e/review_<模块>_matrix.py` | 起栈后按 HTTP 断言 api 通道用例 |
| 门禁 | `.github/workflows/review-<模块>-e2e.yml` | 构建镜像 + 跑矩阵的 CI job |

公共的 HTTP 装配（请求/token/建用户/建库/共享/上传/用例装载与计数）抽在
`tests/e2e/review_harness.py`，九个矩阵共享，避免九份重复样板。

## 2. 用例 schema

每个 `-cases.json`：

```json
{
  "version": 1,
  "module": "copy",
  "title": "复制",
  "review": "couldfile_review20260814.md 二、核心功能设计·复制 / 三、复制与移动流程",
  "comment": "channel 与 perm 口径说明",
  "cases": [
    { "id": "copy-001", "name": "copy requires source read permission",
      "review": "校验来源读取/下载权限", "channel": "api", "perm": "none",
      "expect": "copying from a source the user cannot read is rejected (403)" }
  ]
}
```

字段含义：

- `id`：全局唯一，前缀 = 模块名。
- `channel`：`api` = 可由 HTTP 矩阵断言；`ui` = 浏览器交互，API 矩阵报告为
  skipped，留给未来的浏览器套件。
- `perm`：该用例里被操作主体持有的 CE 权限位（`r`/`rw`/`admin`/`none`/`n/a`）。
  五级角色不落地，因此不存在角色级用例。
- `expect`：单行的通过判据。评审里"部分满足"的条目在这里被拆成**独立的通过/失败项**。

## 3. 模块与用例计数

| 模块 | api | ui | 合计 |
|---|---:|---:|---:|
| 树结构 tree | 1 | 3 | 4 |
| 图标视图 icon | 0 | 5 | 5 |
| 复制 copy | 7 | 0 | 7 |
| 移动 move | 7 | 0 | 7 |
| 标签 tags | 5 | 4 | 9 |
| 搜索 search | 7 | 2 | 9 |
| 操作历史 history | 7 | 0 | 7 |
| 回收站 recycle | 3 | 1 | 4 |
| 外部分享 share | 3 | 1 | 4 |
| **合计** | **40** | **16** | **56** |

## 4. 验证与运行

**先红后绿的"红"现在就能验证**——校验 schema 与计数（不需要容器）：

```bash
python3 tools/validate-review-cases.py
```

**"绿"要等实现**——起栈后逐模块跑矩阵（以 copy 为例）：

```bash
python3 tests/e2e/review_copy_matrix.py --url https://127.0.0.1 --insecure \
    --admin me@example.com --admin-password xxx
```

CI 门禁在 `.github/workflows/review-<模块>-e2e.yml`。当前为契约期，矩阵对
CE 已原生支持的部分应绿（如复制"来源可读+目标可写"、标签"创建需 rw"、文件修订历史），
对评审新要求应红（如权限变化提示、回收站对普通用户拒绝、分享开关关闭）。这条红/绿
边界就是 P2-03/P2-06/P2-07 的施工清单。

P2-07 已把标签模块的 api 用例（tags-001～tags-005）做成绿：系统标签仅 `admin`
可写、用户标签 `rw` 及以上可编辑、批量加标签受 `CF_TAG_BATCH_LIMIT` 上限，实现见
[features/tags.md](features/tags.md) 与 [`review_tags_matrix.py`](../tests/e2e/review_tags_matrix.py)。
标签模块的锁形图标、折叠展示与「点击不弹关联列表」仍为浏览器用例（channel: `ui`）。

P2-08 补齐评审清单「审计」段的可验收点：查询/导出接口按时间/操作人/类型/对象/
来源/结果/路径筛选，`source`/`result`/`before`/`after` 作为一等字段返回，标签增删、
改名与系统标签变化经 `cf_audit_event` 记录前后值并可导出 CSV，实现见
[features/audit.md](features/audit.md) 与 [`audit_matrix.py`](../tests/e2e/audit_matrix.py)。
文件提交变更的协议级来源（Web/桌面/移动）仍以 `commit` 呈现，需 seafevents 改动才能细分。

P2-06 已把复制/移动模块的 api 用例（copy-001～copy-007、move-001～move-007）做成绿：
开启 `CF_ENABLE_FILEOPS` 后 `fileops/copy` 与 `fileops/move` 被影子成统一预检查——权限
否定（来源/目标）走目录 ACL 收紧、跨 owner 移动要求源库 admin、移动返回
`affected_members`、循环移动 400、同名冲突默认 rename、`cf_fileop_task` 幂等去重、大小/
层级逐项进失败清单、配额 443。实现见 [features/fileops.md](features/fileops.md) 与
[`review_copy_matrix.py`](../tests/e2e/review_copy_matrix.py)、
[`review_move_matrix.py`](../tests/e2e/review_move_matrix.py)。移动确认框的 UI 提示
与 v2.1 批量入口仍是后续工作。

P2-05 已把树结构/移动模块里「收藏跟随对象」这条做成绿：开启 `CF_ENABLE_FAVORITES_ID`
后收藏身份改为 `(email, org_id, obj_id)`，移动/重命名不再靠 `repo_id + path` 改写去追，
旧 path 记录经 `manage.py backfill_starred_obj_ids` 无损回填。实现见
[features/favorites.md](features/favorites.md)；开关关闭时保持原生 CE 行为。

## 5. 与既有能力的边界

复制/移动与 `fileop`（写生命周期）、标签与 `metadata`、搜索与 `search`、
操作历史与 `audit` 有重叠。本用例集只覆盖**评审清单新增的可验收点**，不与既有
能力矩阵重复断言同一条语义；重叠处按评审要求补"权限/隐藏/开关"这些既有矩阵没盖住的边。

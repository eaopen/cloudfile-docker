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
| 移动 move | 8 | 0 | 8 |
| 标签 tags | 5 | 4 | 9 |
| 搜索 search | 7 | 2 | 9 |
| 操作历史 history | 7 | 0 | 7 |
| 回收站 recycle | 2 | 0 | 2 |
| 外部分享 share | 3 | 1 | 4 |
| **合计** | **40** | **15** | **55** |

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
对评审新要求应红（如权限变化提示、分享开关关闭）。这条红/绿
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

P2-09 已把搜索模块的 api 用例（search-001～search-007）做成绿：类型/位置/更新时间
筛选由上游参数（`obj_type`/`search_path`/`time_from`）表达，标签/创建人筛选由
`tags`/`creator_emails` 参数转结构化过滤器（需 `CF_PROVIDER_SEARCH=meilisearch`，
矩阵门禁以该 provider 起栈并跑一轮 `cf_worker --once` 回填索引）；`matched_tags`
信号已由 provider 返回。实现见 [features/search.md](features/search.md) 与
[`review_search_matrix.py`](../tests/e2e/review_search_matrix.py)。标签命中徽标与
文件夹「打开/定位到目录树」仍是浏览器用例（channel: `ui`）。

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

P2-10 已把操作历史模块的 5 条 api 用例做成绿（history-002/003/004/006/007）：
`file/history` 增加可选的 `q`（搜索）、`operator`/`source`（按创建人筛选）、
`page`/`per_page`（分页 + `page_next`）；`repo/history` 增加可选的 `path`
（文件夹历史默认只看文件夹自身 + 直属下一级，不递归）与 `current_folder_only`
（仅文件夹自身，排除直属子级）。实现见 [features/history.md](features/history.md)
与 [`review_history_matrix.py`](../tests/e2e/review_history_matrix.py)；不传参数时
与 CE 行为一致。history-001/005（修订列表含创建人、修订详情）为 CE 原生已绿。
容器验收 7/7 通过（2026-08-15 本地栈复验）。

回收站模块决策（2026-08-15）：**维持原生 Seafile CE 回收站行为**，不做管理员
门禁、不隐藏普通用户入口。用例集只保留 CE 原生就绿的 recycle-003（管理员列举/
恢复/永久删除）与 recycle-004（软删除可恢复）；原 recycle-001（普通用户隐藏
入口）与 recycle-002（普通用户 API 拒绝）随决策移除。实现见
[`review_recycle_matrix.py`](../tests/e2e/review_recycle_matrix.py)。
P2-11 已把外部分享模块的 api 用例做成绿（share-002/003/004）：新增开关
`CF_ENABLE_SHARE_RESTRICT`（默认 false = 原生 CE）。开启后非管理员创建外链
被拒（403）、匿名访问旧外链按不存在处理（404）、列表/查询端点保留、管理员仍可
创建与管理。实现见 [features/share-restrict.md](features/share-restrict.md) 与
[`review_share_matrix.py`](../tests/e2e/review_share_matrix.py)；share-001
（前端隐藏分享入口）属浏览器用例，随浏览器套件验收。

## 4.5 UI 用例实现状态（2026-08-15 代码核对）

channel=ui 的 15 条用例，逐个核对前端代码后判定：

| 用例 | 实现状态 | 证据（frontend/src/） |
|---|---|---|
| icon-001 框选 | 已实现且浏览器验证通过 | `dirent-grid-view.js` marquee（getSelectionRect/determineSelectedItems） |
| icon-002 ctrl 离散多选 | 已实现且浏览器验证通过 | `lib-content-view.js` `onDirentClick` 的 ctrl/meta 分支 |
| icon-003 shift 连续多选 | 已实现且浏览器验证通过 | 同上 shift 分支（lastSelectedIndex 区间） |
| icon-004 全选当前页 | 列表视图已实现（头部复选），网格视图未提供 | `dirent-list-view.js` isAllSelected/onAllItemSelected |
| icon-005 批量操作栏 | 已实现且浏览器验证通过 | `selected-dirents-toolbar`（多选后出现） |
| tree-003/004 悬停更多含复制 | 已实现 | `tree-node-view.js` `calculateMenuList`（COPY/MOVE） |
| search-008 匹配标签徽标 | 已实现 | `search-result-item.js` `matched-tag-badge` |
| search-009 文件夹打开/定位 | 已实现 | 同文件 `item-folder-action`「Open folder · Locate」 |
| share-001 分享入口隐藏 | 已实现 | `utils.js` `isHasPermissionToShare`（CF_ENABLE_SHARE_RESTRICT） |
| tree-002 悬停收藏按钮 | 待核对 | 树节点无 star 项，收藏入口在文件行 hover（待确认映射） |
| tags-006 系统标签锁形图标 | 待实现 | metadata 标签数据未贯通 `is_system`（repo_tags 才有） |
| tags-008 超过两枚折叠 | 待实现 | `file-tags` formatter 未做 2+省略 |
| recycle-001 | 已按决策移除（维持原生 CE） | — |

浏览器套件入口 `tests/e2e/review_ui_matrix.py`（Playwright）已就绪并覆盖 icon-001..005；
图标多选在真实栈上跑通前需先解决「DIR_ACL 开启时前端目录视图渲染『Folder does not
exist』」这一独立前端问题（API 目录列举正常，仅前端渲染路径异常）。

## 5. 与既有能力的边界

复制/移动与 `fileop`（写生命周期）、标签与 `metadata`、搜索与 `search`、
操作历史与 `audit` 有重叠。本用例集只覆盖**评审清单新增的可验收点**，不与既有
能力矩阵重复断言同一条语义；重叠处按评审要求补"权限/隐藏/开关"这些既有矩阵没盖住的边。

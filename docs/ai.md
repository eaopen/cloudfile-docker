# AI 能力：自动属性 / 标签 / 摘要（及语义检索）

CE 扩展版的 AI 能力规格，最低目标是**文件自动属性 / 自动标签 / 自动摘要**。
配套：[search.md](search.md)（检索）、[upstream-reuse.md](upstream-reuse.md)（元数据）、
[pro-parity.md](pro-parity.md)、[FEATURES.md](FEATURES.md)、[BRANCHES.md](BRANCHES.md)。

本文是对"需要哪些新代码"的核对与确认，凡"确认"的给出代码位置。

---

## 一、结论：生成能力 CE 已有，缺的是"自动"那一环

按[原则 0（优先复用官方组件）](BRANCHES.md#〇首要原则优先复用官方组件)核对，
AI 生成能力**在 CE 里已经存在、且不被 `is_pro_version()` 挡**：

| 能力 | CE 现状 | 代码位置 |
|---|---|---|
| 生成文件标签 | ✅ 有，按需（用户触发） | `seahub/ai/utils.py:generate_file_tags` → `POST {SEAFILE_AI_SERVER_URL}/api/v1/generate-file-tags/` |
| 生成摘要 | ✅ 有，按需 | `generate_summary` → `/api/v1/generate-summary` |
| 图片描述（属性） | ✅ 有，按需 | `image_caption` → `/api/v1/image-caption/` |
| OCR / 翻译 / 写作助手 / 对话 | ✅ 有，按需 | `seahub/ai/apis.py` 一整套 |
| 门控 | `ENABLE_SEAFILE_AI` env（**非 Pro**），`SEAFILE_AI_SERVER_URL` | `seahub/settings.py:1096,1376` |

所以**生成本身零新增代码**——启用 `ENABLE_SEAFILE_AI`、把 `SEAFILE_AI_SERVER_URL`
指向官方 `seafileltd/seafile-ai` 组件即可（打包层，见第二节）。

**缺的只有"自动"**：现有端点都是**按需**（用户点一下"生成标签"）。核对后确认
**没有**任何"文件入库即自动生成标签/摘要"的接线：

```bash
grep -rniE "auto.*tag|on_commit|auto_summary|auto_metadata" seahub/ai/ seahub/repo_metadata/   # → 空
```

CE 里唯一**自动**的 AI 管线是**人脸识别**（seafevents，`ENABLE_FACE_RECOGNITION`，
`repo_metadata/seafile_ai_api.py` 的 face-embeddings/cluster/recognize）。自动的
**标签/摘要**要 CloudFile 自己接。这就是本能力唯一的**构建**部分。

---

## 二、打包层：官方 seafile-ai 组件 + 启用

Compose 直接引用官方镜像，不重打包：

| 组件 | 镜像 | 作用 |
|---|---|---|
| Seafile AI | `seafileltd/seafile-ai` | 提供 `/api/v1/{generate-file-tags,generate-summary,image-caption,ocr,...}` |

启用同 SSO/搜索那样，从 `.env` 写上游已读的设置（bootstrap `_settings_block_*`），
**不新增 `CF_ENABLE_*`、不开分支**：

```bash
ENABLE_SEAFILE_AI=true
SEAFILE_AI_SERVER_URL=http://seafile-ai:8888
SEAFILE_AI_SECRET_KEY=...
```

> **seafile-ai 需要一个 LLM 后端**（`seafile_ai_config.yaml`，operator 自备——
> OpenAI 兼容 API 或本地模型）。这是 AI 能力真正的运行依赖与成本所在。**这也是
> AI 与其它能力不同的地方**：其它能力零外部成本，AI 要么接一个自备模型、要么
> 接一个付费 API。

> **计费边界**：`seahub/ai/` 带用量/额度统计（`StatsAIByOwner`、`OrgMemberQuota`），
> 那是 seafile.com **托管 AI 按量计费**的钩子。**自建 seafile-ai + 自备模型即绕开
> 计费**——这正是"复用官方组件、但不受制于其托管服务"的又一处体现。

---

## 三、构建层：自动管线（依赖簇 D 元数据）

把"按需生成"变成"入库自动生成并落库"，是唯一要写的新代码。形状与检索的索引
worker 完全一致——**同一条提交事件流的又一个消费者**：

```
文件提交 → 提交事件（seafevents 事件总线 / cf-worker）
        → 取出新增/变更文件
        → 调 seafile-ai：generate_file_tags / generate_summary / image_caption
        → 写入元数据存储（属性/标签列）
        → 前端与检索照常读元数据
```

关键点：

1. **结果落在元数据存储里**（属性、标签、摘要都是文件的元数据），所以 **AI 自动
   管线依赖簇 D（元数据）先就位**——[upstream-reuse.md](upstream-reuse.md) 探针 1
   的那套：默认官方 `seafile-md-server`，前端/API/投喂全白拿。AI 只是又往里写几列。
2. **住在 cf-worker，不 fork seafevents**（与 meilisearch 索引器同理）：新增一个
   周期/事件消费者（`register_periodic_task` 或事件订阅），零上游改动。
3. **幂等与去重**：同一文件的同一版本只生成一次（按 obj_id/commit 去重），否则每次
   投喂都重算，既烧钱又刷元数据。
4. **可控触发**：按库/按类型/按大小限制自动生成范围——AI 调用有成本，"整库自动
   摘要"应是显式选择，不是默认对所有文件开。

---

## 四、语义检索（延伸，接簇 E）

嵌入（embedding）→ 写入检索后端 → 语义检索，是 AI × 检索的交叉，归
[search.md](search.md) 的 **P3**：seafile-ai 产出嵌入，检索后端（seasearch/meilisearch）
存与查。与自动标签同源（都消费提交事件、都经 cf-worker），可共用同一个 worker。

---

## 五、分阶段

| 阶段 | 内容 | 归类 | 依赖 |
|---|---|---|---|
| **P0** | 启用官方 seafile-ai + 按需能力（生成标签/摘要/描述/OCR）；配 LLM 后端 | 📦 打包 | seafile-ai 镜像 + LLM |
| **P1** | 自动管线：cf-worker 消费提交 → 生成标签/摘要 → 写元数据；幂等 + 可控触发 | 🔨 构建 | **簇 D** + P0 |
| **P2** | 人脸识别自动管线（`ENABLE_FACE_RECOGNITION`，seafevents 已有） | 📦 打包 | seafile-ai + P0 |
| **P3** | 语义检索：嵌入 → 检索后端 | 🔨 构建 | 簇 E + P0（见 search.md P3） |

**P1 的验收面**：新文件入库后，元数据里出现 AI 标签/摘要；同一版本不重复生成
（幂等）；关闭 `ENABLE_SEAFILE_AI` 时管线不触发、行为回落原生 CE；触发范围限制生效。
进 `ai-e2e.yml` 能力门禁（可用一个假 seafile-ai 桩，避免门禁依赖真实 LLM/联网）。

> **门禁为什么要桩**：真实 seafile-ai 需要 LLM（联网/付费/不确定输出），拿它跑门禁
> 既慢又不可复现。桩只需按契约回固定标签/摘要，验证的是**管线接线与落库**，不是
> 模型质量——与检索门禁验"权限边界"而非"召回率"是同一个道理。

---

## 六、与 Pro 对标的关系

**AI 不在官方 Pro vs CE 对比表里**——它是 seafile.com 之后加的、按用量单独计费的
维度（托管 AI credits），不是传统 Pro 特性。但**代码在 CE 里且不受 `is_pro` 门控**，
所以 CloudFile 可以自建：官方 seafile-ai 组件 + 自备 LLM。这是"是否开源不是首要
约束、优先复用官方组件"在 AI 上的直接落地——复用官方组件，但用自备模型绕开其
托管计费。

## 七、产品口径

> CloudFile 复用 Seafile 官方 seafile-ai 组件提供文件标签、摘要、图片描述、OCR
> 等能力（CE 已带、无 Pro 门控，接自备 LLM 后端）；在此之上由 cf-worker 增加
> **自动**管线，文件入库即生成标签/摘要并写入元数据（依赖官方 metadata-server），
> 前端与检索照常读取。语义检索作为 AI × 检索的延伸接入可替换的检索后端。

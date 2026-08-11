---
phase: 1
slug: security-and-collaboration-contract-closure
status: draft
shadcn_initialized: false
preset: none
created: 2026-08-11
---

# Phase 1 — UI Design Contract

> Security and Collaboration Contract Closure 的视觉与交互约束。实现必须扩展现有 Seahub/CloudFile 界面，不得重做 Seahub 页面框架。

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none；沿用现有 Seahub CSS 与 Bootstrap utility |
| Preset | not applicable |
| Component library | Reactstrap 9.2.3 + 现有 Seahub 组件 |
| Icon library | 现有 Seafile multicolor icon font；本阶段状态不得只靠图标表达 |
| Font | Seahub 默认 system/Roboto sans-serif；CloudFile file-actions 已有 Georgia 标题与 monospace eyebrow 原样保留，不新增字体 |

设计系统决策来自现有代码与“不得重做 Seahub”的阶段边界。项目是 React 18，但没有 `components.json`、Tailwind 或 shadcn；本阶段不得初始化并行设计系统。

必须复用：

- `reactstrap` 的 `Button`、`Spinner`、`Table`；Seahub 的 `Loading`、`toaster`、`FileViewTip`。
- `cloudfile/file-actions` 的 `ActionCard`、`LocalSession`、checkout 状态区和现有 `cf-*` 样式语言。
- `cloudfile/admin` 的普通 Seahub 标题与表格结构；运行时 feature 状态和资格门禁结果必须分开表达。
- OnlyOffice 文件页现有 `FileView` / `FileViewTip` 容器和下载兜底，不在编辑器 iframe 上另建导航或视觉外壳。

不得新增全局导航、设置中心、仪表盘、插画、营销文案、渐变、阴影体系或新的图标包。所有新增字符串必须使用 `gettext()`。

---

## Spacing Scale

Declared values (must be multiples of 4):

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | 状态点与文本、图标与标签间距 |
| sm | 8px | 紧凑行内元素、按钮内 spinner 间距 |
| md | 16px | 状态行、错误区、表格单元默认间距 |
| lg | 24px | session/status panel 内边距和区块间距 |
| xl | 32px | 独立协作状态区之间的间距 |
| 2xl | 48px | 现有页面的大区块分隔；不用于紧凑 admin 表格 |
| 3xl | 64px | 仅继承现有 file-actions 宽屏页面留白，不新增使用点 |

Exceptions: 键盘可操作控件的最小点击目标为 44×44px；这是控件尺寸而非 spacing token。现有 Reactstrap 小按钮若视觉高度不足，可扩大透明命中区，但其新增 padding、gap 和 margin 仍只能使用 4、8、16、24、32、48、64px。未被 Phase 1 修改的 legacy 组件可继承原有 off-scale spacing；这些值属于 out-of-scope styling，不进入本合同。任何由 Phase 1 新增或修改的 spacing 必须使用声明的 scale。

---

## Typography

新增的状态、错误和操作文案只使用以下四个字号与两个字重。现有 file-actions hero/card 标题尺寸作为已存在的页面资产保留，不得复制到新增状态文案。

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 16px | 400 | 1.5 |
| Label | 12px | 600 | 1.4 |
| Heading | 20px | 600 | 1.2 |
| Display | 24px | 600 | 1.2 |

允许字重仅为 400 和 600。文件名、路径、generation、protocol version 等机器值可用现有 monospace 字族，但仍使用 12px 或 16px；长文件名和路径必须换行或省略并提供完整的可访问名称，不得撑破容器。

---

## Color

60/30/10 比例仅约束 CloudFile file-actions 表面；嵌入 Seahub 的 admin 与 OnlyOffice 页面继承其现有主题变量，不得被这组颜色重新着色。

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `#F4F0E7` (`--cf-paper`) | 现有 file-actions 页面背景 |
| Secondary (30%) | `#FFFFFF` at 62% over paper | action card、session panel、checkout/status panel |
| Accent (10%) | `#18231D` (`--cf-ink`) | 主要 CTA、标题/边框、当前状态的高对比强调 |
| Destructive | `#B44631` (`--cf-red`) | 冲突、过期、stale generation、配置拒绝和失败边框；不得用于普通 CTA |

Accent reserved for: `Download local session`、`Start new session` 等主要恢复动作，当前 session/status panel 的关键边框，以及已存在的 action-card 标题。不得把所有链接、状态或表格值改成 accent。

现有 Seahub 表面继续使用其 `#FF8000` primary、`#ED7109` hover、Bootstrap secondary/danger 语义。PASS、SKIP、FAIL 必须同时显示大写文本；颜色只是辅助：PASS 使用既有 success，SKIP 使用 neutral/muted，FAIL 使用 danger。不得用绿色表示“Enabled”，也不得把 feature flag 的 Enabled 当成 PASS。

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Primary CTA | `Download local session` |
| Empty state heading | `No local action is available` |
| Empty state body | `This file has no enabled CloudFile local workflow. You can return to the library or use the available Seahub actions.` |
| Error state | `This file action could not be prepared. Reload the file and try again. If the problem continues, contact an administrator.` |
| Destructive confirmation | None；本阶段不新增删除或不可逆 UI 动作，generation-fenced check-in/release 不弹确认框 |

文案必须说明“发生了什么、文件是否被改变、下一步做什么”，不得显示原始异常、JWT、ticket、cookie、内部 URL 或 generation token。推荐恢复动作必须是明确的动词+对象，禁止 `OK`、`Continue`、`Something went wrong`。

### Required State Copy

| State | Heading / message | Primary action | Secondary action |
|-------|-------------------|----------------|------------------|
| Local view ready | `Viewing session ready`；`Download the short-lived session file to open this file read-only.` | `Download local session` | `Close session` |
| Local edit ready | `Editing session ready`；`Download the short-lived session file to edit this file with protected write-back.` | `Download local session` | `Close session` |
| Session claimed | `Local session claimed`；`The local agent claimed this one-time session.` | none | `Close session` |
| Heartbeat delayed | `Waiting for the local agent`；`The session is still active. Keep the local app open while CloudFile reconnects.` | none | `Close session` |
| Retry in progress | `Retrying save…`；`CloudFile is checking the previous save outcome. Do not start another upload.` | none | none |
| Retry resolved | `File saved`；`The previous save already completed. No duplicate file was created.` | `Open current file` | `Close session` |
| Conflict | `This file changed elsewhere`；`Your local changes did not overwrite the newer version.` | `Open current file` | `Start new edit session` |
| Session expired | `This local session expired`；`The file was not changed. Start a new session to continue.` | `Start new session` | `Close session` |
| Stale generation | `This session is out of date`；`A newer file generation exists, so this save or check-in was refused.` | `Open current file` | `Start new edit session` |
| Unsupported protocol | `This local session version is not supported`；`Update the CloudFile Local agent, then start a new session.` | `Start new session` | `Close session` |
| OnlyOffice disabled | `Online editing is not enabled for this deployment.` | `Download file` | none |
| OnlyOffice secure config rejected | `OnlyOffice is unavailable because its secure configuration is incomplete. Ask an administrator to verify matching JWT settings.` | `Download file` | none |
| OnlyOffice conflict/stale callback | `This document changed elsewhere. The current save was refused and did not overwrite the newer version.` | `Download file` | `Reload current file` |
| Gate PASS | `PASS — Assertions executed successfully.` | evidence link when available | none |
| Gate SKIP | `SKIP — Optional capability was intentionally not run.` | reason/details | none |
| Gate FAIL | `FAIL — Required capability was unavailable or an assertion failed.` | evidence/details | none |
| Gate absent | `NOT RUN — No result was reported for this capability.` | evidence/details when available | none |

The browser may show claimed/heartbeat/retry states only when the API reports them. It must not infer agent health from a downloaded descriptor or display a success state merely because the download started.

---

## Interaction Contract

### Local View And Edit

1. Existing `local-view` and `local-edit` action cards remain in the current responsive grid. Cards use the server-provided availability and reason; an unavailable action has no active CTA and exposes the reason as text.
2. Selecting an action disables only the affected action controls, replaces its label with the existing small `Spinner`, and prevents duplicate session creation until the request resolves. A request lasting more than 10 seconds exposes a cancel/close route and never appears complete.
3. A successful pre-claim response replaces no page context: append the existing `LocalSession` panel, move focus to its heading, and show file name, mode, protocol version, and absolute expiry plus remaining time. Never render the one-time ticket in visible UI.
4. `Download local session` produces the existing `.cloudfile` descriptor. Download start is not a claim or save success. The panel stays available until claimed, expired, or explicitly closed.
5. Edit write-back must target the same visible file name/path. Successful idempotent retry reports the prior outcome without a second success event or duplicate file. Read-only local view never displays save/check-in controls.
6. Conflict, expiry, unsupported protocol, and stale generation replace the ready/status content with a persistent inline panel using `role="alert"`; a toast may supplement it but cannot be the only record. These states never auto-dismiss and never offer “force overwrite”.
7. A stale check-in/release leaves checkout state visible and marks it unresolved; the UI does not announce `File checked in` until the generation-fenced release succeeds.

### OnlyOffice

1. No settings toggle is added. `CF_ENABLE_ONLYOFFICE` and matching non-empty JWT values are operator configuration; valid startup registration controls whether the existing OnlyOffice entry point is available.
2. Disabled OnlyOffice is hidden from normal action choices. A bookmarked/direct OnlyOffice URL renders `FileViewTip` with the disabled message and a `Download file` fallback when Phase 1 controls that action label.
3. Missing or mismatched JWT configuration is primarily a startup/preflight failure. If a partially available deployment returns a page error, show the secure-config message without identifying which secret or printing either value.
4. Callback retry remains visually quiet until it has a terminal result. Conflict or stale generation becomes a persistent parent-page error with download/reload recovery; it must never report a saved state before authenticated, deduplicated write-back commits.
5. Preserve the existing `FileView`, OnlyOffice iframe area, Safari initialization path, and native editor controls. No custom toolbar is introduced.

### Truthful Gate Status

1. Local and CI output use exactly `PASS`, `SKIP`, `FAIL`, and `NOT RUN`; the browser/admin UI must not invent a fifth success-like label.
2. `PASS` is permitted only after assertions executed. A missing required dependency is `FAIL`; a deliberately omitted optional capability is `SKIP` with a reason; missing evidence is `NOT RUN`.
3. The existing CloudFile admin `Enabled`/`Disabled` feature table reports runtime switches only. If preflight results are surfaced there, they appear in a separately titled `Capability checks` table with status, reason, checked-at timestamp, environment (`local` or `CI`), and evidence identifier/link.
4. Never derive check status from a feature switch, service registration, HTTP 200, or skipped test process. A stale prior result includes `Result may be stale` and its timestamp; it is not promoted to PASS.
5. No new admin dashboard is required for Phase 1. CLI/CI remains the source of truth unless the backend exposes the same declared capability table to the existing admin page.

---

## Component Inventory

| Surface | Existing component/pattern | Contracted change |
|---------|----------------------------|-------------------|
| File action chooser | `ActionCard`, Reactstrap `Button`/`Spinner` | Keep layout; distinguish loading, unavailable, and safe retry without new card type |
| Local session | `LocalSession`, `cf-agent-ticket` | Add protocol/expiry facts and terminal status variants inside the same panel |
| Checkout | `cf-checkout-status` | Keep check-in action; report stale generation inline and suppress false success toast |
| Transient feedback | Seahub `toaster` | Use for successful start/save/release; never as sole conflict/expiry/error surface |
| OnlyOffice failure | `FileViewTip` | Supply actionable sanitized copy and use `Download file` when Phase 1 controls the fallback label |
| Admin feature state | Reactstrap `Table`, Seahub `Loading` | Keep runtime switch table; optional gate table must be visibly separate and truthful |

Status panels use the same one-pixel border, paper/white surface, left signal border, square/Bootstrap button treatment, and max-width as their containing view. Do not add modal dialogs for routine session outcomes.

---

## Responsive And Accessibility Contract

- Preserve the current file-actions maximum width of 72rem and its breakpoint at 40rem. At or below the breakpoint, facts and actions stack in DOM order; the primary recovery action appears first and fills available width when needed.
- Admin and OnlyOffice surfaces inherit existing Seahub responsive layout. No fixed-width status column; reason text wraps before status text truncates.
- Loading status uses `aria-live="polite"`; conflict, expiry, stale generation, unsupported protocol, secure-config failure, FAIL, and NOT RUN use persistent `role="alert"` or equivalent assertive announcement.
- Focus moves to a newly inserted terminal-state heading after an action response. Closing a panel returns focus to the button that opened it. All actions are keyboard reachable with a visible existing-theme focus ring.
- Spinner-only moments have an accessible label. Status is always conveyed by explicit text, not color, dot, icon, or opacity alone. Respect `prefers-reduced-motion`; no new animation beyond the existing spinner.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none | not applicable — shadcn not initialized |
| third-party | none | not applicable — no registry code permitted in this phase |

---

## Source Decisions

| Source | Decisions applied |
|--------|-------------------|
| `01-CONTEXT.md` | Existing local session flow; protocol-versioned descriptor; exact-file write-back; heartbeat/retry/conflict/expiry/stale behavior; OnlyOffice default-off startup registration and secure JWT refusal; PASS/SKIP/failure truthfulness |
| `REQUIREMENTS.md` | LOCAL-01/02, OFFICE-01/02, LOCK-01 and GATE-01 outcome boundaries |
| `ROADMAP.md` | Phase goal and five success criteria; no identity/storage/tags/AI/release UI expansion |
| Existing CloudFile/Seahub frontend | Reactstrap components, `toaster`, `FileViewTip`, CloudFile file-actions/admin composition and current visual tokens |

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS
- [x] Dimension 5 Spacing: PASS
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved 2026-08-11 — gsd-ui-checker returned 6/6 PASS (commit de4c1c9); recorded here as the working approval for current UI Plans 11/15.

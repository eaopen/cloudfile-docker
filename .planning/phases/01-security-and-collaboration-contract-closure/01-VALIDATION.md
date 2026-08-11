---
phase: 1
slug: security-and-collaboration-contract-closure
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-08-11
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python/shell control-plane tests; Hub pytest/Jest; Server C harness/Go tests; Agent Go tests; Compose E2E |
| **Config file** | Existing repository test configs plus Phase 1 shared contract fixtures |
| **Quick run command** | `python3 tools/test-bootstrap-settings.py && python3 tools/preflight-checks.py . ..` |
| **Full suite command** | `PATH="../cloudfile-hub/.venv/bin:$PATH" ./tools/run-checks.sh` followed by ACL/search/fileop/collaboration gates, then same-tuple all-switches-off `python3 tests/e2e/smoke.py` and `python3 tests/e2e/baseline.py` |
| **Estimated runtime** | Quick: <30 seconds; full local/CI matrices: up to 2 hours |

---

## Sampling Rate

- **After every task commit:** Run the focused owning-repository test plus `python3 tools/preflight-checks.py . ..`.
- **After every plan wave:** Run `PATH="../cloudfile-hub/.venv/bin:$PATH" ./tools/run-checks.sh` and all focused suites changed by that wave.
- **Before `/gsd-verify-work`:** ACL, search, fileop, collaboration, and native-disabled baseline matrices must be green against the same repository tuple.
- **Max feedback latency:** 30 seconds for task-level sampling; slow container matrices run at wave/phase gates.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01 | 01 | 1 | GATE-01 | Dynamic parity, four-state truth, same-tuple disabled dual baseline | unit/static | capability manifest suite | ❌ W0 | ⬜ pending |
| 01-02 | 02 | 2 | SEC-01/02 | Shared authority/search contracts distinguish disabled from active outage | Python/C/Go | focused red suites | ❌ W0 | ⬜ pending |
| 01-03 | 03 | 3 | SEC-01/02 | Hub revision and authorization-before-observability | Hub pytest | focused ACL/search pytest | ✅ extend | ⬜ pending |
| 01-04 | 04 | 3 | SEC-02 | Server active unavailable denies at final boundary | C/Go | focused ACL C/Go | ✅ extend | ⬜ pending |
| 01-05 | 05 | 4 | SEC-01/02 | Real ACL/search plus disabled native matrices | E2E gate | `cap acl` + `cap search` | ✅ extend | ⬜ pending |
| 01-06 | 06 | 2 | FILEOP-01/LOCK-01 | Canonical operation/fence contract and expected_commit_id | C/Go | focused red suites | ❌ W0 | ⬜ pending |
| 01-07 | 07 | 4 | FILEOP-01/LOCK-01 | Native C/RPC scope, one terminal, and generation/version fence | C | focused C harness | ✅ extend | ⬜ pending |
| 01-17 | 17 | 5 | FILEOP-01/LOCK-01 | Go/Python adapters preserve native identity and fence fields | Go/Python | focused adapter suites | ✅ extend | ⬜ pending |
| 01-08 | 08 | 6 | FILEOP-01/LOCK-01 | Every write path plus disabled native path | E2E gate | `cap fileop` | ✅ extend | ⬜ pending |
| 01-09 | 09 | 2 | LOCAL-01/02 | Four-client v2/status/writeback golden contract | Python/Jest/Go/Node | focused red suites | ❌ W0 | ⬜ pending |
| 01-10 | 10 | 6 | LOCAL-01/02 | Durable writeback and authenticated status API | Hub pytest | focused file_actions pytest | ❌ W0 | ⬜ pending |
| 01-11 | 11 | 7 | LOCAL-01/02 | Browser polling and Agent/extension retry | Jest/Go/Node | focused client suites | ❌ W0 | ⬜ pending |
| 01-12 | 12 | 8 | LOCAL-01/02 | Local flow; unavailable Chrome is explicit SKIP | E2E gate | collaboration local phase | ❌ W0 | ⬜ pending |
| 01-13 | 13 | 2 | OFFICE-01/02 | Startup/JWT and safe-download contracts | Python/pytest | focused red suites | ❌ W0 | ⬜ pending |
| 01-14 | 14 | 7 | OFFICE-01/02 | Durable callback/status transaction and safe download | Hub pytest | focused office suites | ❌ W0 | ⬜ pending |
| 01-18 | 18 | 8 | OFFICE-01/02 | Deployment/editor hook, focused regression, patch governance | settings/pytest/static | focused Office integration | ❌ W0 | ⬜ pending |
| 01-15 | 15 | 9 | OFFICE-02 | UI polls authenticated status route | Jest | focused Office Jest | ❌ W0 | ⬜ pending |
| 01-16 | 16 | 10 | GATE-01/OFFICE-01/02 | Real Docs and same-tuple smoke+baseline final gate | E2E gate | collaboration + dual baseline | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Plan 01 dynamic manifest and PASS/SKIP/FAIL/NOT RUN self-tests；Task 1 必须精确确认 pre-implementation parity 红因为 local missing `[external_sources]`，Task 2 才要求 full preflight green。
- [ ] Plan 02 ACL authority/search leakage shared fixtures and red tests.
- [ ] Plan 06 operation/generation fixtures with canonical `expected_commit_id` and red tests.
- [ ] Plan 09 local-session/status golden fixtures consumed by Hub/Jest/Go/Node red tests.
- [ ] Plan 13 Office startup/JWT/callback/safe-download red tests.
- [ ] Full matrices are reserved for Plans 05/08/12/16 plan and wave gates.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real Chrome download observer to Native Messaging host handoff | LOCAL-01 | Headless CI/browser availability varies; absence must be SKIP, never PASS | In a supported Chrome runner, install the unpacked extension and native-host manifest, download one valid and one expired `.cloudfile` descriptor, then verify exactly one valid handoff and an explicit expired-session error. |

---

## Validation Sign-Off

- [x] All planned requirement groups have an automated command or Wave 0 dependency.
- [x] Sampling continuity: no 3 consecutive tasks without automated verification.
- [x] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Task feedback target is <30 seconds; slow suites are isolated to wave/phase gates.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** approved 2026-08-11 for planning; Wave 0 remains pending execution.

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
| **Full suite command** | `PATH="../cloudfile-hub/.venv/bin:$PATH" ./tools/run-checks.sh` followed by `./tools/verify-local.sh cap acl`, `cap search`, `cap fileop`, and `cap collaboration` |
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
| 01-01-01 | 01 | 1 | GATE-01 | No missing or unexecuted capability is reported PASS | unit/static | `python3 tools/preflight-checks.py . ..` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | SEC-01 | Hidden names, snippets, totals, and cached candidates never cross the response boundary | unit + E2E | `./tools/verify-local.sh cap search` | ✅ extend | ⬜ pending |
| 01-02-02 | 02 | 1 | SEC-02 | Active unavailable/malformed/stale ACL authority denies; inactive mode passes through | C/Go + E2E | `./tools/verify-local.sh cap acl` | ✅ extend | ⬜ pending |
| 01-03-01 | 03 | 2 | FILEOP-01 | Each operation has one PREPARE and exactly one terminal fact | C/Go + E2E | `./tools/verify-local.sh cap fileop` | ✅ extend | ⬜ pending |
| 01-03-02 | 03 | 2 | LOCK-01 | Missing or stale generation cannot mutate or release newer work | C/Go + E2E | `./tools/verify-local.sh cap fileop` | ❌ W0 | ⬜ pending |
| 01-04-01 | 04 | 3 | LOCAL-01 | All four consumers reject unsupported schema versions and receive required pre-claim fields | Python/Jest/Go | `cd ../cloudfile-local-agent && go test ./...` | ❌ W0 | ⬜ pending |
| 01-04-02 | 04 | 3 | LOCAL-02 | Existing-file update is idempotent and rejects conflict, expiry, origin mismatch, and stale generation | unit + E2E | `./tools/verify-local.sh cap collaboration` | ❌ W0 | ⬜ pending |
| 01-05-01 | 05 | 4 | OFFICE-01 | Enabled Office without same-source non-empty JWT fails before serving callbacks | settings/unit + E2E | `python3 tools/test-bootstrap-settings.py` | ✅ extend | ⬜ pending |
| 01-05-02 | 05 | 4 | OFFICE-02 | Callback retry is authenticated, idempotent, conflict-aware, and generation-fenced | transaction + E2E | `./tools/verify-local.sh cap collaboration` | ❌ W0 | ⬜ pending |

> Threat refs live in each plan's STRIDE register (T-01-01 .. T-01-25); this table tracks requirement → automated check mapping only.

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Canonical capability manifest and status self-tests for PASS/SKIP/FAIL/NOT RUN semantics.
- [ ] Shared ACL, file-operation, local-session, and generation golden cases consumed by their owning test layers.
- [ ] Hub search ACL, file-action idempotency, and Office registry/JWT/callback tests.
- [ ] Server authority-state/revision, operation pairing, and generation-fence C/Go tests.
- [ ] Local Agent session/runner and Chrome handoff contract tests.
- [ ] `tests/e2e/collaboration_matrix.py`, matching workflow, and `verify-local` capability entry.

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

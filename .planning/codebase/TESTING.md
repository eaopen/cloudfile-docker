# Testing Patterns

**Analysis Date:** 2026-08-11

## Test Framework

**Runner:**
- `cloudfile-docker` has no single test framework. `tools/run-checks.sh` is the fast aggregate runner; `tools/verify-local.sh` is the image/build/Compose orchestrator; `tests/e2e/*.py` are executable standard-library assertion clients.
- Hub CloudFile unit tests use pytest through `../cloudfile-hub/pytest.ini` and are invoked by `tools/run-checks.sh` as `python3 -m pytest cloudfile_ext/ -q`.
- Server policy tests are compiled C executables driven by `../cloudfile-server/tests/cf-acl/run.sh`, `../cloudfile-server/tests/cf-fileop/run.sh`, and `../cloudfile-server/tests/cf-s3/run.sh`.
- Server Go contract tests use the standard `testing` package in `../cloudfile-server/fileserver/cf_fileop_test.go`; the quick gate selects root-package tests matching `Cf[A-Z]`.
- Config-generation regression checks use a custom `check()` harness in `tools/test-bootstrap-settings.py`; upstream-patch policy uses the executable shell test `tests/tools/test-check-upstream-patches.sh`.

**Assertion Library:**
- Python unit assertions: pytest's plain `assert` and `pytest.raises` in `../cloudfile-hub/cloudfile_ext/**/tests/test_*.py`.
- Docker E2E assertions: local `record()` / `check()` helpers in `tests/e2e/*.py` with a non-zero process exit on any failed case.
- C assertions: explicit counters and test helpers compiled by `../cloudfile-server/tests/cf-acl/run.sh` and `../cloudfile-server/tests/cf-fileop/run.sh`.
- Go assertions: `testing.T` methods in `../cloudfile-server/fileserver/cf_fileop_test.go`.

**Run Commands:**
```bash
./tools/run-checks.sh                    # Fast cross-repository CI gate
./tools/verify-local.sh preflight         # Fast gate plus static workflow/config consistency
./tools/verify-local.sh                   # Build image, start baseline stack, run baseline E2E
./tools/verify-local.sh e2e               # Run baseline E2E against an existing local image
./tools/verify-local.sh cap acl           # Run one registered capability gate
python3 tools/test-bootstrap-settings.py  # Execute generated configuration fragments
```

Adjacent repository commands used by `tools/run-checks.sh`:

```bash
cd ../cloudfile-hub && python3 -m pytest cloudfile_ext/ -q
../cloudfile-server/tests/cf-acl/run.sh
../cloudfile-server/tests/cf-fileop/run.sh
cd ../cloudfile-server/fileserver && go build ./... && go vet ./...
cd ../cloudfile-server/fileserver && go test -count=1 -run 'Cf[A-Z]' .
```

## Test File Organization

**Location:**
- Put deployable-system HTTP matrices in `tests/e2e/`; baseline compatibility lives in `tests/e2e/smoke.py` and `tests/e2e/baseline.py`, while capabilities use `<capability>_matrix.py`.
- Put Docker-tool regression tests in `tests/tools/`, currently `tests/tools/test-check-upstream-patches.sh`.
- Put source-extraction and static validators in `tools/test-bootstrap-settings.py` and `tools/preflight-checks.py`; these validate build/deploy contracts rather than product APIs.
- Co-locate Hub unit tests under each capability at `../cloudfile-hub/cloudfile_ext/<capability>/tests/test_*.py`; framework-level tests live at `../cloudfile-hub/cloudfile_ext/tests/`.
- Put server pure-policy tests in `../cloudfile-server/tests/cf-<capability>/` with a `run.sh`; put Go tests beside implementation under `../cloudfile-server/fileserver/`.
- Keep shared cross-language semantic fixtures in this repository at `docs/acl-cases.json` and `docs/fileop-cases.json` so Hub, C, and Go cannot silently diverge.

**Naming:**
- Use `test_*.py` / `tests.py` for pytest discovery as configured by `../cloudfile-hub/pytest.ini`.
- Use `test_<subject>()` functions for Python, `TestCf...` functions for CloudFile Go contracts, `test-cf-*.c` for C harnesses, and `<capability>_matrix.py` for whole-system clients.
- Pair every capability CI workflow `<capability>-e2e.yml` in `.github/workflows/` with its matrix in `tests/e2e/` and, when supported locally, an entry in the `CAPABILITIES` array in `tools/verify-local.sh`.

**Structure:**
```text
cloudfile-docker/
├── docs/{acl-cases.json,fileop-cases.json}       # Shared semantic cases
├── tests/e2e/{smoke,baseline,*_matrix}.py        # Real-stack HTTP clients
├── tests/tools/test-check-upstream-patches.sh    # Tool behavior test
├── tools/{run-checks,verify-local}.sh             # Aggregate runners
├── tools/{preflight-checks,test-bootstrap-settings}.py
└── .github/workflows/{checks,build-and-e2e,*-e2e}.yml

../cloudfile-hub/cloudfile_ext/<capability>/tests/test_*.py
../cloudfile-server/tests/cf-<capability>/{run.sh,test-cf-*.c}
../cloudfile-server/fileserver/*_test.go
```

## Test Structure

**Suite Organization:**
```python
# Pattern from tests/e2e/storage_matrix.py
def check(name, ok, detail=''):
    print('  %s %s' % ('✓' if ok else '✗', name), flush=True)
    return ok

def phase1(base, admin, password, context, state_file):
    passed = check('管理员登录', bool(token), detail)
    passed &= check('上传跨多 block 的文件', ok, detail)
    return passed

def main():
    # argparse -> phase selection -> 0/1 exit
    return 0 if ok else 1
```

```python
# Pattern from ../cloudfile-hub/cloudfile_ext/acl/tests/test_resolver.py
@pytest.mark.parametrize('case,check', list(_flatten()))
def test_shared_cases(case, check):
    got = resolver.resolve(...)
    assert got == check['expect']
```

**Patterns:**
- Set up a real scenario through public APIs, assert positive and negative controls, then delete created repositories where possible; see `tests/e2e/smoke.py` and `tests/e2e/acl_matrix.py`.
- Assert that a feature switch or provider is actually active before testing its behavior; `tests/e2e/sso_matrix.py` and `tests/e2e/fileop_matrix.py` guard against false-green disabled features.
- For state transitions, split into explicit phases and persist the minimum state in a JSON file. `tests/e2e/sso_matrix.py`, `tests/e2e/search_matrix.py`, `tests/e2e/storage_matrix.py`, and `tests/e2e/fileop_matrix.py` use this pattern.
- Run baseline smoke before each capability matrix in `.github/workflows/*-e2e.yml`; a capability must not break the native CE path when enabled.
- Treat expected 403/404/409/423 responses as assertions, not exceptions; the request helpers in `tests/e2e/acl_matrix.py` and `tests/e2e/fileop_matrix.py` preserve HTTP error bodies.

## Mocking

**Framework:** Handwritten fakes and monkeypatching; no repository-wide mocking library.

**Patterns:**
```python
# Pattern from tools/test-bootstrap-settings.py
ns = {
    'get_conf': lambda key, default='': env.get(key, default),
    'cf_enabled': lambda key: env.get(key, 'false').lower() == 'true',
}
exec(compile(ast.Module(body=[node], type_ignores=[]), BOOTSTRAP, 'exec'), ns)
```

- Extract the actual function AST from `scripts/scripts_14.0/bootstrap.py` in `tools/test-bootstrap-settings.py`; do not copy the generator into a fixture.
- Use small fake connection/cursor objects and temporary `sys.modules` injection for configuration-time database behavior in `tools/test-bootstrap-settings.py`.
- Hub pure-policy tests construct in-memory rules and provider stubs under `../cloudfile-hub/cloudfile_ext/**/tests/`; filesystem boundary tests use real `tmp_path` directories and symlinks in `../cloudfile-hub/cloudfile_ext/external_sources/tests/test_paths.py`.
- The write-lifecycle E2E uses the deliberately shipped, default-off fake provider in `../cloudfile-server/common/cf-fileop-test.c`; `tests/e2e/fileop_matrix.py` verifies the provider is selected before asserting journal behavior.

**What to Mock:**
- Mock process-local configuration, clocks, provider responses, and database adapters when testing pure Hub/config logic, following `../cloudfile-hub/cloudfile_ext/sso/tests/` and `tools/test-bootstrap-settings.py`.
- Generate C case headers from `docs/acl-cases.json` and `docs/fileop-cases.json` in temporary directories through `../cloudfile-server/tests/cf-acl/gen-cases.py` and `../cloudfile-server/tests/cf-fileop/gen-cases.py`.

**What NOT to Mock:**
- Do not mock realpath/symlink containment in `../cloudfile-hub/cloudfile_ext/external_sources/tests/test_paths.py`.
- Do not mock REST, WebDAV, upload/download, worker, GC/FSCK, migration, or provider switching in `tests/e2e/*.py` and `.github/workflows/*-e2e.yml`; those tests exist specifically to cross process and protocol boundaries.
- Do not hand-copy generated settings as a fixture; `tools/test-bootstrap-settings.py` must execute source extracted from `scripts/scripts_14.0/bootstrap.py`.

## Fixtures and Factories

**Test Data:**
```python
# Pattern from ../cloudfile-hub/cloudfile_ext/acl/tests/test_resolver.py
for case in data['cases']:
    for check in case['checks']:
        yield pytest.param(case, check, id='%s :: %s' % (...))
```

**Location:**
- ACL truth table: `docs/acl-cases.json`, consumed by `../cloudfile-hub/cloudfile_ext/acl/tests/test_resolver.py`, `../cloudfile-server/tests/cf-acl/gen-cases.py`, and server Go/C tests.
- Write-lifecycle vocabulary and cases: `docs/fileop-cases.json`, consumed by `../cloudfile-server/tests/cf-fileop/gen-cases.py` and `../cloudfile-server/fileserver/cf_fileop_test.go`.
- Real-stack fixtures are created dynamically by `tests/e2e/*.py`; multi-phase scripts persist only repository IDs and content hashes in caller-supplied state files.
- External-service fixtures are local CI services defined by `deploy/compose/docker-compose.yml` and started by workflows such as `.github/workflows/storage-e2e.yml` and `.github/workflows/search-e2e.yml`.

## Coverage

**Requirements:** No line, branch, or mutation coverage threshold is enforced in `cloudfile-docker`, `tools/run-checks.sh`, or `.github/workflows/checks.yml`.

**View Coverage:**
```bash
# No coverage command or generated coverage artifact is configured.
```

- Measure confidence by explicit semantic case counts and real-stack matrices rather than percentage coverage: current fast CI reports 217 Hub tests, 62 C ACL checks, 159 C fileop checks, and 50 `repo-op.c` call-site type checks from `tools/run-checks.sh`.
- When adding a security invariant, encode it as an exhaustive or adversarial test, as in `../cloudfile-hub/cloudfile_ext/acl/tests/test_resolver.py` (`test_never_widens`) and `../cloudfile-hub/cloudfile_ext/external_sources/tests/test_paths.py` (traversal and symlink escape cases).

## Validation Layers

**Fast aggregate (`tools/run-checks.sh`):**
- Audits upstream-modification lists through `tools/check-upstream-patches.sh` and locks warning-only behavior with `tests/tools/test-check-upstream-patches.sh`.
- Runs all Hub extension pytest tests under `../cloudfile-hub/cloudfile_ext/` and accepts pytest exit `5` only when no capability tests exist.
- Discovers server `tests/*/run.sh` dynamically, runs C tests when compiler/glib are available, then runs Go build, vet, and selected `Cf*` contracts under `../cloudfile-server/fileserver/`.
- Validates Compose expansion/profiles, CloudFile shell/Python/JSON syntax, the expected two-hunk build-script fork, generated configuration, and required `release.yaml` keys.
- Reports missing optional tools and the unset C S3 endpoint as visible skips. A skipped `../cloudfile-server/tests/cf-s3/run.sh` is not proof of S3 behavior.

**Static preflight (`tools/preflight-checks.py`):**
- Validates workflow script references, TLS/URL agreement, bootstrap hostname compatibility, pinned Node major, clean build ref behavior, self-contained generated settings, switch-list parity, extension-point documentation, local/CI capability-gate parity, and feature-document freshness.
- `tools/verify-local.sh preflight` runs both `tools/run-checks.sh` and `tools/preflight-checks.py`; `.github/workflows/checks.yml` runs only `tools/run-checks.sh`, so the additional preflight detectors are currently local-only.
- Source inspection shows a current parity mismatch: `.github/workflows/external_sources-e2e.yml` exists, but `tools/verify-local.sh` has no `external_sources` entry in `CAPABILITIES`. `tools/preflight-checks.py::check_capability_gates` is designed to reject exactly this mismatch.

**Baseline build/E2E (`.github/workflows/build-and-e2e.yml`):**
- Builds the release from refs in `release.yaml`, builds `image/cloudfile_14.0/Dockerfile`, starts `deploy/compose/docker-compose.yml` with CloudFile switches off, then runs `tests/e2e/smoke.py` and `tests/e2e/baseline.py`.
- `tests/e2e/smoke.py` covers authentication, account lookup, repository/directory creation, upload/list/download, share link, WebDAV, sync, and cleanup.
- `tests/e2e/baseline.py` proves extension routes/settings exist while capabilities remain disabled, preventing a false-green image where `cloudfile_ext` was never loaded.

**Capability E2E (`.github/workflows/*-e2e.yml`):**
- ACL: `.github/workflows/acl-e2e.yml` + `tests/e2e/acl_matrix.py` cover REST, upload/download, zip, sync, WebDAV, move/copy/rename, no-widening, and admin recovery.
- SSO: `.github/workflows/sso-e2e.yml` + `tests/e2e/sso_matrix.py` cover periodic worker, webhook, apply/remove membership, idempotence, dry-run, and restart-time config rewrite.
- Metadata/tags: `.github/workflows/metadata-e2e.yml` + `tests/e2e/metadata_matrix.py` cover the official metadata service path.
- Audit: `.github/workflows/audit-e2e.yml` + `tests/e2e/audit_matrix.py` cover server update through seafevents to the CloudFile query API.
- External sources: `.github/workflows/external_sources-e2e.yml` + `tests/e2e/external_sources_matrix.py` cover mounted local-path source registration, authorization, browse/download, shadow repository, and write refusal.
- Storage: `.github/workflows/storage-e2e.yml` + `tests/e2e/storage_matrix.py` cover multi-block content, MinIO-backed storage, GC/FSCK, repair refusal while online, offline migration, and post-migration read/write.
- Search: `.github/workflows/search-e2e.yml` + `tests/e2e/search_matrix.py` span SeaSearch, Meilisearch backfill, provider restart, and disabled-feature fallback.
- File lifecycle: `.github/workflows/fileop-e2e.yml` + `tests/e2e/fileop_matrix.py` span observation and refusal phases over write entry points, journal facts, and provider-off regression.

## Current CI Signals

**Observation time:** 2026-08-11 19:57 CST, commit `0134d854520024f9c6fac717c2ddae9efb6809ad` in `cloudfile-docker`.

**Proven on the exact current Docker commit:**
- `.github/workflows/checks.yml` run `31487861638` is green. It executed `tools/run-checks.sh` against current sibling `dev` refs and reported 217 Hub pytest cases passed, 62 C ACL checks passed, 159 C fileop checks passed, 50 write call sites type-checked, Go build/vet/contracts passed, Compose/syntax/config generation passed, and the C S3 integration test visibly skipped because no endpoint was configured.
- `../cloudfile-server/.github/workflows/cloudfile-checks.yml` job `build-c` in run `31484604514` is green on current server commit `ae1428c6b0fe0c5bab183a003a5647018566b16d`; the workflow's aggregate status is red only because its fast job used the older Docker policy where upstream-patch warnings were fatal.
- `../cloudfile-server/.github/workflows/golangci-lint.yml` run `31484604483` is green on current server commit `ae1428c6b0fe0c5bab183a003a5647018566b16d`.
- `../cloudfile-hub/.github/workflows/cloudfile-checks.yml` run `31487345580` is red on current Hub commit `2a6176ecae655da82a43690c86f379f7c4c2c6fe`, but its actual Hub tests and downstream checks passed; the failure is the same now-fixed Docker upstream-patch policy. The later green Docker run is the authoritative fast-gate signal for this three-repository combination.

**Most recent completed whole-system evidence before the current wave:**

| Gate | Source paths | Completed evidence |
|---|---|---|
| Baseline | `.github/workflows/build-and-e2e.yml`, `tests/e2e/smoke.py`, `tests/e2e/baseline.py` | Run `31484601813` green on `bd1e779`: smoke 12/12, baseline 9/9 |
| ACL | `.github/workflows/acl-e2e.yml`, `tests/e2e/acl_matrix.py` | Run `31484601804` green: smoke 12/12, matrix 31/31 |
| SSO | `.github/workflows/sso-e2e.yml`, `tests/e2e/sso_matrix.py` | Run `31484601805` green: smoke 12/12, phases 15/15 and 11/11 |
| Metadata/tags | `.github/workflows/metadata-e2e.yml`, `tests/e2e/metadata_matrix.py` | Run `31484601781` green |
| Audit | `.github/workflows/audit-e2e.yml`, `tests/e2e/audit_matrix.py` | Run `31484601773` green |
| External sources | `.github/workflows/external_sources-e2e.yml`, `tests/e2e/external_sources_matrix.py` | Run `31484601808` green |
| S3/storage | `.github/workflows/storage-e2e.yml`, `tests/e2e/storage_matrix.py` | Run `31484601817` green: smoke 12/12 and both migration phases passed |
| File lifecycle | `.github/workflows/fileop-e2e.yml`, `tests/e2e/fileop_matrix.py` | Run `31484601784` red: phase 1 was 19/21; bulk delete returned 404 and produced no expected fact |
| Search | `.github/workflows/search-e2e.yml`, `tests/e2e/search_matrix.py` | Run `31484601779` red: SeaSearch phase 1 returned both files for alpha- and beta-specific queries |

**In progress on the exact current Docker commit:**
- `.github/workflows/build-and-e2e.yml` plus all eight capability workflows under `.github/workflows/*-e2e.yml` were in progress at observation time. Until they complete, the exact current commit has fast-gate proof but not completed whole-system proof.

## Test Types

**Unit Tests:**
- Hub pure-policy and provider tests under `../cloudfile-hub/cloudfile_ext/**/tests/` are the broadest unit layer; the current quick gate proves 217 cases pass without installing Django.
- Server pure C policy tests under `../cloudfile-server/tests/cf-acl/` and `../cloudfile-server/tests/cf-fileop/` compile only glib-dependent code, keeping them fast and portable.
- `tools/test-bootstrap-settings.py` is a source-level configuration regression suite, not a pytest suite.

**Integration Tests:**
- `tools/run-checks.sh` is cross-repository integration at source/config level, while `.github/workflows/build-and-e2e.yml` and `.github/workflows/*-e2e.yml` are service-level integration.
- `../cloudfile-server/tests/cf-s3/run.sh` is an integration test only when `CF_S3_TEST_ENDPOINT` is set; the standard fast CI currently skips it. `.github/workflows/storage-e2e.yml` supplies the stronger real-stack storage proof.
- `../cloudfile-server/.github/workflows/cloudfile-checks.yml` job `build-c` performs the Linux full C build that macOS cannot reproduce reliably.

**E2E Tests:**
- Python clients in `tests/e2e/` exercise the built image over HTTPS, public REST/upload/download APIs, WebDAV, worker execution, and direct container CLI where required.
- E2E workflows build from `release.yaml` refs, so a Docker-repository PR tests the referenced Hub/server `dev` tips. Adjacent Hub/server PR workflows in `../cloudfile-hub/.github/workflows/cloudfile-checks.yml` and `../cloudfile-server/.github/workflows/cloudfile-checks.yml` run the fast gate but do not run these whole-system Docker matrices against the PR ref.

## Missing or Partial Coverage

- No coverage percentage is collected by `.github/workflows/checks.yml`, `tools/run-checks.sh`, or the adjacent CloudFile workflows.
- The quick Go gate in `tools/run-checks.sh` intentionally does not run `go test ./...`; MySQL-dependent upstream tests such as `../cloudfile-server/fileserver/repomgr/repomgr_test.go` require the full CI environment.
- The quick Hub gate installs only pytest, causing `../cloudfile-hub/pytest.ini`'s `DJANGO_SETTINGS_MODULE` option to emit an unknown-option warning; this is intentional for Django-free `cloudfile_ext` policy tests but is not proof of the full upstream Seahub suite under `../cloudfile-hub/tests/`.
- `tools/preflight-checks.py` is not invoked by `.github/workflows/checks.yml`, and current source lists expose a real local/CI capability mismatch for external sources.
- `tests/e2e/fileop_matrix.py` and `tests/e2e/search_matrix.py` have current completed red evidence; their failed assertions must not be described as covered behavior until a green whole-system run exists.
- `tests/e2e/metadata_matrix.py` and `tests/e2e/audit_matrix.py` print pass/fail summaries without numbered totals, unlike `tests/e2e/acl_matrix.py`, `tests/e2e/sso_matrix.py`, `tests/e2e/smoke.py`, and `tests/e2e/baseline.py`.
- Manual load tooling under `../cloudfile-server/tests/test_upload/` performs no assertions, does not clean up, and is not wired into workflows (`../cloudfile-server/README.testing.md`).
- Full-system workflows are expensive single jobs with 120-minute timeouts under `.github/workflows/*-e2e.yml`; baseline, audit, and metadata workflows do not run on pull requests, and adjacent repository PRs do not get a matching full-system matrix with the PR ref.

## Common Patterns

**Async Testing:**
```python
# Pattern used by tests/e2e/sso_matrix.py
deadline = time.time() + timeout
while time.time() < deadline:
    status, body = admin.api('/api/v2.1/admin/cloudfile/sso/sync/')
    if status == 200 and data.get('last_status') == 'ok':
        return
    time.sleep(2)
record('worker', '周期 worker 已完成首次 SSO 同步', False, last)
```

- Poll with a bounded deadline and retain the last response for diagnostics, as in `tests/e2e/sso_matrix.py`, `tests/e2e/search_matrix.py`, and `tests/e2e/smoke.py`.
- Use Compose `--wait --wait-timeout` for service health where supported, as in `.github/workflows/storage-e2e.yml` and `.github/workflows/search-e2e.yml`; still poll the public API because container health alone does not prove application readiness.

**Error Testing:**
```python
# Pattern used by ../cloudfile-hub/cloudfile_ext/external_sources/tests/test_paths.py
with pytest.raises(paths.UnsafePath):
    paths.resolve(root, '/sub/../../outside/passwd', allowed)
```

```python
# Pattern used by tests/e2e/acl_matrix.py
status, body = client.api(path)
record('REST API', '读取被拒', status in (403, 404),
       'status=%s %s' % (status, body[:160]))
```

- Test both refusal and a nearby allowed control so a broken endpoint cannot masquerade as enforcement; this pairing is central to `tests/e2e/acl_matrix.py` and `tests/e2e/fileop_matrix.py`.
- For safety gates, assert the failure message as well as non-zero status when operators depend on it, as `.github/workflows/storage-e2e.yml` does for online `seaf-fsck.sh --repair` refusal.

---

*Testing analysis: 2026-08-11*

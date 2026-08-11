# Coding Conventions

**Analysis Date:** 2026-08-11

## Naming Patterns

**Files:**
- Name operator scripts with lowercase kebab-case and a `.sh` suffix, as in `tools/run-checks.sh`, `tools/verify-local.sh`, and `tools/check-upstream-patches.sh`.
- Name Python utilities with lowercase kebab-case when they are standalone commands, as in `tools/preflight-checks.py` and `build/cloudfile_14.0/read-manifest.py`; name importable or test-oriented Python modules with snake_case, as in `scripts/scripts_14.0/cluster_conf_init.py` and `tests/e2e/external_sources_matrix.py`.
- Name whole-system capability tests `<capability>_matrix.py` under `tests/e2e/` and pair them with `<capability>-e2e.yml` under `.github/workflows/`, as shown by `tests/e2e/acl_matrix.py` and `.github/workflows/acl-e2e.yml`.
- Encode retained upstream generations in directory names such as `scripts/scripts_14.0/`, `build/seafile_14.0/`, and `image/pro_seafile_14.0/`; put current CloudFile-specific build code in `build/cloudfile_14.0/` and `image/cloudfile_14.0/`.
- In the adjacent server fork, prefix CloudFile C files and symbols with `cf-` / `cf_`, as in `../cloudfile-server/common/cf-fileop.c`, `../cloudfile-server/common/cf_fileop_prepare`, and `../cloudfile-server/fileserver/cf_fileop.go`.
- In the adjacent Hub fork, put new backend code under `../cloudfile-hub/cloudfile_ext/<capability>/` and frontend code under `../cloudfile-hub/frontend/src/cloudfile/`; do not add capability code to upstream-owned packages unless an extension seam cannot express it (`../cloudfile-hub/AGENTS.md`).

**Functions:**
- Use `snake_case` for Python functions, including private helpers prefixed with `_`, as in `tests/e2e/sso_matrix.py` (`wait_ready`, `check_enabled`, `_webhook_token`).
- Use `snake_case` for shell functions and capability hooks, as in `tools/verify-local.sh` (`build_dist`, `cap_storage_run`, `cap_search_env`).
- Use `snake_case` with a `cf_` prefix for CloudFile C APIs in `../cloudfile-server/common/`; use ordinary Go conventions in `../cloudfile-server/fileserver/`, with lower camel case for internal helpers and `TestCf...` for tests.
- Keep executable Python modules behind `main()` and `if __name__ == '__main__':`, as in `build/cloudfile_14.0/read-manifest.py`, `tools/preflight-checks.py`, and every `tests/e2e/*.py` script.

**Variables:**
- Reserve uppercase names for process configuration and constants: `CF_*` environment variables in `tools/verify-local.sh`, `VERSION` / `IMAGE` / `PROJECT` in `tools/verify-local.sh`, and `CONTENT_SIZE` / `FILENAME` in `tests/e2e/storage_matrix.py`.
- Use lowercase shell variables for resolved paths and working state (`repo`, `workspace`, `hub`, `server`) and quote expansions whenever they become command arguments, following `tools/run-checks.sh` and `tools/verify-local.sh`.
- Use descriptive snake_case for Python local state (`state_file`, `worker_timeout`, `upload_url`) in `tests/e2e/`; avoid introducing a second spelling for an existing wire or manifest key.

**Types:**
- Use PascalCase for Python classes such as `Client` in `tests/e2e/sso_matrix.py` and `Project` in `build/cloudfile_14.0/cloudfile-build.py`.
- The Docker repository mostly uses dynamic Python without annotations in `tools/*.py` and `tests/e2e/*.py`; match the surrounding module rather than introducing isolated typing syntax.
- Keep cross-language vocabulary literal and test it in both directions, as `../cloudfile-server/fileserver/cf_fileop_test.go` does for C constants, Go constants, JSON keys, and error codes.

## Code Style

**Formatting:**
- No repository-level formatter configuration is present in `cloudfile-docker`; `tools/run-checks.sh` enforces parseability with `bash -n` and `python3 -m py_compile`, not formatting.
- Use four-space indentation in Python and C. CloudFile C code follows the upstream style documented in `../cloudfile-server/AGENTS.md`, including `snake_case`, 4-space indentation, and the existing C mode header.
- Use conventional `gofmt` formatting for files under `../cloudfile-server/fileserver/`; CI applies `golangci-lint` through `../cloudfile-server/.github/workflows/golangci-lint.yml`.
- Prefer single-quoted Python strings in new Docker-repository scripts because that is the dominant local style in `tests/e2e/*.py` and `tools/test-bootstrap-settings.py`; preserve an upstream file's style when editing copied code such as `build/cloudfile_14.0/cloudfile-build.py`.
- Keep E2E clients standard-library-only (`argparse`, `urllib`, `json`, `ssl`) as demonstrated across `tests/e2e/*.py`; workflows can run them without installing application dependencies.

**Shell:**
- Start new shell scripts with `#!/bin/bash`. Use `set -euo pipefail` for fail-fast tests such as `tests/tools/test-check-upstream-patches.sh`; use the explicit failure-accumulation pattern from `tools/run-checks.sh` when all checks must run before exit.
- Use `mktemp -d` or `mktemp` and `trap` cleanup for temporary state, following `tests/tools/test-check-upstream-patches.sh`, `../cloudfile-server/tests/cf-acl/run.sh`, and `tools/run-checks.sh`.
- Validate changed CloudFile shell scripts with the scoped `bash -n` loop in `tools/run-checks.sh`; do not sweep generated build trees or retained upstream copies that are explicitly pruned there.

**Linting:**
- `cloudfile-docker` has no ShellCheck, Ruff, Black, Flake8, mypy, or coverage configuration. Treat `tools/run-checks.sh`, `tools/preflight-checks.py`, and review as the effective lint/validation layer.
- The adjacent Hub fork has `../cloudfile-hub/pylintrc`, but the CloudFile quick gate in `tools/run-checks.sh` runs `pytest` only and does not run pylint.
- The adjacent server fork runs `go vet ./...` from `tools/run-checks.sh` and `golangci-lint` from `../cloudfile-server/.github/workflows/golangci-lint.yml`; C warnings are enabled directly in `../cloudfile-server/tests/cf-acl/run.sh` and `../cloudfile-server/tests/cf-fileop/run.sh` with `-Wall -Wextra`.

## Import Organization

**Order:**
1. Put Python standard-library imports first, as in `tests/e2e/storage_matrix.py` and `tools/preflight-checks.py`.
2. Put third-party imports next, separated by a blank line; `pytest` precedes local imports in `../cloudfile-hub/cloudfile_ext/acl/tests/test_resolver.py`.
3. Put project imports last, as in `from cloudfile_ext.acl import resolver` in `../cloudfile-hub/cloudfile_ext/acl/tests/test_resolver.py`.

**Path Aliases:**
- No Python path alias is configured in `cloudfile-docker`; executable scripts resolve paths from `__file__` or from the three-repository sibling layout in `tools/run-checks.sh` and `tools/verify-local.sh`.
- Shared semantic fixtures resolve to `docs/acl-cases.json` and `docs/fileop-cases.json` from adjacent Hub and server tests; allow explicit `CF_ACL_CASES` / `CF_FILEOP_CASES` overrides as in `../cloudfile-hub/cloudfile_ext/acl/tests/test_resolver.py` and `../cloudfile-server/tests/cf-fileop/run.sh`.
- Avoid module-level Django imports in pure Hub policy modules. `../cloudfile-hub/AGENTS.md` requires capability `register()` functions to import feature plumbing lazily so `../cloudfile-hub/cloudfile_ext/` tests stay Django-free.

## Error Handling

**Patterns:**
- In E2E HTTP helpers, convert `urllib.error.HTTPError` into `(status, body)` rather than raising because denial statuses are assertions; convert transport errors to status `0`, following `tests/e2e/acl_matrix.py` and `tests/e2e/sso_matrix.py`.
- Fail immediately with `sys.exit(...)` when fixture construction or authentication makes later assertions meaningless, as in `tests/e2e/acl_matrix.py`; accumulate independent assertions through `record()` / `check()` and exit `1` only after printing failures.
- Return integer status from Python `main()` and pass it to `sys.exit`, following `tools/preflight-checks.py`, `tests/e2e/audit_matrix.py`, and `tests/e2e/storage_matrix.py`.
- In shell orchestrators, preserve each check's exit status, print a named result, and aggregate failures using `run()` / `skip()` from `tools/run-checks.sh`; never report an unavailable tool or test endpoint as a pass without a visible skip message.
- Fail closed for permission and policy decisions in adjacent code. The invariants are documented in `../cloudfile-hub/AGENTS.md` and `../cloudfile-server/AGENTS.md` and are exercised by `../cloudfile-hub/cloudfile_ext/acl/tests/test_resolver.py` and `../cloudfile-server/tests/cf-acl/run.sh`.

## Logging

**Framework:** Console output for repository scripts; `seaf_warning()` / `seaf_message()` for adjacent C code.

**Patterns:**
- Prefix check output with visible `✓`, `✗`, or `⊘` and include failure detail only where it aids diagnosis, following `tools/run-checks.sh`, `tools/preflight-checks.py`, and `tests/e2e/sso_matrix.py`.
- Group long workflows with named GitHub Actions steps and dump component logs only on failure, as in `.github/workflows/build-and-e2e.yml` and `.github/workflows/search-e2e.yml`.
- Redact or omit secrets from diagnostics. Workflow test credentials are ephemeral fixtures, but new logs in `.github/workflows/*.yml` and `tools/verify-local.sh` must not print deployment credentials or local environment files.

## Comments

**When to Comment:**
- Explain the integration hazard or invariant, not the visible statement. `tools/preflight-checks.py`, `tools/run-checks.sh`, and `.github/workflows/fileop-e2e.yml` preserve the concrete failure mode each guard prevents.
- Document deliberate skips and scope exclusions beside the command, as `tools/run-checks.sh` does for upstream MySQL-dependent Go tests and generated build trees.
- Keep shared semantic decisions in `docs/acl-cases.json`, `docs/fileop-cases.json`, `docs/fileop-lifecycle.md`, and `docs/EXTENSION-POINTS.md`; implementation comments must not become a competing specification.

**Language:**
- The repository rule in `AGENTS.md` is English for code, comments, and commit messages, and Chinese for Markdown documentation. Existing operator-facing scripts in `tools/` and `tests/e2e/` contain Chinese docstrings, labels, and historical comments; preserve a file's established user-facing language while using English for new implementation comments.

**JSDoc/TSDoc:**
- Not applicable to the Docker repository. Python module and function docstrings are used selectively in `tools/preflight-checks.py` and `tests/e2e/*.py`; use them for contracts, invariants, and non-obvious orchestration.

## Function Design

**Size:**
- Keep protocol helpers small (`request`, `json_body`, `wait_ready`) and isolate scenario phases, following `tests/e2e/sso_matrix.py`, `tests/e2e/search_matrix.py`, and `tests/e2e/storage_matrix.py`.
- Long workflow logic belongs in named shell functions such as `cap_storage_run` and `cap_fileop_run` in `tools/verify-local.sh`, not in the command dispatch block.

**Parameters:**
- Pass runtime endpoints, identities, and state paths through `argparse` in `tests/e2e/*.py`; do not hard-code deployment-specific endpoints.
- Use keyword defaults for optional E2E behavior such as `context=None`, `headers=None`, and `timeout=600`, following `tests/e2e/storage_matrix.py` and `tests/e2e/sso_matrix.py`.
- Use explicit environment overrides for cross-repository paths and build refs (`CF_*_REF`, `CF_*_CASES`) as defined by `release.yaml`, `tools/verify-local.sh`, and adjacent test runners.

**Return Values:**
- E2E request helpers return `(status, body)` so callers can assert both success and expected denial, as in `tests/e2e/smoke.py` and `tests/e2e/acl_matrix.py`.
- Scenario functions return booleans or record into a shared result list; `main()` maps the aggregate to exit `0` or `1`, as in `tests/e2e/storage_matrix.py` and `tests/e2e/sso_matrix.py`.

## Module Design

**Exports:**
- `cloudfile-docker` validation code is command-oriented rather than library-oriented: keep executable orchestration in `tools/` and whole-system assertions in `tests/e2e/`.
- Keep pure cross-layer algorithms importable and dependency-light in `../cloudfile-hub/cloudfile_ext/<capability>/` and `../cloudfile-server/common/cf-*.c`; keep registration, database, and process wiring in separate modules as required by both adjacent `AGENTS.md` files.
- Make configuration generation idempotent and test the exact source implementation. `tools/test-bootstrap-settings.py` extracts functions from `scripts/scripts_14.0/bootstrap.py` with `ast` instead of maintaining copied fixtures.

**Barrel Files:**
- No barrel-file convention is used in `cloudfile-docker`. In the Hub fork, keep capability package `__init__.py` lightweight and perform runtime registration through `register()` and `../cloudfile-hub/cloudfile_ext/apps.py`.

## Cross-Repository Change Discipline

- Treat `release.yaml` as the only build-ref authority; do not hard-code Hub or server refs in `build/cloudfile_14.0/cloudfile-build.sh` or `.github/workflows/*.yml` except explicit workflow-dispatch overrides.
- Change cross-layer semantics in this order: specification under `docs/`, shared JSON cases under `docs/`, then Hub and server implementations. This rule is enforced by `AGENTS.md`, `../cloudfile-hub/AGENTS.md`, and `../cloudfile-server/AGENTS.md`.
- Register modifications to upstream-owned files through `tools/check-upstream-patches.sh` and the lists documented by `BRANCHING.md`; its current policy is warning-only, while `tests/tools/test-check-upstream-patches.sh` locks that warning behavior.

---

*Convention analysis: 2026-08-11*

#!/usr/bin/env python3
"""Capability manifest: dynamic parity and four-state result classifier.

Single source of truth for which capabilities exist, their feature switches,
their matrix file, their CI workflow, and whether they are required. Both
``tools/verify-local.sh`` and ``tools/preflight-checks.py`` consume this file
through this module, so local and CI never drift -- the bug that made the gate
red (external_sources present in CI but not in the local CAPABILITIES table)
cannot recur.

Status vocabulary is exactly: PASS, SKIP, FAIL, NOT RUN. PASS requires an
executed run with assertions passed AND a non-empty evidence id; anything else
is one of the other three states.

CLI (no third-party dependencies, stdlib only):

    python3 tools/capability_manifest.py validate [repo]
    python3 tools/capability_manifest.py list      [repo] [--field switch|matrix|workflow]
    python3 tools/capability_manifest.py classify  '<json record>'
    python3 tools/capability_manifest.py phase-gate <source-sha> <image-digest> \
        --switch-state '<json>' --result '<json>'

Exit codes:
    validate:    0 if manifest == matrices == workflows, else 1
    list:        0 always (prints requested field per capability)
    classify:    0 always (prints status, logs FAIL/NOT RUN to stderr)
    phase-gate:  0 if tuple complete and both baselines PASS, else 1
"""

import argparse
import hashlib
import json
import os
import re
import sys

STATUS_VALUES = ("PASS", "SKIP", "FAIL", "NOT RUN")

DEFAULT_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_REL = os.path.join("config", "capabilities.json")
E2E_DIR_REL = "tests/e2e"
WORKFLOW_DIR_REL = ".github/workflows"


# --------------------------------------------------------------------------- #
# Loading and discovery
# --------------------------------------------------------------------------- #

def manifest_path(repo):
    return os.path.join(repo, MANIFEST_REL)


def load_manifest(repo=DEFAULT_REPO):
    with open(manifest_path(repo), encoding="utf-8") as fp:
        data = json.load(fp)
    return data


def discover_matrix_ids(repo=DEFAULT_REPO):
    """Capability IDs derived from tests/e2e/<id>_matrix.py filenames."""
    e2e_dir = os.path.join(repo, E2E_DIR_REL)
    ids = set()
    if not os.path.isdir(e2e_dir):
        return ids
    for name in os.listdir(e2e_dir):
        m = re.match(r"^(.+)_matrix\.py$", name)
        if m:
            ids.add(m.group(1))
    return ids


def discover_workflow_ids(repo=DEFAULT_REPO):
    """Capability IDs derived from .github/workflows/<id>-e2e.yml filenames.

    ``build-and-e2e.yml`` is the baseline gate (all switches off), not a
    capability gate, so it is excluded.
    """
    wf_dir = os.path.join(repo, WORKFLOW_DIR_REL)
    ids = set()
    if not os.path.isdir(wf_dir):
        return ids
    for name in os.listdir(wf_dir):
        m = re.match(r"^(.+)-e2e\.yml$", name)
        if m and m.group(1) != "build-and":
            ids.add(m.group(1))
    return ids


# --------------------------------------------------------------------------- #
# Result classifier -- four-state truth
# --------------------------------------------------------------------------- #

def classify_result(record):
    """Return one of PASS, SKIP, FAIL, NOT RUN for a capability record.

    Truth table (status vocabulary is exact, do not introduce new spellings):

        executed + assertions_passed + evidence_id  -> PASS
        executed + not assertions_passed            -> FAIL
        not executed + required + dep unavailable   -> FAIL
        not executed + optional (has reason)        -> SKIP
        not executed + required + no reason         -> FAIL  (never silently SKIP)
        missing record (None)                       -> NOT RUN
    """
    if record is None:
        return "NOT RUN"

    required = bool(record.get("required", True))

    if record.get("executed"):
        if record.get("assertions_passed") and record.get("evidence_id"):
            return "PASS"
        return "FAIL"

    # Not executed.
    if not required:
        # Optional capability: a reason means intentional SKIP.
        if record.get("reason"):
            return "SKIP"
        # Optional with no reason is still suspicious; treat as NOT RUN so the
        # gate reports it rather than hiding it behind a green SKIP.
        return "NOT RUN"

    # Required but not executed: missing dependency is a hard FAIL; anything
    # else (no evidence at all) is NOT RUN only if we genuinely have no record
    # context, but here we DO have a record -- so required + not executed is
    # always blocking. Distinguish dep-missing (FAIL) from no-attempt (NOT RUN).
    deps = record.get("dependencies") or []
    dep_unavailable = any(not d.get("available", True) for d in deps)
    if dep_unavailable:
        return "FAIL"
    if record.get("reason"):
        # Required, not executed, no missing dependency but a reason given:
        # the capability was never attempted. NOT RUN blocks the gate.
        return "NOT RUN"
    return "FAIL"


def aggregate_exit_code(records, required=None):
    """Non-zero if any required capability is FAIL or NOT RUN.

    ``records`` is a list of dicts with at least ``capability`` and ``status``.
    ``required`` optional set of capability IDs considered required; defaults
    to all (matches the manifest default).
    """
    if required is None:
        required = {r.get("capability") for r in records}
    for rec in records:
        if rec.get("capability") in required and rec.get("status") in (
            "FAIL",
            "NOT RUN",
        ):
            return 1
    return 0


# --------------------------------------------------------------------------- #
# Phase-gate tuple identity
# --------------------------------------------------------------------------- #

def build_tuple_id(source_sha, image_digest):
    """Stable identity for (source SHA, image digest) under the phase gate."""
    raw = "%s|%s" % (source_sha or "", image_digest or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def is_phase_gate_complete(gate):
    """True iff the gate ran both baselines on one tuple with all switches off.

    Either baseline failing, switches being on, or one of the two scripts
    missing all make the gate incomplete (blocking).
    """
    if not gate:
        return False
    if not gate.get("all_switches_off"):
        return False
    if not gate.get("tuple_id"):
        return False
    runs = {r.get("script"): r.get("status") for r in gate.get("runs", [])}
    scripts = {"smoke.py", "baseline.py"}
    if set(runs) != scripts:
        return False
    return all(runs[s] == "PASS" for s in scripts)


# --------------------------------------------------------------------------- #
# CLI subcommands
# --------------------------------------------------------------------------- #

def _print_validation(repo):
    manifest = load_manifest(repo)
    manifest_ids = {cap["id"] for cap in manifest["capabilities"]}
    matrix_ids = discover_matrix_ids(repo)
    workflow_ids = discover_workflow_ids(repo)

    print("manifest : %s" % ", ".join(sorted(manifest_ids)))
    print("matrices : %s" % ", ".join(sorted(matrix_ids)))
    print("workflows: %s" % ", ".join(sorted(workflow_ids)))

    problems = []
    if manifest_ids != matrix_ids:
        problems.append(
            "manifest vs matrices drift "
            "(manifest only: %s, matrix only: %s)"
            % (
                sorted(manifest_ids - matrix_ids),
                sorted(matrix_ids - manifest_ids),
            )
        )
    if manifest_ids != workflow_ids:
        problems.append(
            "manifest vs workflows drift "
            "(manifest only: %s, workflow only: %s)"
            % (
                sorted(manifest_ids - workflow_ids),
                sorted(workflow_ids - manifest_ids),
            )
        )

    # Each manifest entry must point at a real matrix file and a real workflow.
    for cap in manifest["capabilities"]:
        if not os.path.isfile(os.path.join(repo, cap["matrix"])):
            problems.append(
                "%s: matrix file missing: %s" % (cap["id"], cap["matrix"])
            )
        wf = os.path.join(repo, WORKFLOW_DIR_REL, cap["workflow"])
        if not os.path.isfile(wf):
            problems.append(
                "%s: workflow file missing: %s" % (cap["id"], cap["workflow"])
            )

    return problems


def cmd_validate(args):
    repo = args.repo or DEFAULT_REPO
    problems = _print_validation(repo)
    if problems:
        for p in problems:
            print("FAIL: %s" % p, file=sys.stderr)
        return 1
    print("OK: manifest, matrices, and workflows agree (%d capabilities)"
          % len(load_manifest(repo)["capabilities"]))
    return 0


def cmd_list(args):
    repo = args.repo or DEFAULT_REPO
    manifest = load_manifest(repo)
    for cap in manifest["capabilities"]:
        if args.field == "switch":
            print(" ".join(cap.get("feature_switches", [])))
        elif args.field == "matrix":
            print(cap["matrix"])
        elif args.field == "workflow":
            print(cap["workflow"])
        elif args.field == "id":
            print(cap["id"])
        else:
            # Default: pipe-delimited row matching the legacy verify-local
            # CAPABILITIES table shape: id|switches|matrix
            switches = " ".join(cap.get("feature_switches", []))
            print("%s|%s|%s" % (cap["id"], switches, cap["matrix"]))
    return 0


def cmd_classify(args):
    record = json.loads(args.record)
    status = classify_result(record)
    print(status)
    return 0


def cmd_phase_gate(args):
    gate = {
        "tuple_id": build_tuple_id(args.source_sha, args.image_digest),
        "all_switches_off": _all_switches_off(args.switch_state),
        "runs": json.loads(args.result) if args.result else [],
    }
    complete = is_phase_gate_complete(gate)
    print(json.dumps(gate, sort_keys=True))
    if complete:
        print("OK: phase gate complete (tuple=%s)" % gate["tuple_id"])
        return 0
    print("FAIL: phase gate incomplete", file=sys.stderr)
    return 1


def _all_switches_off(switch_state_json):
    """switch_state_json is a dict of CF_ENABLE_* -> bool/string.

    All switches off means every declared feature switch is false/empty.
    """
    if not switch_state_json:
        return True
    state = json.loads(switch_state_json)
    for value in state.values():
        if isinstance(value, bool):
            if value:
                return False
        elif isinstance(value, str):
            if value.strip().lower() not in ("", "false", "0", "off", "no"):
                return False
        elif value:  # any non-empty non-string non-bool truthy
            return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="dynamic parity check")
    p_val.add_argument("repo", nargs="?", default=None)
    p_val.set_defaults(func=cmd_validate)

    p_list = sub.add_parser("list", help="list capability rows")
    p_list.add_argument("repo", nargs="?", default=None)
    p_list.add_argument(
        "--field",
        choices=["id", "switch", "matrix", "workflow"],
        default=None,
    )
    p_list.set_defaults(func=cmd_list)

    p_cls = sub.add_parser("classify", help="classify a single record")
    p_cls.add_argument("record", help="JSON record")
    p_cls.set_defaults(func=cmd_classify)

    p_pg = sub.add_parser("phase-gate", help="phase-gate tuple check")
    p_pg.add_argument("source_sha")
    p_pg.add_argument("image_digest")
    p_pg.add_argument(
        "--switch-state",
        default=None,
        help='JSON dict of CF_ENABLE_* -> value; empty means all off',
    )
    p_pg.add_argument(
        "--result",
        default=None,
        help='JSON list of {"script":..., "status":...} runs',
    )
    p_pg.set_defaults(func=cmd_phase_gate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Wave 0 contract tests for the capability manifest and four-state classifier.

These tests run BEFORE the implementation module exists and must fail red -- not
with ImportError syntax errors, but with assertion failures that name the
contract. They lock:

  - dynamic capability parity (manifest == matrices == workflows)
  - the four-state PASS/SKIP/FAIL/NOT RUN truth table
  - the phase-gate tuple identity (same source SHA + image digest) running
    smoke.py and baseline.py back-to-back with every CF_ENABLE_* disabled

Run:

    python3 tests/tools/test-capability-manifest.py

Implementation lives in tools/capability_manifest.py. The import below is
deferred so that a missing module surfaces as a named contract failure instead
of a traceback during collection.
"""

import json
import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "tools"))

MANIFEST_PATH = os.path.join(REPO, "config", "capabilities.json")
WORKFLOW_DIR = os.path.join(REPO, ".github", "workflows")
E2E_DIR = os.path.join(REPO, "tests", "e2e")


def _load_manifest():
    """Load canonical capability declarations from config/capabilities.json."""
    with open(MANIFEST_PATH, encoding="utf-8") as fp:
        return json.load(fp)


def _discover_matrix_capability_ids():
    """Derive capability IDs from tests/e2e/<id>_matrix.py filenames.

    Dynamic by design: adding a new matrix file automatically extends the
    parity requirement, so a future capability cannot silently drift past the
    gate the way external_sources did.
    """
    ids = set()
    if not os.path.isdir(E2E_DIR):
        return ids
    for name in os.listdir(E2E_DIR):
        m = re.match(r"^(.+)_matrix\.py$", name)
        if m:
            ids.add(m.group(1))
    return ids


def _discover_workflow_capability_ids():
    """Derive capability IDs from .github/workflows/<id>-e2e.yml filenames.

    `build-and-e2e.yml` is the baseline gate (all switches off), not a
    capability gate, so it is excluded -- mirroring preflight-checks.py.
    """
    ids = set()
    if not os.path.isdir(WORKFLOW_DIR):
        return ids
    for name in os.listdir(WORKFLOW_DIR):
        m = re.match(r"^(.+)-e2e\.yml$", name)
        if m and m.group(1) != "build-and":
            ids.add(m.group(1))
    return ids


class ManifestParityTests(unittest.TestCase):
    """The manifest, the matrices, and the workflows must agree as sets."""

    def test_manifest_file_exists(self):
        self.assertTrue(
            os.path.isfile(MANIFEST_PATH),
            "config/capabilities.json is the single machine-readable capability "
            "declaration; it is currently missing.",
        )

    def test_manifest_ids_match_matrices_and_workflows(self):
        manifest = _load_manifest()
        manifest_ids = {cap["id"] for cap in manifest["capabilities"]}
        matrix_ids = _discover_matrix_capability_ids()
        workflow_ids = _discover_workflow_capability_ids()

        # external_sources specifically: the path that is RED today. If this
        # assertion ever drops the capability from any source, the test must
        # name it.
        self.assertIn(
            "external_sources",
            manifest_ids,
            "external_sources must be declared in the manifest -- its omission "
            "is exactly the drift that made the gate red.",
        )
        self.assertIn(
            "external_sources",
            matrix_ids,
            "tests/e2e/external_sources_matrix.py must exist.",
        )
        self.assertIn(
            "external_sources",
            workflow_ids,
            ".github/workflows/external_sources-e2e.yml must exist.",
        )

        self.assertEqual(
            manifest_ids,
            matrix_ids,
            "manifest capabilities differ from discovered matrices; "
            "missing from manifest: %s; missing from matrices: %s"
            % (
                sorted(matrix_ids - manifest_ids),
                sorted(manifest_ids - matrix_ids),
            ),
        )
        self.assertEqual(
            manifest_ids,
            workflow_ids,
            "manifest capabilities differ from discovered workflows; "
            "missing from manifest: %s; missing from workflows: %s"
            % (
                sorted(workflow_ids - manifest_ids),
                sorted(manifest_ids - workflow_ids),
            ),
        )


class ResultClassifierTests(unittest.TestCase):
    """Four-state truth: PASS, SKIP, FAIL, NOT RUN. Nothing else is PASS."""

    def _classify(self, record):
        try:
            from capability_manifest import classify_result
        except ImportError as exc:
            self.fail(
                "tools/capability_manifest.py must define classify_result(); "
                "got ImportError: %s" % exc
            )
        return classify_result(record)

    def test_pass_requires_executed_assertions_and_evidence(self):
        status = self._classify(
            {
                "executed": True,
                "assertions_passed": True,
                "evidence_id": "smoke@tuple-abc",
                "required": True,
            }
        )
        self.assertEqual(status, "PASS")

    def test_executed_without_evidence_is_not_pass(self):
        status = self._classify(
            {
                "executed": True,
                "assertions_passed": True,
                "evidence_id": None,
                "required": True,
            }
        )
        self.assertNotEqual(status, "PASS")

    def test_required_dependency_missing_is_fail(self):
        status = self._classify(
            {
                "executed": False,
                "required": True,
                "dependencies": [{"available": False}],
                "reason": "required dependency unavailable",
            }
        )
        self.assertEqual(status, "FAIL")

    def test_optional_with_reason_is_skip(self):
        status = self._classify(
            {
                "executed": False,
                "required": False,
                "reason": "optional capability, runner dependency absent",
            }
        )
        self.assertEqual(status, "SKIP")

    def test_missing_record_is_not_run(self):
        status = self._classify(None)
        self.assertEqual(status, "NOT RUN")

    def test_assertions_failed_is_fail(self):
        status = self._classify(
            {
                "executed": True,
                "assertions_passed": False,
                "evidence_id": "search@tuple-abc",
                "required": True,
            }
        )
        self.assertEqual(status, "FAIL")

    def test_status_vocabulary_is_exact(self):
        allowed = {"PASS", "SKIP", "FAIL", "NOT RUN"}
        for record in [
            {"executed": True, "assertions_passed": True,
             "evidence_id": "x", "required": True},
            {"executed": False, "required": True,
             "dependencies": [{"available": False}]},
            {"executed": False, "required": False, "reason": "opt"},
            None,
        ]:
            self.assertIn(self._classify(record), allowed)


class AggregateExitCodeTests(unittest.TestCase):
    """Required FAIL or NOT RUN must produce a non-zero aggregate exit code."""

    def test_required_fail_nonzero(self):
        try:
            from capability_manifest import aggregate_exit_code
        except ImportError as exc:
            self.fail(
                "tools/capability_manifest.py must define "
                "aggregate_exit_code(): %s" % exc
            )
        records = [
            {"capability": "search", "status": "FAIL"},
            {"capability": "acl", "status": "PASS"},
        ]
        self.assertNotEqual(aggregate_exit_code(records), 0)

    def test_all_pass_zero(self):
        from capability_manifest import aggregate_exit_code
        records = [{"capability": "acl", "status": "PASS"}]
        self.assertEqual(aggregate_exit_code(records, required={"acl"}), 0)


class PhaseGateTupleTests(unittest.TestCase):
    """The phase gate runs smoke.py and baseline.py on the same tuple.

    Tuple identity = (source SHA, image digest). All switches off. The gate
    must record both runs under one tuple id; either failing blocks.
    """

    def test_phase_gate_records_tuple_identity(self):
        try:
            from capability_manifest import build_tuple_id, is_phase_gate_complete
        except ImportError as exc:
            self.fail(
                "tools/capability_manifest.py must define build_tuple_id() and "
                "is_phase_gate_complete(): %s" % exc
            )

        tuple_id = build_tuple_id(
            source_sha="abc123", image_digest="sha256:deadbeef"
        )
        self.assertTrue(tuple_id, "tuple id must be non-empty")

        complete = {
            "tuple_id": tuple_id,
            "all_switches_off": True,
            "runs": [
                {"script": "smoke.py", "status": "PASS"},
                {"script": "baseline.py", "status": "PASS"},
            ],
        }
        self.assertTrue(is_phase_gate_complete(complete))

    def test_phase_gate_incomplete_without_both_baselines(self):
        from capability_manifest import is_phase_gate_complete
        incomplete = {
            "tuple_id": "x",
            "all_switches_off": True,
            "runs": [{"script": "smoke.py", "status": "PASS"}],
        }
        self.assertFalse(is_phase_gate_complete(incomplete))

    def test_phase_gate_blocked_when_switches_on(self):
        from capability_manifest import is_phase_gate_complete
        invalid = {
            "tuple_id": "x",
            "all_switches_off": False,
            "runs": [
                {"script": "smoke.py", "status": "PASS"},
                {"script": "baseline.py", "status": "PASS"},
            ],
        }
        self.assertFalse(is_phase_gate_complete(invalid))

    def test_phase_gate_blocked_when_either_baseline_fails(self):
        from capability_manifest import is_phase_gate_complete
        for failing in ("smoke.py", "baseline.py"):
            runs = [
                {"script": "smoke.py", "status": "PASS"},
                {"script": "baseline.py", "status": "PASS"},
            ]
            for run in runs:
                if run["script"] == failing:
                    run["status"] = "FAIL"
            self.assertFalse(
                is_phase_gate_complete(
                    {
                        "tuple_id": "x",
                        "all_switches_off": True,
                        "runs": runs,
                    }
                ),
                "phase gate must block when %s fails" % failing,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

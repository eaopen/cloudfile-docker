"""Cheap source and CI policy regressions (no Docker, compiler or network)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class DevSourcePolicy(unittest.TestCase):
    def test_current_dev_is_default_but_historical_snapshot_is_explicit(self):
        assembler = read("tools/prepare-v2-source.py")
        self.assertIn("if args.source_set else 'dev'", assembler)
        self.assertIn("sources['components'][component]['overlay_commit'] = commit", assembler)
        frozen = read(".github/workflows/v2-clean.yml")
        self.assertEqual(
            frozen.count("--source-set cloudfile-docker/build/v2/source-set.json"), 2
        )

    def test_hub_only_revision_does_not_invalidate_native_compiler_layer(self):
        dockerfile = read("build/v2/Dockerfile.dev")
        server_layer = dockerfile.split("FROM go-dependencies AS native", 1)[1].split(
            "FROM ${CF_BASE_IMAGE} AS frontend-dependencies", 1
        )[0]
        self.assertNotIn("COPY v2-source-receipt.json", server_layer)
        self.assertIn("COPY seafile-server /source/seafile-server", server_layer)
        self.assertIn(
            "COPY v2-source-receipt.json /opt/cloudfile-v2/source/v2-source-receipt.json",
            dockerfile,
        )
        preflight = read("build/v2/build-image.sh")
        self.assertLess(
            preflight.index("Prepared source receipt verified"),
            preflight.index('docker tag "$build_id"'),
        )

    def test_current_bundle_includes_the_go_storage_seam(self):
        current = read(".github/workflows/v2-dev-bundle.yml")
        self.assertIn("native.append('fileserver/objstore/backend_fs.go')", current)

    def test_native_and_release_workflows_never_auto_run(self):
        paths = (
            ".github/workflows/v2-clean.yml",
            ".github/workflows/v2-dev-bundle.yml",
            ".github/workflows/cf-edit-native.yml",
            ".github/workflows/prod.yml",
        )
        for path in paths:
            with self.subTest(workflow=path):
                trigger = read(path).split("permissions:", 1)[0]
                self.assertIn("workflow_dispatch:", trigger)
                self.assertNotIn("\n  push:", trigger)
                self.assertNotIn("\n  pull_request:", trigger)


if __name__ == "__main__":
    unittest.main()

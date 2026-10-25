"""The cf-worker service must not restart forever after a clean idle exit.

`manage.py cf_worker` exits 0 when no capability registered a periodic task, and
the standalone V2 runtime registers none without a Directory. With `restart: unless-stopped` that clean
exit becomes an endless restart loop (observed ExitCode=0, RestartCount 455+ on
minio157), so the policy must be `on-failure`.

Read-only text assertions on the Compose file: no Docker daemon and no PyYAML
are required, so this test runs in the default gate.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "compose" / "docker-compose.yml"
SERVICE = "cf-worker"


def service_block(text, name):
    """Return the lines of one top-level service, delimited by indentation."""
    lines = text.splitlines()
    header = f"  {name}:"
    start = next((i for i, line in enumerate(lines) if line.rstrip() == header), None)
    if start is None:
        raise AssertionError(f"service {name!r} is missing from {COMPOSE}")
    block = []
    for line in lines[start + 1:]:
        # A service block ends at the next key indented two spaces (the next
        # service, a comment introducing one) or at a top-level key.
        if line.strip() and not line.startswith("    "):
            break
        block.append(line)
    return block


def service_values(block, key, indent=4):
    """Values of a repeated 4-space key inside a service block, in order."""
    prefix = " " * indent + f"{key}:"
    values = []
    for line in block:
        if line.startswith(prefix):
            value = line[len(prefix):].split("#", 1)[0].strip()
            values.append(value.strip("\"'"))
    return values


class WorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.block = service_block(COMPOSE.read_text(), SERVICE)

    def test_worker_restarts_on_failure_not_on_clean_exit(self):
        restarts = service_values(self.block, "restart")
        self.assertEqual(1, len(restarts), f"expected exactly one restart policy, got {restarts}")
        self.assertEqual("on-failure", restarts[0])
        # `always` and `unless-stopped` both restart a clean exit, which is the
        # loop this test exists to prevent.
        self.assertNotIn(restarts[0], ("always", "unless-stopped"))

    def test_worker_still_runs_the_cf_worker_command(self):
        command = "\n".join(self.block)
        self.assertIn("manage.py cf_worker", command)

    def test_worker_runs_the_meilisearch_indexer_when_it_is_the_provider(self):
        # Meilisearch answers queries but never indexes CloudFile's derived
        # documents itself, so the worker container has to run the indexer when
        # it is the configured provider.
        command = "\n".join(self.block)
        self.assertIn("CF_PROVIDER_SEARCH", command)
        self.assertIn("meilisearch", command)
        self.assertIn("cloudfile_ext.v2.search.worker", command)
        self.assertIn("/shared/search-v2-checkpoint.json", command)

    def test_meili_mode_keeps_directory_catalog_scheduling(self):
        command = "\\n".join(self.block)
        self.assertIn('CF_SERVICE_SSO_DIRECTORY_URL', command)
        self.assertIn('periodic_pid=$!', command)
        self.assertIn('wait -n "${periodic_pid}" "${search_pid}"', command)
        self.assertIn('CF_DIRECTORY_SYNC_INTERVAL_SECONDS: ${CF_DIRECTORY_SYNC_INTERVAL_SECONDS:-600}', command)

    def test_worker_stays_in_the_default_stack(self):
        self.assertEqual([], service_values(self.block, "profiles"))


if __name__ == "__main__":
    unittest.main()

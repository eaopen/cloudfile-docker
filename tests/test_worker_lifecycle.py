"""CloudFile org/role sync is external-triggered; Docker never starts its poller.

The optional cf-worker service is a single Meilisearch indexer under
search/full profiles. These cheap source checks need no Docker daemon.
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

    def test_search_worker_not_in_default_core_stack(self):
        self.assertEqual(['["search", "full"]'],
                         service_values(self.block, "profiles"))

    def test_worker_runs_only_meilisearch_indexer_when_selected(self):
        command = "\\n".join(self.block)
        self.assertIn('CF_ENABLE_SEARCH', command)
        self.assertIn('CF_PROVIDER_SEARCH', command)
        self.assertIn('cloudfile_ext.v2.search.worker', command)
        self.assertIn('/shared/search-v2-checkpoint.json', command)
        self.assertNotIn('manage.py cf_worker', command)
        self.assertNotIn('periodic_pid', command)
        self.assertNotIn('wait -n', command)
        self.assertNotIn('CF_DIRECTORY_SYNC_INTERVAL_SECONDS', command)
        self.assertNotIn('CF_SEARCH_BOOTSTRAP_PAGES_PER_TICK', command)

    def test_single_search_worker_restarts_only_on_failure(self):
        self.assertEqual(['on-failure'], service_values(self.block, 'restart'))
        self.assertIn('exec /opt/seafile/', "\\n".join(self.block))

    def test_native_search_does_not_double_index(self):
        bootstrap = (ROOT / 'scripts/scripts_cf14.0/cloudfile_bootstrap.py').read_text()
        self.assertIn("not get_conf('CF_PROVIDER_SEARCH', '').strip()", bootstrap)
        self.assertIn("'enabled': 'true' if (cf_enabled('CF_ENABLE_SEARCH')", bootstrap)
        self.assertNotIn('CF_DIRECTORY_SYNC_INTERVAL_SECONDS', bootstrap)

    def test_external_directory_catalog_has_no_scheduler_config(self):
        settings = (ROOT / 'deploy/compose/.env.enterprise-sso.example').read_text()
        self.assertIn('/directory/entities/sync/', settings)
        self.assertNotIn('CF_DIRECTORY_SYNC_INTERVAL_SECONDS', settings)
        compose = COMPOSE.read_text()
        self.assertNotIn('CF_DIRECTORY_SYNC_INTERVAL_SECONDS', compose)
        self.assertNotIn('CF_WORKER_LOCK_FILE', compose)



if __name__ == "__main__":
    unittest.main()

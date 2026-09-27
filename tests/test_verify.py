import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cloudfile_verify', Path(__file__).with_name('verify.py'))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class SelectionTests(unittest.TestCase):
    def test_identity_change_keeps_runtime_gate_visible(self):
        with patch.object(verify, 'test_modules', return_value=['identity-test']):
            selected = verify.plan(['cloudfile-hub/cloudfile_extensions/identity/runtime.py'])
        self.assertEqual(selected['modules'], ['identity-test'])
        self.assertEqual(selected['required_gates'], ['identity-runtime'])

    def test_shared_schema_and_unknown_native_never_silently_pass(self):
        for path in ['cloudfile-hub/cloudfile_extensions/schema/runner.py',
                     'cloudfile-hub/cloudfile_extensions/common/errors.py',
                     'cloudfile-server/fileserver/http.go', 'other/unmapped.py']:
            self.assertIn('full-regression', verify.plan([path])['required_gates'])

    def test_probe_edit_selects_docker_and_identity_but_no_full_rebuild(self):
        selected = verify.plan(['cloudfile-docker/tests/probe_identity_runtime.py'])
        self.assertEqual(selected['groups'], ['docker'])
        self.assertEqual(selected['required_gates'], ['identity-runtime'])

    def test_reverse_imports_include_transitive_consumers_and_relative_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            hub = Path(directory)
            contents = {
                'identity/runtime.py': 'from .bindings import resolve\n',
                'identity/bindings.py': 'def resolve(): pass\n',
                'delegation/host.py': 'from ..identity.runtime import runtime\n',
                'tests/test_consumer.py': 'from cloudfile_extensions.delegation.host import host\n',
                'tests/test_unrelated.py': 'import json\n',
            }
            for name, content in contents.items():
                path = hub / 'cloudfile_extensions' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            with patch.object(verify, 'HUB', hub):
                self.assertEqual(verify.test_modules('identity'), ['cloudfile_extensions.tests.test_consumer'])


class OwnershipTests(unittest.TestCase):
    def test_stale_native_image_is_rejected_before_starting_services(self):
        metadata = [{'Id': 'fixture-image', 'Config': {'Labels': {
            'com.cloudfile.source.seafile-server': 'old-native'}}}]
        with patch.object(verify, 'docker', return_value=json.dumps(metadata)), \
                patch.object(verify, 'git', side_effect=['', 'new-native']), \
                patch.object(verify, 'core') as services:
            with self.assertRaisesRegex(RuntimeError, 'Native source changed'):
                verify.run_components(['fixture-test'], 'fixture-image', False)
            services.assert_not_called()

    def test_unowned_services_cannot_be_reused_or_removed(self):
        response = type('Result', (), {'returncode': 0, 'stdout': json.dumps([{'Config': {'Labels': {}}}])})()
        with patch.object(verify, 'command', return_value=response), self.assertRaisesRegex(RuntimeError, 'unowned'):
            verify.owned('container', 'existing-user-db')

    def test_partial_start_failure_only_cleans_newly_created_resources(self):
        calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            if args[0] == 'run':
                raise RuntimeError('fixture start failed')
            return ''
        with patch.object(verify, 'owned', return_value=None), patch.object(verify, 'docker', side_effect=docker):
            with self.assertRaises(RuntimeError):
                verify.core_up(('new-network', 'new-db', 'new-redis'))
        self.assertIn(('network', 'rm', 'new-network'), calls)
        self.assertFalse(any(call[0] == 'rm' for call in calls))


if __name__ == '__main__':
    unittest.main()

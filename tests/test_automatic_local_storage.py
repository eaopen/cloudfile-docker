"""Cross-layer key and directory policy, independent of Django/Seafile."""
import types
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Exercise the exact dependency payload applied by the production build, so a
# standalone Docker checkout does not need a separate seafobj working tree.
patch = (ROOT / 'patches/seafobj/automatic-local-storage.patch').read_text()
part = patch.split('+++ b/seafobj/auto_local.py\n', 1)[1]
source = '\n'.join(line[1:] for line in part.splitlines() if line.startswith('+'))
policy = types.ModuleType('cf_auto_local_policy')
exec(compile(source, 'auto_local.py', 'exec'), policy.__dict__)
CASES = json.loads((ROOT / 'docs/features/automatic-local-storage-cases.json').read_text())


@pytest.mark.parametrize('case', CASES)
def test_shared_keys(case):
    if case['valid']:
        assert policy.local_key('auto-local:' + case['key']) == case['key']
    else:
        with pytest.raises(KeyError):
            policy.local_key('auto-local:' + case['key'])


def test_template_requires_matching_roots():
    item = dict(storage_id='auto-local', is_auto=True, is_default=False,
                **{k: {'backend': 'fs', 'dir': '/shared/libraries'} for k in ('commits', 'fs', 'blocks')})
    assert policy.auto_template([item]) == '/shared/libraries'
    item['blocks']['dir'] = '/elsewhere'
    with pytest.raises(ValueError):
        policy.auto_template([item])


def test_key_symlink_is_rejected(tmp_path):
    root, outside = tmp_path / 'libraries', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    os.symlink(outside, root / 'redirect')
    stores = policy.AutoLocalStores(str(root), 'fs', None)
    with pytest.raises(ValueError):
        stores['auto-local:redirect']


def test_unknown_static_class_never_falls_back(tmp_path):
    stores = policy.AutoLocalStores(str(tmp_path), 'fs', None)
    with pytest.raises(KeyError):
        stores['missing-class']

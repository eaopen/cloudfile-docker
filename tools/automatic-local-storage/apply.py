"""Install a verified native storage patch onto the existing release image."""
import hashlib
import json
from pathlib import Path
import shutil

payload = Path(__file__).parent
manifest = json.loads((payload / 'manifest.json').read_text())
roots = [p for p in Path('/opt/seafile').glob('seafile-server-*')
         if (p / 'seafile/bin/seaf-server').is_file()]
if len(roots) != 1:
    raise SystemExit('Ambiguous installed release')
root = roots[0]
info = (root / 'cloudfile-build-info.txt').read_text()
if ('seafile-server: ' + manifest['native_baseline']) not in info:
    raise SystemExit('Native source baseline differs from the verified build')
factory = root / 'seahub/thirdpart/seafobj/objstore_factory.py'
if hashlib.sha256(factory.read_bytes()).hexdigest() != manifest['original_factory_sha256']:
    raise SystemExit('Unexpected existing seafobj patch; reconcile before overlaying')
for name, digest in manifest['files'].items():
    source = payload / name
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise SystemExit('Storage payload differs from its verification manifest')
    if name.endswith('.py'):
        compile(source.read_text(), name, 'exec')
for name in manifest['native_binaries']:
    source = payload / name
    if source.read_bytes()[:4] != b'\x7fELF':
        raise SystemExit('Native binary is not an ELF artifact')
    shutil.copy2(source, root / 'seafile/bin' / name)
    (root / 'seafile/bin' / name).chmod(0o755)
shutil.copy2(payload / 'storage-views.py', root / 'seahub/cloudfile_ext/storage/views.py')
shutil.copy2(payload / 'objstore_factory.py', factory)
shutil.copy2(payload / 'auto_local.py', factory.parent / 'auto_local.py')
shutil.copy2(payload / 'cloudfile.sql', root / 'sql/mysql/cloudfile.sql')
# Preserve provenance of the original release and record this overlay beside
# it, rather than pretending the unmodified baseline produced these binaries.
(root / 'cloudfile-automatic-storage.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Verified automatic-local storage overlay installed')

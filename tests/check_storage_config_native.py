#!/usr/bin/env python3
"""Compile the current Server guard and check actual Docker-generated config.

Usage: python3 tests/check_storage_config_native.py /path/to/cloudfile-server
Requires the Server local-storage include seams, a C compiler, glib and jansson dev.
"""
import importlib.util
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile


def main():
    server = Path(sys.argv[1]).resolve()
    module_path = Path(__file__).resolve().parents[1] / 'scripts/scripts_14.0/library_storage.py'
    spec = importlib.util.spec_from_file_location('library_storage', module_path)
    storage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(storage)
    flags = shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'glib-2.0', 'gobject-2.0', 'jansson'], text=True))
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / 'guard.c'
        source.write_text('#include "common.h"\n#include "cf-v2-storage.c"\n'
                          'SeafileSession *seaf;\n'
                          'int main(int argc, char **argv) {\n'
                          '  GKeyFile *config = g_key_file_new();\n'
                          '  if (argc != 2 || !g_key_file_load_from_file(config, argv[1], G_KEY_FILE_NONE, NULL)) return 2;\n'
                          '  int result = cf_v2_storage_validate_config(config);\n'
                          '  g_key_file_free(config); return result == 0 ? 0 : 1;\n}\n')
        command = ['cc', '-D_GNU_SOURCE', '-ffunction-sections', '-fdata-sections']
        for include in ('tests/local_storage/include', 'common', 'lib'):
            command += ['-I' + str(server / include)]
        command += [str(source), '-Wl,-dead_strip' if sys.platform == 'darwin' else '-Wl,--gc-sections']
        subprocess.run(command + flags + ['-o', str(root / 'guard')], check=True)
        config = root / 'seafile.conf'
        rendered = storage._render_auto('[database]\nhost = db\n', '[cloudfile]\n')
        config.write_text(rendered)
        subprocess.run([str(root / 'guard'), str(config)], check=True)
        config.write_text(rendered.replace('name = filesystem', 'name = fs'))
        rejected = subprocess.run([str(root / 'guard'), str(config)], check=False)
        if rejected.returncode != 1:
            raise AssertionError('Native guard did not reject invalid fs backend spelling')
    print('Current Server guard accepts generated filesystem backends and rejects fs')


if __name__ == '__main__':
    main()

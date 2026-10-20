"""Exercise source closure without compilers or external dependencies."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "native_source", Path(__file__).resolve().parents[1] /
    "build/v2/check-native-source.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativeSourceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in module.MAKEFILES:
            self.write(name, "# native fixture\n")
        self.write("server/Makefile.am",
                   "seaf_server_SOURCES = main.c ../common/cf-v2-storage.c\n")
        self.write("server/main.c", '#include "local.h"\n#include "config.h"\n')
        self.write("server/local.h", '#include "common.h"\n')
        self.write("common/common.h", "#include <glib.h>\n")
        self.write("common/cf-v2-storage.c", '#include "common.h"\n')

    def write(self, name, content):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def test_native_and_v2_closure(self):
        self.assertEqual(module.check(self.root), [])

    def test_missing_manifest(self):
        (self.root / "fuse/Makefile.am").unlink()
        self.assertIn("missing build manifest: fuse/Makefile.am", module.check(self.root))

    def test_missing_source(self):
        (self.root / "common/cf-v2-storage.c").unlink()
        self.assertTrue(any("missing build input" in e for e in module.check(self.root)))

    def test_missing_transitive_header(self):
        self.write("common/common.h", '#include "missing.h"\n')
        self.assertIn("common/common.h: unresolved quoted header: missing.h",
                      module.check(self.root))

    def test_copying_legacy_headers_back_does_not_bypass_gate(self):
        self.write("server/local.h", '#include "cloudfile-policy.h"\n')
        self.write("server/cloudfile-policy.h", "/* obsolete */\n")
        self.assertIn("server/local.h: legacy header: cloudfile-policy.h",
                      module.check(self.root))

    def test_legacy_source_is_rejected_even_when_present(self):
        self.write("server/Makefile.am", "seaf_server_SOURCES = ../common/cf-fileop.c\n")
        self.write("common/cf-fileop.c", "/* obsolete */\n")
        self.assertTrue(any("legacy build input" in e for e in module.check(self.root)))

    def test_commented_inputs_are_not_dependencies(self):
        self.write("server/main.c", '/* #include "missing.h" */\n')
        self.assertEqual(module.check(self.root), [])

    def test_build_entry_stops_before_fetching_dependencies(self):
        import subprocess
        result = subprocess.run(
            ["bash", str(Path(__file__).resolve().parents[1] /
                         "build/v2/build-native.sh"), str(self.root), "unused", "sources"],
            capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Native source preflight failed", result.stderr)
        self.assertFalse((self.root / "libsearpc").exists())


if __name__ == "__main__":
    unittest.main()

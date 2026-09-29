"""Selected-directory staging and resume evidence boundaries."""

import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_module("migration_prepare", ROOT / "tools" / "prepare-migration.py")
selection = load_module("migration_selection", ROOT / "image" / "migration" / "selection.py")
preflight = load_module("migration_preflight", ROOT / "image" / "migration" / "preflight.py")


class MigrationPreparationTests(unittest.TestCase):
    def test_first_binding_requires_empty_library_and_rejects_redirect(self):
        class Handler(BaseHTTPRequestHandler):
            body = b"[]"
            status = 200

            def do_GET(self):
                self.server.seen_path = self.path
                self.server.seen_token = self.headers.get("Authorization")
                self.send_response(self.status)
                if self.status == 302:
                    self.send_header("Location", "http://example.invalid/leak")
                self.end_headers()
                self.wfile.write(self.body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                token = Path(temporary) / "token"
                token.write_text("secret-token")
                endpoint = "http://127.0.0.1:" + str(server.server_port)
                repo = "00000000-0000-0000-0000-000000000001"
                preflight.require_empty(endpoint, repo, str(token))
                self.assertEqual(server.seen_path, "/api2/repos/" + repo + "/dir/?p=%2F")
                self.assertEqual(server.seen_token, "Token secret-token")
                Handler.body = b'[{"name":"existing"}]'
                with self.assertRaisesRegex(ValueError, "not empty"):
                    preflight.require_empty(endpoint, repo, str(token))
                Handler.status = 302
                with self.assertRaisesRegex(ValueError, "could not be read"):
                    preflight.require_empty(endpoint, repo, str(token))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_selected_directories_map_to_target_and_bind_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            (source / "设计" / "2024").mkdir(parents=True)
            (source / "设计" / "2024" / "small.txt").write_bytes(b"small")
            (source / "合同" / "归档" / "empty").mkdir(parents=True)
            (source / "合同" / "归档" / "large.bin").write_bytes(b"x" * (2 * 1024 * 1024 + 7))
            (source / "excluded.txt").write_bytes(b"outside")
            mapping_file = base / "mapping.json"
            mapping_file.write_text(json.dumps({"version": 1, "mappings": [
                {"source": "设计/2024", "target": "/历史资料/设计"},
                {"source": "合同/归档", "target": "/历史资料/合同"},
            ]}, ensure_ascii=False))
            output = base / "attempt"
            result = prepare.build(str(source), str(output), prepare.read_mapping(mapping_file))
            self.assertEqual((result["files"], result["bytes"]), (2, 2 * 1024 * 1024 + 12))
            self.assertEqual(selection.inspect(str(output)), result["selection_id"])
            self.assertEqual((output / "data" / "历史资料" / "设计" / "small.txt").read_bytes(), b"small")
            self.assertTrue((output / "data" / "历史资料" / "合同" / "empty").is_dir())
            self.assertFalse((output / "data" / "excluded.txt").exists())
            self.assertFalse((output / "data" / ".cf-migration").exists())
            self.assertEqual((source / "excluded.txt").read_bytes(), b"outside")
            with self.assertRaises(ValueError):
                prepare.build(str(source), str(output), prepare.read_mapping(mapping_file))
            (output / ".cf-migration" / "manifest.ndjson").write_bytes(b"tampered\n")
            with self.assertRaises(ValueError):
                selection.inspect(str(output))

    def test_rejects_overlapping_and_escaping_mappings(self):
        for document in (
            {"version": 1, "mappings": [{"source": "../secret", "target": "/A"}]},
            {"version": 1, "mappings": [{"source": "A", "target": "/A"},
                                        {"source": "B", "target": "/a/B"}]},
            {"version": 1, "mappings": [{"source": "A", "target": "/A"},
                                        {"source": "A/B", "target": "/C"}]},
        ):
            with self.subTest(document=document), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "map.json"
                path.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    prepare.read_mapping(path)

    def test_symlink_failure_retains_incomplete_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            (source / "selected").mkdir(parents=True)
            (source / "selected" / "link").symlink_to(base)
            output = base / "attempt"
            with self.assertRaises(ValueError):
                prepare.build(str(source), str(output), [(("selected",), ("target",))])
            self.assertFalse(output.exists())
            partial = list(base.glob("attempt.incomplete-*"))
            self.assertEqual(len(partial), 1)
            self.assertTrue((partial[0] / ".cf-migration" / "incomplete").exists())
            with self.assertRaises(ValueError):
                selection.inspect(str(partial[0]))


if __name__ == "__main__":
    unittest.main()

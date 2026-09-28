import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'build/seafile_14.0/image_platform.py'
SPEC = importlib.util.spec_from_file_location('image_platform', SCRIPT)
IMAGE_PLATFORM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMAGE_PLATFORM)


class ImagePlatformTests(unittest.TestCase):
    def test_native_and_explicit_platforms(self):
        with patch.object(IMAGE_PLATFORM.platform, 'machine', return_value='arm64'):
            self.assertEqual(IMAGE_PLATFORM.resolve('native'), 'linux/arm64')
        self.assertEqual(IMAGE_PLATFORM.resolve('linux/amd64'), 'linux/amd64')
        with self.assertRaises(ValueError):
            IMAGE_PLATFORM.resolve('linux/arm/v7')

    def test_release_binary_must_match_requested_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            binary_dir = package / 'seafile/bin'
            binary_dir.mkdir(parents=True)
            for name in ('seaf-server', 'fileserver'):
                header = bytearray(20)
                header[:6] = b'\x7fELF\x02\x01'
                header[18:20] = struct.pack('<H', 183)
                (binary_dir / name).write_bytes(header)
            IMAGE_PLATFORM.verify_package(package, 'linux/arm64')
            with self.assertRaisesRegex(ValueError, 'does not match'):
                IMAGE_PLATFORM.verify_package(package, 'linux/amd64')


if __name__ == '__main__':
    unittest.main()

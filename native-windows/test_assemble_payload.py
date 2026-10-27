"""Synthetic runtime-manifest checks; never accesses ChemDraw or the registry."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('payload_assembler', Path(__file__).with_name('assemble_payload.py'))
assembler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assembler)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='schemegrid-payload-test-', dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        path = self.root / 'runtime/example.txt'
        path.parent.mkdir()
        path.write_bytes(b'example')
        self.manifest = {'schema': 1, 'architecture': 'windows-x64', 'files': [
            {'file': 'runtime/example.txt', 'bytes': 7, 'sha256': hashlib.sha256(b'example').hexdigest()}]}
        self.write()

    def write(self):
        (self.root / 'RUNTIME-MANIFEST.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_exact_manifest_accepted(self):
        self.assertEqual(assembler.verify_runtime(self.root), assembler.output_path(self.root))

    def test_changed_bytes_refused(self):
        (self.root / 'runtime/example.txt').write_bytes(b'changed')
        with self.assertRaises(RuntimeError):
            assembler.verify_runtime(self.root)

    def test_extra_file_refused(self):
        (self.root / 'runtime/extra.txt').write_text('extra', encoding='utf-8')
        with self.assertRaises(RuntimeError):
            assembler.verify_runtime(self.root)

    def test_missing_file_refused(self):
        (self.root / 'runtime/example.txt').unlink()
        with self.assertRaises(RuntimeError):
            assembler.verify_runtime(self.root)

    def test_traversal_and_absolute_entries_refused(self):
        for name in ('runtime/../escape', 'runtime//escape', '../escape', 'runtime/C:/escape',
                     'C:/escape', 'runtime\\escape'):
            with self.subTest(name=name):
                self.manifest['files'][0]['file'] = name
                self.write()
                with self.assertRaises(RuntimeError):
                    assembler.verify_runtime(self.root)

    def test_duplicate_case_entries_refused(self):
        self.manifest['files'].append(dict(self.manifest['files'][0], file='runtime/EXAMPLE.txt'))
        self.write()
        with self.assertRaises(RuntimeError):
            assembler.verify_runtime(self.root)

    def test_production_core_allowlist_is_exact(self):
        self.assertEqual(len(assembler.CORE_FILES), 12)
        self.assertEqual(len(set(assembler.CORE_FILES)), 12)
        self.assertNotIn('native-runtime.json', assembler.CORE_FILES)
        self.assertFalse(any('/' in name or '\\' in name for name in assembler.CORE_FILES))


if __name__ == '__main__':
    unittest.main(verbosity=2)

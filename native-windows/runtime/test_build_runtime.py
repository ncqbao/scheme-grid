"""Synthetic safety tests; no downloads, installers, ChemDraw, or registry use."""
from __future__ import annotations
import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

SPEC = importlib.util.spec_from_file_location('runtime_builder', Path(__file__).with_name('build_runtime.py'))
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class RuntimeBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='schemegrid-runtime-test-', dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def zip(self, entries):
        path = self.root / 'test.zip'
        with zipfile.ZipFile(path, 'w') as package:
            for name, content in entries:
                package.writestr(name, content)
        return path

    def tar(self, entries):
        path = self.root / 'test.tgz'
        with tarfile.open(path, 'w:gz') as package:
            for item, content in entries:
                if isinstance(item, str):
                    metadata = tarfile.TarInfo(item)
                    metadata.size = len(content)
                else:
                    metadata = item
                package.addfile(metadata, io.BytesIO(content))
        return path

    def test_windows_path_validation(self):
        self.assertEqual(builder.member_parts('package/lib/a.js'), ['package', 'lib', 'a.js'])
        for name in ('../escape', '/escape', 'C:/escape', 'a\\escape', 'a//b', 'a/./b',
                     'a/../b', 'a\x00b', 'a/name.', 'a/name ', 'a/CON.txt', 'a/LPT9', 'a/*'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                builder.member_parts(name)

    def test_zip_preflight_rejects_traversal_before_writes(self):
        archive = self.zip([('package/valid.txt', b'ok'), ('../escape.txt', b'bad')])
        with self.assertRaises(ValueError):
            builder.extract_zip(archive, self.root / 'output', prefix='package/')
        self.assertFalse((self.root / 'output').exists())
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_zip_links_refused(self):
        link = zipfile.ZipInfo('package/link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            builder.extract_zip(self.zip([(link, b'target')]), self.root / 'output', prefix='package/')

    def test_zip_case_collision_refused(self):
        with self.assertRaises(ValueError):
            builder.extract_zip(self.zip([('a.txt', b'a'), ('A.txt', b'b')]), self.root / 'output')

    def test_zip_filter_still_validates_excluded_entries(self):
        archive = self.zip([('package/keep', b'a'), ('package/../bad', b'b')])
        with self.assertRaises(ValueError):
            builder.extract_zip(archive, self.root / 'output', prefix='package/', only={'keep'})
        self.assertFalse((self.root / 'output').exists())

    def test_zip_only_files_exact(self):
        archive = self.zip([('package/keep', b'a'), ('package/skip', b'b')])
        builder.extract_zip(archive, self.root / 'output', prefix='package/', only={'keep'})
        self.assertEqual((self.root / 'output/keep').read_bytes(), b'a')
        self.assertFalse((self.root / 'output/skip').exists())
        with self.assertRaises(ValueError):
            builder.extract_zip(archive, self.root / 'missing', prefix='package/', only={'missing'})

    def test_archive_limits_checked_before_writes(self):
        archive = self.zip([('a', b'123'), ('b', b'456')])
        with mock.patch.object(builder, 'MAX_EXPANDED', 5), self.assertRaises(ValueError):
            builder.extract_zip(archive, self.root / 'output')
        self.assertFalse((self.root / 'output').exists())

    def test_tar_preflight_rejects_traversal_before_writes(self):
        archive = self.tar([('package/okay', b'a'), ('package/../escape', b'b')])
        with self.assertRaises(ValueError):
            builder.extract_tar(archive, self.root / 'output')
        self.assertFalse((self.root / 'output').exists())

    def test_tar_links_and_special_files_refused(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind):
                item = tarfile.TarInfo('package/link')
                item.type, item.linkname = kind, 'target'
                with self.assertRaises(ValueError):
                    builder.extract_tar(self.tar([(item, b'')]), self.root / 'output')

    def test_tar_case_collision_refused(self):
        with self.assertRaises(ValueError):
            builder.extract_tar(self.tar([('package/a', b'a'), ('package/A', b'b')]), self.root / 'output')

    def test_tar_expected_content_extracted(self):
        builder.extract_tar(self.tar([('package/lib/test.js', b'example')]), self.root / 'output')
        self.assertEqual((self.root / 'output/lib/test.js').read_bytes(), b'example')

    def source(self, content=b'archive bytes'):
        return {'archive': 'archive.zip', 'url': 'https://example.invalid/archive.zip',
                'sha256': hashlib.sha256(content).hexdigest(),
                'npmIntegrity': 'sha512-' + base64.b64encode(hashlib.sha512(content).digest()).decode('ascii')}

    def test_both_archive_hashes_required(self):
        path = self.root / 'archive.zip'
        path.write_bytes(b'archive bytes')
        row = self.source()
        builder.verify_archive(path, row)
        with self.assertRaises(ValueError):
            builder.verify_archive(path, dict(row, sha256='0' * 64))
        with self.assertRaises(ValueError):
            builder.verify_archive(path, dict(row, npmIntegrity='sha512-' + base64.b64encode(b'0' * 64).decode('ascii')))

    def test_missing_archive_never_downloads_without_flag(self):
        with mock.patch.object(builder.urllib.request, 'build_opener') as opener:
            with self.assertRaises(ValueError):
                builder.obtain(self.source(), self.root / 'cache')
            opener.assert_not_called()

    def test_bad_cache_is_preserved_and_never_redownloaded(self):
        path = self.root / 'archive.zip'
        path.write_bytes(b'changed')
        with mock.patch.object(builder.urllib.request, 'build_opener') as opener:
            with self.assertRaises(ValueError):
                builder.obtain(self.source(), self.root, download=True)
            opener.assert_not_called()
        self.assertEqual(path.read_bytes(), b'changed')

    def download(self, content, url='https://example.invalid/archive.zip'):
        response = io.BytesIO(content)
        response.url = url
        opener = mock.Mock()
        opener.open.return_value = response
        return mock.patch.object(builder.urllib.request, 'build_opener', return_value=opener)

    def test_explicit_download_verifies_then_commits(self):
        with self.download(b'archive bytes'):
            path = builder.obtain(self.source(), self.root / 'cache', download=True)
        self.assertEqual(path.read_bytes(), b'archive bytes')
        self.assertEqual([item.name for item in path.parent.iterdir()], ['archive.zip'])

    def test_failed_download_verification_cleans_owned_temporary_file(self):
        with self.download(b'changed'), self.assertRaises(ValueError):
            builder.obtain(self.source(), self.root / 'cache', download=True)
        self.assertEqual(list((self.root / 'cache').iterdir()), [])

    def test_download_https_downgrade_refused(self):
        with self.download(b'archive bytes', 'http://example.invalid/archive.zip'), self.assertRaises(ValueError):
            builder.obtain(self.source(), self.root / 'cache', download=True)
        self.assertEqual(list((self.root / 'cache').iterdir()), [])
        with self.assertRaises(ValueError):
            builder.HTTPSRedirect().redirect_request(None, None, 302, '', {}, 'http://example.invalid/file')

    def test_source_lock_requires_all_components_and_https(self):
        lock = json.loads(builder.LOCK.read_text(encoding='utf-8'))
        self.assertEqual(len(builder.sources(lock)), 8)
        changed = copy.deepcopy(lock)
        changed['components'][0]['url'] = 'http://example.invalid/file'
        with self.assertRaises(ValueError):
            builder.sources(changed)
        changed = copy.deepcopy(lock)
        changed['components'].pop()
        with self.assertRaises(ValueError):
            builder.sources(changed)

    def test_existing_output_refused_before_archive_or_signature_work(self):
        output = self.root / 'output'
        output.mkdir()
        with mock.patch.object(builder, 'obtain') as obtain:
            with self.assertRaises(ValueError):
                builder.build(self.root / 'cache', output)
            obtain.assert_not_called()

    def test_failed_build_removes_only_its_owned_stage(self):
        unrelated = self.root / 'keep.txt'
        unrelated.write_text('keep', encoding='utf-8')
        with mock.patch.object(builder, 'obtain', return_value=self.root / 'not-executed.exe'), \
             mock.patch.object(builder, 'verify_python_signature', return_value={'status': 'Valid'}), \
             mock.patch.object(builder, 'extract_zip', side_effect=ValueError('synthetic failure')):
            with self.assertRaises(ValueError):
                builder.build(self.root / 'cache', self.root / 'output')
        self.assertEqual(unrelated.read_text(encoding='utf-8'), 'keep')
        self.assertFalse((self.root / 'output').exists())
        self.assertEqual(list(self.root.glob('.runtime-stage-*')), [])

    def test_reparse_paths_refused(self):
        info = mock.Mock(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with mock.patch.object(Path, 'lstat', return_value=info), self.assertRaises(ValueError):
            builder.no_links(self.root / 'linked')


if __name__ == '__main__':
    unittest.main(verbosity=2)

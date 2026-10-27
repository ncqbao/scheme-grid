"""Assemble only reviewed application code and redistributable runtime files."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / 'payload'
VERSION = '0.5.0-native-preview.7'
CORE_FILES = (
    'export_id_rebinding.py', 'native_discovery.py', 'native_executor.py',
    'native_prepare.cjs', 'native_request.py', 'native_restore.py',
    'native_runtime.py', 'operation_plan.py', 'preservation_guard.py',
    'reaction-layout.js', 'SchemeGrid-Native.py', 'SchemeGrid-Restore.py',
)


def output_path(path):
    absolute = os.path.abspath(path)
    if os.name == 'nt' and not absolute.startswith('\\\\?\\'):
        absolute = '\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute
    return Path(absolute)


def no_links(path):
    current = Path(os.path.abspath(path))
    while True:
        if current.is_symlink() or (current.exists() and
                getattr(current.stat(), 'st_file_attributes', 0) & 0x400):
            raise RuntimeError('Linked build paths are not supported.')
        if current == current.parent:
            return
        current = current.parent


def verify_runtime(root):
    root = output_path(root)
    no_links(root)
    manifest = json.loads((root / 'RUNTIME-MANIFEST.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 1 or manifest.get('architecture') != 'windows-x64':
        raise RuntimeError('Unsupported runtime build manifest.')
    expected, folded = set(), set()
    for item in manifest['files']:
        name = item['file']
        if (not isinstance(name, str) or not name.startswith(('runtime/', 'prerequisites/')) or
                '\\' in name or ':' in name or any(part in {'', '.', '..'} for part in name.split('/')) or
                not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise RuntimeError('Invalid runtime build manifest entry.')
        if name.casefold() in folded:
            raise RuntimeError('Duplicate runtime build manifest entry.')
        folded.add(name.casefold())
        expected.add(name)
        path = root.joinpath(*name.split('/'))
        no_links(path)
        if not path.is_file() or path.stat().st_size != item['bytes']:
            raise RuntimeError('A runtime file is missing or has a changed size: ' + name)
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != item['sha256']:
            raise RuntimeError('A runtime file has changed: ' + name)
    actual_files = set()
    for path in root.rglob('*'):
        no_links(path)
        if path.is_file():
            actual_files.add(path.relative_to(root).as_posix())
    if actual_files != expected | {'RUNTIME-MANIFEST.json'}:
        raise RuntimeError('Unexpected files are present in the runtime output.')
    return root


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2) + '\n').encode('utf-8'))


def assemble(runtime_payload):
    PAYLOAD.mkdir()
    shutil.copytree(runtime_payload / 'runtime', PAYLOAD / 'runtime')
    shutil.copytree(runtime_payload / 'prerequisites', PAYLOAD / 'prerequisites')
    (PAYLOAD / 'core').mkdir()
    for name in CORE_FILES:
        no_links(HERE / 'core' / name)
        shutil.copyfile(HERE / 'core' / name, PAYLOAD / 'core' / name)
    (PAYLOAD / 'installer').mkdir(exist_ok=True)
    (PAYLOAD / 'host').mkdir(exist_ok=True)
    for name in ('selfcheck.py', 'selfcheck.cjs'):
        shutil.copyfile(HERE / 'runtime' / name, PAYLOAD / 'installer' / name)

    config = {
        'releaseStatus': 'not-released-preview', 'mode': 'prepare', 'interactive': True,
        'packagePath': '../runtime/playwright', 'nodePath': '../runtime/node/node.exe',
        'pythonPath': '../runtime/python/python.exe',
        'browserPath': '../runtime/chromium/chrome-headless-shell.exe',
        'runDirectory': r'%LOCALAPPDATA%\SchemeGrid\Native',
    }
    write_json(PAYLOAD / 'core/native-runtime.json', config)
    write_json(PAYLOAD / 'installer/native-runtime.template.json', config)

    commands = []
    for command, label, entry in (
        ('Arrange', 'Scheme Grid - Arrange Selection in Place.py', 'SchemeGrid-Native.py'),
        ('Restore', 'Scheme Grid - Restore Last Arrangement.py', 'SchemeGrid-Restore.py'),
    ):
        template = (
            '# SchemeGridNative managed shim v1\n# command: ' + command + '\n'
            '# Installed command; run through ChemDraw File > ChemScripts.\n'
            'from pathlib import Path\nimport runpy\nimport sys\n'
            'sys.dont_write_bytecode = True\n'
            '_core = Path(__INSTALL_DIR_JSON__) / "core"\n'
            'sys.path.insert(0, str(_core))\n'
            'sys.argv[0] = str(_core / ' + repr(entry) + ')\n'
            'runpy.run_path(sys.argv[0], run_name="__main__")\n'
        )
        filename = 'host/' + command + '.py.template'
        (PAYLOAD / filename).write_bytes(template.encode('utf-8'))
        commands.append({'command': command, 'fileName': label, 'source': filename, 'template': True})

    write_json(PAYLOAD / 'install-contract.json', {
        'schema': 1,
        'runtimeConfigFile': 'core/native-runtime.json',
        'runtimeTemplateFile': 'installer/native-runtime.template.json',
        'commands': commands,
        'retireLegacy': [{'command': 'Arrange', 'fileName': 'Scheme Grid - Snap Scheme.py'}],
        'pythonInstallers': [
            {'architecture': 'x64', 'file': 'prerequisites/python-3.14.10-amd64.exe'},
            {'architecture': 'x86', 'file': 'prerequisites/python-3.14.10.exe'},
        ],
        'selfChecks': [{
            'executable': 'runtime/python/python.exe',
            'arguments': ['-I', '-B', '__INSTALL_DIR__/installer/selfcheck.py', '__INSTALL_DIR__',
                          '__INSTALL_DIR__/installer/selfcheck.cjs', '__DATA_DIR__/checks/runtime-selfcheck.json'],
            'timeoutSeconds': 90,
        }],
    })
    write_json(PAYLOAD / 'SCHEMEGRID-VERSION.json', {
        'name': 'Scheme Grid for ChemDraw', 'version': VERSION, 'status': 'Windows lab preview',
        'nativeCoreBase': '0.5.0-native-preview.3',
        'nativeCoreBaseManifestSHA256': '1f2f7ab597325003df60e48258c8b1188966a5a672141366bbd8e175c1b370a9',
        'nativeCoreChanges': ['Bundled browser execution', 'No generated Python bytecode',
                              'Strict caption allocation seed from captured native page'],
        'supportedOS': '64-bit Windows 10 or later',
        'supportedChemDraw': 'ChemDraw26, 32-bit or 64-bit, standard per-user installation with ChemScripts',
        'dependenciesIncluded': True,
        'features': ['Arrange Selection in Place', 'Restore Last Arrangement'],
        'limits': ['Direct saved CDX/CDXML drawings', 'Supported selections within one reaction row',
                   'Straight horizontal reaction arrows', 'No PowerPoint/OLE support',
                   'No macOS support', 'No empty-selection whole-document command',
                   'Numbering enabled with automatic layout defaults'],
    })
    shutil.copyfile(HERE / 'LICENSE.md', PAYLOAD / 'LICENSE.md')
    (PAYLOAD / 'THIRD-PARTY-NOTICES.md').write_text('''# Third-party notices

Scheme Grid includes redistributable components under their original licenses.
The full license and notice files remain with the installed runtimes:

- CPython: `runtime/python/LICENSE.txt`
- pywin32: `runtime/python/Lib/site-packages/pywin32-312.dist-info/licenses/`
- Node.js: `runtime/node/LICENSE`
- Chrome Headless Shell: `runtime/chromium/LICENSE.headless_shell`
- Playwright: `runtime/playwright/node_modules/playwright/LICENSE` and `NOTICE`
- Playwright Core: `runtime/playwright/node_modules/playwright-core/LICENSE` and `NOTICE`

The included official Python host installers contain their own license notices.
Versions, download sources, and archive checksums are listed in `RUNTIME-SOURCES.json`.
See `LICENSE.md` for the separate Scheme Grid project license status.
''', encoding='utf-8')

    provenance = json.loads((HERE / 'runtime/PUBLIC-RUNTIME-PROVENANCE.json').read_text(encoding='utf-8'))
    if provenance:
        write_json(PAYLOAD / 'RUNTIME-SOURCES.json', provenance)
    (PAYLOAD / 'INSTALLER-NOTICES.txt').write_bytes(('''Scheme Grid for ChemDraw - Windows lab preview

ChemDraw and its license are supplied separately by Revvity. This package adds
Arrange Selection and Restore commands through ChemDraw's ChemScripts feature.

Included redistributable components: CPython and its third-party components,
pywin32, Node.js, Playwright and Chrome Headless Shell. Their original licenses
and notices are included with each runtime. Official Python host installers for
32-bit and 64-bit are included and run only when the required script host is
missing. They are installed per user without PATH, association or launcher changes.

Source URLs, versions and archive checksums are recorded in RUNTIME-SOURCES.json
and prerequisites/PYTHON-HOST*-PROVENANCE.json after installation.

The Scheme Grid project owner has not selected an open-source license. See
LICENSE.md. This package is an unsigned lab preview; organizational application
control may require lab IT approval. It does not change security settings.
''').encode('utf-8'))
    readme = '''SCHEME GRID FOR CHEMDRAW - WINDOWS LAB PREVIEW

Install
Open SchemeGrid-ChemDraw-Windows-Setup.exe and click Install commands.
When it finishes, save your work and reopen ChemDraw. A PC reboot is normally
unnecessary; follow the installer's result if Windows reports that one is needed.

Use
Open a saved CDX/CDXML drawing directly in ChemDraw26. Marquee-select complete
molecules and straight arrows in one reaction row, then choose File > ChemScripts
> Scheme Grid - Arrange Selection in Place. Review the result and save normally.
Use Scheme Grid - Restore Last Arrangement before further edits or closing the
drawing if you want the previous layout back.

Included support
The setup includes private Python/COM, Node, Playwright and a layout browser.
Teammates do not install Node, Python or Chrome separately. If ChemDraw has no
compatible registered Python script host, setup provisions the included official
Python installer for that architecture. Existing compatible hosts are preserved;
the installer does not change PATH or Python file associations. No internet
downloads are needed during installation or cleanup.

Compatibility
Requires licensed ChemDraw26 with File > ChemScripts on 64-bit Windows10 or later,
in a standard per-user Revvity installation. ChemDraw itself and its license are
not included. Setup checks the supported locations and stops with instructions
if compatibility cannot be established.

Preview scope
Only supported selections in one reaction row are cleaned. Missing main-molecule
numbers are added automatically with consistent spacing. Select a region before
running the command. Restore
requires the same open drawing/process and the verified post-cleanup state; it is
not a guarantee of a single Ctrl+Z undo step. Local snapshots and journals are
kept under %LOCALAPPDATA%\\SchemeGrid\\Native.

This is an unsigned lab preview. Your organization's application-control policy
may require IT approval. No security settings are changed by this package.
Third-party licenses and notices are included with their runtimes. The project
license has not yet been selected; see LICENSE.md.
'''
    (PAYLOAD / 'READ-ME.txt').write_bytes(readme.encode('utf-8'))
    files = [p for p in PAYLOAD.rglob('*') if p.is_file()]
    forbidden = [str(p.relative_to(PAYLOAD)) for p in files
                 if p.suffix.lower() in {'.cdx', '.cdxml', '.pptx', '.pyc'} or p.name == 'debug.log'
                 or (p.suffix.lower() in {'.png', '.jpg'} and not p.is_relative_to(PAYLOAD / 'runtime'))]
    if forbidden:
        raise RuntimeError('Unreviewed files in payload: ' + repr(forbidden))
    return {'version': VERSION, 'files': len(files), 'bytes': sum(p.stat().st_size for p in files)}


def main():
    global PAYLOAD
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-payload', type=Path, default=HERE / 'runtime/payload')
    parser.add_argument('--output-dir', type=Path, default=HERE / 'payload')
    args = parser.parse_args()
    destination = output_path(args.output_dir)
    no_links(destination)
    if destination.exists():
        raise RuntimeError('Refusing to overwrite an existing application payload.')
    runtime_payload = verify_runtime(args.runtime_payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    PAYLOAD = destination.parent / ('.payload-stage-' + uuid.uuid4().hex)
    try:
        report = assemble(runtime_payload)
        no_links(destination)
        if destination.exists():
            raise RuntimeError('The application output appeared while building; nothing was replaced.')
        PAYLOAD.rename(destination)
        print(json.dumps(report))
    finally:
        if PAYLOAD.exists():
            if PAYLOAD.parent != destination.parent or not re.fullmatch(r'\.payload-stage-[0-9a-f]{32}', PAYLOAD.name):
                raise RuntimeError('Refusing cleanup outside the owned application staging folder.')
            no_links(PAYLOAD)
            for path in PAYLOAD.rglob('*'):
                no_links(path)
            shutil.rmtree(PAYLOAD)


if __name__ == '__main__':
    main()

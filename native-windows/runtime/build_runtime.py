"""Build the private Windows runtime from pinned public distributions.

Developer tool only. Downloads require --download; cached builds are offline.
Never runs an installer, modifies the registry, or uses an installed npm package.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import urllib.parse
import urllib.request
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
LOCK = HERE / 'PUBLIC-RUNTIME-PROVENANCE.json'
MAX_FILE = 1024 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 20000
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$', re.I)
ARCHIVES = {
    'CPython embeddable distribution': 'python-3.14.10-embed-amd64.zip',
    'pywin32 wheel': 'pywin32-312-cp314-cp314-win_amd64.whl',
    'Node.js': 'node-v24.19.0-win-x64.zip',
    'Chrome Headless Shell': 'chrome-headless-shell-win64-151.0.7922.34.zip',
    'playwright': 'playwright-1.62.1.tgz',
    'playwright-core': 'playwright-core-1.62.1.tgz',
}


def need(okay, message):
    if not okay:
        raise ValueError(message)


def digest(path, algorithm='sha256'):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).digest()


def output_path(path):
    absolute = os.path.abspath(path)
    if os.name == 'nt' and not absolute.startswith('\\\\?\\'):
        absolute = '\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute
    return Path(absolute)


def no_links(path):
    """Reject symlinks and Windows reparse points before following any path."""
    current = Path(os.path.abspath(path))
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            pass
        else:
            need(not stat.S_ISLNK(info.st_mode) and
                 not getattr(info, 'st_file_attributes', 0) & 0x400,
                 'Linked build paths are not supported: ' + str(current))
        if current.parent == current:
            return
        current = current.parent


def member_parts(name):
    need(isinstance(name, str) and name and not name.startswith('/') and
         '\\' not in name and '\x00' not in name, 'Unsafe archive member: ' + repr(name))
    value = name[:-1] if name.endswith('/') else name
    parts = value.split('/')
    for part in parts:
        need(part and part not in {'.', '..'} and not part.endswith((' ', '.')) and
             not any(ord(char) < 32 or char in '<>:"|?*' for char in part) and
             not RESERVED.fullmatch(part.split('.')[0]),
             'Unsafe archive member: ' + repr(name))
    return parts


def archive_plan(entries, prefix, only):
    """Validate every entry, including entries excluded by prefix/only filters."""
    need(len(entries) <= MAX_MEMBERS, 'The archive has too many members.')
    seen, selected, total = set(), [], 0
    for name, size, directory, item in entries:
        parts = member_parts(name)
        key = '/'.join(parts).casefold()
        need(key not in seen, 'Duplicate archive member: ' + name)
        seen.add(key)
        need(0 <= size <= MAX_FILE and (not directory or size == 0), 'Invalid archive member size.')
        total += size
        need(total <= MAX_EXPANDED, 'The expanded archive is too large.')
        if directory:
            continue
        need(not prefix or name.startswith(prefix), 'Unexpected archive root: ' + name)
        relative = name[len(prefix):] if prefix else name
        relative_parts = member_parts(relative)
        if only is None or relative in only:
            selected.append((relative_parts, size, item))
    need(selected, 'No expected files were found in the archive.')
    if only is not None:
        need({'/'.join(parts) for parts, _, _ in selected} == set(only),
             'Expected distribution files are missing.')
    return selected


def write_member(destination, parts, size, source):
    target = Path(destination).joinpath(*parts)
    no_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    copied = 0
    with target.open('xb') as output:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            copied += len(block)
            need(copied <= size, 'An archive member exceeds its declared size.')
            output.write(block)
    need(copied == size, 'An archive member is truncated.')


def extract_zip(archive, destination, *, prefix='', only=None):
    with zipfile.ZipFile(archive) as package:
        entries = []
        for item in package.infolist():
            kind = (item.external_attr >> 16) & 0xF000
            need(kind in {0, stat.S_IFREG, stat.S_IFDIR}, 'Archive links or special files are not allowed.')
            need(not item.flag_bits & 1, 'Encrypted archive members are not allowed.')
            entries.append((item.filename, item.file_size, item.is_dir(), item))
        plan = archive_plan(entries, prefix, only)
        for parts, size, item in plan:
            with package.open(item) as source:
                write_member(destination, parts, size, source)


def extract_tar(archive, destination, *, prefix='package/'):
    with tarfile.open(archive, 'r:gz') as package:
        entries = []
        for item in package.getmembers():
            need(item.isdir() or item.isfile(), 'Archive links or special files are not allowed.')
            entries.append((item.name, item.size, item.isdir(), item))
        plan = archive_plan(entries, prefix, None)
        for parts, size, item in plan:
            source = package.extractfile(item)
            need(source is not None, 'An archive member could not be read.')
            with source:
                write_member(destination, parts, size, source)


def sources(lock):
    need(lock.get('schema') == 1 and lock.get('architecture') == 'windows-x64', 'Unsupported runtime lock.')
    components = lock.get('components', [])
    need(len(components) == len(ARCHIVES) and
         {row['component'] for row in components} == set(ARCHIVES), 'The runtime component list is incomplete.')
    result = [dict(row, archive=ARCHIVES[row['component']]) for row in components]
    hosts = lock.get('conditionalScriptHostInstallers', [])
    need(len(hosts) == 2 and {row['architecture'] for row in hosts} == {'x86', 'x64'},
         'Both offline script host installers are required.')
    for row in hosts:
        name = 'python-3.14.10-amd64.exe' if row['architecture'] == 'x64' else 'python-3.14.10.exe'
        result.append(dict(row, archive=name))
    for row in result:
        url = urllib.parse.urlsplit(row['url'])
        need(url.scheme == 'https' and url.hostname and not url.username and not url.password,
             'Sources must use public HTTPS URLs without credentials.')
        need(re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None, 'A source checksum is invalid.')
        if row.get('npmIntegrity'):
            integrity = row['npmIntegrity']
            need(integrity.startswith('sha512-') and
                 len(base64.b64decode(integrity[7:], validate=True)) == 64, 'Invalid npm integrity value.')
    return result


def verify_archive(path, source):
    no_links(path)
    need(Path(path).is_file() and digest(path).hex() == source['sha256'],
         'Pinned SHA256 mismatch: ' + source['archive'])
    if source.get('bytes') is not None:
        need(Path(path).stat().st_size == source['bytes'], 'Archive size mismatch: ' + source['archive'])
    if source.get('npmIntegrity'):
        need(digest(path, 'sha512') == base64.b64decode(source['npmIntegrity'][7:], validate=True),
             'Pinned npm SHA512 mismatch: ' + source['archive'])


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        need(urllib.parse.urlsplit(new_url).scheme == 'https', 'A download redirected outside HTTPS.')
        return super().redirect_request(request, response, code, message, headers, new_url)


def obtain(source, cache, download=False):
    cache = Path(os.path.abspath(cache))
    target = cache / source['archive']
    no_links(target)
    if target.exists():
        verify_archive(target, source)
        return target
    need(download, 'Missing cached archive: ' + source['archive'] + '; rerun with --download to fetch pinned sources.')
    cache.mkdir(parents=True, exist_ok=True)
    temporary = cache / ('.download-' + uuid.uuid4().hex)
    try:
        opener = urllib.request.build_opener(HTTPSRedirect())
        request = urllib.request.Request(source['url'], headers={'User-Agent': 'SchemeGrid-runtime-builder'})
        with opener.open(request, timeout=60) as response, temporary.open('xb') as output:
            need(urllib.parse.urlsplit(response.url).scheme == 'https', 'A download did not finish over HTTPS.')
            total = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                need(total <= MAX_FILE, 'The downloaded archive is too large.')
                output.write(block)
        verify_archive(temporary, source)
        no_links(target)
        need(not target.exists(), 'A cached archive appeared during download; nothing was replaced.')
        temporary.rename(target)  # Windows refuses an existing destination.
        return target
    finally:
        if temporary.is_file():
            temporary.unlink()


def verify_python_signature(path):
    need(os.name == 'nt', 'Build on Windows so official Python host signatures can be verified.')
    powershell = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    need(powershell.is_file(), 'Windows PowerShell is required for Authenticode verification.')
    literal = base64.b64encode(str(Path(path).resolve()).encode('utf-8')).decode('ascii')
    command = """$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$sgPath=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%s'))
$sgSignature=Get-AuthenticodeSignature -LiteralPath $sgPath
$sgName=if($sgSignature.SignerCertificate){$sgSignature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false)}else{''}
[pscustomobject]@{status=[string]$sgSignature.Status;simpleName=$sgName;subject=if($sgSignature.SignerCertificate){$sgSignature.SignerCertificate.Subject}else{''}}|ConvertTo-Json -Compress
""" % literal
    encoded = base64.b64encode(command.encode('utf-16-le')).decode('ascii')
    check = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=120, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    need(check.returncode == 0, 'Python host signature verification could not finish.')
    report = json.loads(check.stdout.decode('utf-8-sig'))
    need(report.get('status') == 'Valid' and report.get('simpleName') == 'Python Software Foundation',
         'The Python host does not have a valid Python Software Foundation signature.')
    return report


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def build(cache, output, *, download=False):
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    rows = sources(lock)
    output = output_path(output)
    no_links(output)
    need(not output.exists(), 'Refusing to overwrite an existing runtime output: ' + str(output))
    archives = {row['archive']: obtain(row, cache, download) for row in rows}
    signatures = {row['architecture']: verify_python_signature(archives[row['archive']])
                  for row in rows if 'architecture' in row}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.parent / ('.runtime-stage-' + uuid.uuid4().hex)
    stage.mkdir()
    try:
        runtime = stage / 'runtime'
        extract_zip(archives[ARCHIVES['CPython embeddable distribution']], runtime / 'python')
        extract_zip(archives[ARCHIVES['pywin32 wheel']], runtime / 'python/Lib/site-packages')
        (runtime / 'python/python314._pth').write_bytes(
            b'python314.zip\r\n.\r\nLib/site-packages\r\nLib/site-packages/win32\r\n'
            b'Lib/site-packages/win32/lib\r\nLib/site-packages/Pythonwin\r\nimport site\r\n')
        extract_zip(archives[ARCHIVES['Node.js']], runtime / 'node', prefix='node-v24.19.0-win-x64/',
                    only={'node.exe', 'LICENSE', 'README.md'})
        extract_zip(archives[ARCHIVES['Chrome Headless Shell']], runtime / 'chromium',
                    prefix='chrome-headless-shell-win64/')
        for name in ('playwright', 'playwright-core'):
            folder = runtime / 'playwright/node_modules' / name
            extract_tar(archives[ARCHIVES[name]], folder)
            metadata = json.loads((folder / 'package.json').read_text(encoding='utf-8'))
            need(metadata['name'] == name and metadata['version'] == '1.62.1', 'Unexpected npm package version.')
            for notice in ('LICENSE', 'NOTICE'):
                need((folder / notice).is_file(), 'A required npm license or notice is missing.')
        browsers = json.loads((runtime / 'playwright/node_modules/playwright-core/browsers.json').read_text(encoding='utf-8'))
        need(any(item['name'] == 'chromium-headless-shell' and item.get('browserVersion') == '151.0.7922.34'
                 for item in browsers['browsers']), 'The browser version does not match Playwright.')
        for relative in lock['licenses'].values():
            need((stage / relative).exists(), 'A required runtime license or notice is missing: ' + relative)
        prerequisites = stage / 'prerequisites'
        prerequisites.mkdir()
        for row in rows:
            if 'architecture' not in row:
                continue
            shutil.copyfile(archives[row['archive']], prerequisites / row['archive'])
            suffix = '-X86' if row['architecture'] == 'x86' else ''
            write_json(prerequisites / ('PYTHON-HOST' + suffix + '-PROVENANCE.json'),
                       {key: row[key] for key in ('component', 'version', 'architecture', 'url', 'sha256', 'bytes')} |
                       {'signature': signatures[row['architecture']], 'executedDuringBuild': False})
        write_json(runtime / 'RUNTIME-PROVENANCE.json', lock)
        files = [{'file': path.relative_to(stage).as_posix(), 'bytes': path.stat().st_size,
                  'sha256': digest(path).hex()} for path in sorted(stage.rglob('*')) if path.is_file()]
        manifest = {'schema': 1, 'architecture': 'windows-x64', 'files': files, 'fileCount': len(files),
                    'expandedBytes': sum(row['bytes'] for row in files), 'installerExecution': False,
                    'networkDownloadsEnabled': bool(download)}
        write_json(stage / 'RUNTIME-MANIFEST.json', manifest)
        no_links(stage)
        no_links(output)
        need(not output.exists(), 'The runtime output appeared while building; nothing was replaced.')
        stage.rename(output)
        return {key: manifest[key] for key in ('architecture', 'fileCount', 'expandedBytes', 'installerExecution', 'networkDownloadsEnabled')}
    finally:
        if stage.exists():
            need(stage.parent == output.parent and re.fullmatch(r'\.runtime-stage-[0-9a-f]{32}', stage.name),
                 'Refusing cleanup outside the owned staging folder.')
            no_links(stage)
            for path in stage.rglob('*'):
                no_links(path)
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', type=Path, default=HERE / 'downloads')
    parser.add_argument('--output-dir', type=Path, default=HERE / 'payload')
    parser.add_argument('--download', action='store_true', help='Fetch missing pinned archives over HTTPS at developer build time.')
    args = parser.parse_args()
    print(json.dumps(build(args.cache_dir, args.output_dir, download=args.download)))


if __name__ == '__main__':
    main()

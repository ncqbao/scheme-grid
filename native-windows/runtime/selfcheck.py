"""Standalone dependency check; no native application is read or changed.

Arguments: installation root, adjacent selfcheck.cjs path, owned report path.
The interpreter running this file must be the payload's private Python.
"""
from __future__ import annotations
import json
from pathlib import Path
import struct
import subprocess
import sys
import uuid


def main():
    if len(sys.argv) != 4:
        raise RuntimeError('Expected installation root, JavaScript check and report paths.')
    base, javascript, output = [Path(value).resolve() for value in sys.argv[1:]]
    expected = (base / 'runtime/python/python.exe').resolve()
    if Path(sys.executable).resolve() != expected:
        raise RuntimeError('The runtime check must use its private bundled Python.')
    if not sys.flags.isolated or any(not Path(value).resolve().is_relative_to(expected.parent) for value in sys.path):
        raise RuntimeError('The private Python import path is not isolated.')
    import pythoncom
    import win32com.client
    if not Path(pythoncom.__file__).resolve().is_relative_to(expected.parent):
        raise RuntimeError('The COM helper came from outside the bundled runtime.')
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = output.parent / ('runtime-check-' + uuid.uuid4().hex)
    scratch.mkdir()
    result = subprocess.run([str(base / 'runtime/node/node.exe'), str(javascript), str(base), str(scratch / 'browser.log')],
                            cwd=scratch, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
    if result.returncode:
        raise RuntimeError('The bundled browser check failed: ' + result.stderr.decode('utf-8', errors='replace')[-1500:])
    browser = json.loads(result.stdout.decode('utf-8'))
    report = {'ok': browser['ok'], 'pythonVersion': sys.version.split()[0], 'pythonBits': struct.calcsize('P') * 8,
              'pythonCOMImports': True, 'isolatedPython': True, 'browser': browser, 'runtimeDownloads': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes((json.dumps(report, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(report))


if __name__ == '__main__':
    main()

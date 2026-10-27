"""Package-local configuration. Reading this module changes no app or file."""
from __future__ import annotations

import os
from pathlib import Path
import json
import shutil
import subprocess
import sys

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / 'native-runtime.json'
DEFAULTS = {
    'releaseStatus': 'not-released-preview', 'mode': 'prepare', 'interactive': True,
    'packagePath': '.', 'nodePath': 'node', 'pythonPath': 'host',
    'browserPath': '',
    'runDirectory': r'%LOCALAPPDATA%\SchemeGrid\NativePreview',
}


def expand_path(value, base=BASE):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A runtime path is empty or invalid.')
    expanded = os.path.expandvars(value.strip())
    if '%' in expanded:
        raise ValueError('A runtime path contains an unresolved environment variable.')
    path = Path(expanded).expanduser()
    return path.resolve() if path.is_absolute() else (Path(base) / path).resolve()


def configuration(path=None):
    target = CONFIG_PATH if path is None else Path(path)
    config = dict(DEFAULTS)
    if target.is_file():
        value = json.loads(target.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict) or set(value) - set(DEFAULTS):
            raise ValueError('native-runtime.json contains an unsupported option.')
        config.update(value)
    if config['mode'] not in {'prepare', 'apply-selected'}:
        raise ValueError('Use prepare or explicitly enabled apply-selected mode.')
    if type(config['interactive']) is not bool:
        raise ValueError('The interactive option must be a boolean.')
    if config['releaseStatus'] != 'not-released-preview':
        raise ValueError('This package is an unreleased preview.')
    for name in ('packagePath', 'runDirectory'):
        config[name] = str(expand_path(config[name]))
    for name in ('pythonPath', 'nodePath'):
        if not isinstance(config[name], str) or not config[name].strip():
            raise ValueError(name + ' must identify a configured runtime.')
    for name in ('browserPath',):
        if not isinstance(config[name], str):
            raise ValueError(name + ' must identify a bundled executable.')
        if config[name]:
            config[name] = str(expand_path(config[name]))
    return config


def run_root():
    return Path(configuration()['runDirectory'])


def allowed_application_paths(environment=None):
    env = os.environ if environment is None else environment
    local = env.get('LOCALAPPDATA')
    if not local:
        raise ValueError('LOCALAPPDATA is unavailable; the standard ChemDraw installation cannot be verified.')
    base = Path(local) / 'Programs' / 'RevvitySignalsSoftware'
    return tuple((base / folder / 'ChemDraw.exe').resolve()
                 for folder in ('ChemDrawApplications', 'ChemDrawApplications_x64'))


def executable(value, *, host=False):
    if host and value == 'host':
        candidate = Path(sys.executable).resolve()
    elif value == 'node':
        found = shutil.which('node')
        if not found:
            raise ValueError("Scheme Grid's included layout helper is unavailable. The installation needs repair.")
        candidate = Path(found).resolve()
    else:
        candidate = expand_path(value)
    if not candidate.is_file() or candidate.suffix.lower() != '.exe':
        raise ValueError('The configured runtime executable was not found: ' + str(candidate))
    return str(candidate)


def choose_python(config):
    candidate = executable(config['pythonPath'], host=True)
    try:
        check = subprocess.run([candidate, '-B', '-c', 'import pythoncom, win32com.client'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=10, check=False,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('The configured Python COM helper could not start.') from exc
    if check.returncode:
        raise ValueError("Scheme Grid's included ChemDraw helper could not start. The installation needs repair.")
    return candidate


def require_saved_drawing(fullname):
    path = Path(fullname)
    if not path.is_absolute() or path.suffix.lower() not in {'.cdx', '.cdxml'} or not path.is_file():
        raise ValueError('Save the drawing as CDX or CDXML before running the native preview.')
    return path.resolve()

"""Selected-region native Windows preview; not released.

File > Run ChemScript entry. Default: prepare only. Applying requires explicit
apply-selected configuration, native user launch and a saved CDX/CDXML drawing. No host
output is produced. No ActiveDocument, Save, import, activation or installation.
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
import time
import traceback
import uuid

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from native_runtime import (configuration, run_root, choose_python, executable,
                            require_saved_drawing)
ROOT = run_root()
from native_request import (MAX_AGE, GuardError, assert_same, capture, is_busy,
                            locate_document, owned, resolved, running_application,
                            semantic_hash, status, write_snapshot)
from native_discovery import (caller_provenance, discover_one, identity,
                              require, validate_provenance)

CALLER_VERIFIED = False








def notify(message):
    # Product UI only, called after an explicit native host invocation. Tests
    # disable interactive mode; the agent never calls this function directly.
    ctypes.windll.user32.MessageBoxW(None, str(message)[:1600], 'Scheme Grid', 0x10)


def stage(argv=None, config=None):
    global CALLER_VERIFIED
    started = time.time()
    argv = list(sys.argv if argv is None else argv)
    require(len(argv) == 3, 'Choose File > ChemScripts > Scheme Grid - Arrange Selection in Place in ChemDraw.')
    source_path, output_path = Path(argv[1]).resolve(), Path(argv[2]).resolve()
    require(source_path != output_path, 'Host input and output paths must differ.')
    parent = caller_provenance()
    CALLER_VERIFIED = True
    config = configuration() if config is None else config
    stat = source_path.stat()
    require(started - 10 <= stat.st_mtime <= time.time() + 2,
            'The native FileRun input is stale or has a future timestamp.')
    raw = source_path.read_bytes()
    host_identity = identity(raw)
    identifier = uuid.uuid4().hex
    folder = owned(ROOT / 'runs' / identifier)
    folder.mkdir(parents=True)
    locks = owned(ROOT / 'inplace-locks')
    locks.mkdir(exist_ok=True)
    lock_path = locks / (str(parent['pid']) + '-' + str(parent['creationFileTime']) + '.lock')
    try:
        with lock_path.open('x', encoding='utf-8') as handle:
            json.dump({'requestId': identifier, 'folder': str(folder)}, handle)
    except FileExistsError:
        raise GuardError('A cleanup is already running in this ChemDraw instance.')
    try:
        (folder / 'host-input.cdxml').write_bytes(raw)
        launch = {
            'schema': 4, 'mode': 'selected-native-preview', 'requestId': identifier,
            'createdAt': started, 'expiresAt': started + MAX_AGE, 'caller': parent,
            'hostInputPath': str(source_path), 'hostInputModifiedAt': stat.st_mtime,
            'hostInputCreatedAt': stat.st_ctime, 'hostInputBytes': len(raw),
            'hostInputSHA256': hashlib.sha256(raw).hexdigest(), 'hostGUID': host_identity['guid'],
            'hostOutputPath': str(output_path), 'hostOutputWritten': False,
            'pythonPath': choose_python(config), 'config': config, 'nativeUserCommand': True,
            'lockPath': str(lock_path),
        }
        (folder / 'inplace-launch.json').write_text(json.dumps(launch, indent=2), encoding='utf-8')
        (ROOT / 'inplace-last-run.json').write_text(json.dumps({'folder': str(folder)}), encoding='utf-8')
        status(folder, 'inplace-host-staged', mode=config['mode'], hostOutputWritten=False)
        subprocess.Popen([launch['pythonPath'], '-I', '-B', str(Path(__file__).resolve()), 'supervise', str(folder)],
                         cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception:
        release_lock(launch if 'launch' in locals() else {'requestId': identifier, 'lockPath': str(lock_path)})
        raise
    return folder


def load_launch(folder, check_expiry=True):
    folder = owned(folder)
    launch = json.loads((folder / 'inplace-launch.json').read_text(encoding='utf-8'))
    require(folder.parent == ROOT / 'runs' and folder.name == launch.get('requestId'),
            'The in-place request folder does not agree with its ID.')
    require(launch.get('schema') == 4 and launch.get('mode') == 'selected-native-preview' and launch.get('nativeUserCommand') is True,
            'Unsupported native preview request.')
    require(launch['config'] == configuration(), 'The runtime configuration changed after launch.')
    require(0 < launch['expiresAt'] - launch['createdAt'] <= MAX_AGE,
            'Invalid native in-place request lifetime.')
    if check_expiry:
        require(launch['createdAt'] <= time.time() <= launch['expiresAt'], 'The native request expired.')
    raw = (folder / 'host-input.cdxml').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == launch['hostInputSHA256'], 'The owned host input bytes changed.')
    require(identity(raw)['guid'] == launch['hostGUID'], 'The host input GUID changed.')
    lock = owned(launch['lockPath'])
    require(json.loads(lock.read_text(encoding='utf-8'))['requestId'] == launch['requestId'],
            'The in-place request no longer owns its process lock.')
    return launch, folder


def release_lock(launch):
    lock = owned(launch['lockPath'])
    if lock.is_file():
        content = json.loads(lock.read_text(encoding='utf-8'))
        if content.get('requestId') == launch['requestId']:
            lock.unlink()


def concise_failure(folder):
    try:
        report = json.loads((folder / 'execution' / 'execution-report.json').read_text(encoding='utf-8'))
        if report.get('rollback', {}).get('ok'):
            return 'Cleanup stopped. The original drawing was restored and verified.'
        if report.get('rollback') is not None:
            return ('Cleanup stopped and restoration could not be verified. Review the drawing. '
                    'Its backup is in ' + str(folder / 'execution' / 'source-backup.cdxml'))
    except (OSError, ValueError):
        pass
    try:
        value = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
        detail = value.get('error', 'The selected cleanup could not finish.')
    except (OSError, ValueError):
        detail = 'The selected cleanup could not finish.'
    return str(detail)[:1000] + '\n\nDetails: ' + str(folder)


def supervise(folder):
    launch, folder = load_launch(folder)
    status(folder, 'inplace-waiting-for-host-return', mode=launch['config']['mode'])
    try:
        child = subprocess.Popen([launch['pythonPath'], '-I', '-B', str(Path(__file__).resolve()), 'worker', str(folder)],
                                 cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        # Never terminate an applying worker: that could interrupt its rollback.
        # The native host has already returned, so this wait does not block UI.
        child.wait()
        final = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
        if final.get('phase') not in {'prepared-only', 'inplace-complete'} and launch['config']['interactive']:
            notify(concise_failure(folder))
    except Exception as exc:
        status(folder, 'stopped', error=str(exc), liveDrawingEdited=None)
        if launch['config']['interactive']:
            notify(concise_failure(folder))
        raise
    finally:
        release_lock(launch)


def discover_snapshot(launch, folder):
    while True:
        try:
            validate_provenance(launch['caller'])
            app = running_application(launch['caller']['executable'])
            require(resolved(str(app.FullName)) == resolved(launch['caller']['executable']), 'Public COM resolved to another ChemDraw installation.')
            require(int(app.Documents.Count) <= 20, 'Too many drawings for bounded source discovery.')
            candidates = []
            for i in range(1, int(app.Documents.Count) + 1):
                doc = app.Documents.Item(i)
                fullname = str(doc.FullName)
                if fullname and Path(fullname).is_absolute() and not bool(doc.ReadOnly):
                    candidates.append(capture(fullname, str(launch['caller']['executable']), app=app))
            source = discover_one((folder / 'host-input.cdxml').read_bytes(), candidates)
            require(source['discoveryScope'] == 'selection' and source['selectedIds'],
                    'Select the reaction structures and arrows to clean, then run Scheme Grid again.')
            require_saved_drawing(source['documentFullName'])
            doc = locate_document(app, source['documentFullName'], str(launch['caller']['executable']))
            return app, doc, source
        except Exception as exc:
            if not is_busy(exc) or time.time() >= launch['expiresAt']:
                raise
            time.sleep(0.25)


def prepare(source, folder, config):
    write_snapshot(folder / 'source.cdxml', source['fullCDXML'])
    write_snapshot(folder / 'selection.cdxml', source['selectionCDXML'])
    (folder / 'options.json').write_text(json.dumps({'selectedIds': source['selectedIds'], 'numbering': True}), encoding='utf-8')
    node = executable(config['nodePath'])
    status(folder, 'inplace-preparing', document=source['documentFullName'], selectedIds=source['selectedIds'])
    browser = executable(config['browserPath'])
    completed = subprocess.run([node, str(BASE / 'native_prepare.cjs'), config['packagePath'], str(folder), browser],
                               cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
    require(completed.returncode == 0, 'Layout preparation stopped: ' + completed.stderr.decode('utf-8', 'replace')[-1500:])
    plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
    spec = importlib.util.spec_from_file_location('native_inplace_preservation_guard', str(BASE / 'preservation_guard.py'))
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    guard.verify_reaction_cleanup(source['fullCDXML'], plan['cdxml'], selected_ids=source['selectedIds'],
                                  scope=plan['scope'], numbering=plan['numbering'])
    from operation_plan import compile_plan
    operations = compile_plan(source['fullCDXML'], plan, source['selectedIds'])
    (folder / 'prevalidated-operations.json').write_text(json.dumps(operations, indent=2), encoding='utf-8')
    return plan


def commit_prepared(app, doc, source, plan, folder, config, caller, executor=None, native_user_command=False):
    require(source.get('selectedIds'), 'Select a reaction region before applying cleanup.')
    require(config['mode'] == 'apply-selected' and native_user_command is True,
            'Applying requires explicit apply-selected mode and a native user command.')
    require_saved_drawing(source['documentFullName'])
    require(config == configuration(), 'The apply-selected runtime configuration changed.')
    require(resolved(str(app.FullName)) == resolved(caller['executable']) and
            resolved(str(doc.FullName)) == resolved(source['documentFullName']),
            'The explicit source document or application changed before cleanup.')
    require(semantic_hash(source['fullCDXML']) == source['fullSemanticSHA256'],
            'The saved native source snapshot changed before cleanup.')
    validate_provenance(caller)
    latest = capture(source['documentFullName'], str(caller['executable']), app=app)
    assert_same(source, latest)
    require(resolved(str(doc.FullName)) == resolved(latest['documentFullName']),
            'The retained document reference changed identity.')
    status(folder, 'inplace-committing', document=source['documentFullName'], selectedIds=source['selectedIds'])
    if executor is None:
        from native_executor import execute_plan
        executor = execute_plan
    report = executor(doc, source['fullCDXML'], plan, source['selectedIds'], folder / 'execution')
    require(report.get('ok') is True and isinstance(report.get('verification'), dict) and report['verification'].get('ok') is True,
            report.get('error') or 'Native cleanup verification failed; inspect the execution report.')
    success = {'schema': 1, 'executionFolder': str(folder / 'execution'),
               'sourceFullName': source['documentFullName'],
               'sourceApplicationPath': caller['executable'],
               'sourceGuid': source.get('discoveryGUID'), 'sourceParentProcess': caller}
    pending = owned(ROOT / ('.last-successful-' + uuid.uuid4().hex + '.json'))
    pending.write_text(json.dumps(success, indent=2), encoding='utf-8')
    pending.replace(owned(ROOT / 'last-successful.json'))
    return report


def worker(folder):
    launch, folder = load_launch(folder)
    import pythoncom
    pythoncom.CoInitialize()
    try:
        app, doc, source = discover_snapshot(launch, folder)
        (folder / 'discovered-source.json').write_text(json.dumps({
            key: value for key, value in source.items() if key not in {'fullCDXML', 'selectionCDXML'}
        }, indent=2), encoding='utf-8')
        plan = prepare(source, folder, launch['config'])
        if launch['config']['mode'] == 'prepare':
            latest = capture(source['documentFullName'], str(launch['caller']['executable']), app=app)
            assert_same(source, latest)
            status(folder, 'prepared-only', document=source['documentFullName'],
                   selectedIds=source['selectedIds'], stats=plan.get('stats'), preservationGuard=True)
            return
        report = commit_prepared(app, doc, source, plan, folder, launch['config'], launch['caller'], native_user_command=launch['nativeUserCommand'])
        status(folder, 'inplace-complete', liveDrawingEdited=True, document=source['documentFullName'],
               selectedIds=source['selectedIds'], verification=report.get('verification'),
               executionReport=str(folder / 'execution' / 'execution-report.json'))
    except Exception as exc:
        disposition = {}
        report_path = folder / 'execution' / 'execution-report.json'
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding='utf-8'))
            restored = bool(report.get('rollback', {}).get('ok'))
            disposition = {'liveDrawingEdited': False if restored else None,
                           'originalRestoredAndVerified': restored,
                           'failureDisposition': report.get('failureDisposition')}
        elif (folder / 'execution' / 'rollback-journal.json').exists():
            disposition = {'liveDrawingEdited': None, 'originalRestoredAndVerified': False}
        status(folder, 'stopped', error=str(exc), executionReport=str(report_path), **disposition)
        raise
    finally:
        pythoncom.CoUninitialize()


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] in {'worker', 'supervise'}:
            return worker(sys.argv[2]) if sys.argv[1] == 'worker' else supervise(sys.argv[2])
        return stage()
    except Exception:
        error = traceback.format_exc()
        ROOT.mkdir(parents=True, exist_ok=True)
        (ROOT / 'inplace-host-error.json').write_text(json.dumps({
            'at': time.time(), 'arguments': sys.argv, 'error': error,
            'hostOutputWritten': False,
        }, indent=2), encoding='utf-8')
        if CALLER_VERIFIED:
            try:
                if configuration()['interactive']:
                    notify(error.splitlines()[-1])
            except Exception:
                pass
        raise


if __name__ == '__main__':
    main()

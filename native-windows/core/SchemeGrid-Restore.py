"""Unreleased File > Run ChemScript preview for explicit Scheme Grid Restore.

Default preparation only. Explicit apply-selected configuration and a native user
command are required for mutation of a saved CDX/CDXML drawing. Host staging performs no COM calls and writes no host output. The
background worker identifies the current drawing by path, then restores only
the separately resolved named drawing with the saved exact post fingerprint.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
import time
import traceback
import uuid

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from native_runtime import (configuration, run_root, choose_python, require_saved_drawing,
                            allowed_application_paths)
ROOT = run_root()
from native_request import (MAX_AGE, GuardError, drawing, is_busy,
                            locate_document, resolved, running_application)
from native_discovery import (caller_provenance, require,
                              validate_provenance)
def notify(message):
    ctypes.windll.user32.MessageBoxW(None, str(message)[:1600], 'Scheme Grid Restore', 0x10)

CALLER_VERIFIED = False


def owned(path):
    candidate = Path(path).resolve()
    require(candidate.is_relative_to(ROOT), 'Restore request files must stay inside the configured preview data directory.')
    return candidate


def read_json(path):
    return json.loads(Path(path).read_bytes().decode('utf-8-sig'))


def guid_from_cdxml(value, required=False):
    root = drawing(value)
    values = [n.get('Content') for page in root.findall('page')
              for n in page if n.tag == 'annotation' and n.get('Keyword') == 'GUID']
    require(len(values) <= 1 and (not required or len(values) == 1),
            'Restore requires one unambiguous original drawing GUID.')
    if not values:
        return None
    try:
        return str(uuid.UUID(values[0]))
    except (ValueError, AttributeError, TypeError):
        raise GuardError('The drawing GUID is invalid.')


def pointer_path():
    return ROOT / 'last-successful.json'


def load_success(pointer=None):
    """Read a pointer written by a verified commit; never search other drawings."""
    path = pointer_path() if pointer is None else owned(pointer)
    raw = path.read_bytes()
    record = json.loads(raw.decode('utf-8-sig'))
    require(isinstance(record, dict) and record.get('schema') == 1,
            'There is no supported verified cleanup to restore.')
    expected = {'executionFolder', 'sourceFullName', 'sourceApplicationPath',
                'sourceGuid', 'sourceParentProcess'}
    require(expected <= set(record), 'The last successful cleanup record is incomplete.')
    folder = owned(record['executionFolder'])
    require(folder.name == 'execution' and folder.parent.parent == ROOT / 'runs' and
            re.fullmatch(r'[0-9a-f]{32}', folder.parent.name),
            'The successful execution record is outside the owned native run directory.')
    require(Path(record['sourceFullName']).is_absolute() and
            resolved(record['sourceApplicationPath']) in {resolved(p) for p in allowed_application_paths()},
            'The successful cleanup belongs to another drawing or application.')
    execution = read_json(folder / 'execution-report.json')
    journal = read_json(folder / 'rollback-journal.json')
    source = (folder / 'source-backup.cdxml').read_bytes().decode('utf-8')
    require_saved_drawing(record['sourceFullName'])
    require(execution.get('ok') is True and execution.get('verification', {}).get('ok') is True and
            journal.get('schema') == 'scheme-grid-native-rollback/v1',
            'The last cleanup was not verified successfully.')
    require(resolved(execution['documentFullName']) == resolved(record['sourceFullName']) ==
            resolved(journal['documentFullName']), 'Restore drawing identities disagree.')
    require(hashlib.sha256(source.encode('utf-8')).hexdigest() == journal['sourceSHA256'],
            'The original Restore backup changed.')
    post_hash = execution.get('postSnapshotSHA256', '')
    require(re.fullmatch(r'[0-9a-f]{64}', post_hash), 'The verified post-cleanup fingerprint is missing.')
    guid = guid_from_cdxml(source, required=True)
    try:
        require(guid == str(uuid.UUID(record['sourceGuid'])), 'The recorded original drawing GUID differs.')
    except (ValueError, TypeError, AttributeError):
        raise GuardError('The recorded original drawing GUID is invalid.')
    parent = record['sourceParentProcess']
    require(isinstance(parent, dict) and type(parent.get('pid')) is int and parent['pid'] > 0 and
            type(parent.get('creationFileTime')) is int and parent['creationFileTime'] > 0 and
            resolved(parent.get('executable', '')) == resolved(record['sourceApplicationPath']),
            'The recorded ChemDraw process identity is invalid.')
    restore_report = folder / 'restore-command-report.json'
    require(not restore_report.is_file() or read_json(restore_report).get('ok') is not True,
            'This cleanup has already been restored.')
    return {'record':record, 'pointerSHA256':hashlib.sha256(raw).hexdigest(),
            'executionFolder':folder, 'journalSourceGUID':guid,
            'postSnapshotSHA256':post_hash}


def check_record_for_caller(success, caller, host_guid=None):
    require(success['record']['sourceParentProcess'] == caller,
            'Restore must run in the same trusted ChemDraw process as the successful cleanup.')
    require(host_guid is None or host_guid == success['journalSourceGUID'],
            'The current drawing GUID differs from the cleanup journal.')


def status(folder, phase, **details):
    value = {'phase':phase, 'at':time.time(), 'liveDrawingEdited':False}
    value.update(details)
    owned(folder / 'status.json').write_text(json.dumps(value, indent=2), encoding='utf-8')


def release_lock(launch):
    path = owned(launch['lockPath'])
    expected = ROOT / 'inplace-locks' / (str(launch['caller']['pid']) + '-' +
                                       str(launch['caller']['creationFileTime']) + '.lock')
    require(path == expected.resolve() and re.fullmatch(r'[0-9a-f]{32}', launch['requestId']),
            'The Restore lock identity is invalid.')
    if path.is_file() and read_json(path).get('requestId') == launch['requestId']:
        path.unlink()


def stage(argv=None, config=None):
    global CALLER_VERIFIED
    argv = list(sys.argv if argv is None else argv)
    started = time.time()
    require(len(argv) == 3, 'Choose File > ChemScripts > Scheme Grid - Restore Last Arrangement in ChemDraw.')
    input_path, output_path = Path(argv[1]).resolve(), Path(argv[2]).resolve()
    require(input_path != output_path, 'Host input and output paths must differ.')
    caller = caller_provenance()
    CALLER_VERIFIED = True
    config = configuration() if config is None else config
    stat = input_path.stat()
    require(started - 10 <= stat.st_mtime <= time.time() + 2, 'The native Restore input is stale.')
    raw = input_path.read_bytes()
    host_guid = guid_from_cdxml(raw)
    success = load_success()
    check_record_for_caller(success, caller, host_guid)
    request_id = uuid.uuid4().hex
    folder = owned(ROOT / 'restores' / request_id)
    folder.mkdir(parents=True)
    locks = owned(ROOT / 'inplace-locks')
    locks.mkdir(exist_ok=True)
    lock_path = locks / (str(caller['pid']) + '-' + str(caller['creationFileTime']) + '.lock')
    try:
        with lock_path.open('x', encoding='utf-8') as handle:
            json.dump({'requestId':request_id, 'folder':str(folder)}, handle)
    except FileExistsError:
        raise GuardError('A cleanup or Restore is already running in this ChemDraw instance.')
    launch = {'schema':2, 'mode':'restore-native-preview', 'requestId':request_id,
              'createdAt':started, 'expiresAt':started+MAX_AGE, 'caller':caller,
              'hostInputSHA256':hashlib.sha256(raw).hexdigest(), 'hostGUID':host_guid,
              'journalSourceGUID':success['journalSourceGUID'], 'hostOutputPath':str(output_path),
              'hostOutputWritten':False, 'pointerSHA256':success['pointerSHA256'],
              'pythonPath':choose_python(config), 'config':config, 'nativeUserCommand':True,
              'executionFolder':str(success['executionFolder']), 'lockPath':str(lock_path)}
    try:
        (folder / 'host-input.cdxml').write_bytes(raw)
        (folder / 'restore-launch.json').write_text(json.dumps(launch, indent=2), encoding='utf-8')
        (ROOT / 'restore-last-run.json').write_text(json.dumps({'folder':str(folder)}), encoding='utf-8')
        status(folder, 'restore-host-staged', hostOutputWritten=False)
        subprocess.Popen([launch['pythonPath'], '-I', '-B', str(Path(__file__).resolve()), 'supervise', str(folder)],
                         cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception:
        release_lock(launch)
        raise
    return folder


def load_launch(folder):
    folder = owned(folder)
    launch = read_json(folder / 'restore-launch.json')
    require(folder.parent == ROOT / 'restores' and folder.name == launch.get('requestId') and
            launch.get('schema') == 2 and launch.get('mode') == 'restore-native-preview' and launch.get('nativeUserCommand') is True,
            'The Restore request identity is invalid.')
    require(0 < launch['expiresAt']-launch['createdAt'] <= MAX_AGE and
            launch['createdAt'] <= time.time() <= launch['expiresAt'], 'The Restore request expired.')
    require(launch['config'] == configuration(), 'The Restore configuration changed after launch.')
    raw = (folder / 'host-input.cdxml').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == launch['hostInputSHA256'] and
            guid_from_cdxml(raw) == launch['hostGUID'], 'The immutable Restore host input changed.')
    require(read_json(owned(launch['lockPath'])).get('requestId') == launch['requestId'],
            'The Restore request no longer owns its process lock.')
    return launch, folder


def explicit_current_document(app, success, caller):
    validate_provenance(caller)
    require(resolved(str(app.FullName)) == resolved(caller['executable']), 'Restore COM resolved to another installation.')
    # ActiveDocument is consulted only for current-window identity. Never pass
    # that object into the mutating Restore path or read its drawing contents.
    active_path = str(app.ActiveDocument.FullName)
    source_path = success['record']['sourceFullName']
    require(active_path and Path(active_path).is_absolute() and resolved(active_path) == resolved(source_path),
            'Open the drawing that was last cleaned before running Restore.')
    require(int(app.Documents.Count) <= 20, 'Too many drawings for bounded Restore lookup.')
    return locate_document(app, source_path, str(caller['executable']))


def restore_named(app, success, launch, folder, restorer=None):
    check_record_for_caller(success, launch['caller'], launch['hostGUID'])
    require(success['pointerSHA256'] == launch['pointerSHA256'] and
            str(success['executionFolder']) == launch['executionFolder'],
            'The last successful cleanup changed after Restore was requested.')
    doc = explicit_current_document(app, success, launch['caller'])
    from native_executor import capture
    require(hashlib.sha256(capture(doc).encode('utf-8')).hexdigest() == success['postSnapshotSHA256'],
            'The drawing changed after cleanup. Restore stopped before making changes.')
    validate_provenance(launch['caller'])
    if launch['config']['mode'] == 'prepare':
        status(folder, 'restore-prepared-only', document=success['record']['sourceFullName'],
               postFingerprintMatched=True)
        return {'preparedOnly':True, 'ok':True}
    require(launch['config']['mode'] == 'apply-selected' and launch.get('nativeUserCommand') is True,
            'Restore requires explicit apply-selected mode and a native user command.')
    require_saved_drawing(success['record']['sourceFullName'])
    # Recheck the current window immediately before entering the named-doc
    # restorer, which independently repeats the complete post-snapshot check.
    require(resolved(str(app.ActiveDocument.FullName)) == resolved(success['record']['sourceFullName']),
            'The current drawing changed before Restore began.')
    if restorer is None:
        from native_restore import restore_last_execution
        restorer = restore_last_execution
    status(folder, 'restore-committing', document=success['record']['sourceFullName'])
    result = restorer(doc, success['executionFolder'])
    require(result.get('ok') is True,
            'Restore could not be verified. Review the drawing and keep its original backup: ' +
            str(success['executionFolder'] / 'source-backup.cdxml') +
            ('\n' + str(result['error']) if result.get('error') else ''))
    status(folder, 'restore-complete', liveDrawingEdited=True, originalRestoredAndVerified=True,
           document=success['record']['sourceFullName'], restoreReport=str(success['executionFolder'] / 'restore-command-report.json'))
    return result


def worker(folder):
    launch, folder = load_launch(folder)
    import pythoncom
    pythoncom.CoInitialize()
    try:
        while True:
            try:
                validate_provenance(launch['caller'])
                success = load_success()
                return restore_named(running_application(launch['caller']['executable']), success, launch, folder)
            except Exception as exc:
                if not is_busy(exc) or time.time() >= launch['expiresAt']:
                    raise
                time.sleep(0.25)
    finally:
        pythoncom.CoUninitialize()


def supervise(folder):
    folder = owned(folder)
    launch = read_json(folder / 'restore-launch.json')
    try:
        launch, folder = load_launch(folder)
        status(folder, 'restore-waiting-for-host-return')
        child = subprocess.Popen([launch['pythonPath'], '-I', '-B', str(Path(__file__).resolve()), 'worker', str(folder)],
                                 cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        # Never terminate a worker that may be restoring original drawing data.
        child.wait()
        final = read_json(folder / 'status.json')
        if final.get('phase') not in {'restore-complete', 'restore-prepared-only'} and launch['config']['interactive']:
            notify(final.get('error', 'Restore did not complete. Review its report and original backup.'))
    finally:
        release_lock(launch)


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] in {'worker', 'supervise'}:
            folder = owned(sys.argv[2])
            try:
                return worker(folder) if sys.argv[1] == 'worker' else supervise(folder)
            except Exception as exc:
                status(folder, 'stopped', liveDrawingEdited=None, error=str(exc))
                raise
        return stage()
    except Exception:
        error = traceback.format_exc()
        ROOT.mkdir(parents=True, exist_ok=True)
        (ROOT / 'restore-host-error.json').write_text(json.dumps({'at':time.time(), 'error':error,
                                                               'hostOutputWritten':False}, indent=2), encoding='utf-8')
        if CALLER_VERIFIED:
            try:
                if configuration()['interactive']:
                    notify(error.splitlines()[-1])
            except Exception:
                pass
        raise


if __name__ == '__main__':
    main()

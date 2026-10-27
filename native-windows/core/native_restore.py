"""Explicit Restore prototype: accepts a caller-supplied identified document only.

Restoration is refused if the full native drawing differs from the exact saved
post-arrangement fingerprint. No active-document discovery or clipboard use.
"""
from pathlib import Path
import json

from operation_plan import digest, require
from native_executor import capture, lookup, native_ids, rollback, native_text_matches

from native_request import ROOT


def restore_last_execution(doc, run_folder):
    folder = Path(run_folder).resolve()
    require(folder.is_relative_to(ROOT), 'Restore journal must remain inside this prototype workspace.')
    execution = json.loads((folder / 'execution-report.json').read_bytes().decode('utf-8'))
    saved = json.loads((folder / 'rollback-journal.json').read_bytes().decode('utf-8'))
    plan = json.loads((folder / 'compiled-operations.json').read_bytes().decode('utf-8'))
    source = (folder / 'source-backup.cdxml').read_bytes().decode('utf-8')
    require(execution.get('ok') is True and saved.get('schema') == 'scheme-grid-native-rollback/v1',
            'There is no verified successful arrangement to restore.')
    name = str(doc.FullName)
    require(name and Path(name).is_absolute() and Path(name).resolve() == Path(saved['documentFullName']).resolve(),
            'The Restore drawing differs from the journal\'s exact named drawing.')
    require(execution['documentFullName'] == saved['documentFullName'], 'Restore document identities disagree.')
    require(digest(source) == saved['sourceSHA256'] == plan['sourceSHA256'], 'Restore source backup fingerprint differs.')
    require(digest(capture(doc)) == execution['postSnapshotSHA256'],
            'The drawing changed after arrangement. Restore stopped before any mutation.')
    entries = saved['operations']
    retained = set(saved['retainedNativeIds'])
    created = {e['actualId'] for e in entries if e['op'] == 'create_number' and e.get('actualId')}
    require(native_ids(doc) == retained | created, 'Physical native object IDs changed since arrangement.')
    groups = lookup(doc.Groups, {e['targetId'] for e in entries if e['op'] == 'move_rigid'})
    captions = lookup(doc.Captions, {e['targetId'] for e in entries if e['op'] == 'set_caption'} | created)
    arrows = lookup(doc.Arrows, {e['nativeTargetId'] for e in entries if e['op'] == 'set_arrow'})
    for entry in entries:
        if entry['op'] == 'move_rigid':
            require(entry['targetId'] in groups, 'An original Restore molecule/group is missing.')
            entry['_object'] = groups[entry['targetId']]
        elif entry['op'] == 'set_caption':
            require(entry['targetId'] in captions, 'An original Restore caption is missing.')
            entry['_object'] = captions[entry['targetId']]
        elif entry['op'] == 'set_arrow':
            require(entry['nativeTargetId'] in arrows, 'An original Restore arrow is missing.')
            entry['_object'] = arrows[entry['nativeTargetId']]
        elif entry['op'] == 'create_number':
            require(entry['actualId'] in captions and entry['actualId'] not in retained,
                    'Refusing to delete a caption without exact creation ownership.')
            entry['_object'] = captions[entry['actualId']]
            require(native_text_matches(str(entry['_object'].Text), entry['plannedText']),
                    'A newly created number changed since arrangement.')
        else:
            raise ValueError('Unknown Restore journal operation.')
    result = rollback(doc, source, plan, entries, retained, folder)
    result['explicitRestorePostFingerprintMatched'] = True
    (folder / 'restore-command-report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result

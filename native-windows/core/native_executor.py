"""Conservative public-COM executor for explicitly supplied, prevalidated documents.

Prototype only. It does not discover/activate a document, install an entry, save
over a source, or claim a transaction/one-step Undo. Callers own isolation.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from operation_plan import (compile_plan, parse, digest, object_digest, COORDS,
                            numbers, text, require, ownership)
from export_id_rebinding import rebind_export_ids

TOL = 0.035  # ChemDraw CDXML exports coordinates to hundredths of a point.
AUX = {'Center3D', 'MajorAxisEnd3D', 'MinorAxisEnd3D'}
JUST = {'Justification', 'CaptionJustification'}
RXN_ORDER = {'ReactionStepObjectsAboveArrow', 'ReactionStepObjectsBelowArrow'}


def capture(doc):
    import pythoncom
    collection = doc.Objects
    dispid = collection._oleobj_.GetIDsOfNames('Data')
    return str(collection._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYGET,
                                         True, 'chemical/x-cdxml'))


def near(a, b, tolerance=TOL):
    return len(a) == len(b) and all(abs(x-y) <= tolerance for x, y in zip(a, b))


def point(p):
    return [float(p.X), float(p.Y)]


def set_point(obj, property_name, xy):
    p = getattr(obj, property_name)
    p.X, p.Y = float(xy[0]), float(xy[1])
    setattr(obj, property_name, p)


def lookup(collection, wanted):
    result = {}
    require(int(collection.Count) <= 20000, 'Unexpectedly large native collection.')
    for i in range(1, int(collection.Count) + 1):
        obj = collection.Item(i)
        identifier = str(int(obj.ID))
        if identifier in wanted:
            require(identifier not in result, 'Duplicate native object ID.')
            result[identifier] = obj
    return result


def native_ids(doc):
    identifiers = set()
    for name in ['Objects', 'Atoms', 'Bonds', 'Groups', 'Captions', 'Graphics', 'Arrows']:
        collection = getattr(doc, name)
        require(int(collection.Count) <= 20000, 'Unexpected native collection size.')
        for i in range(1, int(collection.Count) + 1):
            identifiers.add(str(int(collection.Item(i).ID)))
    return identifiers


def normalized_text(value):
    return re.sub(r'\s+', ' ', value).strip()


def native_text_matches(value, expected):
    if normalized_text(value) == normalized_text(expected):
        return True
    # The installed automation getter reports UTF-8 text decoded as cp1252 for
    # some non-ASCII captions, while its CDXML export is correct. Accept only a
    # lossless inverse that exactly equals the independently captured XML text.
    try:
        return normalized_text(value.encode('cp1252').decode('utf-8')) == normalized_text(expected)
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


def preflight(doc, source, plan):
    require(plan.get('schema') == 'scheme-grid-inplace-plan/v1', 'Unexpected operation-plan schema.')
    require(digest(source) == plan['sourceSHA256'], 'Operation plan source hash differs.')
    require(capture(doc) == source, 'The complete native drawing changed before execution.')
    root, page, index = parse(source)
    group_ids, caption_ids, arrow_ids = set(), set(), set()
    for op in plan['operations']:
        kind = op['op']
        if kind == 'create_number':
            require(object_digest(index[op['ownerId']]) == op['expectedOwnerFingerprint'], 'Number owner changed.')
            require(op['justification'] == 'Center' and re.fullmatch(r'\d+[a-z]?', op['text']), 'Unsupported new caption.')
            require(set(op['font']) <= {'font', 'face', 'size', 'color'} and int(op['font']['face']) == 1,
                    'Unsupported number styling.')
            continue
        require(kind in {'move_rigid', 'set_caption', 'set_arrow'}, 'Unsupported native operation.')
        require(op['targetId'] in index and object_digest(index[op['targetId']]) == op['expectedFingerprint'],
                'Original object fingerprint changed.')
        if kind == 'move_rigid':
            require(op['kind'] in {'fragment', 'group'}, 'Unsupported move target.')
            group_ids.add(op['targetId'])
        elif kind == 'set_caption':
            caption_ids.add(op['targetId'])
        else:
            arrow_ids.add(op['nativeTargetId'])
    groups = lookup(doc.Groups, group_ids)
    captions = lookup(doc.Captions, caption_ids)
    arrows = lookup(doc.Arrows, arrow_ids)
    require(set(groups) == group_ids and set(captions) == caption_ids and set(arrows) == arrow_ids,
            'A planned object has no matching native object.')
    mappings = {}
    for op in plan['operations']:
        if op['op'] == 'set_caption':
            native_text = str(captions[op['targetId']].Text)
            require(native_text_matches(native_text, op['expectedText']),
                    'Native caption text differs from its original snapshot: ' + op['targetId'] +
                    ' native=' + repr(native_text) + ' expected=' + repr(op['expectedText']))
            # Access all required setters' source values before the first mutation.
            point(captions[op['targetId']].Position)
            int(captions[op['targetId']].Justification)
        elif op['op'] == 'set_arrow':
            native = arrows[op['nativeTargetId']]
            a, b = point(native.Start), point(native.End)
            head, tail = numbers(index[op['targetId']].get('Head3D'))[:2], numbers(index[op['targetId']].get('Tail3D'))[:2]
            if near(a, head) and near(b, tail):
                mappings[op['targetId']] = {'Start': 'head', 'End': 'tail'}
            elif near(a, tail) and near(b, head):
                mappings[op['targetId']] = {'Start': 'tail', 'End': 'head'}
            else:
                raise ValueError('Native arrow endpoints do not match either original orientation.')
            require(bool(native.IsStraightArrow) and not bool(native.IsArc), 'Only native straight arrows are supported.')
        elif op['op'] == 'move_rigid':
            require(int(groups[op['targetId']].Objects.Count) > 0, 'Empty native molecule/group.')
    fonts = {f.get('id'): f.get('name') for f in root.iter('font')}
    font_scales = []
    for identifier, caption in captions.items():
        runs = list(index[identifier].iter('s'))
        if runs and float(runs[0].get('size', '0')) > 0 and int(caption.Styles.Count) > 0:
            native_size = float(caption.Styles.Item(1).Size)
            xml_size = float(runs[0].get('size'))
            font_scales.append({'captionId': identifier, 'nativeSize': native_size,
                                'cdxmlSize': xml_size, 'ratio': native_size/xml_size})
    needs_new_number = any(op['op'] == 'create_number' for op in plan['operations'])
    if needs_new_number:
        require(font_scales and all(0.25 < f['ratio'] < 4 for f in font_scales), 'Cannot calibrate native font units.')
        font_scale = font_scales[0]['ratio']
        require(all(abs(f['ratio'] - font_scale) < 0.01 for f in font_scales), 'Native font units are inconsistent.')
    else:
        font_scale = None
    for op in plan['operations']:
        if op['op'] == 'create_number':
            require(op['font']['font'] in fonts and fonts[op['font']['font']], 'Number font is absent from original font table.')
    return groups, captions, arrows, mappings, fonts, font_scale, font_scales


def place_caption(doc, caption, identifier, wanted):
    # Position's native anchor is not assumed to be CDXML p. Apply a delta
    # measured from a fresh export after any justification change.
    _, _, current = parse(capture(doc))
    current_p = numbers(current[identifier].get('p', ''))
    require(len(current_p) == 2, 'Native caption lacks a CDXML anchor.')
    native_p = point(caption.Position)
    set_point(caption, 'Position', [native_p[0] + wanted['x'] - current_p[0],
                                    native_p[1] + wanted['y'] - current_p[1]])


def make_journal(doc, source, plan, groups, captions, arrows):
    _, _, index = parse(source)
    journal = []
    for op in plan['operations']:
        entry = {'op': op['op'], 'targetId': op.get('targetId'),
                 'ownerId': op.get('ownerId'), 'started': False, 'applied': False}
        if op['op'] == 'move_rigid':
            entry.update(originalNativePosition=point(groups[op['targetId']].Position),
                         inverseTranslation=[-float(op['dx']), -float(op['dy'])],
                         _object=groups[op['targetId']])
        elif op['op'] == 'set_caption':
            entry.update(originalNativePosition=point(captions[op['targetId']].Position),
                         originalAnchor=numbers(index[op['targetId']].get('p')),
                         originalJustification=int(captions[op['targetId']].Justification),
                         _object=captions[op['targetId']])
        elif op['op'] == 'set_arrow':
            entry.update(nativeTargetId=op['nativeTargetId'],
                         originalStart=point(arrows[op['nativeTargetId']].Start),
                         originalEnd=point(arrows[op['nativeTargetId']].End),
                         _object=arrows[op['nativeTargetId']])
        else:
            entry.update(proposedId=op['proposedId'], plannedText=op['text'], actualId=None)
        journal.append(entry)
    return journal


def serial_journal(journal):
    return [{k:v for k,v in entry.items() if not k.startswith('_')} for entry in journal]


def rollback(doc, source, plan, journal, retained_native, folder):
    """Restore only this journal's objects, then independently verify the result."""
    restored, failures = [], []
    allocated = [entry['actualId'] for entry in journal if entry['op'] == 'create_number' and entry.get('actualId')]
    result = {'attempted': True, 'allocatedNumberIds': allocated, 'transactionOrBatchUndoClaimed': False}
    for entry in reversed(journal):
        if not entry['started']:
            continue
        try:
            obj = entry.get('_object')
            if entry['op'] == 'create_number':
                if not entry.get('actualId'):
                    continue
                require(entry['actualId'] not in retained_native and str(int(obj.ID)) == entry['actualId'],
                        'Refusing to delete anything except this journal\'s newly created caption.')
                obj.Delete()
            elif entry['op'] == 'move_rigid':
                current = point(obj.Position)
                original = entry['originalNativePosition']
                obj.Objects.Move(original[0]-current[0], original[1]-current[1])
            elif entry['op'] == 'set_caption':
                if int(obj.Justification) != entry['originalJustification']:
                    obj.Justification = entry['originalJustification']
                place_caption(doc, obj, entry['targetId'],
                              {'x':entry['originalAnchor'][0], 'y':entry['originalAnchor'][1]})
            elif entry['op'] == 'set_arrow':
                set_point(obj, 'Start', entry['originalStart'])
                set_point(obj, 'End', entry['originalEnd'])
            restored.append({'op': entry['op'], 'targetId': entry.get('targetId'), 'actualId': entry.get('actualId')})
        except Exception as exc:
            failures.append({'op': entry['op'], 'targetId': entry.get('targetId'), 'error': str(exc)})
    result['restoredOperations'] = restored
    result['restorationCallErrors'] = failures
    try:
        require(not failures, 'Some native restoration calls failed.')
        require(native_ids(doc) == retained_native, 'Original native object IDs were not restored exactly.')
        raw = capture(doc)
        (folder / 'rollback-native-after.cdxml').write_bytes(raw.encode('utf-8'))
        before_root, _, before_index = parse(source)
        raw_root, _, raw_index = parse(raw)
        default_serialization = []
        enums = {-1:'Right', 0:'Left', 1:'Center', 2:'Full', 3:'Above', 4:'Below', 5:'Auto', 6:'Best'}
        for entry in journal:
            if entry['op'] != 'set_caption' or not entry['started']:
                continue
            require(int(entry['_object'].Justification) == entry['originalJustification'],
                    'Original effective caption justification was not restored.')
            old, actual = before_index[entry['targetId']], raw_index[entry['targetId']]
            for key in JUST:
                if old.get(key) is None and actual.get(key) is not None:
                    require(actual.get(key) == enums[entry['originalJustification']],
                            'Restored caption acquired an inequivalent explicit justification.')
                    default_serialization.append({'captionId':entry['targetId'], 'attribute':key,
                                                  'effectiveOriginalEnum':entry['originalJustification'],
                                                  'explicitSerialization':actual.get(key)})
                    del actual.attrib[key]
        import xml.etree.ElementTree as ET
        canonical_defaults = ET.tostring(raw_root, encoding='unicode')
        selected_bonds = [i for i in plan['independentlyAllowedIds'] if before_index[i].tag == 'b']
        rebound = rebind_export_ids(source, canonical_defaults, retained_native, [],
                                    allocated_caption_ids=allocated,
                                    allowed_geometry_ids=plan['independentlyAllowedIds'],
                                    allowed_crossing_bond_ids=selected_bonds,
                                    allow_derived_ancestor_bounds=True)
        result['exportIdRebinding'] = rebound['report']
        result['equivalentExplicitJustificationSerialization'] = default_serialization
        result['verification'] = verify_readback(source, source, rebound['cdxml'], plan, [])
        (folder / 'normalized-rollback-after.cdxml').write_bytes(rebound['cdxml'].encode('utf-8'))
        result['ok'] = True
        result['note'] = 'Original visible geometry, chemistry, text/styles and native IDs restored; logged selected drawing metadata may be recomputed.'
    except Exception as exc:
        result['ok'] = False
        result['error'] = str(exc)
        result['note'] = 'Restoration could not be fully verified. Keep the drawing and the original source backup for recovery; partial changes may remain.'
    (folder / 'rollback-report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def verify_readback(source, desired, actual, plan, generated):
    old_root, old_page, old_index = parse(source)
    wanted_root, wanted_page, wanted_index = parse(desired)
    new_root, new_page, new_index = parse(actual)
    allowed = set(plan['independentlyAllowedIds'])
    require(set(old_index) <= set(new_index), 'Native mutation removed an original object.')
    generated_ids = {r['actualId'] for r in generated}
    proposed_ids = {r['proposedId'] for r in generated}
    require(set(new_index) - set(old_index) == generated_ids, 'Unexpected native object creation.')
    generated_map = {r['actualId']: r for r in generated}
    items, primitive, aliases = ownership(old_root, old_page, old_index)
    targeted_arrows = {o['targetId'] for o in plan['operations'] if o['op'] == 'set_arrow'}
    targeted_aliases = {o['nativeTargetId'] for o in plan['operations'] if o['op'] == 'set_arrow'}
    changed_original_ids, outside_count, normalization, reordered, crossings = set(), 0, [], [], []

    def walk(old, wanted, new, inherited=None):
        nonlocal outside_count
        identifier = old.get('id')
        member = identifier if identifier else inherited
        require(old.tag == new.tag == wanted.tag, 'Original native object type/hierarchy changed.')
        require((old.text or '').strip() == (new.text or '').strip(), 'Original text or style-run content changed.')
        require((old.tail or '').strip() == (new.tail or '').strip(), 'Original text tail changed.')
        require(old.get('id') == new.get('id'), 'Original object ID changed.')
        allowed_here = member in allowed
        changes = {k for k in set(old.attrib) | set(new.attrib) if old.get(k) != new.get(k)}
        if changes and identifier:
            changed_original_ids.add(identifier)
        if old.tag == 'step':
            meaningful = changes - RXN_ORDER
            require(not meaningful, 'Native reaction reactants/products/arrows/other metadata changed.')
            for key in changes:
                require(set(old.get(key, '').split()) == set(new.get(key, '').split()), 'Native reaction ownership membership changed.')
                reordered.append({'stepId': identifier, 'attribute': key})
        elif old.tag in {'CDXML', 'group'} and not allowed_here:
            require(not (changes - {'BoundingBox'}), 'Original ancestor changed beyond derived bounds.')
        elif not allowed_here:
            require(not changes, 'Unselected object changed: ' + str(identifier or old.tag))
            outside_count += 1
        else:
            mutable = set(COORDS)
            if old.tag == 'b':
                mutable.add('CrossingBonds')
            if old.tag == 't' and member in items and items[member]['kind'] == 'text':
                mutable |= JUST
            require(not changes - mutable, 'Original chemistry/style/metadata changed: ' + str(identifier or old.tag))
            for key in set(old.attrib) | set(wanted.attrib) | set(new.attrib):
                if key == 'CrossingBonds' and old.tag == 'b':
                    refs = new.get(key, '').split()
                    require(len(refs) == len(set(refs)) and all(ref in old_index and old_index[ref].tag == 'b' for ref in refs),
                            'Native crossing metadata points to an unknown or nonbond object.')
                    if old.get(key) != new.get(key):
                        crossings.append({'bondId': identifier, 'before': old.get(key), 'after': new.get(key)})
                elif key in JUST and old.tag == 't':
                    if wanted.get('Justification') == 'Center':
                        require(new.get('Justification') == 'Center', 'Native caption was not centered.')
                        require(new.get(key) in {None, 'Center', old.get(key)}, 'Native caption justification is unsupported.')
                    else:
                        require(old.get(key) == new.get(key), 'Unrequested native justification change.')
                elif key in AUX and identifier in targeted_arrows:
                    require(new.get(key) is not None and len(numbers(new.get(key))) == 3, 'Invalid selected-arrow auxiliary geometry.')
                    if wanted.get(key) != new.get(key):
                        normalization.append({'arrowId': identifier, 'attribute': key})
                elif key == 'BoundingBox':
                    # ChemDraw derives glyph bounds itself; original font/face/
                    # size/text remain exact and every explicit anchor is checked.
                    require(new.get(key) is not None and len(numbers(new.get(key))) == 4, 'Missing native derived bounds.')
                    if identifier in targeted_aliases:
                        require(near(numbers(wanted.get(key)), numbers(new.get(key))), 'Native arrow fallback bounds differ from planned endpoints.')
                elif key in COORDS:
                    require((wanted.get(key) is None) == (new.get(key) is None), 'Native coordinate fields changed.')
                    if wanted.get(key) is not None:
                        require(near(numbers(wanted.get(key)), numbers(new.get(key))),
                                'Native geometry differs from plan: ' + str(identifier or member) + '/' + key)
                else:
                    require(wanted.get(key) == new.get(key), 'Original chemistry/style differs from plan.')
        fresh_children = []
        for child in new:
            if child.get('id') in generated_ids:
                require(new is new_page and child.tag == 't', 'Generated number is not a top-level caption.')
                fresh_children.append(child)
        original_children = [child for child in new if child not in fresh_children]
        desired_original_children = [child for child in wanted if child.get('id') not in proposed_ids]
        require(len(old) == len(original_children) == len(desired_original_children), 'Original object hierarchy changed.')
        for a, b, c in zip(old, desired_original_children, original_children):
            walk(a, b, c, member)

    walk(old_root, wanted_root, new_root)
    for actual_id, record in generated_map.items():
        node = new_index[actual_id]
        op = record['operation']
        require(text(node) == op['text'] and node.get('Justification') == 'Center', 'Generated number text/alignment differs.')
        require(near(numbers(node.get('p', '')), [op['position']['x'], op['position']['y']]), 'Generated number anchor differs.')
        require(len(node) == 1 and node[0].tag == 's', 'Generated number has unexpected style runs.')
        for key in ('font', 'face', 'size'):
            require(node[0].get(key) == op['font'][key], 'Generated number font/style differs.')
        require(op['ownerId'] in allowed, 'Generated number owner is outside selection.')
    return {'ok': True, 'outsideOriginalNodesExact': outside_count,
            'changedOriginalIds': sorted(changed_original_ids),
            'selectedArrowAuxiliaryNormalization': normalization,
            'reactionReferenceOrderOnly': reordered, 'selectedBondCrossingRecalculation': crossings,
            'newNumbers': len(generated_ids)}


def execute_plan(doc, source, layout_result, selected_ids, run_folder, failure_after=None):
    folder = Path(run_folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    plan = compile_plan(source, layout_result, selected_ids)
    (folder / 'source-backup.cdxml').write_bytes(source.encode('utf-8'))
    (folder / 'compiled-operations.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    groups, captions, arrows, mappings, fonts, font_scale, font_scales = preflight(doc, source, plan)
    retained_native = native_ids(doc)
    (folder / 'original-native-ids.json').write_text(json.dumps(sorted(retained_native), indent=2), encoding='utf-8')
    journal = make_journal(doc, source, plan, groups, captions, arrows)
    def save_journal():
        payload = {'schema':'scheme-grid-native-rollback/v1', 'sourceSHA256':digest(source),
                   'documentFullName':str(doc.FullName), 'retainedNativeIds':sorted(retained_native),
                   'operations':serial_journal(journal)}
        (folder / 'rollback-journal.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
    save_journal()
    generated, applied = [], []
    report = {'schema': 'scheme-grid-native-execution/v1', 'preflight': True,
              'selectedIds': selected_ids, 'operations': [], 'nativeArrowMappings': mappings,
              'backup': str(folder / 'source-backup.cdxml'), 'transactionOrBatchUndoClaimed': False}
    report['documentFullName'] = str(doc.FullName)
    report['nativeFontUnitCalibration'] = font_scales
    try:
        for op_index, op in enumerate(plan['operations']):
            kind = op['op']
            entry = journal[op_index]
            entry['started'] = True
            save_journal()
            if kind == 'move_rigid':
                groups[op['targetId']].Objects.Move(float(op['dx']), float(op['dy']))
            elif kind == 'set_caption':
                caption = captions[op['targetId']]
                if op['justification'] == 'Center':
                    caption.Justification = 1
                place_caption(doc, caption, op['targetId'], op['position'])
            elif kind == 'set_arrow':
                arrow = arrows[op['nativeTargetId']]
                for prop, meaning in mappings[op['targetId']].items():
                    set_point(arrow, prop, [op[meaning]['x'], op[meaning]['y']])
            elif kind == 'create_number':
                caption = doc.MakeCaption()
                actual_id = str(int(caption.ID))
                entry.update(actualId=actual_id, _object=caption)
                generated.append({'proposedId': op['proposedId'], 'actualId': actual_id,
                                  'ownerId': op['ownerId'], 'operation': op})
                save_journal()
                caption.Text = op['text']
                require(int(caption.Styles.Count) == 1, 'New number requires one native text style run.')
                style = caption.Styles.Item(1)
                style.Family = fonts[op['font']['font']]
                style.Size = float(op['font']['size']) * font_scale
                style.Face = int(op['font']['face'])
                caption.Justification = 1
                place_caption(doc, caption, actual_id, op['position'])
            entry['applied'] = True
            save_journal()
            applied.append({'op': kind, 'targetId': op.get('targetId'), 'ownerId': op.get('ownerId')})
            if failure_after is not None and len(applied) == failure_after:
                raise RuntimeError('Injected isolated test failure after ' + str(failure_after) + ' operations.')
        actual = capture(doc)
        (folder / 'native-after.cdxml').write_bytes(actual.encode('utf-8'))
        require(native_ids(doc) == retained_native | {r['actualId'] for r in generated},
                'Native physical object IDs changed unexpectedly.')
        _, _, original_index = parse(source)
        rebound = rebind_export_ids(source, actual, retained_native, generated,
                                    allowed_geometry_ids=plan['independentlyAllowedIds'],
                                    allowed_caption_centering_ids=[o['targetId'] for o in plan['operations'] if o['op'] == 'set_caption'],
                                    allowed_crossing_bond_ids=[i for i in plan['independentlyAllowedIds'] if original_index[i].tag == 'b'],
                                    allow_derived_ancestor_bounds=True)
        (folder / 'normalized-native-after.cdxml').write_bytes(rebound['cdxml'].encode('utf-8'))
        normalized_generated = [dict(r, actualId=r['proposedId']) for r in generated]
        report['exportIdRebinding'] = rebound['report']
        report['verification'] = verify_readback(source, layout_result['cdxml'], rebound['cdxml'], plan, normalized_generated)
        report['ok'] = True
        report['postSnapshotSHA256'] = digest(actual)
    except Exception as exc:
        report['ok'] = False
        report['error'] = str(exc)
        try:
            (folder / 'native-failed-after.cdxml').write_bytes(capture(doc).encode('utf-8'))
        except Exception as capture_error:
            report['captureError'] = str(capture_error)
        report['rollback'] = rollback(doc, source, plan, journal, retained_native, folder)
        report['failureDisposition'] = ('Original drawing restored and independently verified.' if report['rollback'].get('ok') else
                                        'Restoration is incomplete or unverified; original backup retained and partial changes may remain.')
    report['operations'] = applied
    report['generatedCaptionMapping'] = [{k:v for k,v in x.items() if k != 'operation'} for x in generated]
    (folder / 'execution-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report

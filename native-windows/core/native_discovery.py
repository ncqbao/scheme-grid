"""Optional strict-ID source discovery for native FileRun exports.

Identity only, not a chemical graph matcher or a write validator. A shared page
GUID, exact retained IDs/content and explicit arrow aliases are mandatory.
The original exact prearmed guard in native_request.py is not changed.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import uuid

from native_request import GuardError, drawing, freeze, resolved
from native_runtime import allowed_application_paths

ROOT_VIEW = {'Name', 'BoundingBox', 'WindowPosition', 'WindowSize', 'WindowIsZoomed',
             'Magnification', 'MacPrintInfo'}
ATOM_DERIVED = {'p', 'Z', 'AS', 'Warning'}
BOND_DERIVED = {'Z', 'BS', 'CrossingBonds', 'BondCircularOrdering', 'BeginExternalNum', 'EndExternalNum'}
TEXT_DERIVED = {'p', 'BoundingBox', 'LineStarts', 'Z'}


def require(value, message):
    if not value:
        raise GuardError(message)


def attrs(node, ignored=()):
    return tuple(sorted((key, value) for key, value in node.attrib.items() if key not in ignored))


def runs(node):
    return tuple((attrs(s), s.text or '') for t in node if t.tag == 't' for s in t if s.tag == 's')


def identity(text):
    root = drawing(text)
    font_table = root.find('fonttable')
    font_map = {font.get('id'): attrs(font, {'id'}) for font in font_table} if font_table is not None else {}
    used_font_ids = {node.get(key) for node in root.iter() for key in ('font', 'LabelFont', 'CaptionFont')
                     if node.get(key) is not None}
    require(used_font_ids <= set(font_map), 'A used font reference is absent from the native font table.')
    used_font_semantics = tuple(sorted({font_map[i] for i in used_font_ids}))
    for node in root.iter():
        for key in ('font', 'LabelFont', 'CaptionFont'):
            if node.get(key) is not None:
                node.set(key, '@font:' + json.dumps(font_map[node.get(key)], separators=(',', ':')))
    pages = root.findall('page')
    require(len(pages) == 1, 'Discovery currently requires a single native CDXML page.')
    page = pages[0]
    parents = {child: node for node in page.iter() for child in node}
    identifiers = {}
    for node in page.iter():
        identifier = node.get('id')
        if identifier and node is not page:
            require(identifier not in identifiers, 'Duplicate drawing ID in source-discovery input.')
            identifiers[identifier] = node
    guid = [e.get('Content') for e in page if e.tag == 'annotation' and e.get('Keyword') == 'GUID']
    require(len(guid) == 1 and guid[0], 'Discovery requires one retained page GUID annotation.')
    try:
        uuid.UUID(guid[0])
    except (ValueError, AttributeError):
        raise GuardError('The retained page GUID annotation is not a valid UUID.')
    def inside_fragment(node):
        parent = parents.get(node)
        while parent is not None:
            if parent.tag == 'fragment':
                return True
            parent = parents.get(parent)
        return False
    visible = [node for node in page.iter() if node.tag == 'fragment' and not inside_fragment(node)]
    require(visible, 'Discovery needs a retained native molecule fragment ID.')
    molecules, stacking = {}, {}
    for fragment in visible:
        all_nodes = {node.get('id'): node for node in fragment.iter('n')}
        all_bonds = {node.get('id'): node for node in fragment.iter('b')}
        require(None not in all_nodes and None not in all_bonds, 'Chemical objects need retained IDs.')
        wrappers = {i: n for i, n in all_nodes.items() if n.find('fragment') is not None}
        require(all(n.get('NodeType') in {'Fragment', 'Nickname'} for n in wrappers.values()),
                'Unsupported contracted chemical node in native discovery.')
        ports = {i: n for i, n in all_nodes.items() if n.get('NodeType') == 'ExternalConnectionPoint'}
        port_neighbors = {}
        for identifier in ports:
            links = [b for b in all_bonds.values() if identifier in {b.get('B'), b.get('E')}]
            require(len(links) == 1, 'An external connection point has ambiguous connectivity.')
            link = links[0]
            neighbor = link.get('E') if link.get('B') == identifier else link.get('B')
            require(neighbor in all_nodes and neighbor not in ports, 'Unsupported external port chain.')
            port_neighbors[identifier] = neighbor
        def endpoint(identifier, bond, side, trail=()):
            if identifier not in wrappers:
                return identifier
            require(identifier not in trail, 'Cyclic contracted atom expansion.')
            wrapper = wrappers[identifier]
            inner = wrapper.find('fragment')
            own_ports = [n for n in inner if n.tag == 'n' and n.get('NodeType') == 'ExternalConnectionPoint']
            number = bond.get('BeginExternalNum' if side == 'B' else 'EndExternalNum')
            if number is None:
                ordering = wrapper.get('BondOrdering', '').split()
                if bond.get('id') in ordering:
                    number = str(ordering.index(bond.get('id')) + 1)
                elif len(own_ports) == 1:
                    number = own_ports[0].get('ExternalConnectionNum', '1')
            choices = [p for p in own_ports if p.get('ExternalConnectionNum', '1') == number]
            require(len(choices) == 1, 'A contracted attachment has no exact external-port mapping.')
            target = port_neighbors[choices[0].get('id')]
            require(target not in wrappers, 'Nested contracted attachments are not supported by this command.')
            return target
        atoms = {}
        for identifier, node in all_nodes.items():
            if identifier in wrappers or identifier in ports:
                continue
            atoms[identifier] = (attrs(node, ATOM_DERIVED), runs(node))
        bonds = {}
        for identifier, bond in all_bonds.items():
            if bond.get('B') in ports or bond.get('E') in ports:
                continue
            a, b = endpoint(bond.get('B'), bond, 'B'), endpoint(bond.get('E'), bond, 'E')
            require(a in atoms and b in atoms, 'A normalized bond endpoint is absent.')
            values = dict(attrs(bond, BOND_DERIVED))
            values['B'], values['E'] = a, b
            bonds[identifier] = tuple(sorted(values.items()))
        molecules[fragment.get('id')] = {'attrs': attrs(fragment, {'BoundingBox', 'Z'}), 'atoms': atoms, 'bonds': bonds}
        if fragment.get('Z') is not None:
            stacking[fragment.get('id')] = int(fragment.get('Z'))
    captions = {}
    for node in page.iter('t'):
        if inside_fragment(node):
            continue
        require(node.get('id'), 'Standalone text needs a retained native ID.')
        captions[node.get('id')] = (attrs(node, TEXT_DERIVED), tuple(freeze(s) for s in node))
        if node.get('Z') is not None:
            stacking[node.get('id')] = int(node.get('Z'))
    arrows = []
    native_arrows = [n for n in page.iter('arrow')
                     if n.get('ArrowheadHead', 'None') != 'None' or n.get('ArrowheadTail', 'None') != 'None']
    alias_ids = set()
    for arrow in native_arrows:
        ids = {arrow.get('id')}
        changed = True
        while changed:
            changed = False
            for identifier, node in identifiers.items():
                if node.get('SupersededBy') in ids and identifier not in ids:
                    ids.add(identifier); changed = True
        alias_ids.update(ids)
        arrows.append({'ids': ids, 'data': attrs(arrow, {'id', 'BoundingBox', 'Z'}),
                       'z': int(arrow.get('Z')) if arrow.get('Z') is not None else None})
    decorations = {identifier: freeze(node) for identifier, node in identifiers.items()
                   if node.tag in {'graphic', 'arrow'} and identifier not in alias_ids and not inside_fragment(node)}
    groups = {identifier: attrs(node, {'BoundingBox'}) for identifier, node in identifiers.items()
              if node.tag == 'group' and not inside_fragment(node)}
    # Native selected-part export can omit an unused duplicate font declaration.
    # Every referenced font ID and its exact family/charset remain mandatory.
    tables = []
    for node in root:
        if node.tag == 'colortable':
            tables.append(freeze(node))
        elif node.tag == 'fonttable':
            tables.append((node.tag, attrs(node), used_font_semantics))
    tables = tuple(tables)
    return {'guid': guid[0], 'root': attrs(root, ROOT_VIEW), 'tables': tables,
            'molecules': molecules, 'captions': captions, 'arrows': arrows,
            'decorations': decorations, 'groups': groups, 'stacking': stacking}


def matches(host_xml, native_xml):
    host, native = identity(host_xml), identity(native_xml)
    for key in ('guid', 'root', 'tables', 'molecules', 'captions', 'decorations', 'groups'):
        if host[key] != native[key]:
            return False, 'Retained native identity differs: ' + key
    if len(host['arrows']) != len(native['arrows']):
        return False, 'Reaction-arrow counts differ.'
    used = set()
    retained_ids = tuple(native['molecules']) + tuple(native['captions'])
    z_pairs = [(native['stacking'].get(i), host['stacking'].get(i)) for i in retained_ids]
    for source in native['arrows']:
        candidates = [i for i, arrow in enumerate(host['arrows'])
                      if source['ids'] & arrow['ids'] and source['data'] == arrow['data']]
        if len(candidates) != 1 or candidates[0] in used:
            return False, 'Reaction arrows lack a unique explicit native ID alias.'
        used.add(candidates[0])
        z_pairs.append((source['z'], host['arrows'][candidates[0]]['z']))
    # FileRun's selected export rebases absolute Z indices. Preserve every
    # molecule/caption/arrow pair's exact relative order, including ties.
    if any((a is None) != (b is None) for a, b in z_pairs):
        return False, 'Primary native stacking metadata is missing.'
    z_pairs = [(a, b) for a, b in z_pairs if a is not None]
    require(len(z_pairs) <= 1000, 'Too many primary objects for bounded native identity comparison.')
    for i, (a, b) in enumerate(z_pairs):
        for c, d in z_pairs[:i]:
            if ((a > c) - (a < c)) != ((b > d) - (b < d)):
                return False, 'Native molecule/caption/arrow relative stacking order changed.'
    return True, 'Exact GUID, retained native IDs, text/styles and chemical attachment identities match.'


def discover_one(host_xml, candidates):
    """Pure function. candidates contain stable COM snapshots, not live handles.

    The native selection determines the only candidate scope. Selecting every
    object remains one selected candidate; separate matching documents refuse.
    """
    accepted, rejected = [], []
    host_identity = identity(host_xml)  # fail early on missing GUID/unknown input
    for candidate in candidates:
        fullname = candidate.get('documentFullName', '')
        if not fullname or not Path(fullname).is_absolute():
            rejected.append({'document': fullname, 'reason': 'Only explicit saved documents are supported.'})
            continue
        scopes = ('selection',) if candidate.get('selectedIds') else ('full',)
        for scope in scopes:
            key = 'fullCDXML' if scope == 'full' else 'selectionCDXML'
            try:
                okay, reason = matches(host_xml, candidate[key])
            except GuardError as exc:
                okay, reason = False, str(exc)
            if okay:
                accepted.append((candidate, scope))
            else:
                rejected.append({'document': fullname, 'scope': scope, 'reason': reason})
    require(len(accepted) == 1, 'Native source identity is absent or ambiguous; no drawing is authorized.')
    candidate, scope = accepted[0]
    if scope == 'full':
        require(not candidate.get('selectedIds'), 'The selection changed or global-vs-selected scope is ambiguous.')
    result = dict(candidate)
    result['discoveryScope'] = scope
    result['discoveryGUID'] = host_identity['guid']
    result['rejectedCandidates'] = rejected
    return result


def process_identity(pid):
    """Read process metadata only, with no window/UI APIs or COM calls."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p,
                                                ctypes.POINTER(ctypes.c_ulong)]
    class FileTime(ctypes.Structure):
        _fields_ = [('low', ctypes.c_ulong), ('high', ctypes.c_ulong)]
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(FileTime)] * 4
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    require(handle, 'The native caller process cannot be verified.')
    try:
        text = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(text))
        require(kernel.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(size)),
                'The native caller executable cannot be read.')
        created, exited, kernel_time, user = FileTime(), FileTime(), FileTime(), FileTime()
        require(kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                       ctypes.byref(kernel_time), ctypes.byref(user)),
                'The native caller process creation time cannot be read.')
        return {'pid': int(pid), 'executable': text.value,
                'creationFileTime': int(created.high) << 32 | int(created.low)}
    finally:
        kernel.CloseHandle(handle)


def process_ids():
    """Standard Windows process enumeration, usable by a host without pywin32."""
    api = ctypes.WinDLL('psapi', use_last_error=True)
    api.EnumProcesses.argtypes = [ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong,
                                 ctypes.POINTER(ctypes.c_ulong)]
    count = 4096
    while count <= 131072:
        values = (ctypes.c_ulong * count)()
        used = ctypes.c_ulong()
        require(api.EnumProcesses(values, ctypes.sizeof(values), ctypes.byref(used)),
                'The native process list could not be read.')
        if used.value < ctypes.sizeof(values):
            return list(values[:used.value // ctypes.sizeof(ctypes.c_ulong)])
        count *= 2
    raise GuardError('The process list exceeds the preview limit.')


def executable_major_version(path):
    """Read file-version metadata using version.dll; no COM or UI APIs."""
    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    api.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    api.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                  ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    ignored = ctypes.c_ulong()
    length = api.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
    require(0 < length < 4_000_000, 'The native caller version metadata is unavailable.')
    buffer = ctypes.create_string_buffer(length)
    require(api.GetFileVersionInfoW(str(path), 0, length, buffer), 'The caller version metadata could not be read.')
    value = ctypes.c_void_p()
    size = ctypes.c_uint()
    require(api.VerQueryValueW(buffer, '\\', ctypes.byref(value), ctypes.byref(size)) and size.value >= 52,
            'The caller fixed version metadata is invalid.')
    words = ctypes.cast(value, ctypes.POINTER(ctypes.c_ulong))
    require(words[0] == 0xFEEF04BD, 'The caller version signature is invalid.')
    return int(words[2]) >> 16


def trusted_processes():
    allowed = {resolved(path) for path in allowed_application_paths()}
    result = []
    for pid in process_ids():
        if not pid:
            continue
        try:
            process = process_identity(pid)
            if resolved(process['executable']) in allowed:
                result.append(process)
        except GuardError:
            continue
    return result


def caller_provenance():
    parent = process_identity(os.getppid())
    allowed = {resolved(path) for path in allowed_application_paths()}
    require(resolved(parent['executable']) in allowed,
            'Run Scheme Grid from File > ChemScripts in the installed ChemDraw 26 application.')
    require(executable_major_version(parent['executable']) == 26,
            'The calling application is not the supported ChemDraw26 installation.')
    require(trusted_processes() == [parent], 'There is more than one possible installed ChemDraw26 process.')
    return parent


def validate_provenance(expected):
    require(resolved(expected['executable']) in {resolved(path) for path in allowed_application_paths()},
            'The saved caller is not an allowed ChemDraw26 installation.')
    current = process_identity(expected['pid'])
    require(current == expected and trusted_processes() == [expected],
            'The calling ChemDraw26 process exited, changed, or became ambiguous.')
    return current

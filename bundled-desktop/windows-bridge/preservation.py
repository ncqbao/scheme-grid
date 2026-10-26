"""Windows ChemDraw capture and preservation checks; Python standard library only.

Extracted without behavioral edits from Scheme Grid 0.2.1-lab. No HTTP service.
"""


from __future__ import annotations


import base64
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


MAX_BODY = 15 * 1024 * 1024


COORDINATES = {
    "p", "BoundingBox", "Head3D", "Tail3D", "Center3D", "MajorAxisEnd3D",
    "MinorAxisEnd3D", "Position", "BoundsInParent", "xyz", "CurvePoints",
    "CurvePoints3D", "TopLeft", "TopRight", "BottomRight", "BottomLeft",
}


WINDOWS_CONTEXT = r'''
$ErrorActionPreference = 'Stop'
$taskVisibleApps = @([Diagnostics.Process]::GetProcessesByName('ChemDraw') | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero })
if ($taskVisibleApps.Count -gt 1) { throw 'SG_MULTIPLE_WINDOWS' }
if ($taskVisibleApps.Count -ne 1) { throw 'SG_NO_WINDOW' }
try { $taskApplication = [Runtime.InteropServices.Marshal]::GetActiveObject('ChemDraw.Application') }
catch { throw 'SG_NO_AUTOMATION' }
$taskVisiblePath = [IO.Path]::GetFullPath([string]$taskVisibleApps[0].MainModule.FileName)
$taskAutomationPath = [IO.Path]::GetFullPath([string]$taskApplication.FullName)
if (-not [string]::Equals($taskVisiblePath,$taskAutomationPath,[StringComparison]::OrdinalIgnoreCase)) { throw 'SG_OTHER_INSTALLATION' }
'''


def parse_cdxml(value: str) -> ET.Element:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("The drawing is empty.")
    if len(value.encode("utf-8")) > MAX_BODY:
        raise ValueError("The drawing is too large for this version.")
    if re.search(r"<!ENTITY|<!DOCTYPE\s+[^>]*\[", value, re.I):
        raise ValueError("XML entity declarations are not supported.")
    try:
        root = ET.fromstring(value)
    except ET.ParseError as exc:
        raise ValueError("The drawing is not valid CDXML.") from exc
    if root.tag != "CDXML":
        raise ValueError("Expected a ChemDraw CDXML document.")
    return root


def _numeric(value: str) -> list[float]:
    import math
    try:
        values = [float(part) for part in value.replace(",", " ").split()]
    except ValueError as exc:
        raise ValueError("A drawing coordinate is not numeric.") from exc
    if not values or any(not math.isfinite(v) or abs(v) > 1e7 for v in values):
        raise ValueError("A drawing coordinate is outside the supported range.")
    return values


def _coordinate_deltas(key: str, old_value: str, new_value: str) -> list[tuple[float, float]]:
    old_numbers, new_numbers = _numeric(old_value), _numeric(new_value)
    if len(old_numbers) != len(new_numbers):
        raise ValueError("The result changed a coordinate's dimensions.")
    if key in {"xyz", "Head3D", "Tail3D", "Center3D", "MajorAxisEnd3D", "MinorAxisEnd3D", "CurvePoints3D"}:
        stride = 3
    else:
        stride = 2
    # A few ChemDraw fields use a leading point count. Preserve that prefix.
    start = 0
    if key in {"CurvePoints", "CurvePoints3D"} and len(old_numbers) % stride == 1:
        if old_numbers[0] != new_numbers[0]:
            raise ValueError("The result changed a curve's point count.")
        start = 1
    if (len(old_numbers) - start) % stride:
        raise ValueError("A drawing coordinate has an unsupported shape.")
    deltas = []
    for index in range(start, len(old_numbers), stride):
        deltas.append((new_numbers[index] - old_numbers[index], new_numbers[index + 1] - old_numbers[index + 1]))
        if stride == 3 and abs(old_numbers[index + 2] - new_numbers[index + 2]) > 0.002:
            raise ValueError("The result changed a third-dimensional coordinate.")
    return deltas


def _verify_rigid_subtree(old_root: ET.Element, new_root: ET.Element) -> None:
    shift = None
    for old, new in zip(old_root.iter(), new_root.iter()):
        for key in COORDINATES:
            if old.get(key) is None:
                continue
            for delta in _coordinate_deltas(key, old.get(key), new.get(key)):
                if shift is None:
                    shift = delta
                elif any(abs(delta[i] - shift[i]) > 0.003 for i in (0, 1)):
                    raise ValueError("The result distorted a molecule, label, or arrow instead of moving it together.")


def verify_preservation(source: str, result: str) -> None:
    """Reject altered chemistry, styling, text, IDs, or document topology."""
    before = parse_cdxml(source)
    after = parse_cdxml(result)
    a = list(before.iter())
    b = list(after.iter())
    if len(a) != len(b):
        raise ValueError("The result changed the drawing's object count.")
    for old, new in zip(a, b):
        if old.tag != new.tag or len(old) != len(new):
            raise ValueError("The result changed the drawing's object hierarchy.")
        old_attrs = {k: v for k, v in old.attrib.items() if k not in COORDINATES}
        new_attrs = {k: v for k, v in new.attrib.items() if k not in COORDINATES}
        if old_attrs != new_attrs:
            raise ValueError("The result changed chemistry, styling, IDs, or metadata.")
        # XML indentation may differ. Text in styled runs is never normalized.
        if old.tag == "s":
            same_text = (old.text or "") == (new.text or "")
        else:
            same_text = (old.text or "").strip() == (new.text or "").strip()
        if not same_text or (old.tail or "").strip() != (new.tail or "").strip():
            raise ValueError("The result changed a drawing label.")
        for key in COORDINATES:
            old_value = old.get(key)
            new_value = new.get(key)
            if (old_value is None) != (new_value is None):
                raise ValueError("The result added or removed a coordinate attribute.")
            if old_value is None:
                continue
            _coordinate_deltas(key, old_value, new_value)
    # Every molecule (including atom labels) and every arrow must move rigidly.
    # Containers may change size when their independent children are rearranged.
    for tag in ("fragment", "arrow", "t", "graphic"):
        for old_root, new_root in zip(before.iter(tag), after.iter(tag)):
            _verify_rigid_subtree(old_root, new_root)


def verify_reaction_cleanup(
    source: str, result: str, *, selected_ids=None, scope=None, numbering=None
) -> None:
    """Allow deliberate arrow/text cleanup and number labels; protect chemistry.

    This is separate from the translation-only guard so existing grid operations
    retain their original contract. The input is always a full document snapshot.
    """
    before, after = parse_cdxml(source), parse_cdxml(result)
    old_pages, new_pages = list(before.iter("page")), list(after.iter("page"))
    if len(old_pages) != len(new_pages):
        raise ValueError("The cleanup changed the drawing's page count.")
    old_parents = {child: parent for parent in before.iter() for child in parent}
    new_parents = {child: parent for parent in after.iter() for child in parent}
    old_drawing_ids = {
        node.get("id"): node for page in old_pages for node in page.iter() if node.get("id")
    }
    source_ids = {node.get("id") for node in before.iter() if node.get("id")}
    new_captions = []
    added_caption_ids = set()
    known_fonts = {node.get("id") for node in before.iter("font")}
    for page in new_pages:
        for node in page:
            identifier = node.get("id")
            if node.tag != "t" or not identifier or identifier in old_drawing_ids:
                continue
            if identifier in source_ids or identifier in added_caption_ids:
                raise ValueError("A new compound number reused an existing object ID.")
            if not re.fullmatch(r"[1-9]\d*", identifier):
                raise ValueError("A new compound number has an invalid object ID.")
            allowed = {"id", "p", "BoundingBox", "Z", "CaptionJustification", "Justification", "LineHeight"}
            if set(node.attrib) - allowed or len(node) != 1 or node[0].tag != "s":
                raise ValueError("The cleanup added an unsupported drawing object.")
            span = node[0]
            if len(span) or set(span.attrib) - {"font", "size", "face", "color"}:
                raise ValueError("A new compound number has unsupported contents.")
            if not re.fullmatch(r"[1-9]\d*", span.text or ""):
                raise ValueError("Only integer compound-number captions may be added.")
            if span.get("font") not in known_fonts:
                raise ValueError("A new compound number refers to an unknown font.")
            if node.get("Justification") != "Center" or node.get("CaptionJustification") != "Center":
                raise ValueError("A new compound number must use centered justification.")
            for key in ("p", "BoundingBox"):
                if not node.get(key):
                    raise ValueError("A new compound number is missing its placement.")
                _coordinate_deltas(key, node.get(key), node.get(key))
            added_caption_ids.add(identifier)
            new_captions.append(node)
    if numbering is not None:
        if not isinstance(numbering, list):
            raise ValueError("The compound-number report is invalid.")
        reported = {}
        for record in numbering:
            if not isinstance(record, dict) or not record.get("added"):
                continue
            caption_id, owner_id = str(record.get("captionId", "")), str(record.get("moleculeId", ""))
            owner = old_drawing_ids.get(owner_id)
            if owner is None or owner.tag not in {"fragment", "group"}:
                raise ValueError("A new compound number has no original molecule owner.")
            if caption_id in reported:
                raise ValueError("A compound-number caption was reported more than once.")
            reported[caption_id] = str(record.get("number", ""))
        if set(reported) != added_caption_ids:
            raise ValueError("The new compound-number labels do not match the cleanup report.")
        for node in new_captions:
            if node[0].text != reported[node.get("id")]:
                raise ValueError("A compound-number label does not match its reported number.")
    elif new_captions:
        raise ValueError("The cleanup did not report its new compound-number labels.")

    if selected_ids is None:
        selected_ids = []
    if not isinstance(selected_ids, list) or any(not isinstance(v, (str, int)) for v in selected_ids):
        raise ValueError("The selected-object list is invalid.")
    selection = {str(value) for value in selected_ids}
    if selection - set(old_drawing_ids):
        raise ValueError("A selected object is absent from the full drawing snapshot.")
    affected_nodes = set()
    affected_ancestors = set()
    if selection:
        if not isinstance(scope, dict) or not scope.get("selected") or not isinstance(scope.get("affectedIds"), list):
            raise ValueError("The cleanup did not provide its selected-object scope.")
        affected = {str(value) for value in scope["affectedIds"]}
        if not affected or affected - set(old_drawing_ids) - added_caption_ids:
            raise ValueError("The selected-object cleanup scope is invalid.")
        for identifier in affected & set(old_drawing_ids):
            node = old_drawing_ids[identifier]
            affected_nodes.update(node.iter())
            parent = old_parents.get(node)
            while parent is not None:
                affected_ancestors.add(parent)
                parent = old_parents.get(parent)

    def inside_fragment(node):
        parent = old_parents.get(node)
        while parent is not None:
            if parent.tag == "fragment":
                return True
            parent = old_parents.get(parent)
        return False

    pairs = []

    def compare(old, new):
        if old.tag != new.tag:
            raise ValueError("The cleanup changed the drawing's object hierarchy.")
        pairs.append((old, new))
        centered_caption = old.tag == "t" and not inside_fragment(old)
        ignored = COORDINATES | ({"Justification", "CaptionJustification"} if centered_caption else set())
        if old.tag == "page" and not selection:
            ignored = ignored | {"WidthPages", "HeightPages"}
            count_keys = ("WidthPages", "HeightPages")
            if any(old.get(key) != new.get(key) for key in count_keys):
                old_box, new_box = _numeric(old.get("BoundingBox", "")), _numeric(new.get("BoundingBox", ""))
                if len(old_box) != 4 or len(new_box) != 4 or old_box[:2] != new_box[:2]:
                    raise ValueError("Page expansion changed the page origin.")
                for axis, key in enumerate(count_keys):
                    previous, current = old.get(key, "1"), new.get(key, "1")
                    if (not re.fullmatch(r"[1-9][0-9]*", previous) or not re.fullmatch(r"[1-9][0-9]*", current)
                            or int(current) < int(previous) or int(current) > 1000
                            or (old.get(key) is not None and new.get(key) is None)):
                        raise ValueError("Page expansion must add complete sheets without shrinking.")
                    sheet = (old_box[axis + 2] - old_box[axis]) / int(previous)
                    expected = old_box[axis] + sheet * int(current)
                    if sheet <= 0 or abs(new_box[axis + 2] - expected) > 0.02:
                        raise ValueError("Page expansion changed the original sheet dimensions.")
        if {k: v for k, v in old.attrib.items() if k not in ignored} != {k: v for k, v in new.attrib.items() if k not in ignored}:
            raise ValueError("The cleanup changed chemistry, styling, IDs, or metadata.")
        if centered_caption:
            for key in ("Justification", "CaptionJustification"):
                if old.get(key) != new.get(key) and new.get(key) != "Center":
                    raise ValueError("A caption was changed to unsupported justification.")
        if old.tag == "s":
            same_text = (old.text or "") == (new.text or "")
        else:
            same_text = (old.text or "").strip() == (new.text or "").strip()
        if not same_text or (old.tail or "").strip() != (new.tail or "").strip():
            raise ValueError("The cleanup changed an existing drawing label.")
        for key in COORDINATES:
            if (old.get(key) is None) != (new.get(key) is None):
                raise ValueError("The cleanup added or removed an original coordinate field.")
            if old.get(key) is not None:
                _coordinate_deltas(key, old.get(key), new.get(key))
        if selection and old not in affected_nodes:
            allowed_ancestor_box = old in affected_ancestors and old.tag in {"CDXML", "group", "page"}
            ignored_here = {"BoundingBox"} if allowed_ancestor_box else set()
            if {k: v for k, v in old.attrib.items() if k not in ignored_here} != {k: v for k, v in new.attrib.items() if k not in ignored_here}:
                raise ValueError("The cleanup changed an object outside its selected scope.")
        old_children = list(old)
        new_children = [child for child in new if child not in new_captions]
        if len(old_children) != len(new_children):
            raise ValueError("The cleanup added or removed original drawing objects.")
        for old_child, new_child in zip(old_children, new_children):
            compare(old_child, new_child)

    compare(before, after)
    aliases = {node.get("id"): node.get("SupersededBy") for node in before.iter("graphic") if node.get("SupersededBy")}
    reaction_arrow_ids = {
        node.get("id") for node in before.iter("arrow")
        if node.get("ArrowheadHead") not in {None, "None"} or node.get("ArrowheadTail") not in {None, "None"}
    }
    for old, new in pairs:
        if old.tag == "fragment":
            _verify_rigid_subtree(old, new)
        elif old.tag == "graphic":
            arrow_graphic = old.get("GraphicType") == "Line" and old.get("ArrowType") not in {None, "None"}
            arrow_fallback = aliases.get(old.get("id")) in reaction_arrow_ids
            if not arrow_graphic and not arrow_fallback:
                _verify_rigid_subtree(old, new)
        elif old.tag == "t" and not inside_fragment(old):
            if old.get("BoundingBox") and new.get("BoundingBox"):
                a, b = _numeric(old.get("BoundingBox")), _numeric(new.get("BoundingBox"))
                if any(abs((b[i + 2] - b[i]) - (a[i + 2] - a[i])) > 0.003 for i in (0, 1)):
                    raise ValueError("The cleanup resized existing caption text.")
        elif old.tag == "arrow" and old.get("id") not in reaction_arrow_ids:
            _verify_rigid_subtree(old, new)
        elif old.tag == "arrow" and old.get("Head3D") and old.get("Tail3D"):
            oh, ot = _numeric(old.get("Head3D")), _numeric(old.get("Tail3D"))
            nh, nt = _numeric(new.get("Head3D")), _numeric(new.get("Tail3D"))
            if (nh[0] - nt[0]) ** 2 + (nh[1] - nt[1]) ** 2 < 1:
                raise ValueError("The cleanup collapsed a reaction arrow.")
            if (oh[0] - ot[0]) * (nh[0] - nt[0]) + (oh[1] - ot[1]) * (nh[1] - nt[1]) <= 0:
                raise ValueError("The cleanup reversed a reaction arrow.")
    new_drawing_ids = {
        node.get("id"): node for page in new_pages for node in page.iter() if node.get("id")
    }
    for alias_id, target_id in aliases.items():
        old_graphic, new_graphic = old_drawing_ids.get(alias_id), new_drawing_ids.get(alias_id)
        old_arrow, new_arrow = old_drawing_ids.get(target_id), new_drawing_ids.get(target_id)
        if old_arrow is None or new_arrow is None or not old_arrow.get("Head3D") or not old_arrow.get("Tail3D"):
            continue
        if not old_graphic.get("BoundingBox") or not new_graphic.get("BoundingBox"):
            continue
        old_box, new_box = _numeric(old_graphic.get("BoundingBox")), _numeric(new_graphic.get("BoundingBox"))
        old_ends = [_numeric(old_arrow.get("Head3D")), _numeric(old_arrow.get("Tail3D"))]
        new_ends = [_numeric(new_arrow.get("Head3D")), _numeric(new_arrow.get("Tail3D"))]
        for index in (0, 2):
            nearest = min(range(2), key=lambda end: sum((old_box[index + axis] - old_ends[end][axis]) ** 2 for axis in (0, 1)))
            if any(abs((new_box[index + axis] - old_box[index + axis]) - (new_ends[nearest][axis] - old_ends[nearest][axis])) > 0.003 for axis in (0, 1)):
                raise ValueError("An arrow's legacy fallback did not follow its updated geometry.")


def capture_active_document() -> dict:
    """Read public COM automation data; do not save, select, or alter the document."""
    if os.name != "nt":
        raise ValueError("Reading the active ChemDraw document requires Windows.")
    script = WINDOWS_CONTEXT + r'''
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$taskDocument = $taskApplication.ActiveDocument
if ($null -eq $taskDocument) { throw 'No active ChemDraw document.' }
$taskObjects = $taskDocument.Objects
$taskMissing = [Type]::Missing
$taskCDXML = $taskObjects.GetType().InvokeMember('Data',[Reflection.BindingFlags]::GetProperty,$null,$taskObjects,@('chemical/x-cdxml',$taskMissing,$taskMissing,$taskMissing))
if (-not ($taskCDXML -is [string]) -or $taskCDXML.IndexOf('<CDXML') -lt 0) { throw 'ChemDraw did not return CDXML.' }
$taskSelection = $taskDocument.selection.Objects
$taskSelectedIDs = @()
for ($taskIndex=1; $taskIndex -le $taskSelection.Count; $taskIndex++) {
    $taskSelectedIDs += [string]$taskSelection.Item($taskIndex).ID
}
@{sourceCDXML=$taskCDXML;sourceName=[string]$taskDocument.Name;selectedIds=$taskSelectedIDs;selectionCount=[int]$taskSelection.Count} | ConvertTo-Json -Compress -Depth 4
'''
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    try:
        completed = subprocess.run(
            [str(powershell), "-NoProfile", "-STA", "-NonInteractive", "-EncodedCommand", encoded],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Could not read ChemDraw. Open your scheme in ChemDraw and try again.") from exc
    if completed.returncode:
        error_text = completed.stderr.decode("utf-8", errors="replace")
        if "SG_MULTIPLE_WINDOWS" in error_text:
            raise ValueError("More than one ChemDraw application is open. Save your changes, keep the intended drawing open in one ChemDraw application, then run Clean Active Scheme again.")
        if "SG_NO_WINDOW" in error_text:
            raise ValueError("No ChemDraw drawing window is open. Open your drawing directly in ChemDraw, then run Clean Active Scheme again.")
        if "SG_NO_AUTOMATION" in error_text:
            raise ValueError("ChemDraw's live connection is unavailable. If you are editing an object inside PowerPoint, save a separate ChemDraw or CDXML copy and open it directly in ChemDraw. You can also use CDXML file mode.")
        if "SG_OTHER_INSTALLATION" in error_text:
            raise ValueError("The helper connected to a different ChemDraw installation. Save your changes and keep the intended drawing open in one ChemDraw application, then try again.")
        raise ValueError("Could not read ChemDraw's active drawing. Open a scheme in ChemDraw, finish any dialog, then try again.")
    try:
        captured = json.loads(completed.stdout.decode("utf-8-sig"))
        parse_cdxml(captured.get("sourceCDXML"))
    except (ValueError, UnicodeError, AttributeError) as exc:
        raise ValueError("ChemDraw did not provide a readable CDXML drawing.") from exc
    selected_ids = captured.get("selectedIds") or []
    if not isinstance(selected_ids, list):
        selected_ids = [selected_ids]
    return {
        "ok": True, "sourceCDXML": captured["sourceCDXML"],
        "sourceName": captured.get("sourceName") or "scheme",
        "selectedIds": [str(value) for value in selected_ids],
        "selectionCount": int(captured.get("selectionCount") or 0),
    }


def open_result_in_chemdraw(path: Path, expected_name: str | None = None) -> None:
    """Open a separate document through the same public automation application."""
    script = WINDOWS_CONTEXT + r'''
if ($env:SCHEMEGRID_EXPECTED_NAME -and [string]$taskApplication.ActiveDocument.Name -ne $env:SCHEMEGRID_EXPECTED_NAME) { throw 'The active drawing changed.' }
$taskDocuments = $taskApplication.Documents
$taskMissing = [Type]::Missing
$taskResult = $taskDocuments.GetType().InvokeMember('Open',[Reflection.BindingFlags]::InvokeMethod,$null,$taskDocuments,@($env:SCHEMEGRID_RESULT_PATH,$taskMissing,$taskMissing))
if ($null -eq $taskResult) { throw 'ChemDraw did not open the copy.' }
$taskResult.Activate()
'''
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    child_env = os.environ.copy()
    child_env["SCHEMEGRID_RESULT_PATH"] = str(path)
    child_env["SCHEMEGRID_EXPECTED_NAME"] = expected_name or ""
    try:
        completed = subprocess.run(
            [str(powershell), "-NoProfile", "-STA", "-NonInteractive", "-EncodedCommand", encoded],
            env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("The aligned copy was saved, but ChemDraw did not open it. Open the grid CDXML file from Results.") from exc
    if completed.returncode:
        raise ValueError("The aligned copy was saved, but could not be opened in the same ChemDraw application. Keep one ChemDraw application open and try again, or open the grid CDXML file from Results.")

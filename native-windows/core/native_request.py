"""Read-only, explicit-document ChemDraw COM capture and request guards.

This module never activates, opens, saves, edits, closes, or
selects a ChemDraw object. GetActiveObject obtains the public running automation
server; document lookup always uses an explicitly supplied saved full path.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from native_runtime import run_root
ROOT = run_root()
LIMIT = 15_000_000
MAX_AGE = 90
BUSY_HRESULTS = {-2147418111, -2147417846}  # CALL_REJECTED, SERVERCALL_RETRYLATER


class GuardError(RuntimeError):
    pass


def resolved(path):
    return os.path.normcase(str(Path(path).resolve()))


def owned(path):
    candidate = Path(path).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError:
        raise GuardError("Request files must stay inside the configured native preview data directory.")
    return candidate


def drawing(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > LIMIT:
        raise GuardError("Use a nonempty CDXML drawing smaller than 15 MB.")
    if "<!ENTITY" in text.upper():
        raise GuardError("XML entity declarations are not accepted.")
    try:
        root = ET.fromstring(text)
    except (ValueError, ET.ParseError) as exc:
        raise GuardError("The drawing is not readable XML.") from exc
    if root.tag != "CDXML" or not root.findall("page"):
        raise GuardError("The input is not a CDXML drawing with pages.")
    return root


def freeze(node):
    # Preserve caption characters exactly; ignore XML formatting between objects.
    value = node.text or ""
    if node.tag != "s" and not value.strip():
        value = ""
    return [node.tag, sorted(node.attrib.items()), value, [freeze(child) for child in node]]


def semantic_hash(text):
    packed = json.dumps(freeze(drawing(text)), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def write_snapshot(path, text):
    # COM exports can already contain CRLF inside styled caption runs. Windows
    # text-mode writing would turn CRLF into CRCRLF and change their content.
    owned(path).write_bytes(text.encode("utf-8"))
    if semantic_hash(Path(path).read_bytes()) != semantic_hash(text):
        raise GuardError("The owned drawing snapshot did not round-trip exactly.")


def payload_hash(text):
    # File > Run ChemScript can regenerate its page wrapper. Match the complete
    # drawing-object forest, including all object IDs, text, styles and geometry.
    root = drawing(text)
    packed = json.dumps([[freeze(child) for child in page] for page in root.findall("page")],
                        ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def page_ids(text):
    return {node.get("id") for page in drawing(text).findall("page")
            for node in page.iter() if node.get("id") is not None}


def public_data(objects):
    import pythoncom
    member = objects._oleobj_.GetIDsOfNames("Data")
    return str(objects._oleobj_.Invoke(member, 0, pythoncom.DISPATCH_PROPERTYGET,
                                      True, "chemical/x-cdxml"))


def _automation_paths():
    from native_runtime import allowed_application_paths
    return allowed_application_paths()


def automation_progid(expected_application_path):
    expected = Path(expected_application_path)
    if not expected.is_absolute():
        raise GuardError("An explicit verified ChemDraw executable path is required.")
    names = {"chemdrawapplications": "ChemDraw.Application",
             "chemdrawapplications_x64": "ChemDraw_x64.Application"}
    known = {resolved(path): names.get(Path(path).parent.name.casefold()) for path in _automation_paths()}
    selected = known.get(resolved(expected))
    if not selected:
        raise GuardError("The verified caller path has no supported ChemDraw automation name.")
    return selected


def running_application(expected_application_path):
    progid = automation_progid(expected_application_path)
    import pythoncom
    import win32com.client.dynamic
    # Bind only the caller's official running server. Never create an app or
    # fall back to the other architecture when that server is unavailable.
    unknown = pythoncom.GetActiveObject(progid)
    dispatch = unknown.QueryInterface(pythoncom.IID_IDispatch)
    app = win32com.client.dynamic.Dispatch(dispatch)
    if resolved(str(app.FullName)) != resolved(expected_application_path):
        raise GuardError("The running automation server does not match the verified caller executable.")
    return app


def locate_document(app, document_path, application_path):
    if not Path(document_path).is_absolute() or not Path(application_path).is_absolute():
        raise GuardError("Explicit absolute document and application paths are required.")
    if resolved(str(app.FullName)) != resolved(application_path):
        raise GuardError("The public COM server belongs to a different application executable.")
    matches = []
    documents = app.Documents
    for index in range(1, int(documents.Count) + 1):
        candidate = documents.Item(index)
        fullname = str(candidate.FullName)
        if fullname and Path(fullname).is_absolute() and resolved(fullname) == resolved(document_path):
            matches.append(candidate)
    if len(matches) != 1:
        raise GuardError("The exact named drawing is not uniquely open in this COM application.")
    document = matches[0]
    if bool(document.ReadOnly):
        raise GuardError("The explicitly named drawing is read-only.")
    return document


def capture(document_path, application_path, app=None, reader=public_data):
    app = running_application(application_path) if app is None else app
    document = locate_document(app, document_path, application_path)
    full = reader(document.Objects)
    selection = document.selection.Objects
    count = int(selection.Count)
    selected = [str(selection.Item(index).ID) for index in range(1, count + 1)]
    if len(set(selected)) != count or set(selected) - page_ids(full):
        raise GuardError("The selected-object IDs are not a valid subset of this drawing.")
    selected_xml = reader(selection) if count else full
    # Two complete reads detect changes while the request is being captured.
    again = reader(document.Objects)
    selected_again = [str(document.selection.Objects.Item(index).ID)
                      for index in range(1, int(document.selection.Objects.Count) + 1)]
    selected_xml_again = reader(document.selection.Objects) if count else again
    if (semantic_hash(full) != semantic_hash(again) or selected != selected_again or
            payload_hash(selected_xml) != payload_hash(selected_xml_again)):
        raise GuardError("The drawing or selection changed while it was being captured.")
    return {
        "applicationPath": str(app.FullName),
        "documentFullName": str(document.FullName),
        "documentName": str(document.Name),
        "modified": bool(document.Modified),
        "selectedIds": selected,
        "fullSemanticSHA256": semantic_hash(full),
        "hostPayloadSHA256": payload_hash(selected_xml),
        "fullCDXML": full,
        "selectionCDXML": selected_xml,
    }


def assert_same(expected, current):
    for key in ("applicationPath", "documentFullName"):
        if resolved(expected[key]) != resolved(current[key]):
            raise GuardError("The captured source identity changed: " + key)
    for key in ("fullSemanticSHA256", "hostPayloadSHA256", "selectedIds", "modified"):
        if expected[key] != current[key]:
            raise GuardError("The drawing or selected region changed since arming: " + key)


def load_request(path, now=None):
    request_path = owned(path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    now = time.time() if now is None else now
    if request.get("schema") != 1 or request.get("mode") != "capture-and-prepare-only":
        raise GuardError("This scratch runner accepts only read-only preparation requests.")
    if not request.get("createdAt", 0) <= now <= request.get("expiresAt", 0):
        raise GuardError("The armed request expired or has a future creation time.")
    if request["expiresAt"] - request["createdAt"] > MAX_AGE:
        raise GuardError("The request lifetime exceeds the prototype limit.")
    folder = request_path.parent
    if not folder.name == request.get("requestId") or folder.parent != ROOT / "runs":
        raise GuardError("The request folder and request ID do not agree.")
    full = owned(folder / "source.cdxml").read_text(encoding="utf-8")
    selection = owned(folder / "selection.cdxml").read_text(encoding="utf-8")
    if semantic_hash(full) != request["source"]["fullSemanticSHA256"]:
        raise GuardError("The owned full-drawing snapshot changed.")
    if payload_hash(selection) != request["source"]["hostPayloadSHA256"]:
        raise GuardError("The owned selected-region snapshot changed.")
    if set(request["source"]["selectedIds"]) - page_ids(full):
        raise GuardError("The request contains unknown selected-object IDs.")
    return request, folder


def status(folder, phase, **details):
    value = {"phase": phase, "at": time.time(), "liveDrawingEdited": False}
    value.update(details)
    owned(folder / "status.json").write_text(json.dumps(value, indent=2), encoding="utf-8")


def is_busy(exc):
    return getattr(exc, "hresult", None) in BUSY_HRESULTS

"""Compile selected-layout CDXML into conservative, ID-addressed operations.

Offline only. No COM, process launch, import, deletion, or document mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


EPS = 0.003
COORDS = {"p": 2, "BoundingBox": 2, "Head3D": 3, "Tail3D": 3,
          "Center3D": 3, "MajorAxisEnd3D": 3, "MinorAxisEnd3D": 3,
          "Position": 2, "BoundsInParent": 2, "xyz": 3,
          "CurvePoints": 2, "CurvePoints3D": 3, "TopLeft": 2,
          "TopRight": 2, "BottomLeft": 2, "BottomRight": 2}
NUMBER = re.compile(r"^(?:\(?\d+[a-z]?\)?)$")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse(source):
    require(isinstance(source, str) and source.strip() and len(source.encode()) < 15000000,
            "Expected a nonempty CDXML snapshot smaller than 15 MB.")
    require(not re.search(r"<!ENTITY|<!DOCTYPE\s+[^>]*\[", source, re.I), "XML entities are unsupported.")
    root = ET.fromstring(source)
    require(root.tag == "CDXML", "Expected CDXML.")
    pages = list(root.iter("page"))
    require(len(pages) == 1, "The operation compiler supports one drawing page.")
    index = {}
    for node in pages[0].iter():
        if node.get("id"):
            require(node.get("id") not in index, "Duplicate drawing ID.")
            index[node.get("id")] = node
    return root, pages[0], index


def numbers(value):
    result = [float(v) for v in value.replace(",", " ").split()]
    require(result and all(math.isfinite(v) and abs(v) <= 1e7 for v in result), "Invalid coordinates.")
    return result


def near(a, b):
    return len(a) == len(b) and all(abs(x - y) <= EPS for x, y in zip(a, b))


def shifted(key, value, dx, dy):
    output = numbers(value)
    stride = COORDS[key]
    start = 1 if key in {"CurvePoints", "CurvePoints3D"} and len(output) % stride == 1 else 0
    require((len(output) - start) % stride == 0, "Unsupported coordinate shape.")
    for i in range(start, len(output), stride):
        output[i] += dx
        output[i + 1] += dy
    return output


def bounds(node):
    if node.get("BoundingBox"):
        b = numbers(node.get("BoundingBox"))
        require(len(b) == 4, "Unsupported bounding box.")
        return min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])
    if node.get("Head3D") and node.get("Tail3D"):
        a, b = numbers(node.get("Head3D")), numbers(node.get("Tail3D"))
        return min(a[0], b[0]), min(a[1], b[1]) - 3, max(a[0], b[0]), max(a[1], b[1]) + 3
    child_boxes = [bounds(child) for child in node if child.get("Visible") != "no"]
    child_boxes = [b for b in child_boxes if b is not None]
    if child_boxes:
        return union(child_boxes)
    return None


def union(boxes):
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def center(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def text(node):
    return "".join(node.itertext()).strip()


def shape(node):
    return {"tag": node.tag, "attributes": dict(sorted(node.attrib.items())),
            "text": node.text if node.tag == "s" else (node.text or "").strip(),
            "children": [shape(child) for child in node]}


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def object_digest(node):
    return digest(json.dumps(shape(node), sort_keys=True, separators=(",", ":")))


def ownership(root, page, index):
    """Reconstruct ownership from BEFORE snapshot, never from result reports."""
    items, primitive, aliases = {}, {}, {}

    def scan(node):
        if node.get("Visible") == "no" or node.tag in {"scheme", "step", "annotation", "objecttag", "represent", "border"}:
            return
        if node.tag == "group":
            for child in node:
                scan(child)
            return
        identifier = node.get("id")
        if node.get("SupersededBy"):
            aliases[identifier] = node.get("SupersededBy")
            return
        kind = "molecule" if node.tag == "fragment" else "text" if node.tag == "t" else "decoration"
        if node.tag == "arrow" and any(re.match(r"^(Full|Half|Hollow|Angle|Equilibrium)", node.get(k, "")) for k in ("ArrowheadHead", "ArrowheadTail")):
            kind = "arrow"
        if node.tag == "graphic" and node.get("GraphicType") == "Line" and node.get("ArrowType") not in {None, "None"}:
            kind = "arrow"
        b = bounds(node)
        if not identifier or b is None:
            return
        item = {"id": identifier, "node": node, "kind": kind, "box": b, "center": center(b), "owner": identifier}
        if kind == "arrow":
            if node.get("Head3D") and node.get("Tail3D"):
                h, t = numbers(node.get("Head3D")), numbers(node.get("Tail3D"))
                item["ends"] = t[0], t[1], h[0], h[1]
            else:
                item["ends"] = tuple(numbers(node.get("BoundingBox", "")))
            require(len(item["ends"]) == 4, "Arrow lacks endpoint geometry.")
            e = item["ends"]
            item["center"] = (e[0] + e[2]) / 2, (e[1] + e[3]) / 2
        items[identifier] = item
        for child in node.iter():
            if child.get("id"):
                primitive[child.get("id")] = identifier

    for child in page:
        scan(child)

    def resolve(identifier):
        seen = set()
        while identifier in aliases:
            require(identifier not in seen, "Cyclic arrow aliases.")
            seen.add(identifier)
            identifier = aliases[identifier]
        return primitive.get(identifier)

    for alias in aliases:
        owner = resolve(alias)
        require(owner is not None, "Arrow alias has no original target.")
        primitive[alias] = owner
    molecules = [v for v in items.values() if v["kind"] == "molecule"]
    arrows = [v for v in items.values() if v["kind"] == "arrow"]
    bond = float(root.get("BondLength", "14.4"))
    main, reagents, captions = set(), {}, {}
    for step in root.iter("step"):
        refs = {resolve(v) for v in step.get("ReactionStepArrows", "").split()}
        refs.discard(None)
        for key in ("ReactionStepReactants", "ReactionStepProducts"):
            for ref in step.get(key, "").split():
                if ref in index and index[ref].tag == "fragment":
                    main.add(resolve(ref))
        if len(refs) != 1:
            continue
        arrow = next(iter(refs))
        require(items[arrow]["kind"] == "arrow", "Reaction metadata does not identify an arrow.")
        for key in ("ReactionStepObjectsAboveArrow", "ReactionStepObjectsBelowArrow"):
            for ref in step.get(key, "").split():
                item_id = resolve(ref)
                if item_id is None:
                    continue
                store = reagents if items[item_id]["kind"] == "molecule" else captions if items[item_id]["kind"] == "text" else None
                if store is not None:
                    require(item_id not in store or store[item_id] == arrow, "Conflicting reaction ownership.")
                    store[item_id] = arrow

    def best(candidates):
        candidates.sort()
        require(len(candidates) < 2 or abs(candidates[0][0] - candidates[1][0]) > EPS,
                "Ambiguous nearby ownership; select a less ambiguous complete reaction unit.")
        return candidates[0][1] if candidates else None

    def near_arrow(item, fragment=False):
        x, y = item["center"]
        b = item["box"]
        candidates = []
        for arrow in arrows:
            ax, ay = arrow["center"]
            ends = arrow["ends"]
            if x < min(ends[0], ends[2]) - 8 or x > max(ends[0], ends[2]) + 8 or abs(y - ay) > max(100, bond * 7):
                continue
            if fragment and not (b[3] <= ay + 1 or b[1] >= ay - 1):
                continue
            candidates.append((abs(x - ax) * 0.3 + abs(y - ay), arrow["id"]))
        return best(candidates)

    for molecule in molecules:
        identifier = molecule["id"]
        # Crossing assemblies need a separately verified multi-fragment contract.
        crossing_refs = [ref for n in molecule["node"].iter() for ref in n.get("CrossingBonds", "").split()]
        require(all(resolve(ref) == identifier for ref in crossing_refs), "Cross-fragment crossing-bond assemblies are not supported by this compiler.")
        arrow = reagents.get(identifier) or (near_arrow(molecule, True) if identifier not in main else None)
        if arrow:
            molecule["owner"] = arrow

    def near_molecule(item, is_number=False):
        x, _ = item["center"]
        b = item["box"]
        candidates = []
        for molecule in molecules:
            if molecule["owner"] != molecule["id"]:
                continue
            mb = molecule["box"]
            mx, my = molecule["center"]
            dx, dy = abs(x - mx), max(mb[1] - b[3], b[1] - mb[3], 0)
            if dx > max(55, (mb[2] - mb[0]) / 2 + 20) or dy > max(85, bond * 6) or (is_number and b[3] < my):
                continue
            candidates.append((dx * 0.9 + dy, molecule["id"]))
        return best(candidates)

    for item in items.values():
        if item["kind"] != "text":
            continue
        number_owner = near_molecule(item, True) if NUMBER.fullmatch(text(item["node"])) else None
        owner = number_owner or captions.get(item["id"]) or near_arrow(item) or near_molecule(item)
        if owner:
            item["owner"] = owner
        item["isNumber"] = number_owner is not None
    # Frames may travel with a molecule; the operation compiler will reject their
    # movement until a native graphic-move adapter is separately implemented.
    for item in items.values():
        if item["kind"] != "decoration":
            continue
        b = item["box"]
        enclosed = [m for m in molecules if m["owner"] == m["id"] and b[0] - 3 <= m["center"][0] <= b[2] + 3 and b[1] - 3 <= m["center"][1] <= b[3] + 3]
        if len(enclosed) == 1:
            m = enclosed[0]
            if b[2] - b[0] < (m["box"][2] - m["box"][0]) * 2.5 + 30 and b[3] - b[1] < (m["box"][3] - m["box"][1]) * 2.5 + 30:
                item["owner"] = m["id"]
    return items, primitive, aliases


def rigid_shift(old, new):
    old_nodes, new_nodes = list(old.iter()), list(new.iter())
    require(len(old_nodes) == len(new_nodes), "A rigid unit changed hierarchy.")
    delta = None
    for a, b in zip(old_nodes, new_nodes):
        require(a.tag == b.tag and {k: v for k, v in a.attrib.items() if k not in COORDS} == {k: v for k, v in b.attrib.items() if k not in COORDS}, "A rigid unit changed non-coordinate data.")
        for key in COORDS:
            require((a.get(key) is None) == (b.get(key) is None), "An original coordinate field was added/removed.")
            if a.get(key) is None:
                continue
            av, bv = numbers(a.get(key)), numbers(b.get(key))
            require(len(av) == len(bv), "Coordinate dimensions changed.")
            stride = COORDS[key]
            offset = 1 if key.startswith("CurvePoints") and len(av) % stride == 1 else 0
            candidate = bv[offset] - av[offset], bv[offset + 1] - av[offset + 1]
            if delta is None:
                delta = candidate
            require(near(shifted(key, a.get(key), *delta), bv), "A molecule/group was distorted instead of translated.")
    require(delta is not None, "A moved unit has no supported geometry.")
    return delta


def compile_plan(source, layout_result, selected_ids):
    require(isinstance(selected_ids, list) and selected_ids, "An explicit nonempty selection is required for in-place compilation.")
    selected_ids = [str(v) for v in selected_ids]
    require(isinstance(layout_result, dict) and isinstance(layout_result.get("cdxml"), str), "Expected the complete selected-layout result.")
    before, page, old_index = parse(source)
    after, after_page, new_index = parse(layout_result["cdxml"])
    require(set(selected_ids) <= set(old_index), "Selection refers to absent original IDs.")
    items, primitive, aliases = ownership(before, page, old_index)
    chosen = set()
    for identifier in selected_ids:
        node = old_index[identifier]
        refs = [n.get("id") for n in node.iter()] if node.tag == "group" else [identifier]
        found = False
        for ref in refs:
            item_id = primitive.get(ref)
            if item_id:
                item = items[item_id]
                require(item["kind"] != "decoration" or item["owner"] != item_id, "Standalone decoration edits have no native adapter.")
                chosen.add(item["owner"])
                found = True
        require(found, "Selected object cannot be mapped to a supported original unit.")
    allowed_items = {identifier for identifier, item in items.items() if item["owner"] in chosen}
    allowed_ids = {identifier for identifier, item_id in primitive.items() if item_id in allowed_items}
    scope = layout_result.get("scope", {})
    require(scope.get("selected") is True and isinstance(scope.get("affectedIds"), list), "Missing selected-operation scope.")
    affected = {str(v) for v in scope["affectedIds"]}
    new_ids = set(new_index) - set(old_index)
    require(set(old_index) <= set(new_index), "The result deleted original objects.")
    require(affected <= allowed_ids | new_ids, "Reported affected IDs exceed independently resolved selection ownership.")

    parents = {child: node for node in before.iter() for child in node}
    ancestors = set()
    for identifier in allowed_items:
        node = parents.get(old_index[identifier])
        while node is not None:
            ancestors.add(node)
            node = parents.get(node)
    new_nodes = {new_index[identifier] for identifier in new_ids}
    added_records = {str(r.get("captionId")): r for r in layout_result.get("numbering", []) if r.get("added")}
    require(set(added_records) == new_ids, "New objects differ from the number-caption report.")
    operations = []
    existing_numbers = {text(item["node"]) for item in items.values() if item.get("isNumber")}
    owner_numbers = {item["owner"] for item in items.values() if item.get("isNumber")}
    fonts = {n.get("id") for n in before.iter("font")}
    for identifier in sorted(new_ids):
        node, record = new_index[identifier], added_records[identifier]
        owner_id = str(record.get("moleculeId"))
        require(node in list(after_page) and node.tag == "t" and len(node) == 1 and node[0].tag == "s", "Only top-level number captions may be added.")
        require(owner_id in chosen and owner_id in items and items[owner_id]["kind"] == "molecule" and items[owner_id]["owner"] == owner_id,
                "New number does not belong to a selected principal molecule.")
        require(owner_id not in owner_numbers and re.fullmatch(r"[1-9]\d*", text(node)) and text(node) == str(record.get("number")) and text(node) not in existing_numbers,
                "New number conflicts with existing molecule numbering.")
        require(set(node.attrib) <= {"id", "p", "BoundingBox", "Z", "CaptionJustification", "Justification", "LineHeight"}, "Unsupported new caption attributes.")
        require(set(node[0].attrib) == {"font", "size", "face"} and node[0].get("font") in fonts and not len(node[0]), "Unsupported new number formatting.")
        require(node[0].get("font") == before.get("CaptionFont", "3") and node[0].get("face") == "1" and float(node[0].get("size")) == float(before.get("CaptionSize", "10")), "New number formatting differs from drawing caption defaults.")
        require(node.get("Justification") == node.get("CaptionJustification") == "Center", "Number must be centered.")
        p, b = numbers(node.get("p", "")), bounds(node)
        require(len(p) == 2 and b is not None and abs(p[0] - center(b)[0]) <= EPS, "Number geometry is invalid.")
        mb = bounds(new_index[owner_id])
        require(abs(center(b)[0] - center(mb)[0]) <= EPS and b[1] >= mb[3] - EPS and b[1] - mb[3] <= 150,
                "New number is not positioned below its selected owner.")
        operations.append({"op": "create_number", "ownerId": owner_id, "proposedId": identifier,
                           "text": text(node), "position": {"x": p[0], "y": p[1]},
                           "justification": "Center", "font": dict(node[0].attrib),
                           "expectedOwnerFingerprint": object_digest(old_index[owner_id])})
        owner_numbers.add(owner_id)
        existing_numbers.add(text(node))

    changed = set()
    def compare(old, new, containing_primitive=None):
        require(old.tag == new.tag, "Original object hierarchy changed.")
        require((old.text if old.tag == "s" else (old.text or "").strip()) == (new.text if new.tag == "s" else (new.text or "").strip()), "Existing text changed.")
        require((old.tail or "").strip() == (new.tail or "").strip(), "Existing text tail changed.")
        allowed_attrs = set(COORDS)
        if old.tag == "t" and old.get("id") in items and items[old.get("id")]["kind"] == "text":
            allowed_attrs |= {"Justification", "CaptionJustification"}
        require({k:v for k,v in old.attrib.items() if k not in allowed_attrs} == {k:v for k,v in new.attrib.items() if k not in allowed_attrs}, "Chemistry, style, IDs, or metadata changed.")
        primitive_id = primitive.get(old.get("id")) or containing_primitive
        if old.attrib != new.attrib:
            identifier = old.get("id")
            if primitive_id in allowed_items:
                require(identifier in affected or primitive_id in affected, "Changed object is missing from reported scope.")
                changed.add(primitive_id)
            elif old in ancestors and old.tag in {"CDXML", "group"}:
                require({k:v for k,v in old.attrib.items() if k != "BoundingBox"} == {k:v for k,v in new.attrib.items() if k != "BoundingBox"}, "An ancestor changed beyond its derived bounds.")
                children_for_bounds = after_page if old.tag == "CDXML" else new
                boxes = [bounds(c) for c in children_for_bounds if c.get("Visible") != "no" and c.tag not in {"scheme", "annotation"}]
                boxes = [b for b in boxes if b]
                require(boxes and near(numbers(new.get("BoundingBox", "")), union(boxes)), "An ancestor's bounds do not match its children.")
            else:
                raise ValueError("The result changed an unrelated or unsupported original object: " + str(identifier or old.tag))
        children = [child for child in new if child not in new_nodes]
        require(len(old) == len(children), "Original object count or hierarchy changed.")
        for a, b in zip(old, children):
            compare(a, b, primitive_id)
    compare(before, after)

    # Prefer a native group move only when its complete original subtree truly
    # has one common translation and no caption rejustification or resizing.
    covered = set()
    for group in page.iter("group"):
        if not group.get("id"):
            continue
        descendants = {primitive.get(n.get("id")) for n in group.iter()} - {None}
        if not descendants or not descendants <= allowed_items or not descendants & changed or descendants & covered:
            continue
        try:
            dx, dy = rigid_shift(group, new_index[group.get("id")])
        except ValueError:
            continue
        if abs(dx) <= EPS and abs(dy) <= EPS:
            continue
        operations.append({"op": "move_rigid", "targetId": group.get("id"), "kind": "group", "dx": dx, "dy": dy,
                           "memberIds": sorted(descendants), "expectedFingerprint": object_digest(group)})
        covered.update(descendants)

    for identifier in sorted(changed - covered):
        item, old, new = items[identifier], old_index[identifier], new_index[identifier]
        base = {"targetId": identifier, "ownerId": item["owner"], "expectedFingerprint": object_digest(old)}
        if item["kind"] == "molecule":
            dx, dy = rigid_shift(old, new)
            operations.append(dict(base, op="move_rigid", kind="fragment", dx=dx, dy=dy,
                                   atomIds=[n.get("id") for n in old.iter("n")], bondIds=[n.get("id") for n in old.iter("b")]))
        elif item["kind"] == "text":
            require(set(old.attrib) - {"Justification", "CaptionJustification"} == set(new.attrib) - {"Justification", "CaptionJustification"}, "Original caption coordinate fields changed.")
            p, np, b, nb = numbers(old.get("p", "")), numbers(new.get("p", "")), bounds(old), bounds(new)
            require(len(p) == len(np) == 2 and b and nb, "Caption requires explicit p and BoundingBox geometry.")
            require(near([b[2]-b[0], b[3]-b[1]], [nb[2]-nb[0], nb[3]-nb[1]]) and abs((np[1]-p[1])-(nb[1]-b[1])) <= EPS, "Caption dimensions or vertical anchor changed unexpectedly.")
            require(all(old.get(key) == new.get(key) for key in COORDS if key not in {"p", "BoundingBox"}), "Unsupported caption geometry changed.")
            updates = {}
            for key in ("Justification", "CaptionJustification"):
                if old.get(key) != new.get(key):
                    require(new.get(key) == "Center", "Only centered caption justification is supported.")
                    updates[key] = "Center"
            require(not updates or new.get("Justification") == new.get("CaptionJustification") == "Center", "Caption centering attributes disagree.")
            require(new.get("Justification") != "Center" or abs(np[0] - center(nb)[0]) <= EPS, "Centered caption anchor is inconsistent.")
            require(new.get("Justification") == "Center" or abs((np[0]-p[0])-(nb[0]-b[0])) <= EPS, "Caption horizontal anchor changed unexpectedly.")
            operations.append(dict(base, op="set_caption", position={"x": np[0], "y": np[1]},
                                   justification="Center" if updates else None, expectedText=text(old),
                                   expectedBounds=list(b), targetBounds=list(nb)))
        elif item["kind"] == "arrow":
            require(old.tag == "arrow" and old.get("Head3D") and old.get("Tail3D") and float(old.get("AngularSize", "0")) == 0,
                    "Only native straight arrows with explicit Head3D/Tail3D are supported.")
            oh, ot = numbers(old.get("Head3D")), numbers(old.get("Tail3D"))
            nh, nt = numbers(new.get("Head3D", "")), numbers(new.get("Tail3D", ""))
            require(len(oh) == len(ot) == len(nh) == len(nt) == 3 and abs(oh[1]-ot[1]) <= EPS and abs(nh[1]-nt[1]) <= EPS,
                    "Diagonal or curved arrow changes are unsupported.")
            require(near([oh[2],ot[2]], [nh[2],nt[2]]) and (oh[0]-ot[0])*(nh[0]-nt[0]) > 0, "Arrow direction or depth changed.")
            dx, dy = (nh[0]+nt[0]-oh[0]-ot[0])/2, nh[1]-oh[1]
            for key in COORDS:
                require((old.get(key) is None) == (new.get(key) is None), "Arrow coordinate fields changed.")
                if old.get(key) is None or key in {"Head3D", "Tail3D", "BoundingBox"}:
                    continue
                require(near(shifted(key, old.get(key), dx, dy), numbers(new.get(key))), "Unsupported arrow control-geometry change.")
            if old.get("BoundingBox"):
                ob = numbers(old.get("BoundingBox"))
                require(near(numbers(new.get("BoundingBox")), [min(nh[0], nt[0]), ob[1]+dy, max(nh[0], nt[0]), ob[3]+dy]), "Unsupported arrow bounding-box change.")
            alias_ids = [alias for alias, owner in primitive.items() if alias in aliases and owner == identifier]
            for alias_id in alias_ids:
                a, b = old_index[alias_id], new_index[alias_id]
                for key in COORDS:
                    require((a.get(key) is None) == (b.get(key) is None), "Arrow fallback fields changed.")
                    if a.get(key) is not None:
                        expected = [nh[0], nh[1], nt[0], nt[1]] if key == "BoundingBox" else shifted(key, a.get(key), dx, dy)
                        require(near(numbers(b.get(key)), expected), "Arrow fallback does not match the native arrow.")
            require(len(alias_ids) <= 1, "Multiple native arrow fallbacks need explicit native-ID resolution.")
            operations.append(dict(base, op="set_arrow", start={"x": nt[0], "y": nt[1]}, end={"x": nh[0], "y": nh[1]},
                                   tail={"x": nt[0], "y": nt[1]}, head={"x": nh[0], "y": nh[1]},
                                   visibleArrowId=identifier, nativeGraphicId=alias_ids[0] if alias_ids else None,
                                   nativeTargetId=alias_ids[0] if alias_ids else identifier,
                                   aliasIds=alias_ids, expectedStart={"x":ot[0],"y":ot[1]}, expectedEnd={"x":oh[0],"y":oh[1]},
                                   nativePointMapping="Read native Start/End and match against original CDXML Head3D/Tail3D before mutation; semantic start/end are not native property names.",
                                   nativeAuxiliaryGeometryPolicy={"selectedStraightArrowOnly": True,
                                       "mayRecompute": ["Center3D", "MajorAxisEnd3D", "MinorAxisEnd3D"],
                                       "requiresReadback": True, "exactUndoNotEstablished": True}))
        else:
            raise ValueError("Changed decorations have no supported native adapter: " + identifier)
    # Existing geometry first; added captions last. The executor must preflight
    # ALL original IDs/fingerprints before applying its first operation.
    operations.sort(key=lambda op: op["op"] == "create_number")
    return {"schema": "scheme-grid-inplace-plan/v1", "sourceSHA256": digest(source),
            "resultSHA256": digest(layout_result["cdxml"]), "selectedIds": selected_ids,
            "independentlyAllowedIds": sorted(allowed_ids), "selectedOwnerIds": sorted(chosen),
            "operations": operations, "preservedReferenceFingerprint": digest(json.dumps([shape(n) for n in before.iter("scheme")], sort_keys=True)),
            "executionRequirements": ["Recapture and match full source snapshot before execution.",
                                      "Resolve and preflight every original ID before any mutation.",
                                      "Keep original objects and reaction references; do not import/replace/delete drawing data.",
                                      "Map runtime-generated caption IDs back to proposedId/ownerId; do not assume ID assignment.",
                                      "Verify complete resulting snapshot and outside-selection preservation after execution.",
                                      "Native undo/rollback and API behavior require separate live verification."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--selected-ids", required=True, help="JSON array of original selected IDs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for original in (args.source, args.result):
        require(args.output.resolve() != original.resolve() and not (args.output.exists() and original.exists() and args.output.samefile(original)), "Output must not overwrite either input snapshot.")
    plan = compile_plan(args.source.read_text(encoding="utf-8"), json.loads(args.result.read_text(encoding="utf-8")), json.loads(args.selected_ids))
    args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "operations": len(plan["operations"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()

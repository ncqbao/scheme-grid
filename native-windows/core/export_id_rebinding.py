"""Strict offline rebinding of ChemDraw's allocation-shifted export IDs.

Physical native IDs are never renamed. This helper does not execute or approve
native operations; the caller must additionally verify selected target geometry.
"""
from __future__ import annotations

from collections import Counter
import json
import re
import xml.etree.ElementTree as ET

from operation_plan import COORDS, parse, numbers, near, require, text


SYNTHETIC_TAGS = {"page", "fragment", "scheme", "step", "arrow"}
REFERENCE_ATTRS = {"B", "E", "SupersededBy", "CrossingBonds", "BondOrdering",
                   "ReactionStepReactants", "ReactionStepProducts", "ReactionStepArrows",
                   "ReactionStepObjectsAboveArrow", "ReactionStepObjectsBelowArrow",
                   "ReactionStepAtomMap", "ReactionStepPlusSigns",
                   "ReactionStepChangingAtoms", "ReactionStepChangingBonds",
                   "ReactionStepUnchangedAtoms", "BasisObjects", "object"}
UNORDERED_REFERENCE_ATTRS = {"ReactionStepObjectsAboveArrow", "ReactionStepObjectsBelowArrow", "CrossingBonds"}


def caption_mapping(value):
    if isinstance(value, dict):
        records = [{"actualId": str(a), "proposedId": str(p)} for a, p in value.items()]
    else:
        require(isinstance(value, list) and all(isinstance(r, dict) for r in value), "Expected an explicit new-caption ID mapping.")
        records = value
    actual_to_proposed = {}
    for record in records:
        actual, proposed = str(record.get("actualId", "")), str(record.get("proposedId", ""))
        require(re.fullmatch(r"[1-9]\d*", actual) and re.fullmatch(r"[1-9]\d*", proposed), "Invalid created-caption mapping IDs.")
        require(actual not in actual_to_proposed and proposed not in actual_to_proposed.values(), "Created-caption mapping is not bijective.")
        actual_to_proposed[actual] = proposed
    return actual_to_proposed


def rebind_export_ids(before_xml, after_xml, retained_native_ids, created_caption_mapping, *,
                      allowed_geometry_ids=(), allowed_caption_centering_ids=(),
                      allowed_crossing_bond_ids=(), allow_derived_ancestor_bounds=False,
                      allocated_caption_ids=None):
    """Return normalized CDXML plus a report after proving narrow isomorphism.

    By default every attribute, coordinate, text, and reference must match. The
    caller may explicitly supply previously validated selected geometry/caption
    IDs. CrossingBonds is a separate opt-in for selected existing bond IDs only;
    every changed cache and every ID rebind is reported. No other reference edge
    may be added, removed, or retargeted.
    """
    before, before_page, old_index = parse(before_xml)
    after, after_page, new_index = parse(after_xml)
    native = {str(v) for v in retained_native_ids}
    require(native and native <= set(old_index), "Retained native IDs must come from the original drawing's captured native collections.")
    require(all(re.fullmatch(r"[1-9]\d*", v) for v in native), "Native IDs must be positive integers.")
    created = caption_mapping(created_caption_mapping)
    require(set(created) <= set(new_index), "A newly created caption is absent from the actual export.")
    require(set(created).isdisjoint(native) and set(created.values()).isdisjoint(old_index), "New-caption mapping collides with original IDs.")
    native_max, old_max = max(map(int, native)), max(map(int, old_index))
    allocated = set(created) if allocated_caption_ids is None else {str(v) for v in allocated_caption_ids}
    require(all(re.fullmatch(r"[1-9]\d*", v) for v in allocated) and set(created) <= allocated, "Surviving captions are not a subset of the recorded native allocations.")
    count = len(allocated)
    source_page_id = before_page.get("id")
    observed_allocation_base = None
    if count:
        # Removing a number does not rewind ChemDraw's physical-ID allocator.
        # Its original exported page provides the observed allocator watermark:
        # the next MakeCaption ID is exactly page ID minus one. Require this
        # source anchor, not an arbitrary gap above the largest surviving ID.
        require(source_page_id is not None and re.fullmatch(r"[1-9]\d*", source_page_id)
                and source_page_id not in native, "The source page is not a valid synthetic allocation anchor.")
        original_synthetic_ids = [int(v) for v in old_index if int(v) > native_max]
        require(original_synthetic_ids and all(old_index[str(v)].tag in SYNTHETIC_TAGS for v in original_synthetic_ids),
                "The source contains an unrecognized synthetic allocation object.")
        require(int(source_page_id) == min(original_synthetic_ids),
                "The source page is not the first original synthetic allocation ID.")
        allocation_start = int(source_page_id) - 1
        require(allocation_start > native_max, "The source allocation anchor overlaps retained native IDs.")
        observed_allocation_base = allocation_start - 1
        require(set(map(int, allocated)) == set(range(allocation_start, allocation_start + count)),
                "New native IDs do not follow the exact source-anchored caption-allocation sequence.")
    require((allocated - set(created)).isdisjoint(new_index), "An allocated caption reported deleted is still present in the export.")
    require(all(int(v) > old_max for v in created.values()), "Proposed caption IDs must be above every original export ID.")
    geometry = {str(v) for v in allowed_geometry_ids}
    centering = {str(v) for v in allowed_caption_centering_ids}
    crossing = {str(v) for v in allowed_crossing_bond_ids}
    require(geometry | centering | crossing <= set(old_index), "A selected exception refers to an absent original ID.")
    require(all(old_index[v].tag == "t" for v in centering), "Caption-centering exception refers to a non-caption.")
    require(all(old_index[v].tag == "b" and v in geometry for v in crossing), "Crossing-bond exceptions must be explicitly selected existing bonds.")
    before_nodes, after_nodes = set(before_page.iter()), set(after_page.iter())
    added = {new_index[v] for v in created}
    fonts = {n.get("id") for n in before.iter("font")}
    for node in added:
        require(node in list(after_page) and node.tag == "t" and len(node) == 1 and node[0].tag == "s" and not len(node[0]), "Only mapped top-level number captions may be created.")
        require(re.fullmatch(r"[1-9]\d*", text(node)), "Created caption is not a molecule number.")
        require(set(node.attrib) <= {"id", "p", "BoundingBox", "Z", "Warning", "CaptionJustification", "Justification", "LineHeight"}, "Unknown new-caption attributes.")
        require(set(node[0].attrib) <= {"font", "size", "color", "face"} and node[0].get("font") in fonts, "Unknown created-caption style/font.")
        require(node.get("Justification") == node.get("CaptionJustification") == "Center", "Created number is not centered.")
        require(node[0].get("face") == "1" and float(node[0].get("size", "0")) == float(before.get("CaptionSize", "10")), "Created number differs from caption defaults.")
        require(len(numbers(node.get("p", ""))) == 2 and len(numbers(node.get("BoundingBox", ""))) == 4, "Created number lacks valid placement.")

    pairs, old_to_actual, actual_to_old = [], {}, {}
    def pair(old, actual, selected_geometry=False):
        require(old.tag == actual.tag, "Existing export tree type/order changed.")
        old_id, actual_id = old.get("id"), actual.get("id")
        in_drawing = old in before_nodes
        require(in_drawing == (actual in after_nodes), "Drawing hierarchy changed.")
        if in_drawing:
            require((old_id is None) == (actual_id is None), "Original object gained/lost an ID.")
            if old_id is not None:
                if old_id in native or int(old_id) <= native_max:
                    require(actual_id == old_id, "A retained physical native ID changed.")
                else:
                    require(old.tag in SYNTHETIC_TAGS and int(old_id) > native_max,
                            "An uncaptured/non-synthetic original ID cannot be rebound.")
                    require(int(actual_id) == int(old_id) + count,
                            "Synthetic export ID did not follow the exact +caption-count allocation shift.")
                require(actual_id not in actual_to_old, "Structural ID rebinding is not bijective.")
                old_to_actual[old_id] = actual_id
                actual_to_old[actual_id] = old_id
        inherited_geometry = selected_geometry or old_id in geometry
        pairs.append((old, actual, inherited_geometry))
        actual_children = [n for n in actual if n not in added]
        require(len(old) == len(actual_children), "Original export tree structure/count changed.")
        for a, b in zip(old, actual_children):
            pair(a, b, inherited_geometry)
    pair(before, after)
    require(set(old_to_actual) == set(old_index), "Not every original drawing ID was structurally rebound.")
    require(set(actual_to_old) | set(created) == set(new_index), "Actual export contains an unexplained object ID.")
    normalization = dict(actual_to_old)
    normalization.update(created)
    require(len(set(normalization.values())) == len(normalization), "Normalized export IDs would collide.")
    reference_edges, crossing_changes, reordered, geometry_changes = 0, [], [], []
    selected_ancestors = set()
    parents = {child: parent for parent in before.iter() for child in parent}
    for identifier in geometry:
        parent = parents.get(old_index[identifier])
        while parent is not None:
            selected_ancestors.add(parent)
            parent = parents.get(parent)

    for old, actual, selected_geometry in pairs:
        old_id = old.get("id")
        require((old.text if old.tag == "s" else (old.text or "").strip()) == (actual.text if actual.tag == "s" else (actual.text or "").strip()), "Existing label/text changed during export rebinding.")
        require((old.tail or "").strip() == (actual.tail or "").strip(), "Existing text tail changed during export rebinding.")
        for key in set(old.attrib) | set(actual.attrib):
            old_value, actual_value = old.get(key), actual.get(key)
            if key == "id" and old in before_nodes:
                continue
            if key in REFERENCE_ATTRS:
                before_refs = old_value.split() if old_value else []
                actual_refs = actual_value.split() if actual_value else []
                require(all(ref in old_index for ref in before_refs) and all(ref in new_index for ref in actual_refs), "A reference edge points to an absent drawing object.")
                normalized_refs = [normalization[ref] for ref in actual_refs]
                reference_edges += len(before_refs)
                same = Counter(before_refs) == Counter(normalized_refs) if key in UNORDERED_REFERENCE_ATTRS else before_refs == normalized_refs
                if not same and key == "CrossingBonds" and old_id in crossing:
                    require(old.tag == "b" and all(old_index[ref].tag == "b" for ref in before_refs + normalized_refs), "CrossingBonds cache points to a non-bond or new object.")
                    require(len(set(normalized_refs)) == len(normalized_refs), "CrossingBonds cache duplicates a bond reference.")
                    crossing_changes.append({"bondId": old_id, "before": before_refs, "after": normalized_refs})
                else:
                    require(same and ((old_value is None) == (actual_value is None)), "Existing reference edges changed: " + str(old_id) + "." + key)
                    if before_refs != normalized_refs:
                        reordered.append({"id": old_id, "attribute": key})
                continue
            if key in COORDS:
                require((old_value is None) == (actual_value is None), "An original coordinate field was added or removed.")
                if old_value is None:
                    continue
                a, b = numbers(old_value), numbers(actual_value)
                require(len(a) == len(b), "An original coordinate field changed dimensions.")
                derived = allow_derived_ancestor_bounds and key == "BoundingBox" and old in selected_ancestors and old.tag in {"CDXML", "group"}
                require(selected_geometry or derived or near(a, b), "Unselected geometry changed: " + str(old_id or old.tag) + "." + key)
                if not near(a, b):
                    geometry_changes.append({"id": old_id, "tag": old.tag, "attribute": key, "derivedAncestorBounds": derived})
                continue
            if key in {"Justification", "CaptionJustification"} and old_id in centering:
                require(actual_value == old_value or actual_value == "Center", "Native caption changed to unsupported justification.")
                continue
            require(old_value == actual_value, "Original chemistry/style/metadata changed: " + str(old_id or old.tag) + "." + key)

    # Normalize only IDs and known reference attributes, preserving raw native
    # geometry/cache changes for the executor's separate readback verification.
    for node in after_page.iter():
        if node.get("id"):
            node.set("id", normalization[node.get("id")])
        for key in REFERENCE_ATTRS:
            if node.get(key) is not None:
                refs = node.get(key).split()
                require(all(ref in normalization for ref in refs), "Cannot normalize an unexplained reference.")
                node.set(key, " ".join(normalization[ref] for ref in refs))
    normalized = ET.tostring(after, encoding="unicode")
    _, _, normalized_index = parse(normalized)
    require(set(normalized_index) == set(old_index) | set(created.values()), "Normalized ID domain does not equal originals plus mapped new captions.")
    report = {"schema": "scheme-grid-export-id-rebinding/v1", "nativeIDsPreserved": len(native),
              "additionalStableOriginalIDs": len([v for v in old_index if v not in native and int(v) <= native_max]),
              "originalObjects": len(old_index), "createdCaptions": len(created), "allocationShift": count,
              "sourcePageId": source_page_id, "nativeMax": native_max,
              "observedAllocationBase": observed_allocation_base,
              "observedAllocationBaseMeaning": "Last allocated physical ID, derived as original synthetic page ID minus two; null when no allocation was recorded.",
              "allocatedCaptionIDs": sorted(allocated, key=int), "deletedAllocatedCaptionIDs": sorted(allocated-set(created), key=int),
              "syntheticIDChanges": [{"before": old, "actual": actual} for old, actual in old_to_actual.items() if old != actual],
              "createdActualToProposed": created, "referenceEdgesChecked": reference_edges,
              "unorderedReferenceListsReordered": reordered, "selectedCrossingBondCacheChanges": crossing_changes,
              "selectedGeometryChanges": geometry_changes, "geometryTargetVerificationStillRequired": True}
    return {"cdxml": normalized, "report": report, "originalToActualIDs": old_to_actual,
            "actualToNormalizedIDs": normalization}

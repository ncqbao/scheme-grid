/* Scheme Grid 0.1.1 -- local, translation-only CDXML layout. */
(function (root) {
  'use strict';
  var VERSION = '0.1.1';
  var COORDS = {
    p: 2, xyz: 3, BoundingBox: 2, Head3D: 3, Tail3D: 3,
    Center3D: 3, MajorAxisEnd3D: 3, MinorAxisEnd3D: 3,
    TopLeft: 2, TopRight: 2, BottomLeft: 2, BottomRight: 2,
    CurvePoints: 2, CurvePoints3D: 3
  };
  function fail(message) { throw new Error(message); }
  function kids(el) {
    var out = [], n = el.firstChild;
    for (; n; n = n.nextSibling) { if (n.nodeType === 1) { out.push(n); } }
    return out;
  }
  function each(el, fn) {
    fn(el); var a = kids(el), i;
    for (i = 0; i < a.length; i++) { each(a[i], fn); }
  }
  function tag(el) { return el.localName || el.nodeName; }
  function nums(s) {
    if (!s || !String(s).replace(/\s/g, '')) { return null; }
    var a = String(s).replace(/^\s+|\s+$/g, '').split(/[\s,]+/), out = [], i, n;
    for (i = 0; i < a.length; i++) { n = Number(a[i]); if (!isFinite(n)) { return null; } out.push(n); }
    return out;
  }
  function fmt(n) { var v = Math.round(n * 1000000) / 1000000; return String(v === 0 ? 0 : v); }
  function box(a) { return a && a.length >= 4 ? [Math.min(a[0], a[2]), Math.min(a[1], a[3]), Math.max(a[0], a[2]), Math.max(a[1], a[3])] : null; }
  function union(a, b) {
    if (!a) { return b && b.slice(0); } if (!b) { return a.slice(0); }
    return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
  }
  function center(b) { return {x: (b[0] + b[2]) / 2, y: (b[1] + b[3]) / 2}; }
  function median(a) { var b = a.slice(0).sort(function (x, y) { return x - y; }), m = Math.floor(b.length / 2); return b.length ? (b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2) : 0; }
  function text(el) { return (el.textContent || '').replace(/\s+/g, ' ').replace(/^\s+|\s+$/g, ''); }
  function elementBox(el) {
    var b = box(nums(el.getAttribute('BoundingBox'))), p, a, i, size, label, lines;
    if (b) { return b; }
    p = nums(el.getAttribute('p'));
    if (p && p.length >= 2) {
      if (tag(el) === 't') {
        size = 10; a = el.getElementsByTagName('s');
        if (a.length && Number(a[0].getAttribute('size')) > 0) { size = Number(a[0].getAttribute('size')); }
        label = el.textContent || ''; lines = label.split(/\r?\n/);
        var maxLen = 1; for (i = 0; i < lines.length; i++) { maxLen = Math.max(maxLen, lines[i].length); }
        var width = maxLen * size * 0.58, just = el.getAttribute('Justification'), left = p[0];
        if (just === 'Center') { left -= width / 2; } else if (just === 'Right') { left -= width; }
        return [left, p[1] - size, left + width, p[1] + (lines.length - 1) * size * 1.25 + 2];
      }
      b = [p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3];
      a = kids(el); for (i = 0; i < a.length; i++) { b = union(b, elementBox(a[i])); }
      return b;
    }
    if (tag(el) === 'arrow') {
      a = arrowPoints(el);
      if (a) { return [Math.min(a[0], a[2]) - 3, Math.min(a[1], a[3]) - 3, Math.max(a[0], a[2]) + 3, Math.max(a[1], a[3]) + 3]; }
    }
    a = kids(el); for (i = 0; i < a.length; i++) { b = union(b, elementBox(a[i])); }
    return b;
  }
  function moleculeBox(el) {
    if (tag(el) === 'fragment') {
      var b = null, a = kids(el), i, p;
      for (i = 0; i < a.length; i++) {
        if (tag(a[i]) === 'n') {
          p = nums(a[i].getAttribute('p'));
          if (p && p.length >= 2) { b = union(b, [p[0], p[1], p[0], p[1]]); }
        }
      }
      return b || elementBox(el);
    }
    var out = null, ch = kids(el), j;
    for (j = 0; j < ch.length; j++) {
      if (tag(ch[j]) === 'fragment' || tag(ch[j]) === 'group') { out = union(out, moleculeBox(ch[j])); }
    }
    return out || elementBox(el);
  }
  function isArrow(el) { return tag(el) === 'arrow' || (tag(el) === 'graphic' && el.getAttribute('GraphicType') === 'Line' && !!el.getAttribute('ArrowType') && el.getAttribute('ArrowType') !== 'None'); }
  function arrowPoints(el) {
    var h = nums(el.getAttribute('Head3D')), t = nums(el.getAttribute('Tail3D')), b;
    if (h && t && h.length >= 2 && t.length >= 2) { return [t[0], t[1], h[0], h[1]]; }
    b = nums(el.getAttribute('BoundingBox')); return b && b.length >= 4 ? b.slice(0, 4) : null;
  }
  function arrowCenter(el) {
    var p = arrowPoints(el); return p ? {x: (p[0] + p[2]) / 2, y: (p[1] + p[3]) / 2} : center(elementBox(el));
  }
  function describe(el) { return '“' + text(el).slice(0, 70) + '”'; }
  function plan(source, options) {
    options = options || {};
    if (typeof source !== 'string' || source.length > 15000000) { fail('Please use a CDXML document smaller than 15 MB.'); }
    if (/<!ENTITY/i.test(source)) { fail('XML entities are not supported. Save a fresh CDXML copy in ChemDraw.'); }
    var doc = new DOMParser().parseFromString(source, 'application/xml');
    if (!doc.documentElement || doc.getElementsByTagName('parsererror').length || tag(doc.documentElement) !== 'CDXML') { fail('This is not a valid ChemDraw CDXML document.'); }
    var pages = doc.getElementsByTagName('page');
    if (pages.length !== 1) { fail('Use a single-page scheme. Multiple pages and tables need separate layout.'); }
    var page = pages[0], warnings = [], items = [], byId = {}, rootForId = {}, allIds = {}, aliases = {}, i, j;
    // Font IDs belong to their own namespace; only drawing IDs are global here.
    each(page, function (el) {
      var id = el.getAttribute('id');
      if (id) { if (allIds[id]) { fail('Duplicate CDXML object ID ' + id + '. Save a fresh copy in ChemDraw.'); } allIds[id] = el; }
    });
    function addItem(el, kind, anchorElement) {
      var b = elementBox(el);
      if (!b) { fail('Object ' + (el.getAttribute('id') || tag(el)) + ' has no usable position.'); }
      var id = el.getAttribute('id');
      if (!id) { fail('A visible object is missing its ID. Save a fresh CDXML copy in ChemDraw.'); }
      var mb = kind === 'molecule' ? moleculeBox(el) : b;
      var a = kind === 'arrow' ? arrowCenter(anchorElement || el) : center(mb);
      var item = {id: id, el: el, type: kind, bbox: b, anchor: a, satellites: [], owner: null, aliases: []};
      items.push(item); byId[id] = item;
      each(el, function (child) { var cid = child.getAttribute('id'); if (cid) { rootForId[cid] = item; } });
      return item;
    }
    function scan(el) {
      var n = tag(el), a, k, f = [], ar = [], primary, count;
      if (n === 'scheme' || n === 'step' || n === 'objecttag' || n === 'annotation') { return; }
      if (n === 'fragment') { addItem(el, 'molecule'); return; }
      if (isArrow(el)) {
        if (el.getAttribute('SupersededBy')) { aliases[el.getAttribute('id')] = el.getAttribute('SupersededBy'); return; }
        var ap = arrowPoints(el);
        if (!ap || Math.abs(ap[3] - ap[1]) > Math.max(5, Math.abs(ap[2] - ap[0]) * 0.18) || Number(el.getAttribute('AngularSize') || 0) !== 0) {
          fail('This version supports horizontal reaction arrows. Vertical, diagonal, and curved arrows need a separate layout.');
        }
        addItem(el, 'arrow'); return;
      }
      if (n === 't') { addItem(el, text(el) === '+' ? 'separator' : 'text'); return; }
      if (n === 'graphic' && el.getAttribute('GraphicType') === 'Symbol' && /Plus/.test(el.getAttribute('SymbolType') || '')) { addItem(el, 'separator'); return; }
      if (n === 'group') {
        each(el, function (sub) {
          if (tag(sub) === 'fragment' && (tag(sub.parentNode) === 'group')) { f.push(sub); }
          if (isArrow(sub) && !sub.getAttribute('SupersededBy')) { ar.push(sub); }
        });
        if (f.length && !ar.length) { addItem(el, 'molecule'); return; }
        if (!f.length && ar.length === 1) {
          primary = ar[0]; var pp = arrowPoints(primary);
          if (!pp || Math.abs(pp[3] - pp[1]) > Math.max(5, Math.abs(pp[2] - pp[0]) * 0.18) || Number(primary.getAttribute('AngularSize') || 0) !== 0) { fail('This version supports horizontal reaction arrows.'); }
          addItem(el, 'arrow', primary); return;
        }
        a = kids(el); for (k = 0; k < a.length; k++) { scan(a[k]); } return;
      }
      if (n === 'graphic' && el.getAttribute('SupersededBy')) { aliases[el.getAttribute('id')] = el.getAttribute('SupersededBy'); return; }
      if (n === 'border') { return; }
      fail('The scheme contains an unsupported ' + n + ' object. This version handles molecules, text, plus signs, groups, and horizontal reaction arrows.');
    }
    var top = kids(page); for (i = 0; i < top.length; i++) { scan(top[i]); }
    function resolve(id) {
      var seen = {}, x = id;
      while (aliases[x] && !seen[x]) { seen[x] = true; x = aliases[x]; }
      return rootForId[x] || byId[x] || null;
    }
    for (var aid in aliases) {
      if (Object.prototype.hasOwnProperty.call(aliases, aid)) {
        var real = resolve(aid);
        if (!real || !allIds[aid]) { fail('An arrow fallback refers to a missing object. Save a fresh CDXML copy in ChemDraw.'); }
        real.aliases.push(allIds[aid]); rootForId[aid] = real;
      }
    }
    function ownerOf(item) {
      var seen = {}, out = item;
      while (out.owner) { if (seen[out.id]) { fail('Conflicting annotation associations.'); } seen[out.id] = true; out = out.owner; }
      return out;
    }
    function attach(item, owner, evidence) {
      if (!item || !owner || item === owner) { return; }
      if (item.owner && ownerOf(item) !== ownerOf(owner)) { fail('Object ' + item.id + ' has conflicting reaction associations.'); }
      item.owner = owner; item.evidence = evidence;
    }
    // A crossing-bond reference links a native graphical assembly. Its separate
    // fragments must keep the same translation, even when no user group exists.
    for (i = 0; i < items.length; i++) {
      if (items[i].type !== 'molecule') { continue; }
      (function (item) {
        each(item.el, function (node) {
          var crossing = (node.getAttribute('CrossingBonds') || '').split(/\s+/);
          for (var ci = 0; ci < crossing.length; ci++) {
            var other = resolve(crossing[ci]);
            if (!other || other.type !== 'molecule') { continue; }
            var first = ownerOf(item), second = ownerOf(other);
            if (first === second) { continue; }
            var fb = first.bbox, sb = second.bbox;
            var fa = (fb[2] - fb[0]) * (fb[3] - fb[1]), sa = (sb[2] - sb[0]) * (sb[3] - sb[1]);
            attach(fa >= sa ? second : first, fa >= sa ? first : second, 'native crossing-bond assembly');
          }
        });
      }(items[i]));
    }
    var steps = doc.getElementsByTagName('step'), refs, arrows, ids, attrs, k;
    for (i = 0; i < steps.length; i++) {
      refs = (steps[i].getAttribute('ReactionStepArrows') || '').replace(/^\s+|\s+$/g, '').split(/\s+/); arrows = [];
      for (j = 0; j < refs.length; j++) { var rr = resolve(refs[j]); if (rr && rr.type === 'arrow' && arrows.indexOf(rr) < 0) { arrows.push(rr); } }
      if (arrows.length !== 1) { continue; }
      attrs = ['ReactionStepObjectsAboveArrow', 'ReactionStepObjectsBelowArrow'];
      for (j = 0; j < attrs.length; j++) {
        ids = (steps[i].getAttribute(attrs[j]) || '').split(/\s+/);
        for (k = 0; k < ids.length; k++) { attach(resolve(ids[k]), arrows[0], 'reaction metadata'); }
      }
    }
    var anchors = [], texts = [], heights = [];
    for (i = 0; i < items.length; i++) {
      if (items[i].owner) { continue; }
      if (items[i].type === 'text') { texts.push(items[i]); }
      else { anchors.push(items[i]); if (items[i].type === 'molecule') { heights.push(items[i].bbox[3] - items[i].bbox[1]); } }
    }
    if (!anchors.length) { fail('No positioned molecules or reaction arrows were found.'); }
    var bond = Number(doc.documentElement.getAttribute('BondLength')) || 14.4;
    var reach = Math.max(48, Math.min(110, bond * 5));
    function score(label, anchor) {
      var b = label.bbox, a = anchor.bbox, c = center(b), dx = Math.abs(c.x - anchor.anchor.x), gapY = Math.max(a[1] - b[3], b[1] - a[3], 0);
      var gapX = Math.max(a[0] - b[2], b[0] - a[2], 0);
      if (gapY > reach || gapX > reach * 0.7 || dx > Math.max(45, (a[2] - a[0]) / 2 + 32)) { return Infinity; }
      var labelIsNumber = /^(?:\(?\d+[a-z]?\)?|[A-Z]\d+[a-z]?)$/.test(text(label.el));
      var penalty = anchor.type === 'separator' ? 1000 : 0;
      if (labelIsNumber && anchor.type !== 'molecule') { penalty += 24; }
      return dx * 0.9 + gapY * 1.15 + gapX * 0.8 + penalty;
    }
    function isNumber(item) { return /^(?:\(?\d+[a-z]?\)?|[A-Z]\d+[a-z]?)$/.test(text(item.el)); }
    // Resolve numbers before yields so tightly stacked captions can share an owner.
    texts.sort(function (a, b) { return (isNumber(b) ? 1 : 0) - (isNumber(a) ? 1 : 0); });
    for (i = 0; i < texts.length; i++) {
      var label = texts[i], candidates = [];
      if (/^(?:[<>~\u2248]\s*)?\d+(?:\.\d+)?\s*%(?:\s.*)?$/.test(text(label.el))) {
        var stacks = [], lc = center(label.bbox);
        for (j = 0; j < texts.length; j++) {
          var number = texts[j];
          if (!number.owner || !isNumber(number) || ownerOf(number).type !== 'molecule') { continue; }
          var nc = center(number.bbox), sx = Math.abs(lc.x - nc.x), sy = label.bbox[1] - number.bbox[3];
          if (sx <= Math.max(9, (label.bbox[2] - label.bbox[0]) * 0.45) && sy >= -2 && sy <= 24) {
            stacks.push({number: number, score: sx + Math.max(0, sy) * 0.6});
          }
        }
        stacks.sort(function (a, b) { return a.score - b.score; });
        if (stacks.length && (stacks.length === 1 || stacks[1].score - stacks[0].score >= 6)) {
          attach(label, ownerOf(stacks[0].number), 'stacked compound number and yield'); continue;
        }
        if (stacks.length > 1) { fail('Ambiguous number/yield stack ' + describe(label.el) + '. The original was not changed.'); }
      }
      for (j = 0; j < anchors.length; j++) { var sc = score(label, anchors[j]); if (isFinite(sc)) { candidates.push({item: anchors[j], score: sc}); } }
      candidates.sort(function (a, b) { return a.score - b.score; });
      if (!candidates.length) { fail('Cannot confidently associate caption ' + describe(label.el) + '. Place it nearer its molecule/arrow, or remove unrelated captions from this scheme.'); }
      if (candidates.length > 1 && candidates[1].score - candidates[0].score < 9) { fail('Ambiguous annotation ' + describe(label.el) + ' between objects ' + candidates[0].item.id + ' and ' + candidates[1].item.id + '. Place it nearer the intended object and try again.'); }
      attach(label, candidates[0].item, 'nearby annotation');
    }
    for (i = 0; i < items.length; i++) {
      if (items[i].owner) { var own = ownerOf(items[i]); own.satellites.push(items[i]); own.bbox = union(own.bbox, items[i].bbox); }
    }
    anchors = anchors.filter(function (a) { return !a.owner; });
    var threshold = Math.max(18, Math.min(42, median(heights) * 0.6 || bond * 1.5));
    // A recorded horizontal reaction is stronger row evidence than a messy Y position.
    var rowParent = {}, components = {}, componentList = [];
    for (i = 0; i < anchors.length; i++) { rowParent[anchors[i].id] = anchors[i].id; }
    function rowRoot(id) {
      var out = id; while (rowParent[out] !== out) { out = rowParent[out]; }
      return out;
    }
    function joinRows(a, b) { var ra = rowRoot(a.id), rb = rowRoot(b.id); if (ra !== rb) { rowParent[rb] = ra; } }
    for (i = 0; i < steps.length; i++) {
      var stepAnchors = [], stepAttrs = ['ReactionStepReactants', 'ReactionStepProducts', 'ReactionStepArrows', 'ReactionStepPlusses'];
      for (j = 0; j < stepAttrs.length; j++) {
        ids = (steps[i].getAttribute(stepAttrs[j]) || '').split(/\s+/);
        for (k = 0; k < ids.length; k++) {
          var linked = resolve(ids[k]); if (linked) { linked = ownerOf(linked); }
          if (linked && rowParent[linked.id] && stepAnchors.indexOf(linked) < 0) { stepAnchors.push(linked); }
        }
      }
      for (j = 1; j < stepAnchors.length; j++) { joinRows(stepAnchors[0], stepAnchors[j]); }
    }
    for (i = 0; i < anchors.length; i++) {
      var rid = rowRoot(anchors[i].id);
      if (!components[rid]) { components[rid] = {members: [], y: 0}; componentList.push(components[rid]); }
      components[rid].members.push(anchors[i]);
    }
    for (i = 0; i < componentList.length; i++) {
      var componentArrows = componentList[i].members.filter(function (a) { return a.type === 'arrow'; });
      if (componentArrows.length > 1) {
        var arrowYs = componentArrows.map(function (a) { return a.anchor.y; });
        if (Math.max.apply(null, arrowYs) - Math.min.apply(null, arrowYs) > threshold * 1.5) {
          fail('This connected scheme has reaction arrows on different rows. Branched and wrapped pathways need a separate layout in this version.');
        }
      }
      componentList[i].y = median(componentList[i].members.map(function (a) { return a.anchor.y; }));
    }
    var rows = [], sorted = componentList.sort(function (a, b) { return a.y - b.y; });
    for (i = 0; i < sorted.length; i++) {
      var bestRow = null, bestGap = Infinity;
      for (j = 0; j < rows.length; j++) { var gy = Math.abs(sorted[i].y - rows[j].y); if (gy < threshold && gy < bestGap) { bestRow = rows[j]; bestGap = gy; } }
      if (!bestRow) { bestRow = {members: [], y: sorted[i].y}; rows.push(bestRow); }
      bestRow.members = bestRow.members.concat(sorted[i].members); bestRow.y = median(bestRow.members.map(function (a) { return a.anchor.y; }));
    }
    rows.sort(function (a, b) { return a.y - b.y; });
    var grid = Number(options.grid) || 18, gap = Number(options.gap) || 24;
    if (grid < 6 || grid > 72 || gap < 6 || gap > 144) { fail('Use a grid between 6 and 72 pt and spacing between 6 and 144 pt.'); }
    function ceilGrid(v) { return Math.ceil((v - 0.000001) / grid) * grid; }
    var colWidths = [], fullBox = null, maxColumns = 0;
    for (i = 0; i < rows.length; i++) {
      rows[i].members.sort(function (a, b) { return a.anchor.x - b.anchor.x; });
      rows[i].above = 0; rows[i].below = 0;
      for (j = 0; j < rows[i].members.length; j++) {
        var ob = rows[i].members[j]; ob.row = i; ob.col = j;
        fullBox = union(fullBox, ob.bbox);
        if (!colWidths[j]) { colWidths[j] = {left: 0, right: 0}; }
        colWidths[j].left = Math.max(colWidths[j].left, ob.anchor.x - ob.bbox[0]);
        colWidths[j].right = Math.max(colWidths[j].right, ob.bbox[2] - ob.anchor.x);
        rows[i].above = Math.max(rows[i].above, ob.anchor.y - ob.bbox[1]);
        rows[i].below = Math.max(rows[i].below, ob.bbox[3] - ob.anchor.y);
      }
      maxColumns = Math.max(maxColumns, rows[i].members.length);
    }
    var colX = [], rowY = [];
    colX[0] = ceilGrid(Math.max(24, fullBox[0]) + colWidths[0].left);
    for (i = 1; i < maxColumns; i++) { colX[i] = colX[i - 1] + ceilGrid(colWidths[i - 1].right + gap + colWidths[i].left); }
    rowY[0] = ceilGrid(Math.max(24, fullBox[1]) + rows[0].above);
    for (i = 1; i < rows.length; i++) { rowY[i] = rowY[i - 1] + ceilGrid(rows[i - 1].below + gap * 1.5 + rows[i].above); }
    function translate(el, dx, dy) {
      each(el, function (node) {
        for (var key in COORDS) {
          if (!Object.prototype.hasOwnProperty.call(COORDS, key) || !node.hasAttribute(key)) { continue; }
          var values = nums(node.getAttribute(key)), stride = COORDS[key];
          var start = 0;
          if (values && (key === 'CurvePoints' || key === 'CurvePoints3D') && values.length % stride === 1) { start = 1; }
          if (!values || (values.length - start) % stride) { fail('Unsupported coordinate data in object ' + (node.getAttribute('id') || tag(node)) + '.'); }
          for (var q = start; q < values.length; q += stride) { values[q] += dx; values[q + 1] += dy; }
          node.setAttribute(key, values.map(fmt).join(' '));
        }
      });
    }
    var groups = [], moves = [], moved = {}, moleculeCount = 0, arrowCount = 0, annotationCount = 0;
    for (i = 0; i < anchors.length; i++) {
      var anchor = anchors[i], tx = colX[anchor.col], ty = rowY[anchor.row], dx = tx - anchor.anchor.x, dy = ty - anchor.anchor.y;
      var members = [anchor].concat(anchor.satellites), elementIds = [], annotationIds = [];
      if (anchor.type === 'molecule') { moleculeCount++; } if (anchor.type === 'arrow') { arrowCount++; }
      for (j = 0; j < members.length; j++) {
        var member = members[j]; if (moved[member.id]) { fail('An object was assigned to more than one grid location.'); }
        translate(member.el, dx, dy); moved[member.id] = true; elementIds.push(member.id);
        if (j) { annotationIds.push(member.id); annotationCount++; }
        for (k = 0; k < member.aliases.length; k++) { translate(member.aliases[k], dx, dy); elementIds.push(member.aliases[k].getAttribute('id')); }
        moves.push({id: member.id, ownerId: anchor.id, dx: dx, dy: dy, evidence: member.evidence || 'anchor'});
      }
      groups.push({id: anchor.id, type: anchor.type, elementIds: elementIds, annotationIds: annotationIds, dx: dx, dy: dy, anchor: anchor.anchor, target: {x: tx, y: ty}, row: anchor.row, column: anchor.col});
    }
    // Mixed groups remain native groups; refresh their enclosing boxes after child moves.
    var groupEls = page.getElementsByTagName('group');
    for (i = groupEls.length - 1; i >= 0; i--) {
      if (byId[groupEls[i].getAttribute('id')]) { continue; }
      var gb = null, gc = kids(groupEls[i]); for (j = 0; j < gc.length; j++) { gb = union(gb, elementBox(gc[j])); }
      if (gb && groupEls[i].hasAttribute('BoundingBox')) { groupEls[i].setAttribute('BoundingBox', gb.map(fmt).join(' ')); }
    }
    var newBounds = null;
    top = kids(page); for (i = 0; i < top.length; i++) { if (tag(top[i]) !== 'scheme') { newBounds = union(newBounds, elementBox(top[i])); } }
    if (newBounds && doc.documentElement.hasAttribute('BoundingBox')) { doc.documentElement.setAttribute('BoundingBox', newBounds.map(fmt).join(' ')); }
    if (newBounds && page.hasAttribute('BoundingBox')) {
      var oldPage = box(nums(page.getAttribute('BoundingBox')));
      if (oldPage && (newBounds[2] > oldPage[2] || newBounds[3] > oldPage[3])) { warnings.push('The aligned scheme extends beyond the original page. Adjust the page size or scale it in ChemDraw.'); }
    }
    return {cdxml: new XMLSerializer().serializeToString(doc), groups: groups, moves: moves, warnings: warnings, stats: {molecules: moleculeCount, arrows: arrowCount, annotations: annotationCount, rows: rows.length, columns: maxColumns, grid: grid, gap: gap}};
  }
  root.SchemeGrid = {version: VERSION, plan: plan};
}(typeof window !== 'undefined' ? window : this));

'use strict';
(function () {
  const LIMIT = 15 * 1024 * 1024;
  function parse(xml) {
    if (typeof xml !== 'string' || !xml.trim()) throw Error('Choose a nonempty CDXML drawing.');
    if (new TextEncoder().encode(xml).byteLength > LIMIT) throw Error('This drawing is larger than 15 MB. Try a smaller scheme.');
    if (/<!ENTITY|<!DOCTYPE\s+[^>]*\[/i.test(xml)) throw Error('XML entity declarations are not supported.');
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    if (doc.querySelector('parsererror') || !doc.documentElement || doc.documentElement.tagName !== 'CDXML') {
      throw Error('Choose a ChemDraw CDXML file. In ChemDraw, save a copy using the CDXML format.');
    }
    return doc;
  }
  function chemistry(doc) {
    const positions = new Set(['p', 'xyz', 'BoundingBox', 'Position']);
    return JSON.stringify(Array.from(doc.querySelectorAll('n,b'), element => [
      element.tagName,
      Array.from(element.attributes, attribute => [attribute.name, attribute.value]).filter(attribute => !positions.has(attribute[0])).sort((a,b) => a[0].localeCompare(b[0]))
    ]).sort((a,b) => JSON.stringify(a).localeCompare(JSON.stringify(b))));
  }
  window.SchemeGridDesktopEngine = Object.freeze({
    validate: xml => { parse(xml); return true; },
    arrange: input => {
      const original = parse(input.xml);
      if (!window.ReactionLayout || typeof window.ReactionLayout.plan !== 'function') throw Error('The layout engine did not load. Reinstall Scheme Grid.');
      const plan = window.ReactionLayout.plan(input.xml, input.options || {});
      const cleaned = parse(plan && plan.cdxml);
      if (chemistry(original) !== chemistry(cleaned)) throw Error('The result changed chemical atom or bond data. Keep the original drawing; this result was not accepted.');
      return plan;
    }
  });
}());

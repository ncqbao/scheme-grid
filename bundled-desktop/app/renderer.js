'use strict';
(() => {
  const ui = id => document.getElementById(id);
  let loaded = false, ready = false, working = false;
  function status(kind, title, detail) {
    ui('status').className = 'status ' + kind;
    ui('status-title').textContent = title;
    ui('status-text').textContent = detail;
  }
  function controls() {
    for (const id of ['open','native','numbering']) ui(id).disabled = working;
    ui('arrange').disabled = working || !loaded;
    ui('save').disabled = working || !ready;
    ui('open-result').disabled = working;
  }
  async function run(operation) {
    if (working) return;
    working = true; controls();
    try { await operation(); }
    catch (error) { status('error', 'Let’s try that again', String(error.message || error).replace(/^Error invoking remote method '[^']+': Error: /, '')); }
    finally { working = false; controls(); }
  }
  function showResult(result) {
    ready = true;
    const stats = result.stats || {};
    const details = [];
    if (stats.molecules != null) details.push(stats.molecules + ' molecules');
    if (stats.arrows != null) details.push(stats.arrows + ' arrows');
    if (result.numbered) details.push(result.numbered + ' numbers added');
    ui('summary').textContent = details.length ? details.join(' · ') + '. Your arranged copy stays editable in ChemDraw.' : 'Your arranged copy stays editable in ChemDraw.';
    ui('warnings').replaceChildren();
    for (const warning of result.warnings || []) {
      const item = document.createElement('li'); item.textContent = warning; ui('warnings').appendChild(item);
    }
    ui('warnings').hidden = !(result.warnings || []).length;
  }
  async function arrange() {
    ready = false; ui('open-result').hidden = true;
    status('working', 'Giving everything a little room', 'Aligning molecules, arrows, conditions and yields…');
    showResult(await window.schemeGrid.arrange({numbering: ui('numbering').checked}));
    status('success', 'All set — your arranged copy is ready', 'Save it, then open it in ChemDraw to review the result.');
  }
  async function cleanActive() {
    status('working', 'Reading your active ChemDraw scheme', 'Preparing a separate editable copy…');
    const result = await window.schemeGrid.cleanActive({numbering: ui('numbering').checked});
    loaded = true; ui('drawing').hidden = false; ui('filename').textContent = result.name;
    showResult(result); ui('open-result').hidden = false;
    status('success', 'Your arranged copy is open in ChemDraw', result.message || 'Review it in ChemDraw, then save it where you need it.');
  }
  ui('open').addEventListener('click', () => run(async () => {
    const file = await window.schemeGrid.openFile();
    if (file.canceled) return;
    loaded = true; ready = false;
    ui('drawing').hidden = false; ui('filename').textContent = file.name;
    ui('summary').textContent = 'Ready to arrange.'; ui('warnings').hidden = true; ui('open-result').hidden = true;
    status('', 'Your drawing is ready', 'Click Arrange to tidy this whole drawing.');
  }));
  ui('arrange').addEventListener('click', () => run(arrange));
  ui('native').addEventListener('click', () => run(cleanActive));
  ui('save').addEventListener('click', () => run(async () => {
    const saved = await window.schemeGrid.saveResult();
    if (saved.canceled) return;
    ui('open-result').hidden = false;
    status('success', 'Saved as ' + saved.name, 'Open the arranged copy in ChemDraw to review it.');
  }));
  ui('open-result').addEventListener('click', () => run(async () => {
    await window.schemeGrid.openResult();
    status('success', 'Opening your arranged copy', 'Review the result in ChemDraw before using it in your work.');
  }));
  ui('numbering').addEventListener('change', () => {
    if (!loaded) return;
    ready = false; ui('open-result').hidden = true; controls();
    status('', 'Numbering preference changed', 'Click Arrange again to apply your choice.');
  });
  window.schemeGrid.getInfo().then(info => {
    ui('version').textContent = 'v' + info.version;
    ui('native').hidden = !info.nativeAvailable;
    ui('native-notes').hidden = !info.nativeAvailable;
    if (info.nativeAvailable) {
      ui('instructions').textContent = 'Keep your drawing open in ChemDraw and click Clean active scheme. Or open a CDXML copy here, arrange it, and save the result.';
      if (info.cleanOnLaunch) run(cleanActive);
    }
    controls();
  }).catch(error => status('error', 'Scheme Grid could not start', String(error.message || error)));
  controls();
})();

'use strict';
const {app, BrowserWindow, dialog, ipcMain, shell, session} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL, fileURLToPath} = require('node:url');
const {spawn} = require('node:child_process');

const MAX_BYTES = 15 * 1024 * 1024;
const APP_ROOT = __dirname;
let mainWindow = null;
let workerWindow = null;
let source = null;
let result = null;
let busy = false;
let savedPath = null;
const selfTestIndex = process.argv.indexOf('--schemegrid-self-test');
const selfTest = selfTestIndex !== -1;
const cleanOnLaunch = process.argv.includes('--clean-active');

function cdxmlText(value) {
  if (typeof value !== 'string' || !value.trim()) throw Error('Choose a nonempty CDXML drawing.');
  if (Buffer.byteLength(value, 'utf8') > MAX_BYTES) throw Error('This drawing is larger than 15 MB. Try a smaller scheme.');
  if (/<!ENTITY|<!DOCTYPE\s+[^>]*\[/i.test(value)) throw Error('XML entity declarations are not supported.');
  return value;
}

function sameFile(a, b) {
  const normalize = value => {
    let full = path.resolve(value);
    try { full = fs.realpathSync(full); } catch (_) { /* New output path. */ }
    return process.platform === 'win32' ? full.toLowerCase() : full;
  };
  if (normalize(a) === normalize(b)) return true;
  try {
    const first = fs.statSync(a), second = fs.statSync(b);
    return first.dev === second.dev && first.ino === second.ino;
  } catch (_) { return false; }
}

function localResourceURL(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'file:' || parsed.search || parsed.hash) return false;
    const filename = fileURLToPath(parsed);
    const relative = path.relative(APP_ROOT, filename);
    return relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
  } catch (_) { return false; }
}

function secureWindow(window) {
  window.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.on('will-attach-webview', event => event.preventDefault());
}

function bridgePaths() {
  return {
    python: path.join(process.resourcesPath, 'python', 'python.exe'),
    script: path.join(process.resourcesPath, 'windows-bridge', 'native_bridge.py')
  };
}

function nativeAvailable() {
  const files = bridgePaths();
  return process.platform === 'win32' && fs.existsSync(files.python) && fs.existsSync(files.script);
}

function runNative(command, payload) {
  if (!nativeAvailable()) throw Error('Use Open a CDXML file on this computer. The direct ChemDraw connection is available in the Windows installer.');
  const files = bridgePaths();
  const args = ['-I', '-B', files.script, command];
  if (command === 'open') args.push('--result-dir', path.join(app.getPath('userData'), 'Results'));
  return new Promise((resolve, reject) => {
    const child = spawn(files.python, args, {
      cwd: path.dirname(files.script), windowsHide: true,
      env: {...process.env, PYTHONNOUSERSITE: '1', PYTHONIOENCODING: 'utf-8'},
      stdio: ['pipe', 'pipe', 'pipe']
    });
    let stdout = '', stderr = '', settled = false;
    const finish = (error, data) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error); else resolve(data);
    };
    const timer = setTimeout(() => {
      child.kill();
      finish(Error('The ChemDraw connection took too long. Check ChemDraw before trying again.'));
    }, 70000);
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      stdout += chunk;
      if (Buffer.byteLength(stdout, 'utf8') > 2 * MAX_BYTES + 4096) {
        child.kill(); finish(Error('The ChemDraw connection returned too much data. Try a smaller drawing.'));
      }
    });
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-4000); });
    child.on('error', error => finish(Error('The bundled ChemDraw connection could not start: ' + error.message)));
    child.on('close', code => {
      if (settled) return;
      let data;
      try { data = JSON.parse(stdout.replace(/^\uFEFF/, '').trim()); }
      catch (_) { finish(Error(stderr.trim() || 'The ChemDraw connection returned an unreadable result.')); return; }
      if (code !== 0 || !data.ok) finish(Error(String(data.error || stderr || 'The ChemDraw connection stopped.')));
      else finish(null, data);
    });
    child.stdin.on('error', () => { /* Early child failure is handled by close/error. */ });
    child.stdin.end(payload ? JSON.stringify(payload) : undefined);
  });
}

async function createWorker() {
  if (workerWindow && !workerWindow.isDestroyed()) return workerWindow;
  workerWindow = new BrowserWindow({
    show: false, webPreferences: {nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true}
  });
  secureWindow(workerWindow);
  await workerWindow.loadFile(path.join(APP_ROOT, 'worker.html'));
  return workerWindow;
}

async function makePlan(xml, options = {}) {
  cdxmlText(xml);
  const worker = await createWorker();
  const input = {xml, options: {numbering: options.numbering !== false, selectedIds: Array.isArray(options.selectedIds) ? options.selectedIds : []}};
  const code = 'window.SchemeGridDesktopEngine.arrange(' + JSON.stringify(input) + ')';
  const plan = await worker.webContents.executeJavaScript(code, false);
  cdxmlText(plan && plan.cdxml);
  return plan;
}

function summary(plan) {
  return {
    stats: plan.stats || {},
    warnings: (plan.warnings || []).map(value => String(value && value.message || value)),
    numbered: (plan.numbering || []).filter(item => item.added !== false).length,
    moved: Array.isArray(plan.moves) ? plan.moves.length : 0
  };
}

async function exclusive(operation) {
  if (busy) throw Error('One moment — Scheme Grid is already working.');
  busy = true;
  try { return await operation(); } finally { busy = false; }
}

function assertTrustedSender(event) {
  if (!mainWindow || mainWindow.isDestroyed() || event.sender !== mainWindow.webContents || event.senderFrame !== event.sender.mainFrame) {
    throw Error('Untrusted application request.');
  }
}

function registerIPC() {
  const handle = (name, operation) => ipcMain.handle(name, (event, value) => {
    assertTrustedSender(event);
    return operation(value);
  });
  handle('sg:info', () => ({version: app.getVersion(), platform: process.platform, nativeAvailable: nativeAvailable(), cleanOnLaunch}));
  handle('sg:open', () => exclusive(async () => {
    const picked = await dialog.showOpenDialog(mainWindow, {title: 'Choose a ChemDraw CDXML copy', properties: ['openFile'], filters: [{name: 'ChemDraw XML drawing', extensions: ['cdxml']}]});
    if (picked.canceled || picked.filePaths.length !== 1) return {canceled: true};
    const filename = picked.filePaths[0];
    if (fs.statSync(filename).size > MAX_BYTES) throw Error('This drawing is larger than 15 MB. Try a smaller scheme.');
    const xml = cdxmlText(fs.readFileSync(filename, 'utf8'));
    // Validate parsing and chemistry before replacing the current source.
    await (await createWorker()).webContents.executeJavaScript('window.SchemeGridDesktopEngine.validate(' + JSON.stringify(xml) + ')', false);
    source = {xml, path: filename, name: path.basename(filename)};
    result = null; savedPath = null;
    return {name: source.name};
  }));
  handle('sg:arrange', value => exclusive(async () => {
    if (!source) throw Error('Open a CDXML file first.');
    result = null; savedPath = null;
    result = await makePlan(source.xml, {numbering: !value || value.numbering !== false});
    return summary(result);
  }));
  handle('sg:save', () => exclusive(async () => {
    if (!source || !result) throw Error('Arrange a drawing before saving it.');
    const base = source.name.replace(/\.cdxml$/i, '') + '-arranged.cdxml';
    const initial = source.path ? path.join(path.dirname(source.path), base) : path.join(app.getPath('documents'), base);
    const picked = await dialog.showSaveDialog(mainWindow, {title: 'Save your arranged copy', defaultPath: initial, filters: [{name: 'ChemDraw XML drawing', extensions: ['cdxml']}]});
    if (picked.canceled || !picked.filePath) return {canceled: true};
    let filename = picked.filePath;
    if (!/\.cdxml$/i.test(filename)) filename += '.cdxml';
    if (source.path && sameFile(filename, source.path)) throw Error('Choose a different name to keep your original drawing.');
    fs.writeFileSync(filename, result.cdxml, {encoding: 'utf8'});
    savedPath = filename;
    return {name: path.basename(filename)};
  }));
  handle('sg:open-result', async () => {
    if (!savedPath || !/\.cdxml$/i.test(savedPath)) throw Error('Save your arranged copy first.');
    const error = await shell.openPath(savedPath);
    if (error) throw Error('The copy is saved. Open it from ChemDraw using File > Open.');
    return {ok: true};
  });
  handle('sg:clean-active', value => exclusive(async () => {
    const capture = await runNative('capture');
    const xml = cdxmlText(capture.sourceCDXML);
    result = null; savedPath = null;
    const planned = await makePlan(xml, {numbering: !value || value.numbering !== false, selectedIds: capture.selectedIds || []});
    const opened = await runNative('open', {...capture, cdxml: planned.cdxml, mode: 'reaction', scope: planned.scope, numbering: planned.numbering});
    source = {xml, path: null, name: String(capture.sourceName || 'scheme').replace(/\.cdxml$/i, '') + '.cdxml'};
    result = planned;
    savedPath = opened.path || null;
    return {...summary(planned), name: source.name, opened: true, message: opened.message || 'Your arranged copy is open in ChemDraw.'};
  }));
}

async function runSelfTest() {
  const inputPath = process.argv[selfTestIndex + 1];
  const reportPath = process.argv[selfTestIndex + 2];
  if (!inputPath || !reportPath) throw Error('Self-test needs input CDXML and output report paths.');
  const xml = cdxmlText(fs.readFileSync(inputPath, 'utf8'));
  const first = await makePlan(xml, {numbering: true});
  const second = await makePlan(first.cdxml, {numbering: true});
  const negative = {};
  for (const [name, text] of Object.entries({empty: '',wrongRoot:'<document/>', entity:'<!DOCTYPE CDXML [<!ENTITY bad "x">]><CDXML/>'})) {
    try { await makePlan(text); negative[name] = false; } catch (_) { negative[name] = true; }
  }
  const outputPath = path.resolve(reportPath).replace(/\.json$/i, '') + '.cdxml';
  if (sameFile(inputPath, outputPath) || sameFile(inputPath, reportPath)) throw Error('Self-test output must differ from input.');
  fs.mkdirSync(path.dirname(path.resolve(reportPath)), {recursive: true});
  fs.writeFileSync(outputPath, first.cdxml, 'utf8');
  const report = {
    ok: Object.values(negative).every(Boolean),
    appVersion: app.getVersion(), electron: process.versions.electron,
    chromium: process.versions.chrome, node: process.versions.node,
    engineVersion: first.stats && first.stats.version,
    first: summary(first), second: summary(second), rejectedInputs: negative,
    sourcePreserved: fs.readFileSync(inputPath, 'utf8') === xml,
    output: path.basename(outputPath), platform: process.platform, arch: process.arch
  };
  report.ok = report.ok && report.sourcePreserved;
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n', 'utf8');
  app.exit(report.ok ? 0 : 1);
}

app.setName('Scheme Grid');
if (!selfTest && !app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.show(); mainWindow.focus(); } });
  app.whenReady().then(async () => {
    const currentSession = session.defaultSession;
    currentSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    currentSession.setPermissionCheckHandler(() => false);
    currentSession.webRequest.onBeforeRequest((details, callback) => callback({cancel: !localResourceURL(details.url)}));
    if (selfTest) { await runSelfTest(); return; }
    registerIPC();
    const createMain = async () => {
      mainWindow = new BrowserWindow({
        width: 880, height: 690, minWidth: 620, minHeight: 600,
        title: 'Scheme Grid', backgroundColor: '#f4f7f5', show: false,
        webPreferences: {preload: path.join(APP_ROOT, 'preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true}
      });
      secureWindow(mainWindow);
      mainWindow.setMenuBarVisibility(false);
      mainWindow.once('ready-to-show', () => mainWindow.show());
      mainWindow.on('closed', () => {
        mainWindow = null; source = null; result = null; savedPath = null;
        if (workerWindow && !workerWindow.isDestroyed()) workerWindow.destroy();
        workerWindow = null;
      });
      await mainWindow.loadFile(path.join(APP_ROOT, 'index.html'));
    };
    await createMain();
    app.on('activate', () => { if (!mainWindow) createMain(); });
  }).catch(error => {
    if (selfTest) {
      const reportPath = process.argv[selfTestIndex + 2];
      if (reportPath) { try { fs.writeFileSync(reportPath, JSON.stringify({ok:false,error:error.message,platform:process.platform,arch:process.arch},null,2)); } catch (_) {} }
      app.exit(1);
    } else { dialog.showErrorBox('Scheme Grid could not start', error.message); app.quit(); }
  });
}
app.on('window-all-closed', () => { if (process.platform !== 'darwin' && !selfTest) app.quit(); });
app.on('before-quit', () => { if (workerWindow && !workerWindow.isDestroyed()) workerWindow.destroy(); });

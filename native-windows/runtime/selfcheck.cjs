'use strict';
// Portable public fixture: no research drawing and no native application access.
const path = require('node:path');
async function main() {
  const [installPath, logPath] = process.argv.slice(2);
  if (!installPath || !logPath) throw Error('Expected installation and owned log paths.');
  const base = path.resolve(installPath);
  const {chromium} = require(path.join(base, 'runtime/playwright/node_modules/playwright'));
  let browser;
  try {
    browser = await chromium.launch({
      executablePath: path.join(base, 'runtime/chromium/chrome-headless-shell.exe'), headless: true,
      env: {...process.env, CHROME_LOG_FILE: path.resolve(logPath)}
    });
    const context = await browser.newContext();
    await context.route('**/*', route => route.abort());
    const page = await context.newPage();
    const result = await page.evaluate(() => {
      const document = new DOMParser().parseFromString('<CDXML><page id="1"><fragment id="2"><n id="3" p="0 0"/></fragment></page></CDXML>', 'application/xml');
      return {xmlParser: document.documentElement.tagName === 'CDXML' && !document.querySelector('parsererror'), svgNamespace: document.createElementNS('http://www.w3.org/2000/svg', 'svg').namespaceURI};
    });
    if (!result.xmlParser || result.svgNamespace !== 'http://www.w3.org/2000/svg') throw Error('The bundled browser XML runtime failed its check.');
    process.stdout.write(JSON.stringify({ok: true, nodeVersion: process.versions.node, browserVersion: browser.version(), offline: true, nativeAppsOrCOMUsed: false}));
  } finally { if (browser) await browser.close(); }
}
main().catch(error => {process.stderr.write(String(error.stack || error));process.exitCode=1;});

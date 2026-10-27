'use strict';
// Bundled offline planner. browserPath is supplied by the installed native runtime.
const fs = require('node:fs');
const path = require('node:path');
async function main() {
  const [packagePath, runPath, browserPath] = process.argv.slice(2);
  if (!packagePath || !runPath || !browserPath) throw new Error('Expected bundled package, owned run and browser paths.');
  const {chromium} = require(path.join(path.resolve(packagePath), 'node_modules/playwright'));
  const folder = path.resolve(runPath);
  const source = fs.readFileSync(path.join(folder, 'source.cdxml'), 'utf8');
  const options = JSON.parse(fs.readFileSync(path.join(folder, 'options.json'), 'utf8'));
  const browserFile = path.resolve(browserPath);
  if (!fs.statSync(browserFile).isFile()) throw new Error('The bundled layout browser was not found. Reinstall Scheme Grid.');
  let browser;
  try {
    browser = await chromium.launch({executablePath: browserFile, headless: true,
      args: ['--disable-logging', '--log-file=' + path.join(folder, 'chromium-debug.log')],
      env: {...process.env, CHROME_LOG_FILE: path.join(folder, 'chromium-debug.log')}});
    const context = await browser.newContext();
    await context.route('**/*', route => route.abort());
    const page = await context.newPage();
    await page.addScriptTag({path: path.join(__dirname, 'reaction-layout.js')});
    const plan = await page.evaluate(({source, options}) => window.ReactionLayout.plan(source, options), {source, options});
    fs.writeFileSync(path.join(folder, 'plan.json'), JSON.stringify(plan, null, 2));
    fs.writeFileSync(path.join(folder, 'prepared.cdxml'), plan.cdxml);
  } finally { if (browser) await browser.close(); }
}
main().catch(error => { process.stderr.write(String(error.stack || error)); process.exitCode = 1; });

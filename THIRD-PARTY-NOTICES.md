# Third-party notices

The developer runtime builder obtains pinned original distributions of CPython,
pywin32, Node.js, Playwright, Playwright Core, and Chrome Headless Shell. Versions,
official URLs, SHA256 values, npm SHA512 integrity values, and license locations
are recorded in `runtime/PUBLIC-RUNTIME-PROVENANCE.json`.

The source export contains no third-party runtime binaries. A built installer
retains their complete original license and notice files at these installed paths:

- CPython: `runtime/python/LICENSE.txt`
- pywin32: `runtime/python/Lib/site-packages/pywin32-312.dist-info/licenses/`
- Node.js: `runtime/node/LICENSE`
- Chrome Headless Shell: `runtime/chromium/LICENSE.headless_shell`
- Playwright: `runtime/playwright/node_modules/playwright/LICENSE` and `NOTICE`
- Playwright Core: `runtime/playwright/node_modules/playwright-core/LICENSE` and `NOTICE`

The included official Python script-host installers carry their own license notices.
The Scheme Grid project license status is separately described in `LICENSE.md`.

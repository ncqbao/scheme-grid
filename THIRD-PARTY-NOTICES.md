# Third-party components

The installers retain the license files and notices supplied in the official runtime distributions. The source repository does not contain those large runtime binaries.

| Component | Pinned version | Used by | Official source |
| --- | --- | --- | --- |
| Electron | 45.0.0 | Windows and Mac app | https://github.com/electron/electron/releases/tag/v45.0.0 |
| Chromium | 156.0.8078.48, included in Electron | Local layout engine | Electron's `LICENSES.chromium.html` and runtime notices |
| Node.js | 24.22.0, included in Electron | App main process | Electron's runtime notices |
| CPython embeddable x64 | 3.14.10 | Private Windows connection | https://www.python.org/downloads/release/python-31410/ |

Official Electron checksum list: https://github.com/electron/electron/releases/download/v45.0.0/SHASUMS256.txt

Pinned download SHA256 values:

```text
ae53887a23bb640369c93dbd38c408a2af5c0deb86f2fa76c6c244cb444b7f47  electron-v45.0.0-win32-x64.zip
896c3a50b148e89a158dca08a6996a022ddf39b23aac871e107f5b4087f8caa9  electron-v45.0.0-darwin-arm64.zip
7877c282e74a52f8d87949536a25735cf9982de1265b544c9cd258dd14eff4de  electron-v45.0.0-darwin-x64.zip
90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159  python-3.14.10-embed-amd64.zip
```

Electron's runtime includes its own dependencies; consult its bundled notices for the complete component attribution. CPython's license text is retained in the private Windows Python folder. Scheme Grid's project license remains pending the owner's choice and does not alter third-party licenses.

ChemDraw and Revvity names identify the host application and its publisher. No ChemDraw binaries or activation keys are distributed by this project, and the project is not an official Revvity product.

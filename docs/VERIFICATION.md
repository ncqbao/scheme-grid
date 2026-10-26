# Verification and limits

## Windows desktop 0.4.0

- Full installer extraction to an isolated workspace: 122 files, passed.
- Actual extracted Electron/Chromium layout test: passed.
- Same runtime test with system runtime paths removed: passed.
- Input fixture preserved; empty, wrong-root and XML-entity inputs rejected.
- Real shortcut creation method produced a valid workspace shortcut.
- Five focused installer checks, sixteen isolated app-process checks and nineteen isolated native-bridge checks passed.
- Shared reaction engine: six ordering/stability regression fixtures previously passed.

The new desktop native ChemDraw connection has not received a live end-to-end test. The earlier ChemScript edition passed one live menu test in ChemDraw 26.1 x64 with a synthetic drawing, but that does not establish this desktop connection's host behavior.

## Mac desktop preview

ZIP integrity, payload hashes, all original native-binary hashes, nested vendor files, executable modes, all 28 framework links and app references passed archive checks. Both Intel and Apple Silicon runtime ZIPs matched their official hashes. Minimum macOS version in the vendor Info.plist is 13.0.

No actual Mac execution test was performed. Scheme Grid has no Developer ID signature or Apple notarization. The archive checks do not establish Gatekeeper acceptance or end-to-end compatibility.

See [verification.json](verification.json) and [mac-package-verification.json](mac-package-verification.json). The reports contain no local home-directory paths or private chemistry.

## Review scope

Complex branching, detached text, nonstandard objects and ambiguous condition/yield ownership can require manual correction. Both workflows produce separate editable results. Always inspect chemistry and layout in ChemDraw before publication.

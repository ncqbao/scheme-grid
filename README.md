# Scheme Grid

Arrange reaction schemes into tidy rows, center conditions and yields on arrows, and number unnumbered main reactants and products.

**Desktop preview | version 0.4.0.** Scheme Grid is an independent ChemDraw companion. It is not an official Revvity product or a listing in ChemDraw's official add-in catalog.

## Download

- [Windows x64 installer](https://github.com/ncqbao/scheme-grid/releases/download/v0.4.0/SchemeGrid-Windows-Setup.exe)
- [Mac installer preview - Intel and Apple Silicon](https://github.com/ncqbao/scheme-grid/releases/download/v0.4.0/SchemeGrid-Mac-Installer-Preview.zip)
- [Prepared source archive](https://github.com/ncqbao/scheme-grid/releases/download/v0.4.0/SchemeGrid-GitHub-Source-v0.4.0.zip)
- [Release notes and checksums](https://github.com/ncqbao/scheme-grid/releases/tag/v0.4.0)

The installers include their runtimes. You do not need to install Node.js, Python or Chrome separately, and no Codex account is required. You still need your own licensed ChemDraw installation.

## The two-sentence guide

Open the installer for your computer, then open Scheme Grid: everything it needs is included. On Windows, open your drawing in ChemDraw and click **Clean active ChemDraw scheme**; on Mac, open a CDXML copy, click **Arrange**, and save the arranged copy.

**Mac status:** the Mac package has not been run on a Mac, signed with a Scheme Grid Developer ID or notarized by Apple. macOS may block it; signing/notarization and real-Mac testing are required before treating it as a verified one-click release. The Windows installer is unsigned too.

## What this version does

- Aligns main molecules and reaction arrows into consistent rows and columns.
- Normalizes supported horizontal reaction-arrow lengths.
- Centers associated conditions and yields on their arrows.
- Adds numbers to unnumbered main reactants and products.
- Creates separate editable CDXML results and keeps the source drawing.
- Runs layout processing locally; the desktop app blocks external network requests.

The Windows connection can read the active ChemDraw drawing and supported selections. Mac uses CDXML file import/export. Review results in ChemDraw, especially complex branching, detached labels or ambiguous annotation ownership.

These installers create a desktop companion app. They do not install a native **Add-ins** menu entry, enable a restricted ChemDraw license feature or replace a separately installed ChemScript command. PowerPoint writeback is not included in this release.

## Verification

The Windows installer extracted all 122 payload files into an isolated test folder. The extracted app passed its real bundled Chromium layout test again with system runtime paths removed; the source fixture remained unchanged. Shortcut creation also passed an actual workspace check.

Five focused installer cases, sixteen isolated application-process checks and nineteen isolated native-bridge checks passed. The shared engine previously passed six ordering/stability fixtures. The new desktop native connection has **not** received a live end-to-end ChemDraw test; the earlier ChemScript edition's live test does not establish that.

The Mac archive passed checks for payload hashes, original native binaries, executable modes, framework links and app references on Windows. That is not a Mac execution test. See [verification details](docs/VERIFICATION.md) and [installation](docs/INSTALL.md).

## Build from source

See [BUILD.md](docs/BUILD.md). Runtime binaries are downloaded from pinned official releases during development builds and are distributed as release assets, not committed to this repository. End users do not need the developer build tools.

The small example in `examples/` is a synthetic test drawing, not unpublished research chemistry.

## Project license

The owner has not selected a project license yet. No open-source license is assigned by this repository. Third-party runtime components retain their own licenses and notices; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

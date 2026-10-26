# Scheme Grid Desktop 0.4.0 - preview

Self-contained installers for arranging reaction schemes, centering supported conditions/yields and numbering unnumbered main molecules. Node, Python and Chrome do not need separate installation; your own licensed ChemDraw is still required.

## Downloads

- **Windows x64:** `SchemeGrid-Windows-Setup.exe` - run it, then open Scheme Grid.
- **Mac, Intel and Apple Silicon, macOS 13+:** `SchemeGrid-Mac-Installer-Preview.zip` - extract and open Install Scheme Grid.app.
- `SchemeGrid-GitHub-Source-v0.4.0.zip` - prepared source tree, build scripts and guides.
- `SHA256SUMS.txt` - compare hashes after downloading.

In Scheme Grid, Windows users can click **Clean active ChemDraw scheme**. Mac users open a CDXML copy, choose **Arrange**, save the arranged copy and open it in ChemDraw.

## Verification and preview limits

The Windows installer passed complete 122-file extraction, real bundled-runtime tests with system runtime paths removed and shortcut creation. The new desktop native ChemDraw connection has isolated tests but no live end-to-end host test.

**Mac remains untested on a Mac, unsigned for Scheme Grid and unnotarized. Normal macOS trust checks may block it.** Archive hashes, original binaries, executable modes and framework links passed checks on Windows; these do not establish Mac execution. The Windows installer is unsigned too. Treat this as a prerelease and review practice drawings first.

These are independent desktop-companion installers, not an official ChemDraw listing or native Add-ins menu package. PowerPoint writeback is not included. Project licensing is pending the owner's choice; third-party notices remain bundled unchanged.

# Installation

## Windows x64

1. Download `SchemeGrid-Windows-Setup.exe` from the project's release page.
2. Double-click it. The installer checks and extracts its bundled files without administrator access or runtime downloads.
3. Choose **Open Scheme Grid** when installation finishes. A **Scheme Grid** shortcut is also added to the Start menu if that shortcut name is free.
4. Open a practice scheme in your licensed ChemDraw installation and keep one ChemDraw application running.
5. Click **Clean active ChemDraw scheme**. A supported selection limits cleanup to complete selected units and their annotations; no selection requests the full drawing.
6. Review the separate result in ChemDraw and save it where you need it.

You can also open a CDXML copy in Scheme Grid, arrange it and save a separate file. The desktop native connection has isolated tests but no live end-to-end test in this release. The installer is unsigned; institution-managed computers may require lab IT approval. Do not change institution-wide security policy to run it.

## Mac preview - macOS 13 or later

1. Download and extract `SchemeGrid-Mac-Installer-Preview.zip`.
2. Open **Install Scheme Grid.app**. It chooses the Intel or Apple Silicon payload and copies the app into your own `~/Applications` folder.
3. Choose **Open Scheme Grid**.
4. In ChemDraw, save a copy of your drawing as CDXML. Open that copy in Scheme Grid, click **Arrange**, save the arranged copy and open it in ChemDraw.

Mac file mode processes the whole imported drawing. For a smaller scope, first create a CDXML copy containing that scope.

**Release boundary:** this package has not been run on a Mac, signed with a Scheme Grid Developer ID or notarized by Apple. Normal macOS trust checks may block it. Lab IT or the maintainer must finish signing/notarization and real-Mac testing before using it as a verified one-click release. The installer does not remove quarantine or alter Gatekeeper or certificates.

## Updates and removal

The installers refuse unrelated destination folders and retain an existing marked app as a previous version. Close Scheme Grid before updating. Keep personal drawings outside the application folder.

To remove Scheme Grid, remove only its owned application and shortcut after preserving any work you saved there. Preserve saved drawings and Windows `Results` folders. Do not delete a ChemDraw installation, its Scripts folder or unrelated add-ins.

## Scope

Scheme Grid is a desktop companion, not an official ChemDraw catalog entry. ChemDraw itself and its license are not bundled. PowerPoint writeback and native Add-ins menu installation are not included here. Review chemistry, conditions, yields, numbering and page layout before using a result.

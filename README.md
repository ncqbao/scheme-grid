# Scheme Grid for ChemDraw

Tidy a selected reaction row without leaving ChemDraw. Scheme Grid aligns molecules and straight reaction arrows, centers associated conditions and yields, and adds missing numbers to main reaction molecules.

**Windows preview · v0.5.0-native-preview.7**

Download the [Windows installer](https://github.com/ncqbao/scheme-grid/releases/download/v0.5.0-native-preview.7/SchemeGrid-ChemDraw-Windows-Setup.exe), open it, and click **Install commands**; all helper tools are included.
Save your work and reopen ChemDraw; normally no PC restart is needed.
Select a complete reaction row in a saved CDX or CDXML drawing, then choose **File → ChemScripts → Scheme Grid - Arrange Selection in Place**.

Review the result and save normally. To restore the previous arrangement, choose **File → ChemScripts → Scheme Grid - Restore Last Arrangement** before further edits or closing ChemDraw; it requires the same open drawing and verified post-arrangement state.

Requires licensed ChemDraw 26 with ChemScripts in a supported standard per-user installation on 64-bit Windows 10 or newer. Select complete molecules and straight horizontal arrows in one reaction row, and keep one unambiguous ChemDraw 26 process running.

This is an unsigned lab preview. Installation on a fresh Windows machine without an existing compatible Python script host has not been validated. See the [short user guide](docs/INSTALL.md) and [verification details](docs/VERIFICATION.md).

Scheme Grid's project license is unassigned. Bundled third-party components retain their own licenses and notices.

For developers: [build from source](native-windows/BUILD.md).

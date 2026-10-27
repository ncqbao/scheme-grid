# Verification

This records the tested scope for **v0.5.0-native-preview.7**. The [machine-readable report](../SchemeGrid-Windows-Team-Verification.json) contains the detailed results.

The preview.7 installer passed upgrade and repeat installation after use, verifying all 1,144 installed files. Its installed planner passed with the bundled tools, existing Python registrations were preserved, and the recognized legacy Snap launchers were retired with verified backups. No PC restart was required on the tested machine.

The release also passed 34 installer fixture checks, 18 core offline checks, and 49 release-surface checks.

Live ChemDraw editing was tested with preview.5: two consecutive Arrange/Restore cycles passed in the same 64-bit drawing, and arrangement passed in 32-bit ChemDraw. Each arrangement verified 164 unrelated nodes unchanged and added two missing numbers. Preview.6 additionally passed 31 startup checks and installation/runtime checks.

These earlier live tests cover the native engine; a live preview.7 menu-editing cycle has not been tested. Preview.7 installation and planner verification did not control ChemDraw or the desktop.

Installation without an existing compatible Python script host has fixture coverage, but has not been validated on a fresh Windows machine. The installer is unsigned.

The supported workflow uses a saved CDX or CDXML drawing in licensed ChemDraw 26, with complete objects selected within one reaction row and straight horizontal arrows. Restore requires the same open drawing and ChemDraw process, with the verified post-arrangement state.

The public source export passed 70 privacy, syntax, and content checks. Its portable build scripts passed a full offline runtime build from eight pinned official archives, 21 runtime safety tests, and seven assembly checks. Build metadata can differ, so these checks do not claim a byte-identical installer or a source-rebuilt installation test.

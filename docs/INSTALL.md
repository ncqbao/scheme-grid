# Install and use Scheme Grid

Download the [Windows installer](https://github.com/ncqbao/scheme-grid/releases/download/v0.5.0-native-preview.7/SchemeGrid-ChemDraw-Windows-Setup.exe), open it, and click **Install commands**; all helper tools are included.
Save your work and reopen ChemDraw; normally no PC restart is needed.
Select a complete reaction row in a saved CDX or CDXML drawing, then choose **File → ChemScripts → Scheme Grid - Arrange Selection in Place**.

You need licensed ChemDraw 26 with ChemScripts, installed in a supported standard per-user location on 64-bit Windows 10 or newer. Setup checks compatibility and handles the helper tools automatically.

Use the Marquee tool to select complete molecules and straight horizontal arrows in one reaction row. Keep one ChemDraw 26 process running, wait for arrangement to finish, then review the result and save normally. Scheme Grid does not save the drawing automatically.

To bring back the previous arrangement, choose **File → ChemScripts → Scheme Grid - Restore Last Arrangement** before making further edits or closing ChemDraw. It requires the same drawing, the same running ChemDraw process, and the verified post-arrangement state. Keep your usual saved backup.

Normally, reopening ChemDraw is enough. If setup specifically requests a PC restart, save your work, restart, and run setup again.

This is an unsigned lab preview, so your organization's software policy may require IT approval. [Verification details](VERIFICATION.md).

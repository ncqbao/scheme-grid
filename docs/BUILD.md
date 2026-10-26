# Build from source

The developer build uses pinned official runtimes. End users download the installer and do not need these build tools.

## Windows installer

Use Windows x64 with Windows PowerShell and the .NET Framework compiler installed with Windows. From the repository root:

```powershell
.\scripts\Build-Windows.ps1
```

The script downloads and verifies Electron 45.0.0 and CPython 3.14.10 embeddable x64 from their official release locations, stages the app and private bridge, and compiles `dist/SchemeGrid-Windows-Setup.exe`. It does not install the result or modify machine-wide runtimes. If PowerShell is managed by your institution, ask lab IT to run the reviewed build script; do not change institution-wide policy.

The lower-level builder is `bundled-desktop/windows-installer/Build-Setup.ps1`. Its `-PayloadDirectory`, `-OutputFile`, `-EntryPoint` and `-Version` arguments allow rebuilding an already staged payload.

## Combined Mac preview

Python 3.11+ is required on the **build computer** only. Put the official Electron 45.0.0 `darwin-arm64` and `darwin-x64` ZIP files into `bundled-desktop/downloads/`, beside the committed `electron-SHASUMS256.txt`. Then run:

```sh
python bundled-desktop/mac-installer/build_mac_installer.py
```

The builder verifies vendor hashes and creates `dist/SchemeGrid-Mac-Installer-Preview.zip`. It rewrites ZIP entries directly, preserving Unix executable modes and framework links even when run on Windows. The preview includes both architectures; Mac end users do not need Python, Node or Chrome.

This is packaging, not Apple signing or notarization. Read `bundled-desktop/mac-installer/PACKAGING-NOTES.txt`, then finish signing/notarization and test on actual supported Macs before describing the build as a trusted release.

## Runtime self-test

After building or extracting the Windows app:

```powershell
& 'path/to/SchemeGrid.exe' --schemegrid-self-test 'examples/messy-reaction.cdxml' 'self-test-report.json'
```

This uses the bundled Chromium worker, writes a report and a separate arranged CDXML, checks the chemistry guard and rejects malformed inputs. A GUI executable may require a process-waiting wrapper to collect its final exit code. Do not use this flag with private research drawings when preparing public artifacts.

Large runtimes, installer binaries, local configs and generated reports belong outside Git history. Attach the installers to a GitHub prerelease, along with their SHA256 list and compatibility notes.

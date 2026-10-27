# Build the Windows installer

These instructions are for developers. Labmates use the published setup EXE and
do not install development tools or dependencies separately.

Build on 64-bit Windows 10 or newer with Python 3.11 or newer, Windows PowerShell,
and the .NET Framework C# compiler normally located at
`%WINDIR%/Microsoft.NET/Framework64/v4.0.30319/csc.exe`.
Run these commands from this `native-windows` directory:

```powershell
py -3 -I -B runtime/build_runtime.py --download
py -3 -I -B assemble_payload.py
powershell.exe -NoProfile -File setup/Build-Setup.ps1 -PayloadDirectory payload -OutputFile dist/SchemeGrid-ChemDraw-Windows-Setup.exe -Version 0.5.0-native-preview.7 -PythonHostSource host/PythonHostProvision.cs
```

The first command obtains eight pinned original archives over HTTPS at developer
build time. It checks every SHA256, the two npm SHA512 integrity values, package
versions, required licenses, and the official Python installers' Authenticode
signatures. It extracts files without running npm, pip, Python installers, or
ChemDraw. It does not change the registry, PATH, file associations, or security
settings. The resulting installer contains the runtime and needs no downloads
for the included helpers during installation or arrangement.

`--download` is required to fetch missing archives. For an offline build, place
the eight archives named in `runtime/build_runtime.py` in `runtime/downloads/`,
then omit that flag. An existing archive with a wrong checksum causes refusal;
it is never silently replaced. Sources and checksums are recorded in
`runtime/PUBLIC-RUNTIME-PROVENANCE.json`.

The builders refuse existing output directories. Keep a previous output or
choose fresh paths using the optional `--output-dir` arguments; the assembler
also accepts `--runtime-payload <directory>`. Default outputs are
`runtime/payload/`, `payload/`, and `dist/`. Download caches and generated build
outputs are ignored by Git and are not source files.

The assembler verifies the runtime build manifest and copies an explicit list
of twelve production core files. Runtime configuration starts in `prepare`
mode; the installer enables the registered selected-region commands only after
its checks pass.

## Verify without installing

```powershell
py -3 -I -B runtime/test_build_runtime.py
py -3 -I -B test_assemble_payload.py
powershell.exe -NoProfile -File setup/Test-Setup.ps1
```

The Python tests use synthetic temporary files and mocked downloads. Installer
fixtures use fake ChemDraw executables beneath an isolated test directory;
they do not access real ChemDraw, provision system Python, or edit the registry.

To verify the final EXE without installing, launch it with `--validate-only`
and `--report <absolute-output-report.json>`, and wait for the process to exit.
The report must contain `ok: true` and `testOnly: false` for a release build.

The portable runtime builder and assembler were exercised offline against the
pinned archives. Live HTTP fetching was covered with mocks rather than a new
network download. A source build is not promised to reproduce the release EXE
byte for byte: provenance JSON and ZIP/compiler metadata can differ. Test a
newly built installer before distributing it. This source export does not claim
an installation test of a source-rebuilt EXE on a fresh Windows machine.

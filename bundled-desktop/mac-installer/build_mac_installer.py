"""Build the dependency-bundled Mac preview without extracting Unix links on Windows.

This is packaging, not signing. The resulting app needs signing/notarization
and a real Mac execution check before it can be called a trusted release.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import plistlib
import posixpath
import re
import stat
import zipfile
from pathlib import Path

VERSION = "0.4.0"
OUTER = "Install Scheme Grid.app/Contents/"
ELECTRON_VERSION = "45.0.0"
KINDS = {"arm64": "apple-silicon", "x64": "intel"}
APP_FILES = {
    "package.json", "main.cjs", "preload.cjs", "index.html", "desktop.css",
    "renderer.js", "worker.html", "layout-runner.js", "reaction-layout.js",
    "scheme-grid.js",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def info_for(name: str, mode: int = 0o100644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 10, 26, 12, 0, 0))
    info.create_system = 3
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def safe_relative(name: str) -> None:
    if name.startswith("/") or "\\" in name or ":" in name:
        raise ValueError(f"Unsafe ZIP member: {name}")
    parts = name.rstrip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Unsafe ZIP member: {name}")


def rebrand_plist(name: str, data: bytes) -> bytes:
    if name == "Electron.app/Contents/Info.plist":
        value = plistlib.loads(data)
        if value["CFBundleExecutable"] != "Electron":
            raise ValueError("Unexpected main executable")
        value.update(CFBundleDisplayName="Scheme Grid", CFBundleName="Scheme Grid",
                     CFBundleIdentifier="org.schemegrid.desktop",
                     CFBundleShortVersionString=VERSION, CFBundleVersion=VERSION,
                     LSApplicationCategoryType="public.app-category.productivity")
        return plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=False)
    # Keep all nested helper/framework files and their vendor signatures exact.
    # Only the main bundle is rebranded and can receive a repaired top signature.
    return data


def build(base: Path, output: Path, overrides: Path | None = None) -> dict:
    source = base / "app"
    downloads = base / "downloads"
    recipe = base / "mac-installer"
    actual = {p.name for p in source.iterdir() if p.is_file()}
    if actual != APP_FILES:
        raise ValueError(f"Unexpected app file set: {actual ^ APP_FILES}")
    app_bytes = {name: (source / name).read_bytes() for name in sorted(APP_FILES)}
    for name, data in app_bytes.items():
        if re.search(rb"[A-Za-z]:[\\/]+Users[\\/]+", data):
            raise ValueError(f"Machine-specific path in app source: {name}")
    official_hashes = {}
    for line in (downloads / "electron-SHASUMS256.txt").read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            official_hashes[parts[1].lstrip("*")] = parts[0].lower()
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as target:
        written = set()
        def write(info: zipfile.ZipInfo, data: bytes) -> None:
            safe_relative(info.filename)
            if info.filename in written:
                raise ValueError(f"Duplicate output entry: {info.filename}")
            written.add(info.filename)
            target.writestr(info, data)

        for relative in ("Info.plist", "MacOS/install-scheme-grid"):
            path = recipe / "Install Scheme Grid.app" / "Contents" / relative
            data = path.read_bytes().replace(b"\r\n", b"\n")
            write(info_for(OUTER + relative, 0o100755 if relative.startswith("MacOS/") else 0o100644), data)
        for arch, folder in KINDS.items():
            name = f"electron-v{ELECTRON_VERSION}-darwin-{arch}.zip"
            original = downloads / name
            actual_hash = file_digest(original)
            if official_hashes.get(name) != actual_hash:
                raise ValueError(f"Official runtime checksum failed: {name}")
            prefix = OUTER + f"Resources/payload/{folder}/"
            app_prefix = prefix + "Scheme Grid.app/"
            regular_hashes = {}
            link_hashes = {}
            macho_hashes = {}
            nested_vendor_hashes = {}
            executable_modes = {}
            executable_count = 0
            with zipfile.ZipFile(original) as vendor:
                for original_info in vendor.infolist():
                    safe_relative(original_info.filename)
                    data = vendor.read(original_info)
                    original_digest = digest(data)
                    if original_info.filename.startswith("Electron.app/"):
                        remainder = original_info.filename[len("Electron.app/"):]
                        destination = app_prefix + remainder
                        data = rebrand_plist(original_info.filename, data)
                        if overrides is not None:
                            replacement = overrides / arch / remainder
                            if replacement.is_file():
                                if remainder not in {"Contents/Info.plist", "Contents/MacOS/Electron", "Contents/_CodeSignature/CodeResources"}:
                                    raise ValueError(f"Only top signature replacements are allowed: {remainder}")
                                data = replacement.read_bytes()
                    else:
                        destination = app_prefix + "Contents/Resources/vendor/" + original_info.filename
                    info = copy.copy(original_info)
                    info.filename = destination
                    info.compress_type = zipfile.ZIP_DEFLATED
                    relative = destination[len(prefix):]
                    if data[:4] in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}:
                        if digest(data) != original_digest:
                            raise ValueError(f"A vendor Mach-O was changed: {relative}")
                        macho_hashes[relative] = original_digest
                    if original_info.filename.startswith("Electron.app/Contents/Frameworks/") and not original_info.is_dir():
                        if digest(data) != original_digest:
                            raise ValueError(f"A nested vendor file was changed: {relative}")
                        nested_vendor_hashes[relative] = original_digest
                    write(info, data)
                    mode = original_info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        link_target = data.decode("utf-8")
                        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), link_target))
                        if link_target.startswith("/") or not resolved.startswith("Scheme Grid.app/"):
                            raise ValueError(f"Vendor link escapes app: {relative}")
                        link_hashes[relative] = digest(data)
                    elif not original_info.is_dir():
                        regular_hashes[relative] = digest(data)
                        if mode & 0o111:
                            executable_count += 1
                            executable_modes[relative] = mode
            for name, data in app_bytes.items():
                relative = "Scheme Grid.app/Contents/Resources/app/" + name
                write(info_for(prefix + relative), data)
                regular_hashes[relative] = digest(data)
            marker = plistlib.dumps({"kind": "schemegrid-desktop", "version": VERSION}, fmt=plistlib.FMT_XML)
            relative = "Scheme Grid.app/Contents/Resources/SchemeGridInstallation.plist"
            write(info_for(prefix + relative), marker)
            regular_hashes[relative] = digest(marker)
            manifest = "".join(f"{checksum}  {name}\n" for name, checksum in sorted(regular_hashes.items())).encode("utf-8")
            write(info_for(prefix + "SHA256SUMS.txt"), manifest)
            # This supplementary list attests to link text; shasum -c follows
            # links, so link records are intentionally separate from its list.
            write(info_for(prefix + "SYMLINKS.json"), (json.dumps(link_hashes, indent=2) + "\n").encode("utf-8"))
            counts[arch] = {"vendor_sha256": actual_hash, "regular_files": len(regular_hashes),
                            "symlinks": len(link_hashes), "executables": executable_count,
                            "minimum_macos": "13.0", "macho_original_sha256": macho_hashes,
                            "nested_vendor_files_preserved": len(nested_vendor_hashes),
                            "original_executable_modes": executable_modes}
        signing_status = (
            "Top signature replacement files were applied; the nested vendor binaries and signatures are unchanged.\n"
            "It is not Developer ID signed or notarized for Scheme Grid, and macOS may block it.\n"
            if overrides is not None else
            "It is not Developer ID signed or notarized for Scheme Grid, and macOS may block it.\n"
        )
        start = (
            "Double-click Install Scheme Grid to put it in your Applications folder; everything it needs is already included.\n"
            "Open Scheme Grid, choose a CDXML copy from ChemDraw, and save the neatly arranged result as a new ChemDraw file.\n\n"
            "PREVIEW STATUS\n"
            "Version 0.4.0; macOS 13 or newer, Apple silicon or Intel.\n"
            "This cross-built preview has not been run on a Mac.\n"
            + signing_status +
            "Give a blocking message to lab IT. This preview does not change Gatekeeper or remove security protections.\n"
            "It is prepared for lab IT/testing, rather than a verified frictionless public release.\n\n"
            "WORKFLOW\n"
            "Mac uses CDXML file import/export. It does not capture the active ChemDraw selection or update PowerPoint.\n"
            "ChemDraw itself is not included; keep your own licensed installation. Your source drawing is preserved.\n"
            "No separately installed Node.js, Python or Chrome is needed. The bundled Electron runtime includes Node and Chromium.\n\n"
            "Primary distribution/security documentation:\n"
            "https://www.electronjs.org/docs/latest/tutorial/application-distribution\n"
            "https://www.electronjs.org/docs/latest/tutorial/code-signing\n"
            "https://support.apple.com/en-us/102445\n"
        ).encode("utf-8")
        write(info_for("START-HERE.txt"), start)
    report = {"version": VERSION, "archive": str(output), "bytes": output.stat().st_size,
              "sha256": file_digest(output), "architectures": counts,
              "app_sha256": {name: digest(data) for name, data in app_bytes.items()},
              "signing": "Top signature replacements applied; Developer ID signing and notarization pending" if overrides is not None else "Original vendor Mach-O bytes preserved; no Scheme Grid Developer ID signature or notarization",
              "mac_execution_tested": False}
    validate(output, report)
    return report


def validate(output: Path, report: dict) -> None:
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise AssertionError("ZIP CRC failure")
        for arch, folder in KINDS.items():
            prefix = OUTER + f"Resources/payload/{folder}/"
            for line in archive.read(prefix + "SHA256SUMS.txt").decode("utf-8").splitlines():
                expected, name = line.split("  ", 1)
                if digest(archive.read(prefix + name)) != expected:
                    raise AssertionError(f"Payload hash failure: {arch}/{name}")
            links = json.loads(archive.read(prefix + "SYMLINKS.json"))
            all_paths = set()
            for member in archive.infolist():
                if member.filename.startswith(prefix):
                    relative = member.filename[len(prefix):].rstrip("/")
                    while relative:
                        all_paths.add(relative)
                        relative = posixpath.dirname(relative)
            link_targets = {name: archive.read(prefix + name).decode("utf-8") for name in links}
            def resolve_link_path(name: str) -> str:
                current = name
                visited = set()
                for _ in range(40):
                    if current in visited:
                        raise AssertionError(f"Symlink cycle: {name}")
                    visited.add(current)
                    parts = current.split("/")
                    for index in range(1, len(parts) + 1):
                        component = "/".join(parts[:index])
                        if component in link_targets:
                            current = posixpath.normpath(posixpath.join(posixpath.dirname(component), link_targets[component], *parts[index:]))
                            if not current.startswith("Scheme Grid.app/"):
                                raise AssertionError(f"Symlink escapes payload: {name}")
                            break
                    else:
                        if current not in all_paths:
                            raise AssertionError(f"Dangling symlink: {name}")
                        return current
                raise AssertionError(f"Symlink chain is too deep: {name}")
            for name, expected in links.items():
                member = archive.getinfo(prefix + name)
                if not stat.S_ISLNK(member.external_attr >> 16) or digest(archive.read(member)) != expected:
                    raise AssertionError(f"Symlink preservation failure: {name}")
                resolve_link_path(name)
            for name, expected in report["architectures"][arch]["macho_original_sha256"].items():
                if digest(archive.read(prefix + name)) != expected:
                    raise AssertionError(f"Original Mach-O hash equality failed: {name}")
            for name, expected in report["architectures"][arch]["original_executable_modes"].items():
                if archive.getinfo(prefix + name).external_attr >> 16 != expected:
                    raise AssertionError(f"Original executable permissions changed: {name}")
            app_prefix = prefix + "Scheme Grid.app/"
            main = plistlib.loads(archive.read(app_prefix + "Contents/Info.plist"))
            if main["CFBundleExecutable"] != "Electron" or main["CFBundleName"] != "Scheme Grid":
                raise AssertionError("Main bundle rebrand failed")
            executable = archive.getinfo(app_prefix + "Contents/MacOS/Electron")
            if not (executable.external_attr >> 16) & 0o111:
                raise AssertionError("Main executable permissions were lost")
            for name in archive.namelist():
                if name.startswith(app_prefix + "Contents/Frameworks/Electron Helper") and name.endswith(".app/Contents/Info.plist"):
                    helper = plistlib.loads(archive.read(name))
                    binary = name.removesuffix("Info.plist") + "MacOS/" + helper.get("CFBundleExecutable", helper["CFBundleName"])
                    if binary not in archive.namelist():
                        raise AssertionError(f"Helper executable reference failed: {binary}")
        launcher = archive.getinfo(OUTER + "MacOS/install-scheme-grid")
        if not (launcher.external_attr >> 16) & 0o111:
            raise AssertionError("Installer executable permissions were lost")
        forbidden = ("runtime.json", "runtime-mac.json", ".lnk", ".pyc", "MC1", "Pierce")
        if any(any(word.lower() in name.lower() for word in forbidden) for name in archive.namelist()):
            raise AssertionError("Private or machine-specific artifact in archive")
        report["zip_entries"] = len(archive.infolist())
        report["checks"] = {"crc": True, "payload_hashes": True, "symlink_modes_and_text": True,
                            "main_and_helper_executable_references": True,
                            "installer_executable_permissions": True, "private_artifact_exclusions": True,
                            "all_original_macho_hashes_unchanged": True, "all_nested_vendor_files_unchanged": True,
                            "logical_symlink_targets_resolve_inside_payload": True,
                            "all_original_executable_permissions_unchanged": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--overrides", type=Path)
    options = parser.parse_args()
    base = Path(__file__).resolve().parent.parent
    repository = base.parent
    output = options.output or repository / "dist/SchemeGrid-Mac-Installer-Preview.zip"
    result = build(base, output, options.overrides)
    report_path = base / "mac-installer/package-report.json"
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("archive", "bytes", "sha256", "zip_entries", "checks")}, indent=2))

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace SchemeGridNativeSetup {
    public sealed class PayloadFile { public string path; public string sha256; public long size; }
    public sealed class PayloadManifest { public string kind; public string version; public bool testOnly; public PayloadFile[] files; }
    public sealed class CommandSpec { public string command; public string fileName; public string source; public bool template; public string configFileName; public string configTemplate; }
    public sealed class PythonInstaller { public string architecture; public string file; }
    public sealed class LegacySpec { public string command; public string fileName; }
    public sealed class SelfCheck { public string executable; public string[] arguments; public int timeoutSeconds; }
    public sealed class InstallContract { public int schema; public string runtimeConfigFile; public string runtimeTemplateFile; public CommandSpec[] commands; public LegacySpec[] retireLegacy; public SelfCheck[] selfChecks; public PythonInstaller[] pythonInstallers; }
    public sealed class VendorTarget { public string architecture; public string executable; public string scripts; }
    public sealed class ManagedFile { public string path; public string sha256; public string backupPath; public string backupSHA256; public bool retired; public string command; }
    public sealed class CommandIndex { public string kind; public string version; public string installDirectory; public string transaction; public string previousIndexPath; public string previousIndexSHA256; public ManagedFile[] files; }
    public sealed class InstallMarker { public string kind; public string version; public string manifestSHA256; public string installedUtc; public string status; public PayloadFile[] installedFiles; }
    public sealed class InstallResult { public bool ok; public string destination; public string version; public int files; public string message; public bool restartChemDraw; public bool rebootRequired; public bool testOnly; public string receipt; public bool rollbackVerified; public object pythonHost; }
    public sealed class UserPaths { public string local; public string programs; public string data; public string fixtureRoot; }
    public sealed class RebootRequiredException : Exception { public RebootRequiredException(string message) : base(message) { } }

    internal static class SetupEngine {
        const string Kind = "schemegrid-native";
        const string Marker = ".schemegrid-native-installation.json";
        const string Index = "command-registration.json";
        const string VolatileRuntimeLog = "runtime/chromium/debug.log";
        const string LegacySnapName = "Scheme Grid - Snap Scheme.py";
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 };
        internal static string Serialize(object value) { return Json.Serialize(value); }
        internal static string Notices() { using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("installer-notices.txt")) { if (stream == null) return null; using (StreamReader reader = new StreamReader(stream, Encoding.UTF8, true)) return reader.ReadToEnd(); } }
        internal static InstallResult WithInstallLock(Func<InstallResult> action) {
            string identity = System.Security.Principal.WindowsIdentity.GetCurrent().User.Value;
            string suffix = Hash(new MemoryStream(Encoding.UTF8.GetBytes(identity))).Substring(0, 24);
            using (System.Threading.Mutex mutex = new System.Threading.Mutex(false, @"Local\SchemeGridNativeSetup-" + suffix)) {
                bool held = false;
                try { try { held = mutex.WaitOne(0); } catch (System.Threading.AbandonedMutexException) { held = true; } Require(held, "Another Scheme Grid installer is running. Let it finish, then try again."); return action(); }
                finally { if (held) mutex.ReleaseMutex(); }
            }
        }
        internal static T ReadJson<T>(string path) { NoLinks(path); return Json.Deserialize<T>(File.ReadAllText(path, Encoding.UTF8)); }
        internal static void SaveReport(string path, object value) { if (path != null) { Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))); File.WriteAllText(path, Serialize(value), new UTF8Encoding(false)); } }
        static void Require(bool okay, string message) { if (!okay) throw new InvalidDataException(message); }
        static Stream Resource(string name) { Stream value = Assembly.GetExecutingAssembly().GetManifestResourceStream(name); if (value == null) throw new InvalidDataException("This installer is incomplete. Download the complete installer again."); return value; }
        internal static string Hash(Stream source) { using (SHA256 sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(source)).Replace("-", "").ToLowerInvariant(); }
        internal static string HashFile(string path) { NoLinks(path); using (Stream source = File.OpenRead(path)) return Hash(source); }
        static string ManifestHash() { using (Stream source = Resource("payload-manifest.json")) return Hash(source); }
        internal static PayloadManifest Manifest() {
            PayloadManifest value;
            using (Stream stream = Resource("payload-manifest.json")) using (StreamReader reader = new StreamReader(stream, Encoding.UTF8, true)) value = Json.Deserialize<PayloadManifest>(reader.ReadToEnd());
            Require(value != null && value.kind == Kind && value.files != null && value.files.Length > 0, "The installer file list is invalid.");
            Require(Regex.IsMatch(value.version ?? "", @"^\d+\.\d+\.\d+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?$"), "The installation version is invalid.");
            return value;
        }
        internal static string Relative(string relative) {
            Require(!String.IsNullOrEmpty(relative) && !Path.IsPathRooted(relative) && relative.IndexOf(':') < 0 && relative.IndexOf('\0') < 0, "The installer contains an unsafe filename.");
            string normalized = relative.Replace('/', '\\');
            foreach (string segment in normalized.Split('\\')) {
                Require(!String.IsNullOrEmpty(segment) && segment != "." && segment != ".." && !segment.EndsWith(" ") && !segment.EndsWith(".") && segment.IndexOfAny(Path.GetInvalidFileNameChars()) < 0, "The installer contains an unsafe filename.");
                Require(!Regex.IsMatch(segment.Split('.')[0], @"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", RegexOptions.IgnoreCase), "The installer contains a reserved filename.");
            }
            return normalized;
        }
        static string Leaf(string name) { string valid = Relative(name); Require(valid.IndexOf('\\') < 0, "A command filename must be a single filename."); return valid; }
        internal static string Within(string root, string relative) {
            string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string target = Path.GetFullPath(Path.Combine(root, Relative(relative)));
            Require(target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase), "A file points outside its installation folder.");
            return target;
        }
        internal static void NoLinks(string path) {
            string current = Path.GetFullPath(path);
            while (!String.IsNullOrEmpty(current)) {
                if (File.Exists(current) || Directory.Exists(current)) Require((File.GetAttributes(current) & FileAttributes.ReparsePoint) == 0, "Linked installation folders are not supported. Ask lab IT to use a local folder.");
                string parent = Path.GetDirectoryName(current); if (String.Equals(parent, current, StringComparison.OrdinalIgnoreCase)) break; current = parent;
            }
        }
        static void AtomicWrite(string path, byte[] content) {
            NoLinks(path); Directory.CreateDirectory(Path.GetDirectoryName(path)); string temp = Path.Combine(Path.GetDirectoryName(path), ".sg-" + Guid.NewGuid().ToString("N") + ".tmp");
            try { File.WriteAllBytes(temp, content); if (File.Exists(path)) File.Replace(temp, path, null); else File.Move(temp, path); }
            finally { if (File.Exists(temp)) File.Delete(temp); }
        }
        static void AtomicJson(string path, object content) { AtomicWrite(path, new UTF8Encoding(false).GetBytes(Serialize(content))); }
        internal static int ValidatePayload(PayloadManifest manifest, string extractTo, Action<int,string> progress) {
            Dictionary<string, PayloadFile> expected = new Dictionary<string, PayloadFile>(StringComparer.OrdinalIgnoreCase);
            foreach (PayloadFile file in manifest.files) {
                string relative = Relative(file.path);
                Require(file.size >= 0 && file.size <= 1024L * 1024 * 1024 && Regex.IsMatch(file.sha256 ?? "", "^[0-9a-f]{64}$") && !expected.ContainsKey(relative), "The installer checksum list is invalid.");
                Require(!String.Equals(relative, Marker, StringComparison.OrdinalIgnoreCase), "The payload cannot replace an installation marker."); expected.Add(relative, file);
                Require(!String.Equals(relative.Replace('\\', '/'), VolatileRuntimeLog, StringComparison.OrdinalIgnoreCase), "Generated runtime logs cannot be shipped as payload files.");
            }
            Require(expected.ContainsKey("install-contract.json"), "The installation instructions are missing.");
            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            using (Stream stream = Resource("payload.zip")) using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read)) {
                foreach (ZipArchiveEntry entry in archive.Entries) {
                    Require(((entry.ExternalAttributes >> 16) & 0xF000) != 0xA000, "The payload contains a linked file.");
                    if (entry.FullName.EndsWith("/")) { Relative(entry.FullName.TrimEnd('/')); continue; }
                    string relative = Relative(entry.FullName); PayloadFile file;
                    Require(seen.Add(relative) && expected.TryGetValue(relative, out file), "The archive does not match its file list."); file = expected[relative];
                    Require(file.size == entry.Length, "A bundled file has an unexpected size.");
                    using (Stream source = entry.Open()) Require(Hash(source) == file.sha256, "A bundled file failed verification. Download the installer again.");
                    if (extractTo != null) { string destination = Within(extractTo, relative); NoLinks(destination); Directory.CreateDirectory(Path.GetDirectoryName(destination)); using (Stream source = entry.Open()) using (Stream output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None)) source.CopyTo(output); Require(HashFile(destination) == file.sha256, "A copied file failed verification."); }
                    progress((int)(seen.Count * 65L / expected.Count), "Preparing the included tools…");
                }
            }
            Require(seen.Count == expected.Count, "The installer archive is incomplete."); return seen.Count;
        }
        static UserPaths Paths(PayloadManifest manifest, string fixtureRoot) {
            string local;
            if (fixtureRoot != null) {
                Require(manifest.testOnly, "This production installer does not accept fixture paths."); fixtureRoot = Path.GetFullPath(fixtureRoot); NoLinks(fixtureRoot);
                Dictionary<string, object> tag = ReadJson<Dictionary<string, object>>(Within(fixtureRoot, "fixture.json"));
                Require(tag != null && tag.ContainsKey("kind") && Convert.ToString(tag["kind"]) == "schemegrid-native-installer-fixture", "The test folder is not a Scheme Grid installer fixture.");
                local = Within(fixtureRoot, "profile/AppData/Local");
            } else {
                Require(!manifest.testOnly, "This is a test installer. It cannot install into your Windows profile.");
                Require(Environment.OSVersion.Version.Major >= 10 && Environment.Is64BitOperatingSystem, "Scheme Grid needs 64-bit Windows 10 or later.");
                local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData); Require(!String.IsNullOrWhiteSpace(local), "Your Windows application-data folder could not be located.");
            }
            NoLinks(local); return new UserPaths { local = Path.GetFullPath(local), programs = Within(local, "Programs/SchemeGridNative"), data = Within(local, "SchemeGrid/Native"), fixtureRoot = fixtureRoot };
        }
        static List<VendorTarget> VendorTargets(UserPaths paths) {
            List<VendorTarget> targets = new List<VendorTarget>();
            foreach (string architecture in new[] { "ChemDrawApplications", "ChemDrawApplications_x64" }) {
                string application = Within(paths.local, "Programs/RevvitySignalsSoftware/" + architecture); string executable = Within(application, "ChemDraw.exe"); string scripts = Within(application, "ChemDraw/Scripts");
                if (!File.Exists(executable) || !Directory.Exists(scripts)) continue; NoLinks(executable); NoLinks(scripts);
                Require(FileVersionInfo.GetVersionInfo(executable).FileMajorPart == 26, "A ChemDraw installation is incompatible. This preview requires ChemDraw 26.");
                targets.Add(new VendorTarget { architecture = architecture, executable = executable, scripts = scripts });
            }
            Require(targets.Count > 0, "Install and activate ChemDraw 26 with File > ChemScripts support, then run this installer again. Scheme Grid does not include a ChemDraw license."); return targets;
        }
        static InstallContract Contract(string root) {
            InstallContract contract = ReadJson<InstallContract>(Within(root, "install-contract.json"));
            Require(contract != null && contract.schema == 1 && contract.commands != null && contract.commands.Length == 2, "The installation instructions are invalid.");
            Relative(contract.runtimeConfigFile); Relative(contract.runtimeTemplateFile);
            HashSet<string> names = new HashSet<string>(StringComparer.OrdinalIgnoreCase); HashSet<string> commands = new HashSet<string>(StringComparer.Ordinal);
            foreach (CommandSpec command in contract.commands) {
                Require(command.command == "Arrange" || command.command == "Restore", "An unknown ChemDraw command was requested."); Require(commands.Add(command.command), "A command is duplicated.");
                Require(names.Add(Leaf(command.fileName)) && ((command.fileName.EndsWith(".py", StringComparison.OrdinalIgnoreCase) && command.template) || (command.fileName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) && !command.template)), "The ChemDraw command name is invalid.");
                Relative(command.source); Require(File.Exists(Within(root, command.source)), "A ChemDraw command is missing.");
                if (command.configFileName != null || command.configTemplate != null) { Require(names.Add(Leaf(command.configFileName)) && command.configFileName == command.fileName + ".json", "The command settings filename is invalid."); Relative(command.configTemplate); Require(File.Exists(Within(root, command.configTemplate)), "A command settings template is missing."); }
            }
            Require(commands.SetEquals(new[] { "Arrange", "Restore" }), "Both Arrange and Restore commands are required.");
            foreach (LegacySpec legacy in contract.retireLegacy ?? new LegacySpec[0]) { Require(legacy.command == "Arrange" || legacy.command == "Restore", "An unknown legacy command was requested."); Require(names.Add(Leaf(legacy.fileName)) && legacy.fileName.EndsWith(".py", StringComparison.OrdinalIgnoreCase), "The legacy command name is invalid."); }
            Require(contract.selfChecks != null && contract.selfChecks.Length > 0, "The bundled runtime checks are missing.");
            foreach (SelfCheck check in contract.selfChecks) { Relative(check.executable); Require(check.arguments != null && check.timeoutSeconds >= 1 && check.timeoutSeconds <= 180, "A runtime check is invalid."); }
            foreach (PythonInstaller installer in contract.pythonInstallers ?? new PythonInstaller[0]) { Require(installer.architecture == "x86" || installer.architecture == "x64", "A Python host architecture is invalid."); Relative(installer.file); Require(File.Exists(Within(root, installer.file)), "A bundled official Python host installer is missing."); }
            return contract;
        }
        static bool IsRunning(List<VendorTarget> targets) {
            foreach (Process process in Process.GetProcessesByName("ChemDraw")) using (process) { try { if (targets.Any(t => String.Equals(process.MainModule.FileName, t.executable, StringComparison.OrdinalIgnoreCase))) return true; } catch { return true; } } return false;
        }
        static CommandIndex CurrentIndex(UserPaths paths) {
            string path = Within(paths.data, Index); if (!File.Exists(path)) return null;
            CommandIndex current = ReadJson<CommandIndex>(path); Require(current != null && current.kind == Kind && current.files != null && !String.IsNullOrWhiteSpace(current.transaction), "The command installation record needs review by lab IT. Nothing was replaced."); return current;
        }
        static bool LegacyOwned(string path, string command, UserPaths paths) {
            if (!File.Exists(path)) return false; NoLinks(path);
            if (String.Equals(Path.GetFileName(path), LegacySnapName, StringComparison.Ordinal)) {
                if (command != "Arrange" || paths == null || new FileInfo(path).Length > 8192) return false;
                string actual;
                try { actual = new UTF8Encoding(false, true).GetString(File.ReadAllBytes(path)); }
                catch (DecoderFallbackException) { return false; }
                if (actual.StartsWith("\uFEFF", StringComparison.Ordinal)) actual = actual.Substring(1);
                actual = actual.Replace("\r\n", "\n");
                if (actual.EndsWith("\n", StringComparison.Ordinal)) actual = actual.Substring(0, actual.Length - 1);
                string expected = String.Join("\n", new[] {
                    "# -*- coding: utf-8 -*-",
                    "# Scheme Grid managed ChemScript menu entry",
                    "# File > ChemScripts > Scheme Grid - Snap Scheme",
                    "# Clear all selections first; output opens as a separate drawing.",
                    "import os",
                    "import runpy",
                    "_scheme_grid_entry = " + Json.Serialize(Within(paths.local, "Programs/SchemeGrid/SchemeGrid-ChemScript.py")),
                    "if not os.path.isfile(_scheme_grid_entry):",
                    "    raise RuntimeError('Scheme Grid installation is missing. Reinstall the Scheme Grid ChemScript command.')",
                    "runpy.run_path(_scheme_grid_entry, run_name='__main__')"
                });
                return String.Equals(actual, expected, StringComparison.Ordinal);
            }
            using (StreamReader input = new StreamReader(path, Encoding.UTF8, true)) return input.ReadLine() == "# SchemeGridNativePreview managed shim v1" && input.ReadLine() == "# command: " + command;
        }
        static void CheckCommand(string path, string command, CommandIndex index, bool legacy, UserPaths paths) {
            NoLinks(path); Require(!Directory.Exists(path), "A folder occupies a command filename. Nothing was replaced."); if (!File.Exists(path)) return;
            ManagedFile record = index == null ? null : index.files.SingleOrDefault(f => String.Equals(f.path, path, StringComparison.OrdinalIgnoreCase) && !f.retired);
            Require((record != null && record.command == command && HashFile(path) == record.sha256) || (legacy && LegacyOwned(path, command, paths)), "An existing command was not installed by Scheme Grid or has changed. Nothing was replaced: " + Path.GetFileName(path));
        }
        static void VerifyIndexPaths(CommandIndex index, UserPaths paths, List<VendorTarget> targets) {
            if (index == null) return; HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (ManagedFile file in index.files) {
                Require(seen.Add(file.path) && targets.Any(t => String.Equals(Path.GetDirectoryName(Path.GetFullPath(file.path)), t.scripts, StringComparison.OrdinalIgnoreCase)), "A command installation record points outside the verified ChemDraw Scripts folders.");
                Require(file.command == "Arrange" || file.command == "Restore", "A command installation record has an unknown command.");
                if (file.backupPath != null) { Require(Path.GetFullPath(file.backupPath).StartsWith(Path.GetFullPath(paths.data).TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase), "A command backup points outside Scheme Grid's data folder."); NoLinks(file.backupPath); }
            }
        }
        static string RenderText(string path, string installation, string data) {
            string content = File.ReadAllText(path, Encoding.UTF8).Replace("__INSTALL_DIR_JSON__", Json.Serialize(installation)).Replace("__DATA_DIR_JSON__", Json.Serialize(data));
            Require(!content.Contains("__INSTALL_DIR") && !content.Contains("__DATA_DIR"), "An installation setting could not be resolved."); return content;
        }
        static string Render(string path, string installation, string data) { string content = RenderText(path, installation, data); Json.DeserializeObject(content); return content; }
        static Dictionary<string, object> Runtime(InstallContract contract, string stage, string installation, string data, string mode) {
            Dictionary<string, object> settings = Json.Deserialize<Dictionary<string, object>>(Render(Within(stage, contract.runtimeTemplateFile), installation, data));
            Require(settings != null && settings.ContainsKey("mode") && Convert.ToString(settings["mode"]) == "prepare", "The bundled runtime template must be prepare-only.");
            settings["mode"] = mode; settings["runDirectory"] = data; return settings;
        }
        static string Quote(string value) {
            if (value.Length > 0 && !value.Any(c => Char.IsWhiteSpace(c) || c == '"')) return value;
            StringBuilder result = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value) { if (c == '\\') { slashes++; continue; } if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append('"'); } else { result.Append('\\', slashes); result.Append(c); } slashes = 0; }
            result.Append('\\', slashes * 2); result.Append('"'); return result.ToString();
        }
        static void RuntimeChecks(InstallContract contract, string root, string data, Action<int,string> progress) {
            foreach (SelfCheck check in contract.selfChecks) {
                string executable = Within(root, check.executable); Require(File.Exists(executable), "A bundled helper is missing.");
                string[] arguments = check.arguments.Select(a => a.Replace("__INSTALL_DIR__", root).Replace("__DATA_DIR__", data)).ToArray();
                ProcessStartInfo info = new ProcessStartInfo(executable, String.Join(" ", arguments.Select(Quote))) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, WindowStyle = ProcessWindowStyle.Hidden };
                info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
                using (Process process = Process.Start(info)) {
                    Task<string> output = process.StandardOutput.ReadToEndAsync(), error = process.StandardError.ReadToEndAsync();
                    if (!process.WaitForExit(check.timeoutSeconds * 1000)) { try { process.Kill(); } catch { } throw new InvalidDataException("A private bundled-tool check took too long. ChemDraw was not changed."); }
                    Task.WaitAll(output, error); Require(process.ExitCode == 0, "The included tools could not start. ChemDraw was not changed. " + error.Result.Substring(0, Math.Min(800, error.Result.Length)));
                }
            }
            progress(78, "The included tools are ready.");
        }
        static object EnsurePythonHosts(InstallContract contract, string root, List<VendorTarget> targets, PayloadManifest manifest, bool fixture, Action<int,string> progress) {
            if (fixture) return new { fixtureOnly = true, systemProvisioningExecuted = false };
            Type provision = Assembly.GetExecutingAssembly().GetType("SchemeGridNativeSetup.PythonHostProvision"); Require(provision != null, "The Python host compatibility checker is missing from this installer.");
            string[] architectures = targets.Select(t => t.architecture.EndsWith("_x64", StringComparison.Ordinal) ? "x64" : "x86").Distinct().ToArray();
            Dictionary<string,string> installers = new Dictionary<string,string>(), hashes = new Dictionary<string,string>();
            foreach (PythonInstaller installer in contract.pythonInstallers ?? new PythonInstaller[0]) { string relative = Relative(installer.file); Require(!installers.ContainsKey(installer.architecture), "A Python host installer is duplicated."); installers.Add(installer.architecture, Within(root, relative)); PayloadFile item = manifest.files.Single(f => String.Equals(Relative(f.path), relative, StringComparison.OrdinalIgnoreCase)); hashes.Add(installer.architecture, item.sha256); }
            progress(80, "Checking ChemDraw's Python scripting support…");
            try { object result = provision.InvokeMember("EnsureHosts", BindingFlags.InvokeMethod | BindingFlags.Public | BindingFlags.Static, null, null, new object[] { architectures, installers, hashes, true }); if (HostNeedsReboot(Json.DeserializeObject(Json.Serialize(result)))) throw new RebootRequiredException("Python scripting support needs a Windows restart before it can be used. Save your work, restart Windows when convenient, and run Scheme Grid setup again. ChemDraw command files have not been changed."); return result; }
            catch (TargetInvocationException error) { throw new InvalidDataException(error.InnerException == null ? error.Message : error.InnerException.Message, error); }
        }
        static bool HostNeedsReboot(object value) {
            Dictionary<string,object> fields = value as Dictionary<string,object>;
            if (fields != null) { foreach (KeyValuePair<string,object> field in fields) { if ((String.Equals(field.Key, "rebootRequired", StringComparison.OrdinalIgnoreCase) || String.Equals(field.Key, "restartRequired", StringComparison.OrdinalIgnoreCase)) && field.Value is bool && (bool)field.Value) return true; if (HostNeedsReboot(field.Value)) return true; } }
            object[] items = value as object[]; if (items != null) foreach (object item in items) if (HostNeedsReboot(item)) return true; return false;
        }
        internal static object LastPythonHostReport() { Type provision = Assembly.GetExecutingAssembly().GetType("SchemeGridNativeSetup.PythonHostProvision"); if (provision == null) return null; PropertyInfo property = provision.GetProperty("LastReport", BindingFlags.Public | BindingFlags.Static); return property == null ? null : property.GetValue(null, null); }
        static IEnumerable<string> SafeFiles(string root) { NoLinks(root); foreach (string file in Directory.GetFiles(root)) { NoLinks(file); yield return file; } foreach (string directory in Directory.GetDirectories(root)) { NoLinks(directory); foreach (string file in SafeFiles(directory)) yield return file; } }
        static string InstalledRelative(string root, string path) { return path.Substring(root.TrimEnd('\\').Length + 1).Replace('\\', '/'); }
        static bool VolatileFile(string root, string path) { return String.Equals(InstalledRelative(root, path), VolatileRuntimeLog, StringComparison.OrdinalIgnoreCase); }
        static PayloadFile[] InstalledFiles(string root) { return SafeFiles(root).Where(p => !String.Equals(InstalledRelative(root, p), Marker, StringComparison.OrdinalIgnoreCase) && !VolatileFile(root, p)).OrderBy(p => p).Select(p => new PayloadFile { path = InstalledRelative(root, p), size = new FileInfo(p).Length, sha256 = HashFile(p) }).ToArray(); }
        static void VerifyInstalled(string root, PayloadManifest manifest) {
            NoLinks(root); Require(Directory.Exists(root) && File.Exists(Within(root, Marker)), "An unmarked folder uses this version's installation path. Nothing was replaced.");
            InstallMarker marker = ReadJson<InstallMarker>(Within(root, Marker)); Require(marker != null && marker.kind == Kind && marker.version == manifest.version && marker.manifestSHA256 == ManifestHash() && marker.installedFiles != null, "This version folder belongs to another build. Download a new version or ask lab IT.");
            foreach (PayloadFile file in marker.installedFiles) { string path = Within(root, file.path); Require(File.Exists(path) && new FileInfo(path).Length == file.size && HashFile(path) == file.sha256, "An installed file changed. Nothing was replaced: " + file.path); }
            Require(SafeFiles(root).Count(p => !VolatileFile(root, p)) == marker.installedFiles.Length + 1, "Unexpected files are present in this version folder. Nothing was replaced.");
        }
        static void RemoveOwnedStage(string stage, string programs) {
            string absolute = Path.GetFullPath(stage), parent = Path.GetFullPath(programs).TrimEnd('\\');
            Require(String.Equals(Path.GetDirectoryName(absolute), parent, StringComparison.OrdinalIgnoreCase) && Regex.IsMatch(Path.GetFileName(absolute), @"^\.stage-[0-9a-f]{32}$"), "A temporary folder escaped Scheme Grid's installation area.");
            if (!Directory.Exists(absolute)) return; NoLinks(absolute); foreach (string file in SafeFiles(absolute)) NoLinks(file); Directory.Delete(absolute, true);
        }
        static ManagedFile BackupAndWrite(string path, string command, byte[] content, string backupRoot, CommandIndex prior, bool retired, Action<ManagedFile> journal) {
            NoLinks(path);
            string backup = null, backupHash = null;
            if (File.Exists(path)) { backup = Within(backupRoot, Guid.NewGuid().ToString("N") + ".bak"); File.Copy(path, backup, false); backupHash = HashFile(backup); Require(HashFile(path) == backupHash, "A command changed while it was being backed up."); }
            ManagedFile record = new ManagedFile { path = path, command = command, backupPath = backup, backupSHA256 = backupHash, retired = retired, sha256 = retired ? null : Hash(new MemoryStream(content)) };
            journal(record); // Durable write-ahead record, before a vendor Scripts mutation.
            if (retired) File.Delete(path); else AtomicWrite(path, content);
            return record;
        }
        static bool Rollback(List<ManagedFile> written) {
            bool verified = true;
            foreach (ManagedFile file in written.AsEnumerable().Reverse()) {
                try {
                    if (file.backupPath == null && !File.Exists(file.path)) continue;
                    if (file.backupPath != null && File.Exists(file.path) && HashFile(file.path) == file.backupSHA256) continue;
                    bool expected = file.retired ? !File.Exists(file.path) : File.Exists(file.path) && HashFile(file.path) == file.sha256;
                    if (!expected) { verified = false; continue; }
                    if (file.backupPath != null) { Require(File.Exists(file.backupPath) && HashFile(file.backupPath) == file.backupSHA256, "A command backup changed."); AtomicWrite(file.path, File.ReadAllBytes(file.backupPath)); verified &= HashFile(file.path) == file.backupSHA256; }
                    else { if (File.Exists(file.path)) File.Delete(file.path); verified &= !File.Exists(file.path); }
                } catch { verified = false; }
            }
            return verified;
        }
        internal static InstallResult Install(string fixtureRoot, bool validateOnly, int failAfter, Action<int,string> progress) {
            PayloadManifest manifest = Manifest();
            if (validateOnly) return new InstallResult { ok = true, version = manifest.version, files = ValidatePayload(manifest, null, progress), testOnly = manifest.testOnly, message = "All bundled files passed verification. No installation changes were made." };
            UserPaths paths = Paths(manifest, fixtureRoot); List<VendorTarget> targets = VendorTargets(paths); bool running = fixtureRoot == null && IsRunning(targets);
            string destination = Within(paths.programs, manifest.version); NoLinks(destination); Require(!File.Exists(destination), "A file occupies the version installation folder.");
            CommandIndex prior = CurrentIndex(paths); VerifyIndexPaths(prior, paths, targets);
            if (Directory.Exists(destination) && prior != null && prior.version == manifest.version && String.Equals(prior.installDirectory, destination, StringComparison.OrdinalIgnoreCase)) {
                VerifyInstalled(destination, manifest);
                foreach (ManagedFile file in prior.files) Require(file.retired ? !File.Exists(file.path) : File.Exists(file.path) && HashFile(file.path) == file.sha256, "A registered command changed. Nothing was replaced.");
                InstallContract installedContract = Contract(destination); RuntimeChecks(installedContract, destination, paths.data, progress); object installedHost = EnsurePythonHosts(installedContract, destination, targets, manifest, fixtureRoot != null, progress);
                return new InstallResult { ok = true, version = manifest.version, destination = destination, files = manifest.files.Length, restartChemDraw = running, rebootRequired = false, testOnly = manifest.testOnly, rollbackVerified = true, pythonHost = installedHost, message = "This version is already installed and its files passed verification. Reopen ChemDraw to refresh the File > ChemScripts menu. No PC restart is needed." };
            }
            Directory.CreateDirectory(paths.programs); Directory.CreateDirectory(paths.data);
            string stage = Within(paths.programs, ".stage-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(stage);
            int count; InstallContract contract; object hostReport;
            try {
                count = ValidatePayload(manifest, stage, progress); contract = Contract(stage);
                foreach (VendorTarget target in targets) {
                    foreach (CommandSpec command in contract.commands) { CheckCommand(Within(target.scripts, command.fileName), command.command, prior, command.fileName.EndsWith(".py", StringComparison.OrdinalIgnoreCase), paths); if (command.configFileName != null) CheckCommand(Within(target.scripts, command.configFileName), command.command, prior, false, paths); }
                    foreach (LegacySpec legacy in contract.retireLegacy ?? new LegacySpec[0]) CheckCommand(Within(target.scripts, legacy.fileName), legacy.command, prior, true, paths);
                }
                AtomicJson(Within(stage, contract.runtimeConfigFile), Runtime(contract, stage, stage, paths.data, "prepare")); RuntimeChecks(contract, stage, paths.data, progress); hostReport = EnsurePythonHosts(contract, stage, targets, manifest, fixtureRoot != null, progress);
                if (Directory.Exists(destination)) VerifyInstalled(destination, manifest);
                else { AtomicJson(Within(stage, Marker), new InstallMarker { kind = Kind, version = manifest.version, manifestSHA256 = ManifestHash(), installedUtc = DateTime.UtcNow.ToString("o"), status = "prepared", installedFiles = InstalledFiles(stage) }); Directory.Move(stage, destination); }
            } finally { if (Directory.Exists(stage)) { try { RemoveOwnedStage(stage, paths.programs); } catch { } } }
            string transaction = Guid.NewGuid().ToString("N"); string backupRoot = Within(paths.data, "installer-backups/" + transaction); Directory.CreateDirectory(backupRoot);
            string receipt = Within(backupRoot, "receipt.json"); List<ManagedFile> written = new List<ManagedFile>(); bool indexWritten = false; string indexPath = Within(paths.data, Index); byte[] priorIndex = File.Exists(indexPath) ? File.ReadAllBytes(indexPath) : null; string newIndexHash = null;
            string previousIndexPath = priorIndex == null ? null : Within(backupRoot, "previous-command-registration.json");
            if (previousIndexPath != null) File.WriteAllBytes(previousIndexPath, priorIndex);
            try {
                // Revalidate all ownership immediately before modifying a vendor Scripts file.
                foreach (VendorTarget target in targets) {
                    Require(FileVersionInfo.GetVersionInfo(target.executable).FileMajorPart == 26 && Directory.Exists(target.scripts), "ChemDraw changed while installation was preparing.");
                    foreach (CommandSpec command in contract.commands) {
                        string path = Within(target.scripts, command.fileName); CheckCommand(path, command.command, prior, command.fileName.EndsWith(".py", StringComparison.OrdinalIgnoreCase), paths);
                        byte[] commandContent = command.template ? new UTF8Encoding(false).GetBytes(RenderText(Within(destination, command.source), destination, paths.data)) : File.ReadAllBytes(Within(destination, command.source));
                        BackupAndWrite(path, command.command, commandContent, backupRoot, prior, false, delegate(ManagedFile record) { written.Add(record); AtomicJson(receipt, new { status = "installing", files = written }); });
                        if (failAfter > 0 && written.Count >= failAfter) throw new IOException("Injected fixture failure.");
                        if (command.configFileName != null) { string configPath = Within(target.scripts, command.configFileName); CheckCommand(configPath, command.command, prior, false, paths); BackupAndWrite(configPath, command.command, new UTF8Encoding(false).GetBytes(Render(Within(destination, command.configTemplate), destination, paths.data)), backupRoot, prior, false, delegate(ManagedFile record) { written.Add(record); AtomicJson(receipt, new { status = "installing", files = written }); }); if (failAfter > 0 && written.Count >= failAfter) throw new IOException("Injected fixture failure."); }
                    }
                    foreach (LegacySpec legacy in contract.retireLegacy ?? new LegacySpec[0]) { string path = Within(target.scripts, legacy.fileName); CheckCommand(path, legacy.command, prior, true, paths); if (File.Exists(path)) { BackupAndWrite(path, legacy.command, null, backupRoot, prior, true, delegate(ManagedFile record) { written.Add(record); AtomicJson(receipt, new { status = "installing", files = written }); }); if (failAfter > 0 && written.Count >= failAfter) throw new IOException("Injected fixture failure."); } }
                }
                AtomicJson(Within(destination, contract.runtimeConfigFile), Runtime(contract, destination, destination, paths.data, "apply-selected"));
                CommandIndex current = new CommandIndex { kind = Kind, version = manifest.version, installDirectory = destination, transaction = transaction, previousIndexPath = previousIndexPath, previousIndexSHA256 = previousIndexPath == null ? null : HashFile(previousIndexPath), files = written.ToArray() }; AtomicJson(indexPath, current); indexWritten = true; newIndexHash = HashFile(indexPath);
                AtomicJson(Within(destination, Marker), new InstallMarker { kind = Kind, version = manifest.version, manifestSHA256 = ManifestHash(), installedUtc = DateTime.UtcNow.ToString("o"), status = "complete", installedFiles = InstalledFiles(destination) });
                InstallResult result = new InstallResult { ok = true, destination = destination, version = manifest.version, files = count, restartChemDraw = running, rebootRequired = false, testOnly = manifest.testOnly, receipt = receipt, rollbackVerified = true, pythonHost = hostReport, message = "Scheme Grid commands are installed. " + (running ? "Save your work, close ChemDraw, and reopen it. " : "Open ChemDraw. ") + "Select a reaction region, then choose File > ChemScripts > Scheme Grid - Arrange Selection in Place. No PC restart is needed." };
                AtomicJson(receipt, new { status = "complete", result = result, files = written }); progress(100, "Your ChemDraw commands are ready."); return result;
            } catch (Exception ex) {
                bool restored = Rollback(written);
                try { if (indexWritten && File.Exists(indexPath) && HashFile(indexPath) == newIndexHash) { if (priorIndex != null) AtomicWrite(indexPath, priorIndex); else File.Delete(indexPath); } } catch { restored = false; }
                try { AtomicJson(Within(destination, contract.runtimeConfigFile), Runtime(contract, destination, destination, paths.data, "prepare")); AtomicJson(Within(destination, Marker), new InstallMarker { kind = Kind, version = manifest.version, manifestSHA256 = ManifestHash(), installedUtc = DateTime.UtcNow.ToString("o"), status = "failed", installedFiles = InstalledFiles(destination) }); } catch { restored = false; }
                AtomicJson(receipt, new { status = "failed", error = ex.Message, rollbackVerified = restored, files = written }); throw new IOException(ex.Message + (restored ? " Previous command files were restored and verified." : " Command recovery needs review. See: " + receipt), ex);
            }
        }
        internal static InstallResult Uninstall(string fixtureRoot) {
            PayloadManifest manifest = Manifest(); UserPaths paths = Paths(manifest, fixtureRoot); List<VendorTarget> targets = VendorTargets(paths); CommandIndex current = CurrentIndex(paths); Require(current != null, "No Scheme Grid native commands are registered for this Windows user."); VerifyIndexPaths(current, paths, targets);
            foreach (ManagedFile file in current.files) { Require(file.retired ? !File.Exists(file.path) : File.Exists(file.path) && HashFile(file.path) == file.sha256, "A command has changed since installation. Nothing was removed: " + Path.GetFileName(file.path)); if (file.backupPath != null) Require(File.Exists(file.backupPath) && HashFile(file.backupPath) == file.backupSHA256, "An original command backup changed. Nothing was removed."); }
            if (current.previousIndexPath != null) { Require(Path.GetFullPath(current.previousIndexPath).StartsWith(Path.GetFullPath(paths.data).TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase), "A previous installation record points outside Scheme Grid's data folder."); Require(File.Exists(current.previousIndexPath) && HashFile(current.previousIndexPath) == current.previousIndexSHA256, "A previous installation record changed. Nothing was removed."); }
            Require(Rollback(current.files.ToList()), "Restoring prior command files needs review. Your drawings were not changed.");
            if (current.previousIndexPath != null) AtomicWrite(Within(paths.data, Index), File.ReadAllBytes(current.previousIndexPath)); else File.Delete(Within(paths.data, Index));
            return new InstallResult { ok = true, version = current.version, destination = current.installDirectory, restartChemDraw = fixtureRoot == null && IsRunning(targets), rebootRequired = false, testOnly = manifest.testOnly, rollbackVerified = true, message = "Scheme Grid menu commands were removed and previous command files restored. Saved drawings, backups, and the private runtime folder were kept. Reopen ChemDraw to refresh its menu." };
        }
    }
    public sealed class SetupForm : Form {
        readonly Label title = new Label(), status = new Label(); readonly ProgressBar progress = new ProgressBar(); readonly Button install = new Button(), done = new Button(); bool busy;
        public SetupForm() {
            Text = "Scheme Grid for ChemDraw"; ClientSize = new Size(510, 275); FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; StartPosition = FormStartPosition.CenterScreen; Font = new Font("Segoe UI", 10); BackColor = Color.White;
            title.Text = "Scheme Grid, inside ChemDraw."; title.Font = new Font("Segoe UI", 17, FontStyle.Bold); title.SetBounds(24, 23, 470, 40);
            status.Text = "Select part of a scheme and tidy it without leaving ChemDraw. Includes the helper tools. Requires an installed, licensed ChemDraw 26."; status.SetBounds(24, 77, 462, 78);
            progress.SetBounds(24, 174, 462, 13); install.Text = "Install commands"; install.SetBounds(285, 215, 201, 36); done.Text = "Close"; done.SetBounds(174, 215, 99, 36);
            LinkLabel notices = new LinkLabel { Text = "Third-party notices", AutoSize = true, Left = 24, Top = 225, Visible = SetupEngine.Notices() != null };
            notices.LinkClicked += delegate { using (Form viewer = new Form { Text = "Scheme Grid: third-party notices", Size = new Size(760, 560), StartPosition = FormStartPosition.CenterParent }) { TextBox text = new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, Text = SetupEngine.Notices(), Font = new Font("Consolas", 10) }; viewer.Controls.Add(text); viewer.ShowDialog(this); } };
            install.Click += delegate { StartInstall(); }; done.Click += delegate { if (!busy) Close(); }; FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) e.Cancel = true; };
            Controls.AddRange(new Control[] { title, status, progress, install, done, notices });
        }
        void StartInstall() {
            busy = true; install.Enabled = false; done.Enabled = false;
            Task.Factory.StartNew(delegate { try { InstallResult result = SetupEngine.WithInstallLock(delegate { return SetupEngine.Install(null, false, 0, UpdateProgress); }); BeginInvoke((Action)delegate { title.Text = "Your commands are ready."; status.Text = result.message; busy = false; done.Enabled = true; install.Visible = false; }); } catch (Exception ex) { BeginInvoke((Action)delegate { title.Text = ex is RebootRequiredException ? "Restart needed." : "Installation needs a hand."; status.Text = ex.Message; busy = false; done.Enabled = true; install.Visible = false; }); } });
        }
        void UpdateProgress(int value, string text) { if (!IsDisposed) BeginInvoke((Action)delegate { progress.Value = Math.Max(0, Math.Min(100, value)); status.Text = text; }); }
    }
    public static class Program {
        [STAThread] public static int Main(string[] args) {
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
            string report = null, fixture = null; int failAfter = 0; bool validate = args.Contains("--validate-only"), install = args.Contains("--install"), uninstall = args.Contains("--uninstall");
            for (int i = 0; i < args.Length; i++) { if (args[i] == "--report" && i + 1 < args.Length) report = args[++i]; else if (args[i] == "--fixture-root" && i + 1 < args.Length) fixture = args[++i]; else if (args[i] == "--fail-after" && i + 1 < args.Length) failAfter = Int32.Parse(args[++i]); }
            if (validate || install || uninstall || fixture != null) {
                try { if (failAfter != 0 && (fixture == null || !SetupEngine.Manifest().testOnly)) throw new InvalidDataException("Failure injection is restricted to test fixtures."); InstallResult result = validate ? SetupEngine.Install(fixture, true, failAfter, delegate { }) : SetupEngine.WithInstallLock(delegate { return uninstall ? SetupEngine.Uninstall(fixture) : SetupEngine.Install(fixture, false, failAfter, delegate { }); }); SetupEngine.SaveReport(report, result); return 0; }
                catch (Exception ex) { SetupEngine.SaveReport(report, new InstallResult { ok = false, message = ex.Message, rebootRequired = ex is RebootRequiredException, pythonHost = SetupEngine.LastPythonHostReport() }); return ex is RebootRequiredException ? 3010 : 1; }
            }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false); Application.Run(new SetupForm()); return 0;
        }
    }
}

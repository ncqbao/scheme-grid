// Scheme Grid installer support: provision ChemDraw's documented Python script
// host only when no recognized, usable host is registered for that architecture.
// This helper never changes associations, PATH, licenses, or ChemDraw preferences.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace SchemeGridNativeSetup {
    internal interface IPythonHostSystem {
        string LocalApplicationData { get; }
        Dictionary<string,string> Snapshot();
        Dictionary<string,object> Probe(string executable, string architecture, string tag);
        bool DirectoryExists(string path);
        string Digest(string path);
        void VerifyOfficialInstaller(string path, string architecture);
        int Install(string path, string targetDirectory);
    }

    public static class PythonHostProvision {
        private static readonly string[] Versions = { "3.14", "3.13", "3.10", "3.9" };
        internal static readonly string[] Hives = { "HKCU", "HKLM" };
        internal static readonly string[] Views = { "32", "64" };
        internal const string Core = @"Software\Python\PythonCore";
        internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        public static object LastReport { get; private set; }
        private static void Need(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
        internal static string Full(string value) { return Path.GetFullPath(value).TrimEnd(Path.DirectorySeparatorChar); }
        internal static bool Same(string a, string b) { return String.Equals(Full(a), Full(b), StringComparison.OrdinalIgnoreCase); }
        internal static string Root(string hive, string view) { return hive + "|" + view + "|" + Core; }
        internal static string Key(string hive, string view, string tag) { return Root(hive, view) + "\\" + tag; }
        internal static string EncodeValues(SortedDictionary<string,string> values) { return Json.Serialize(values); }
        internal static string DefaultPath(string record) {
            var values = Json.Deserialize<Dictionary<string,string>>(record);
            string encoded;
            Need(values.TryGetValue("", out encoded), "A registered Python host has no InstallPath default value. Repair that Python installation, then retry.");
            string prefix = encoded.StartsWith("String:", StringComparison.Ordinal) ? "String:" : encoded.StartsWith("ExpandString:", StringComparison.Ordinal) ? "ExpandString:" : null;
            Need(prefix != null, "A registered Python InstallPath has an unsupported value type. Repair that Python installation, then retry.");
            string path = Json.Deserialize<string>(encoded.Substring(prefix.Length));
            if (prefix == "ExpandString:") path = Environment.ExpandEnvironmentVariables(path);
            Need(!String.IsNullOrWhiteSpace(path) && Path.IsPathRooted(path), "A registered Python InstallPath is not an absolute directory. Repair that Python installation, then retry.");
            return Full(path);
        }
        internal static void VerifyExistingUnchanged(Dictionary<string,string> before, Dictionary<string,string> after) {
            foreach (var record in before) {
                string current;
                Need(after.TryGetValue(record.Key, out current) && current == record.Value,
                    "Python setup changed an existing Python registration. Scheme Grid commands were not installed. See the installation report.");
            }
        }
        private static List<Dictionary<string,object>> Find(IPythonHostSystem system, Dictionary<string,string> snapshot, string architecture) {
            var candidates = new List<Dictionary<string,object>>();
            string view = architecture == "x86" ? "32" : "64";
            foreach (string version in Versions) {
                string tag = version + (architecture == "x86" ? "-32" : "");
                foreach (string hive in Hives) {
                    string key = Key(hive, view, tag);
                    if (!snapshot.ContainsKey(key)) continue;
                    string pathRecord;
                    Need(snapshot.TryGetValue(key + @"\InstallPath", out pathRecord),
                        "A recognized Python registration is incomplete (" + hive + " " + tag + "). Repair that Python installation before installing Scheme Grid.");
                    string directory = DefaultPath(pathRecord);
                    string executable = Path.Combine(directory, "python.exe");
                    Dictionary<string,object> probe;
                    try { probe = system.Probe(executable, architecture, tag); }
                    catch (Exception error) { throw new InvalidOperationException("A recognized Python host is unusable (" + hive + " " + tag + "). Scheme Grid will not replace it. Repair that Python installation, then retry. " + error.Message, error); }
                    Need(probe != null && probe.ContainsKey("ok") && probe["ok"] is bool && (bool)probe["ok"], "A recognized Python host failed its standard-library check.");
                    probe["registryHive"] = hive; probe["registryView"] = view; probe["registryTag"] = tag;
                    candidates.Add(probe);
                }
            }
            // Check every recognized registration rather than silently skipping a
            // broken higher-priority registration that ChemDraw could choose.
            return candidates;
        }
        public static object EnsureHosts(string[] architectures, Dictionary<string,string> installers, Dictionary<string,string> expectedHashes, bool installIfNeeded) {
            return EnsureHostsWith(new WindowsPythonHostSystem(), architectures, installers, expectedHashes, installIfNeeded);
        }
        internal static object EnsureHostsWith(IPythonHostSystem system, string[] architectures, Dictionary<string,string> installers, Dictionary<string,string> expectedHashes, bool installIfNeeded) {
            LastReport = null;
            Need(architectures != null && architectures.Length > 0 && architectures.Length <= 2, "No supported ChemDraw architecture was selected.");
            var selected = new HashSet<string>(StringComparer.Ordinal);
            foreach (string architecture in architectures) Need((architecture == "x86" || architecture == "x64") && selected.Add(architecture), "Unsupported or duplicate ChemDraw architecture.");
            Dictionary<string,string> before = system.Snapshot();
            var progress = new Dictionary<string,object> { {"ok", false}, {"beforeRegistry", before}, {"installIfNeeded", installIfNeeded} };
            LastReport = progress;
            try {
            var result = new List<Dictionary<string,object>>();
            var installedTags = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            bool restart = false;
            foreach (string architecture in architectures) {
                Dictionary<string,string> current = system.Snapshot();
                VerifyExistingUnchanged(before, current);
                List<Dictionary<string,object>> hosts = Find(system, current, architecture);
                if (hosts.Count > 0) {
                    result.Add(new Dictionary<string,object> { {"architecture", architecture}, {"action", "existing-host-verified"}, {"hosts", hosts} });
                    continue;
                }
                string targetTag = architecture == "x86" ? "3.14-32" : "3.14";
                // A matching version in another hive/view is still an existing
                // registration. Do not invoke a version installer over it.
                foreach (string hive in Hives) foreach (string view in Views)
                    Need(!current.ContainsKey(Key(hive, view, targetTag)),
                        "Python " + targetTag + " is already registered in another registry view. Scheme Grid will not modify it; repair or complete that installation first.");
                string target = Full(Path.Combine(system.LocalApplicationData, @"Programs\Python\" + (architecture == "x86" ? "Python314-32" : "Python314")));
                Need(!system.DirectoryExists(target), "The Python host destination already exists without a usable registration. Scheme Grid will not overwrite it: " + target);
                Need(installIfNeeded, "ChemDraw needs a Python " + architecture + " script host. The installer must provision its bundled official Python prerequisite before these commands can run.");
                string installer = null, expected = null;
                Need(installers != null && expectedHashes != null && installers.TryGetValue(architecture, out installer) && expectedHashes.TryGetValue(architecture, out expected), "The matching official Python prerequisite is missing from this installer.");
                installer = Full(installer);
                Need(expected != null && System.Text.RegularExpressions.Regex.IsMatch(expected, "^[0-9a-f]{64}$") && system.Digest(installer) == expected, "The bundled Python prerequisite failed its SHA256 verification.");
                system.VerifyOfficialInstaller(installer, architecture);
                // Recheck immediately before the official installer can write.
                Dictionary<string,string> immediate = system.Snapshot();
                VerifyExistingUnchanged(current, immediate);
                Need(immediate.Count == current.Count, "Python registrations changed while preparing installation. Retry after the other installer finishes.");
                Need(!system.DirectoryExists(target), "The Python destination changed while preparing installation. Retry after the other installer finishes.");
                int exit = system.Install(installer, target);
                Dictionary<string,string> afterInstall = system.Snapshot();
                VerifyExistingUnchanged(before, afterInstall);
                Need(exit == 0 || exit == 3010, "The official Python prerequisite did not finish (exit " + exit + "). Scheme Grid commands were not installed. Complete Python setup, then retry.");
                restart = restart || exit == 3010;
                installedTags.Add(targetTag);
                if (exit == 3010) {
                    // Do not try to prove a reboot-pending runtime is ready.
                    // The outer setup must stop before writing ChemDraw commands.
                    result.Add(new Dictionary<string,object> { {"architecture", architecture}, {"action", "official-per-user-host-restart-required"}, {"installerSHA256", expected}, {"targetDirectory", target}, {"installerExitCode", exit} });
                    VerifyNewKeys(before, afterInstall, installedTags);
                    LastReport = Finished(before, afterInstall, result, true, false);
                    return LastReport;
                }
                hosts = Find(system, afterInstall, architecture);
                Need(hosts.Count > 0, "Python setup completed, but ChemDraw's script host could not be verified. Restart the installer after completing Python setup.");
                bool ownTarget = false;
                foreach (var host in hosts) if (Same((string)host["executable"], Path.Combine(target, "python.exe"))) ownTarget = true;
                Need(ownTarget, "Python setup did not register the verified standard host destination.");
                result.Add(new Dictionary<string,object> { {"architecture", architecture}, {"action", "official-per-user-host-installed"}, {"installerSHA256", expected}, {"targetDirectory", target}, {"installerExitCode", exit}, {"hosts", hosts} });
            }
            Dictionary<string,string> after = system.Snapshot();
            VerifyExistingUnchanged(before, after);
            VerifyNewKeys(before, after, installedTags);
            LastReport = Finished(before, after, result, restart, true);
            return LastReport;
            } catch (Exception error) {
                progress["error"] = error.Message;
                try { progress["afterRegistry"] = system.Snapshot(); } catch (Exception inspectError) { progress["afterRegistryError"] = inspectError.Message; }
                throw;
            }
        }
        private static void VerifyNewKeys(Dictionary<string,string> before, Dictionary<string,string> after, HashSet<string> installedTags) {
            foreach (var entry in after) if (!before.ContainsKey(entry.Key)) {
                bool permitted = false;
                // InstallAllUsers=0 may add only the current user's tag. HKCU
                // Python keys can be shared across 32/64 views, so both views
                // are permitted, but no new HKLM key is ever expected.
                if (installedTags.Count > 0) foreach (string view in Views) {
                    string root = Root("HKCU", view);
                    if (entry.Key == root) permitted = true;
                    foreach (string tag in installedTags) if (entry.Key == root + "\\" + tag || entry.Key.StartsWith(root + "\\" + tag + "\\", StringComparison.OrdinalIgnoreCase)) permitted = true;
                }
                Need(permitted, "Python setup introduced an unexpected Python registration. Scheme Grid commands were not installed; see the installation report.");
            }
        }
        private static Dictionary<string,object> Finished(Dictionary<string,string> before, Dictionary<string,string> after, List<Dictionary<string,object>> result, bool restart, bool ready) {
            return new Dictionary<string,object> {
                {"ok", true}, {"ready", ready}, {"hosts", result}, {"rebootRequired", restart}, {"restartComputerRequired", restart}, {"restartChemDrawRequired", true},
                {"existingPythonRegistrationsUnchanged", true}, {"fileAssociationsRequested", false}, {"pathChangesRequested", false}, {"pythonLauncherRequested", false},
                {"registryScope", @"HKCU/HKLM, Registry32/Registry64: Software\Python\PythonCore only"},
                {"beforeRegistry", before}, {"afterRegistry", after}
            };
        }
    }

    internal sealed class WindowsPythonHostSystem : IPythonHostSystem {
        public string LocalApplicationData { get { return Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData); } }
        private static void Need(bool condition, string message) { if (!condition) throw new InvalidOperationException(message); }
        public bool DirectoryExists(string path) { return Directory.Exists(path); }
        public string Digest(string path) { using (var sha = SHA256.Create()) using (var stream = File.OpenRead(path)) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant(); }
        public Dictionary<string,string> Snapshot() {
            var result = new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
            foreach (string hive in PythonHostProvision.Hives) foreach (string view in PythonHostProvision.Views) {
                RegistryHive h = hive == "HKCU" ? RegistryHive.CurrentUser : RegistryHive.LocalMachine;
                RegistryView v = view == "32" ? RegistryView.Registry32 : RegistryView.Registry64;
                using (var root = RegistryKey.OpenBaseKey(h, v)) using (var core = root.OpenSubKey(PythonHostProvision.Core, false))
                    if (core != null) ReadKey(core, PythonHostProvision.Root(hive, view), result, 0);
            }
            return result;
        }
        private static void ReadKey(RegistryKey key, string identity, Dictionary<string,string> result, int depth) {
            Need(depth <= 10 && result.Count < 4096, "Python registrations are too large for a bounded installer check.");
            var values = new SortedDictionary<string,string>(StringComparer.Ordinal);
            string[] names = key.GetValueNames(); Array.Sort(names, StringComparer.Ordinal);
            foreach (string name in names) {
                object value = key.GetValue(name, null, RegistryValueOptions.DoNotExpandEnvironmentNames);
                string encoded = key.GetValueKind(name).ToString() + ":" + PythonHostProvision.Json.Serialize(value);
                Need(encoded.Length <= 65536, "A Python registry value is too large for a bounded installer check.");
                values.Add(name, encoded);
            }
            result.Add(identity, PythonHostProvision.EncodeValues(values));
            string[] children = key.GetSubKeyNames(); Array.Sort(children, StringComparer.Ordinal);
            foreach (string child in children) using (var next = key.OpenSubKey(child, false)) {
                Need(next != null, "A Python registration changed while being read. Retry after other installers finish.");
                ReadKey(next, identity + "\\" + child, result, depth + 1);
            }
        }
        private static string Quote(string value) {
            var result = new StringBuilder("\""); int slash = 0;
            foreach (char c in value) { if (c == '\\') { slash++; continue; } if (c == '"') { result.Append('\\', slash * 2 + 1); result.Append('"'); slash=0; continue; } result.Append('\\', slash); slash=0; result.Append(c); }
            result.Append('\\', slash * 2); result.Append('"'); return result.ToString();
        }
        private static int PeBits(string executable) {
            using (var stream = File.OpenRead(executable)) using (var reader = new BinaryReader(stream)) {
                Need(stream.Length > 256 && reader.ReadUInt16() == 0x5a4d, "Python host is not a valid Windows executable.");
                stream.Position=0x3c; int offset=reader.ReadInt32(); Need(offset >= 64 && offset < stream.Length - 6, "Python host PE header is invalid.");
                stream.Position=offset; Need(reader.ReadUInt32() == 0x00004550, "Python host PE signature is invalid.");
                ushort machine=reader.ReadUInt16(); Need(machine == 0x014c || machine == 0x8664, "Python host architecture is unsupported.");
                return machine == 0x014c ? 32 : 64;
            }
        }
        public Dictionary<string,object> Probe(string executable, string architecture, string tag) {
            Need(File.Exists(executable), "Registered python.exe is missing.");
            int bits = architecture == "x86" ? 32 : 64;
            Need(PeBits(executable) == bits, "Registered Python has a different executable architecture.");
            string source = "import ctypes,hashlib,json,pathlib,struct,subprocess,sys,xml.etree.ElementTree;print(json.dumps({'ok':True,'executable':sys.executable,'major':sys.version_info[0],'minor':sys.version_info[1],'bits':struct.calcsize('P')*8,'version':sys.version.split()[0],'isolated':bool(sys.flags.isolated),'siteDisabled':bool(sys.flags.no_site)}))";
            var start = new ProcessStartInfo(executable, "-I -B -S -c " + Quote(source));
            start.UseShellExecute=false; start.CreateNoWindow=true; start.WindowStyle=ProcessWindowStyle.Hidden;
            start.RedirectStandardOutput=true; start.RedirectStandardError=true;
            string output=null, error=null;
            using (var child = Process.Start(start)) {
                var stdout = child.StandardOutput.ReadToEndAsync(); var stderr = child.StandardError.ReadToEndAsync();
                if (!child.WaitForExit(15000)) { child.Kill(); throw new InvalidOperationException("Registered Python did not complete its read-only standard-library check."); }
                output=stdout.Result; error=stderr.Result;
                Need(child.ExitCode == 0 && output.Length <= 8192 && error.Length <= 8192, "Registered Python failed its isolated standard-library check.");
            }
            var probe=PythonHostProvision.Json.Deserialize<Dictionary<string,object>>(output);
            Need(probe != null && probe.ContainsKey("ok") && Convert.ToBoolean(probe["ok"]), "Registered Python did not produce a valid health report.");
            string expectedVersion=tag.EndsWith("-32", StringComparison.Ordinal) ? tag.Substring(0, tag.Length-3) : tag;
            Need(Convert.ToInt32(probe["major"]) == 3 && "3." + Convert.ToInt32(probe["minor"]) == expectedVersion, "Registered Python version does not match its registration.");
            Need(Convert.ToInt32(probe["bits"]) == bits && PythonHostProvision.Same((string)probe["executable"], executable), "Registered Python runtime identity differs from its executable.");
            return probe;
        }
        public void VerifyOfficialInstaller(string path, string architecture) {
            Need(File.Exists(path), "The bundled Python installer is missing.");
            var info=FileVersionInfo.GetVersionInfo(path);
            Need(info.ProductName != null && info.ProductName.IndexOf("Python", StringComparison.OrdinalIgnoreCase) >= 0 && info.ProductMajorPart == 3 && info.ProductMinorPart == 14, "The prerequisite is not the bundled Python3.14 installer.");
            // The payload manifest pins the complete signed executable's bytes.
            // Also require its embedded PSF signing certificate; build-time trust
            // validation of these same bytes is recorded in package provenance.
            using (var certificate=new X509Certificate2(X509Certificate.CreateFromSignedFile(path)))
                Need(certificate.Subject.IndexOf("Python Software Foundation", StringComparison.OrdinalIgnoreCase) >= 0, "The Python prerequisite lacks its expected PSF publisher certificate.");
            string expected=architecture == "x86" ? "python-3.14.10.exe" : "python-3.14.10-amd64.exe";
            Need(String.Equals(Path.GetFileName(path), expected, StringComparison.OrdinalIgnoreCase), "The Python prerequisite filename does not match the pinned architecture.");
        }
        public int Install(string path, string targetDirectory) {
            string args="/quiet /norestart InstallAllUsers=0 Include_exe=1 Include_lib=1 Include_dev=0 Include_doc=0 Include_test=0 Include_tcltk=0 Include_pip=0 Include_tools=0 Include_launcher=0 InstallLauncherAllUsers=0 AssociateFiles=0 PrependPath=0 AppendPath=0 Shortcuts=0 CompileAll=0 TargetDir=" + Quote(targetDirectory);
            var start=new ProcessStartInfo(path,args); start.UseShellExecute=false; start.CreateNoWindow=true; start.WindowStyle=ProcessWindowStyle.Hidden;
            using(var installer=Process.Start(start)) {
                // Never kill an in-progress Windows installer. If it is slow,
                // leave it to finish and stop before registering native commands.
                if(!installer.WaitForExit(300000)) throw new InvalidOperationException("Official Python setup is still running. Let it finish, then run Scheme Grid setup again.");
                return installer.ExitCode;
            }
        }
    }
}

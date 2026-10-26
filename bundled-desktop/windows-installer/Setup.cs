using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace SchemeGridSetup {
    public sealed class PayloadFile { public string path; public string sha256; public long size; }
    public sealed class PayloadManifest { public string kind; public string version; public string entrypoint; public PayloadFile[] files; }
    public sealed class InstallResult { public bool ok; public string destination; public string version; public int files; public string backup; public string message; }

    internal static class SetupEngine {
        const string Kind = "schemegrid-desktop";
        const string Marker = "schemegrid-desktop-installation.json";
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 32 * 1024 * 1024 };

        internal static Stream Resource(string name) {
            Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name);
            if (stream == null) throw new InvalidDataException("This installer is incomplete. Download the complete installer again.");
            return stream;
        }

        internal static PayloadManifest Manifest() {
            PayloadManifest manifest;
            using (Stream stream = Resource("payload-manifest.json"))
            using (StreamReader reader = new StreamReader(stream, Encoding.UTF8, true)) manifest = Json.Deserialize<PayloadManifest>(reader.ReadToEnd());
            if (manifest == null || manifest.kind != Kind || String.IsNullOrWhiteSpace(manifest.version) || manifest.files == null || manifest.files.Length < 3) throw new InvalidDataException("The installer file list is invalid.");
            ValidateRelative(manifest.entrypoint);
            if (!manifest.entrypoint.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("The application entry point is invalid.");
            return manifest;
        }

        static string ValidateRelative(string relative) {
            if (String.IsNullOrEmpty(relative) || Path.IsPathRooted(relative) || relative.IndexOf(':') >= 0 || relative.IndexOf('\0') >= 0) throw new InvalidDataException("The installer contains an unsafe filename.");
            string normalized = relative.Replace('/', '\\');
            string[] segments = normalized.Split('\\');
            foreach (string segment in segments) {
                if (String.IsNullOrEmpty(segment) || segment == "." || segment == ".." || segment.EndsWith(" ") || segment.EndsWith(".") || segment.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0) throw new InvalidDataException("The installer contains an unsafe filename.");
                string stem = segment.Split('.')[0].ToUpperInvariant();
                if (new[] { "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9" }.Contains(stem)) throw new InvalidDataException("The installer contains a reserved filename.");
            }
            return normalized;
        }

        static string Within(string root, string relative) {
            string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string target = Path.GetFullPath(Path.Combine(root, ValidateRelative(relative)));
            if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("A file points outside its installation folder.");
            return target;
        }

        static void NoLinks(string path) {
            string current = Path.GetFullPath(path);
            while (!String.IsNullOrEmpty(current)) {
                if ((File.Exists(current) || Directory.Exists(current)) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new IOException("Linked installation locations are not supported. Ask lab IT to choose a local folder.");
                string parent = Path.GetDirectoryName(current);
                if (String.Equals(parent, current, StringComparison.OrdinalIgnoreCase)) break;
                current = parent;
            }
        }

        static string Hash(Stream source) {
            using (SHA256 sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(source)).Replace("-", "").ToLowerInvariant();
        }

        internal static int ValidatePayload(PayloadManifest manifest, string extractTo, Action<int,string> progress) {
            Dictionary<string, PayloadFile> expected = new Dictionary<string, PayloadFile>(StringComparer.OrdinalIgnoreCase);
            foreach (PayloadFile file in manifest.files) {
                string relative = ValidateRelative(file.path);
                if (file.size < 0 || file.size > 1024L * 1024 * 1024 || file.sha256 == null || file.sha256.Length != 64 || file.sha256.Any(c => !Uri.IsHexDigit(c)) || expected.ContainsKey(relative)) throw new InvalidDataException("The installer checksum list is invalid.");
                expected.Add(relative, file);
            }
            if (!expected.ContainsKey(ValidateRelative(manifest.entrypoint))) throw new InvalidDataException("The application is missing from its file list.");
            if (expected.ContainsKey(Marker)) throw new InvalidDataException("The payload cannot replace the installation marker.");
            HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            using (Stream stream = Resource("payload.zip"))
            using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read)) {
                foreach (ZipArchiveEntry entry in archive.Entries) {
                    if (entry.FullName.EndsWith("/")) continue;
                    if (((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000) throw new InvalidDataException("The Windows payload contains a linked file.");
                    string relative = ValidateRelative(entry.FullName);
                    PayloadFile file;
                    if (!seen.Add(relative) || !expected.TryGetValue(relative, out file) || file.size != entry.Length) throw new InvalidDataException("The installer archive does not match its file list.");
                    using (Stream source = entry.Open()) { if (!String.Equals(Hash(source), file.sha256, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("A bundled file failed its check. Download the installer again."); }
                    if (extractTo != null) {
                        string destination = Within(extractTo, relative);
                        Directory.CreateDirectory(Path.GetDirectoryName(destination));
                        using (Stream source = entry.Open()) using (FileStream output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None)) source.CopyTo(output);
                        using (FileStream installed = File.OpenRead(destination)) { if (!String.Equals(Hash(installed), file.sha256, StringComparison.OrdinalIgnoreCase)) throw new IOException("A copied file failed verification. The existing app has not been replaced."); }
                    }
                    progress((int)(seen.Count * 90L / expected.Count), "Getting Scheme Grid ready…");
                }
            }
            if (seen.Count != expected.Count) throw new InvalidDataException("The installer archive is incomplete.");
            return seen.Count;
        }

        static void CheckOwnedDestination(string destination) {
            NoLinks(destination);
            if (File.Exists(destination)) throw new IOException("A file already uses the installation folder name. Nothing was replaced.");
            if (!Directory.Exists(destination)) return;
            string markerPath = Path.Combine(destination, Marker);
            if (!File.Exists(markerPath)) throw new IOException("Another folder already uses the name SchemeGridDesktop. Nothing was replaced. Ask lab IT to review it.");
            NoLinks(markerPath);
            Dictionary<string, object> marker = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(markerPath));
            if (!marker.ContainsKey("kind") || Convert.ToString(marker["kind"]) != Kind) throw new IOException("This folder belongs to another application. Nothing was replaced.");
            foreach (string entry in Directory.EnumerateFileSystemEntries(destination)) NoLinks(entry);
        }

        internal static InstallResult Install(string requestedDestination, bool validateOnly, bool testMode, Action<int,string> progress) {
            PayloadManifest manifest = Manifest();
            if (validateOnly) return new InstallResult { ok = true, version = manifest.version, files = ValidatePayload(manifest, null, progress), message = "The bundled installer files passed verification. No files were installed." };
            string destination = Path.GetFullPath(requestedDestination);
            string parent = Path.GetDirectoryName(destination);
            if (String.IsNullOrWhiteSpace(parent) || destination == Path.GetPathRoot(destination)) throw new IOException("The installation location is invalid.");
            CheckOwnedDestination(destination);
            NoLinks(parent);
            Directory.CreateDirectory(parent);
            string stage = Path.Combine(parent, ".schemegrid-stage-" + Guid.NewGuid().ToString("N"));
            string backup = null;
            Directory.CreateDirectory(stage);
            int count = ValidatePayload(manifest, stage, progress);
            Dictionary<string, object> marker = new Dictionary<string, object> {
                { "kind", Kind }, { "version", manifest.version }, { "installedUtc", DateTime.UtcNow.ToString("o") }, { "entrypoint", manifest.entrypoint }, { "installationComplete", true }
            };
            File.WriteAllText(Path.Combine(stage, Marker), Json.Serialize(marker), new UTF8Encoding(false));
            // An upgrade keeps the previous marked folder; no recursive deletion occurs.
            if (Directory.Exists(destination)) {
                CheckOwnedDestination(destination);
                backup = Path.Combine(parent, "SchemeGridDesktop-previous-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N"));
                Directory.Move(destination, backup);
            }
            try { Directory.Move(stage, destination); }
            catch { if (backup != null && !Directory.Exists(destination)) Directory.Move(backup, destination); throw; }
            if (!testMode) {
                progress(95, "Adding your shortcut…");
                string programs = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                string shortcut = Path.Combine(programs, "Scheme Grid.lnk");
                // Never overwrite a pre-existing shortcut: the installed app is still ready to open.
                if (!File.Exists(shortcut)) CreateShortcut(shortcut, Within(destination, manifest.entrypoint), destination);
            }
            progress(100, "You’re ready!");
            return new InstallResult { ok = true, destination = destination, version = manifest.version, files = count, backup = backup, message = "Scheme Grid is installed. Everything it needs is included." };
        }

        static void CreateShortcut(string shortcut, string executable, string workingDirectory) {
            object shell = null, link = null;
            try {
                Type type = Type.GetTypeFromProgID("WScript.Shell");
                if (type == null) return;
                shell = Activator.CreateInstance(type);
                link = type.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { shortcut });
                Type linkType = link.GetType();
                linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { executable });
                linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { workingDirectory });
                linkType.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "Arrange your ChemDraw schemes" });
                linkType.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
            } finally {
                if (link != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(link);
                if (shell != null) System.Runtime.InteropServices.Marshal.ReleaseComObject(shell);
            }
        }

        internal static void SaveReport(string path, object report) { if (path != null) File.WriteAllText(path, Json.Serialize(report), new UTF8Encoding(false)); }
    }

    public sealed class SetupForm : Form {
        readonly Label title = new Label(), status = new Label();
        readonly ProgressBar progress = new ProgressBar();
        readonly Button done = new Button();
        InstallResult result;
        public SetupForm() {
            Text = "Install Scheme Grid"; ClientSize = new Size(440, 220); FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = false; StartPosition = FormStartPosition.CenterScreen;
            Font = new Font("Segoe UI", 10); BackColor = Color.White;
            title.Text = "Let’s get your schemes in shape."; title.Font = new Font("Segoe UI", 16, FontStyle.Bold); title.SetBounds(24, 24, 400, 38);
            status.Text = "Everything you need is included."; status.SetBounds(24, 74, 392, 44);
            progress.SetBounds(24, 130, 392, 12);
            done.Text = "Open Scheme Grid"; done.Enabled = false; done.SetBounds(242, 164, 174, 34);
            done.Click += delegate { if (result != null && result.ok) System.Diagnostics.Process.Start(Path.Combine(result.destination, SetupEngine.Manifest().entrypoint)); Close(); };
            Controls.AddRange(new Control[] { title, status, progress, done });
            Shown += delegate {
                Task.Factory.StartNew(delegate {
                    try {
                        string destination = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "SchemeGridDesktop");
                        result = SetupEngine.Install(destination, false, false, UpdateProgress);
                        BeginInvoke((Action)delegate { title.Text = "You’re ready!"; status.Text = result.message; done.Enabled = true; });
                    } catch (Exception ex) {
                        BeginInvoke((Action)delegate { title.Text = "Installation needs a hand."; status.Text = ex.Message; done.Text = "Close"; done.Enabled = true; });
                    }
                });
            };
        }
        void UpdateProgress(int value, string message) { if (!IsDisposed) BeginInvoke((Action)delegate { progress.Value = Math.Max(0, Math.Min(100, value)); status.Text = message; }); }
    }

    public static class Program {
        [STAThread]
        public static int Main(string[] args) {
            string reportPath = null, testDestination = null;
            bool validate = args.Contains("--validate-only");
            for (int i = 0; i < args.Length; i++) {
                if (args[i] == "--report" && i + 1 < args.Length) reportPath = args[++i];
                else if (args[i] == "--test-install" && i + 1 < args.Length) testDestination = args[++i];
            }
            if (validate || testDestination != null) {
                try {
                    InstallResult result = SetupEngine.Install(testDestination, validate, true, delegate { });
                    SetupEngine.SaveReport(reportPath, result);
                    return 0;
                } catch (Exception ex) { SetupEngine.SaveReport(reportPath, new InstallResult { ok = false, message = ex.Message }); return 1; }
            }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false); Application.Run(new SetupForm()); return 0;
        }
    }
}

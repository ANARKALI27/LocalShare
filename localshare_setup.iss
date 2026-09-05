; Inno Setup script for LocalShare.
;
; Requires Inno Setup (free): https://jrsoftware.org/isinfo.php
; Don't run this directly — use build_installer.bat, which builds
; LocalShare.exe first and then compiles this script automatically.
;
; IMPORTANT: keep MyAppVersion below in sync with APP_VERSION in
; app/version.py whenever you release a new build — the two are
; separate values (this file isn't Python) and won't sync themselves.

#define MyAppName "LocalShare"
#define MyAppVersion "3.0.0"
#define MyAppPublisher "ANARKALI"
#define MyAppExeName "LocalShare.exe"

[Setup]
AppId={{A6E1F2B4-3C9D-4E7A-9B2F-1234567890AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install to AppData\Local\Programs — no admin rights needed
; to install or run normally. (WebDAV specifically still needs the
; installed LocalShare.exe launched via "Run as administrator" — that's
; a runtime choice, unrelated to how it was installed.)
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; Lets the installer detect and gracefully close a running LocalShare
; instance before installing — needed for the in-app auto-update flow
; (a running .exe's file is locked; without this, launching the new
; installer over a still-open old version would just fail or hang).
CloseApplications=yes
CloseApplicationsFilter=LocalShare.exe
; Not using RestartApplications: it only actually relaunches an app
; that's registered via Windows' RegisterApplicationRestart API, which
; this app doesn't call — setting it wouldn't do anything real. The
; [Run] section below already offers to launch LocalShare after
; install finishes, which covers this without needing that API.
OutputDir=Output
OutputBaseFilename=LocalShareSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\LocalShare.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "packaging\windows\download_cloudflared.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Fetches cloudflared automatically so Internet/Global sharing works
; immediately without the user needing to separately install it via
; winget or find it themselves — previously the installer did nothing
; about this at all, and Global mode would just fail with a "not
; found" error until the user manually tracked it down. Genuinely
; non-fatal by design (see the script itself): a failed download here
; (no internet at install time, corporate firewall, GitHub
; unreachable, etc.) does NOT fail or block the LocalShare install —
; Local sharing works completely fine either way, and the app's
; existing not-found handling covers Global mode gracefully if this
; didn't get a chance to run successfully.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\download_cloudflared.ps1"" -DestDir ""{app}"""; StatusMsg: "Setting up Internet Sharing component (optional)..."; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

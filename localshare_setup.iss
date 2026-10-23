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
#define MyAppVersion "3.4.0"
#define MyAppPublisher "ANARKALI"
#define MyAppExeName "LocalShare.exe"
#define MyAppURL "https://github.com/ANARKALI27/LocalShare"

[Setup]
AppId={{A6E1F2B4-3C9D-4E7A-9B2F-1234567890AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Shown in Windows "Apps & features" / the installer's About box.
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
; File properties of LocalShareSetup.exe (needs four numbers).
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
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
; Installer's own icon and the icon Windows shows in Apps & features.
SetupIconFile=assets\localshare.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
; MIT license is shown as a page in the wizard.
LicenseFile=LICENSE
; LocalShare is a 64-bit build.
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; Windows 10 or newer (the Python 3.13 runtime bundled in the build needs it).
MinVersion=10.0
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; recursesubdirs + createallsubdirs: onedir mode produces a whole
; folder (LocalShare.exe plus its supporting DLLs/_internal folder),
; not a single file — see localshare.spec for why this changed from
; onefile. Source ends in \* to copy the CONTENTS of dist\LocalShare\
; into {app}, not a nested LocalShare\ subfolder inside {app}.
Source: "dist\LocalShare\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; "Launch at startup" (Settings) writes a per-user Run-key value named
; LocalShare. Without this line, uninstalling would leave that entry
; behind, pointing at an exe that no longer exists. ValueType none = the
; installer never creates it, it only removes it on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "{#MyAppName}"; ValueType: none; Flags: dontcreatekey uninsdeletevalue

[Run]
; Internet/Global sharing uses Cloudflare's cloudflared, which LocalShare
; downloads by itself the first time Global mode is used — nothing to
; install here.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

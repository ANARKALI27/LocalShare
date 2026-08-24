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
#define MyAppVersion "1.0.0"
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

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

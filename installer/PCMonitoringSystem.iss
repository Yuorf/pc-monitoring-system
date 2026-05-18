#define AppName "PC Monitoring System"
#define AppVersion "0.1.0"
#define AppExeName "PCMonitoringSystem.exe"
#define AppPublisher "PC Monitoring System"
#define AppSourceDir "..\dist\PCMonitoringSystem"
#define AppOutputDir "..\dist\installer"
#define AppOutputBaseName "PCMonitoringSystemSetup-0.1.0"

[Setup]
AppId={{C26A6438-7B7E-4A54-8B75-D9D10D27419E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\PC Monitoring System
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#AppOutputDir}
OutputBaseFilename={#AppOutputBaseName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "_internal\backend\data\*.db,_internal\backend\data\*.db-*,_internal\backend\data\*.sqlite,_internal\backend\data\*.sqlite3"
[Icons]

Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

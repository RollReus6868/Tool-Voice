; Inno Setup script - per-user install, no admin rights needed.
; Build:  ISCC.exe /DAppVersion=2.1.0 installer\TTSCloneStudio.iss
; Expects PyInstaller onedir output in dist\TTSCloneStudio\

#ifndef AppVersion
  #error "Pass /DAppVersion=x.y.z to ISCC"
#endif

[Setup]
AppId={{8F3C2A51-6B7D-4E2F-9C1A-2D5E7B9F0A13}
AppName=TTS Clone Studio
AppVersion={#AppVersion}
AppVerName=TTS Clone Studio {#AppVersion}
AppPublisher=TTS Clone Studio
DefaultDirName={localappdata}\Programs\TTS Clone Studio
DefaultGroupName=TTS Clone Studio
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=TTSCloneStudio-{#AppVersion}-windows-setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\TTSCloneStudio.exe
UninstallDisplayName=TTS Clone Studio
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName=TTS Clone Studio

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; wipe files of the previous version so stale libraries never mix with new ones
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\TTSCloneStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\TTS Clone Studio"; Filename: "{app}\TTSCloneStudio.exe"
Name: "{autodesktop}\TTS Clone Studio"; Filename: "{app}\TTSCloneStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TTSCloneStudio.exe"; Description: "Launch TTS Clone Studio"; Flags: nowait postinstall skipifsilent

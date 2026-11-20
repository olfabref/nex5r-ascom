; Inno Setup 6 script of the Alpaca Server installer for Windows (ADR 0002).
;
;     ISCC.exe /DAppVersion=X.Y.Z alpaca-server\installer\nex5r-ascom.iss
;
; Wraps the PyInstaller bundle (installer\nex5r-ascom.spec, in alpaca-server\dist\nex5r-ascom) into
; alpaca-server\dist\nex5r-ascom-setup.exe, the installer attached to every Release.
;
; - Per user, no admin rights: installed in %LOCALAPPDATA%\Programs\nex5r-ascom.
; - Starts at login through a shortcut in the user's Startup folder (removed by the uninstaller).
; - Never touches %APPDATA%\nex5r-ascom (config.toml): a reinstall, an Update or an uninstall keeps it.
; - Silent mode, used by the Update:  nex5r-ascom-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
;   It stops a running server first, and starts the new one at the end (also in silent mode).
; - Not signed: Windows SmartScreen warns on first launch (see alpaca-server/README.md).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppExe "nex5r-ascom.exe"

[Setup]
AppId={{6F3C2B8E-5D1A-4E7B-9C0F-2A8D4B6E1F35}
AppName=nex5r-ascom Alpaca Server
AppVersion={#AppVersion}
AppVerName=nex5r-ascom Alpaca Server {#AppVersion}
AppPublisher=nex5r-ascom
AppPublisherURL=https://github.com/olfabref/nex5r-ascom
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\nex5r-ascom
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=nex5r-ascom-setup
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName=nex5r-ascom Alpaca Server
; The running server is stopped in PrepareToInstall: no Restart Manager prompt
CloseApplications=no
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[InstallDelete]
; Files of the previous version that the new bundle no longer has
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\nex5r-ascom\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userstartup}\nex5r-ascom Alpaca Server"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{userprograms}\nex5r-ascom Alpaca Server"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"

[Run]
; No skipifsilent: the silent install of an Update restarts the server
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Description: "Start the Alpaca Server now"; Flags: nowait postinstall

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "StopServer"

[UninstallDelete]
; The log (alpyca.log and its rotations), written in the working folder
Type: files; Name: "{app}\alpyca.log*"

[Code]
procedure StopServer();
var
  ResultCode: Integer;
begin
  { Exits with 128 when no server runs: nothing to do then }
  if Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE,
          ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    Sleep(1000);   { let Windows release the files of the stopped process }
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopServer();
  Result := '';
end;

; SCC Broadcast Engine installer (Inno Setup 6).
;
; The installer doesn't carry the app: it downloads the latest release from
; GitHub while installing, so the same SCC-Broadcast-Engine-Setup.exe always
; installs the newest version. Installs to C:\SCC Broadcast Engine by default
; (the folder can be changed on the "Select Destination Location" page; no
; admin rights needed for C:\), adds a desktop shortcut, and keeps the data
; folder (every part's settings, graphics and HUDs) when run again over an
; existing install.
;
; Build:  ISCC.exe /DAppVersion=1.0.1 installer\SCC-Broadcast-Engine.iss
; (the GitHub Actions workflow does this for every release)

#ifndef AppVersion
  #define AppVersion "1.0"
#endif
#define AppName "SCC Broadcast Engine"
#define Repo "owenbparker/SCCBroadcastEngine"
#define ZipName "SCCBroadcastEngine-windows.zip"
#define ExeName "SCCBroadcastEngine.exe"

[Setup]
AppId={{8E1F4C2A-7B3D-4E59-A6C1-2D9F0B7E5A13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName}
AppPublisher=St. Clair Saints
AppPublisherURL=https://github.com/{#Repo}
DefaultDirName=C:\SCC Broadcast Engine
; The folder can be changed (and is remembered when Setup runs again).
DisableDirPage=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
; C:\ lets any user create a folder, and the app updates itself in place,
; so no administrator prompt is needed. A folder that needs one (Program
; Files) can be picked: Setup then asks for administrator rights.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=SCC-Broadcast-Engine-Setup
SetupIconFile=..\packaging\icon.ico
UninstallDisplayIcon={app}\{#ExeName}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The app's files (unpacked from the download, so Setup doesn't track them).
; The data folder (settings, graphics, HUDs) is asked about separately.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\_update"
Type: files; Name: "{app}\{#ExeName}"
Type: files; Name: "{app}\version.txt"
Type: files; Name: "{app}\README.md"
Type: files; Name: "{app}\smoke-test.txt"

[Messages]
ReadyLabel2a=Setup will download the latest version of SCC Broadcast Engine from GitHub and install it.

[Code]
const
  ZipUrl = 'https://github.com/{#Repo}/releases/latest/download/{#ZipName}';

var
  DownloadPage: TDownloadWizardPage;
  Downloaded: Boolean;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading SCC Broadcast Engine',
    'Getting the latest version from GitHub...', nil);
end;

{ Downloads the latest release zip into Setup's temp folder. '' on success. }
function DownloadLatest: String;
begin
  Result := '';
  if Downloaded then
    Exit;
  try
    if WizardSilent then
      DownloadTemporaryFile(ZipUrl, '{#ZipName}', '', nil)
    else begin
      DownloadPage.Clear;
      DownloadPage.Add(ZipUrl, '{#ZipName}', '');
      DownloadPage.Show;
      try
        DownloadPage.Download;
      finally
        DownloadPage.Hide;
      end;
    end;
    Downloaded := True;
  except
    Result := 'Couldn''t download SCC Broadcast Engine from GitHub. Check the internet connection and try again.'
      + #13#10#13#10 + GetExceptionMessage;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Err: String;
begin
  Result := True;
  if CurPageID = wpReady then begin
    Err := DownloadLatest;
    if Err <> '' then begin
      SuppressibleMsgBox(Err, mbCriticalError, MB_OK, IDOK);
      Result := False;
    end;
  end;
end;

{ Runs a program without a window; returns its exit code, or -1 if it couldn't start. }
function RunHidden(const Exe, Params: String): Integer;
var
  Code: Integer;
begin
  if Exec(Exe, Params, '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Result := Code
  else
    Result := -1;
end;

{ Everything that can fail happens here, so a problem stops Setup cleanly
  with a message instead of leaving a half-installed app. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Tmp, App: String;
  Code, Size: Integer;
begin
  Result := DownloadLatest;  { silent installs skip the Ready page }
  if Result <> '' then
    Exit;
  Tmp := ExpandConstant('{tmp}');
  App := ExpandConstant('{app}');

  { Close the app if it's running so its files can be replaced. }
  RunHidden(ExpandConstant('{sys}\taskkill.exe'), '/IM {#ExeName} /F');
  Sleep(800);

  if FileSize(Tmp + '\{#ZipName}', Size) then
    Log('Downloaded ' + IntToStr(Size) + ' bytes');
  Code := RunHidden('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference=''Stop''; Expand-Archive -LiteralPath '''
    + Tmp + '\{#ZipName}'' -DestinationPath ''' + Tmp + '\new'' -Force"');
  if not FileExists(Tmp + '\new\{#ExeName}') then begin
    { Expand-Archive can stop without saying why (a Windows that won't load
      its module): Windows' own tar unpacks zips too. }
    Log('Expand-Archive gave code ' + IntToStr(Code) + ' and no app; unpacking with tar');
    ForceDirectories(Tmp + '\new');
    Code := RunHidden(ExpandConstant('{sys}\tar.exe'), '-xf "' + Tmp + '\{#ZipName}" -C "' + Tmp + '\new"');
  end;
  if (Code <> 0) or not FileExists(Tmp + '\new\{#ExeName}') then begin
    Result := 'Couldn''t unpack the download (code ' + IntToStr(Code) + ').';
    Exit;
  end;

  if not ForceDirectories(App) then begin
    Result := 'Couldn''t create ' + App + '.';
    Exit;
  end;
  { App files only: the data folder isn't in the download, so an
    existing install keeps it. }
  Code := RunHidden('robocopy.exe', '"' + Tmp + '\new\_internal" "' + App + '\_internal" /MIR /R:3 /W:1 /NFL /NDL /NJH /NJS /NP');
  if (Code < 0) or (Code >= 8) then begin
    Result := 'Copying files failed (robocopy ' + IntToStr(Code) + '). Is SCC Broadcast Engine still open?';
    Exit;
  end;
  Code := RunHidden('robocopy.exe', '"' + Tmp + '\new" "' + App + '" /XD _internal data _update /R:3 /W:1 /NFL /NDL /NJH /NJS /NP');
  if (Code < 0) or (Code >= 8) then
    Result := 'Copying files failed (robocopy ' + IntToStr(Code) + ').';
end;

function InitializeUninstall: Boolean;
begin
  RunHidden(ExpandConstant('{sys}\taskkill.exe'), '/IM {#ExeName} /F');
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DirExists(ExpandConstant('{app}')) then
    if SuppressibleMsgBox('Also delete your data (graphics, HUDs, logos and every setting)? It''s in the data folder.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    begin
      { Only the app's own data folder: the install folder may have been
        one with other things in it. }
      DelTree(ExpandConstant('{app}\data'), True, True, True);
      RemoveDir(ExpandConstant('{app}'));
    end;
end;

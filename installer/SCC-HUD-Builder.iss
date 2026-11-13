; SCC HUD Builder installer (Inno Setup 6).
;
; The installer doesn't carry the app: it downloads the latest release from
; GitHub while installing, so the same SCC-HUD-Builder-Setup.exe always installs
; the newest version. Installs to C:\SCC HUD Builder (no admin rights needed),
; adds a desktop shortcut, and keeps settings and your HUDs (the huds folder)
; when run again over an existing install.
;
; Build:  ISCC.exe /DAppVersion=1.0.15 installer\SCC-HUD-Builder.iss
; (the GitHub Actions workflow does this for every release)

#ifndef AppVersion
  #define AppVersion "1.0"
#endif
#define AppName "SCC HUD Builder"
#define Repo "owenbparker/HUD-Builder"
#define ZipName "HUDBuilder-windows.zip"

[Setup]
AppId={{2378728D-64F0-4200-A249-2BB1B7020AB7}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName}
AppPublisher=St. Clair Saints
AppPublisherURL=https://github.com/{#Repo}
DefaultDirName=C:\SCC HUD Builder
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
; C:\ lets any user create a folder, and the app updates itself in place,
; so no administrator prompt is needed.
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SCC-HUD-Builder-Setup
SetupIconFile=..\packaging\icon.ico
UninstallDisplayIcon={app}\HUDBuilder.exe
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\HUDBuilder.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\HUDBuilder.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\HUDBuilder.exe"; WorkingDir: "{app}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The app's files (unpacked from the download, so Setup doesn't track them).
; Settings and your HUDs are asked about separately.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\_update"
Type: files; Name: "{app}\HUDBuilder.exe"
Type: files; Name: "{app}\README.md"
Type: files; Name: "{app}\smoke-test.txt"

[Messages]
ReadyLabel2a=Setup will download the latest version of SCC HUD Builder from GitHub and install it to C:\SCC HUD Builder.

[Code]
const
  ZipUrl = 'https://github.com/{#Repo}/releases/latest/download/{#ZipName}';

var
  DownloadPage: TDownloadWizardPage;
  Downloaded: Boolean;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading SCC HUD Builder',
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
    Result := 'Couldn''t download SCC HUD Builder from GitHub. Check the internet connection and try again.'
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
  Code: Integer;
begin
  Result := DownloadLatest;  { silent installs skip the Ready page }
  if Result <> '' then
    Exit;
  Tmp := ExpandConstant('{tmp}');
  App := ExpandConstant('{app}');

  { Close HUD Builder if it's running so its files can be replaced. }
  RunHidden(ExpandConstant('{sys}\taskkill.exe'), '/IM HUDBuilder.exe /F');
  Sleep(800);

  Code := RunHidden('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '''
    + Tmp + '\{#ZipName}'' -DestinationPath ''' + Tmp + '\new'' -Force"');
  if (Code <> 0) or not FileExists(Tmp + '\new\HUDBuilder.exe') then begin
    Result := 'Couldn''t unpack the download (code ' + IntToStr(Code) + ').';
    Exit;
  end;

  if not ForceDirectories(App) then begin
    Result := 'Couldn''t create ' + App + '.';
    Exit;
  end;
  { App files only: config.json and the huds folder aren't in the
    download, so an existing install keeps them. }
  Code := RunHidden('robocopy.exe', '"' + Tmp + '\new\_internal" "' + App + '\_internal" /MIR /R:3 /W:1 /NFL /NDL /NJH /NJS /NP');
  if (Code < 0) or (Code >= 8) then begin
    Result := 'Copying files failed (robocopy ' + IntToStr(Code) + '). Is SCC HUD Builder still open?';
    Exit;
  end;
  Code := RunHidden('robocopy.exe', '"' + Tmp + '\new" "' + App + '" /XD _internal /R:3 /W:1 /NFL /NDL /NJH /NJS /NP');
  if (Code < 0) or (Code >= 8) then
    Result := 'Copying files failed (robocopy ' + IntToStr(Code) + ').';
end;

function InitializeUninstall: Boolean;
begin
  RunHidden(ExpandConstant('{sys}\taskkill.exe'), '/IM HUDBuilder.exe /F');
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DirExists(ExpandConstant('{app}')) then
    if SuppressibleMsgBox('Also delete your HUD Builder settings and every HUD you made (the huds folder)?',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      DelTree(ExpandConstant('{app}'), True, True, True);
end;

; The Windows installer for BetterMarkItDown (Inno Setup 6). Built by installer/build.py,
; which passes AppVersion, WheelFile, SourceDir and OutputDir (absolute paths):
;   ISCC /DAppVersion=1.6.0 /DWheelFile=bettermarkitdown-1.6.0-py3-none-any.whl
;        /DSourceDir=C:\...\build\installer /DOutputDir=C:\...\dist BetterMarkItDown.iss
;
; Per user, no administrator rights: the program goes to %LOCALAPPDATA%\Programs. Setup
; copies uv and the package, then runs install.ps1, which gives the program its own Python
; and libraries inside that folder (internet needed, about 500 MB). The person's library,
; settings and saved keys live elsewhere and stay on uninstall unless they ask otherwise;
; their converted files in Documents are never touched.

#ifndef AppVersion
  #error Build with installer/build.py, which defines AppVersion
#endif

[Setup]
AppId={{6B0E6F2A-3C41-4E7B-9A55-2F1D8B7C4E90}
AppName=BetterMarkItDown
AppVersion={#AppVersion}
AppVerName=BetterMarkItDown {#AppVersion}
AppPublisher=BetterMarkItDown contributors
AppPublisherURL=https://github.com/miguel-arias-sv/BetterMarkItDown
AppSupportURL=https://github.com/miguel-arias-sv/BetterMarkItDown/issues
DefaultDirName={localappdata}\Programs\BetterMarkItDown
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; RedirectionGuard (on by default) stops a process from following folder links (junctions)
; made by others, and the programs Setup starts inherit it. It guards installers that run
; with administrator rights; this one never has more rights than the person running it, so
; a link could gain nobody anything. Left on, it refuses the link uv makes for its Python
; version (error 448), and setup fails.
RedirectionGuard=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
LicenseFile={#SourceDir}\LICENSE.txt
; What the program sends, and where: shown before installing (SignPath's conditions ask for it).
InfoBeforeFile={#SourceDir}\privacy.txt
; File details, the same in every build of a version (also a SignPath condition).
VersionInfoProductName=BetterMarkItDown
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoDescription=BetterMarkItDown installer
VersionInfoCompany=BetterMarkItDown contributors
VersionInfoCopyright=MIT licence, BetterMarkItDown contributors
SetupIconFile={#SourceDir}\app.ico
UninstallDisplayIcon={app}\app.ico
UninstallDisplayName=BetterMarkItDown
OutputDir={#OutputDir}
OutputBaseFilename=BetterMarkItDown-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

[Messages]
SetupAppTitle=Install BetterMarkItDown
WelcomeLabel2=This installs BetterMarkItDown {#AppVersion}, which turns PDF, Word and PowerPoint files into Markdown, including what is in their pictures.%n%nIt needs an internet connection now, to download its own copy of Python and its libraries (about 500 MB). Nothing else on this computer is changed, and no administrator rights are needed.

[Tasks]
Name: "desktopicon"; Description: "Put a BetterMarkItDown icon on the desktop"; GroupDescription: "Shortcuts:"
Name: "addtopath"; Description: "Let terminals and AI agents run the bettermarkitdown command (adds it to your PATH)"; GroupDescription: "Command line:"
Name: "ocr"; Description: "Local OCR, for pages an AI service will not read (about 100 MB more)"; GroupDescription: "Optional parts:"
Name: "anthropic"; Description: "Claude (Anthropic) as an AI service"; GroupDescription: "Optional parts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\uv.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\{#WheelFile}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\app.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; An older version's package, so install.ps1 finds only this one.
Type: files; Name: "{app}\bettermarkitdown-*.whl"

[Icons]
Name: "{userprograms}\BetterMarkItDown"; Filename: "{app}\bin\bettermarkitdown-app.exe"; IconFilename: "{app}\app.ico"; Comment: "Convert documents to Markdown"
Name: "{userdesktop}\BetterMarkItDown"; Filename: "{app}\bin\bettermarkitdown-app.exe"; IconFilename: "{app}\app.ico"; Comment: "Convert documents to Markdown"; Tasks: desktopicon

[Run]
Filename: "{app}\bin\bettermarkitdown-app.exe"; Description: "Open BetterMarkItDown now"; Flags: postinstall nowait skipifsilent; Check: SetUpOK

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\cache"
Type: files; Name: "{app}\install.log"
Type: files; Name: "{app}\install.done"

[Code]
const
  EnvKey = 'Environment';

var
  InstallOK: Boolean;
  DeleteData: Boolean;
  Progress: TOutputMarqueeProgressWizardPage;

function SetUpOK: Boolean;
begin
  Result := InstallOK;
end;

function BinDir: String;
begin
  Result := ExpandConstant('{app}\bin');
end;

{ The person's PATH, in HKCU only: add our bin folder once, and on uninstall remove
  exactly that entry and nothing else. }
procedure AddToPath(Dir: String);
var
  Paths: String;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Paths) then
    Paths := '';
  if Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';') > 0 then
    exit;
  { RemoveFromPath takes out the entry and the ';' before it, so a PATH that ended with ';'
    gets one after the entry too, and comes back exactly as it was. }
  if Paths = '' then
    Paths := Dir
  else if Copy(Paths, Length(Paths), 1) = ';' then
    Paths := Paths + Dir + ';'
  else
    Paths := Paths + ';' + Dir;
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Paths);
end;

procedure RemoveFromPath(Dir: String);
var
  Paths: String;
  P: Integer;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Paths) then
    exit;
  P := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Paths) + ';');
  if P = 0 then
    exit;
  if P > 1 then
    Delete(Paths, P - 1, Length(Dir) + 1)    { the entry and the ';' before it }
  else
    Delete(Paths, 1, Length(Dir) + 1);       { the first entry and the ';' after it }
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Paths);
end;

{ Exit code 10 when the program could not be set up, so a silent install (and the release
  workflow's test) fails instead of reporting success. Called only when Setup finishes. }
function GetCustomSetupExitCode: Integer;
begin
  if InstallOK then
    Result := 0
  else
    Result := 10;
end;

{ BetterMarkItDown still open from this folder holds its Python's files, and an update
  cannot replace them ("Access is denied", os error 5). Find its programs, by where they
  run from, and close them after asking. Nothing else on the computer is touched. }
function PowerShellAbout(Action: String): Integer;
var
  Dir, Script: String;
begin
  Dir := ExpandConstant('{app}');
  StringChangeEx(Dir, '''', '''''', True);
  Script := '$p = @(Get-Process | Where-Object { $_.Path -like ''' + Dir + '\*'' }); ';
  if Action = 'stop' then
    Script := Script + '$p | Stop-Process -Force; Start-Sleep -Milliseconds 500; exit 0'
  else
    Script := Script + 'if ($p.Count) { exit 1 } else { exit 0 }';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
              '-NoProfile -NonInteractive -Command "' + Script + '"', '', SW_HIDE,
              ewWaitUntilTerminated, Result) then
    Result := 0;
end;

function CloseRunningCopy(Doing: String): Boolean;
begin
  Result := True;
  if not DirExists(ExpandConstant('{app}')) or (PowerShellAbout('check') = 0) then
    exit;
  if SuppressibleMsgBox('BetterMarkItDown is open. Setup closes it to ' + Doing + '.' + #13#10#13#10 +
      'Your files, library and settings are kept. If you are editing a page, save it first.',
      mbConfirmation, MB_OKCANCEL, IDOK) <> IDOK then
  begin
    Result := False;
    exit;
  end;
  PowerShellAbout('stop');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not CloseRunningCopy('update it') then
    Result := 'BetterMarkItDown is still open. Close it (Quit, at the top of its page), then run Setup again.';
end;

function InitializeUninstall: Boolean;
begin
  Result := CloseRunningCopy('remove it');
end;

function LastLine(FileName: String): String;
var
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  if not LoadStringsFromFile(FileName, Lines) then
    exit;
  for I := GetArrayLength(Lines) - 1 downto 0 do
    if Trim(Lines[I]) <> '' then
    begin
      Result := Trim(Lines[I]);
      exit;
    end;
end;

function Extras: String;
begin
  Result := '';
  if WizardIsTaskSelected('ocr') then
    Result := 'ocr';
  if WizardIsTaskSelected('anthropic') then
  begin
    if Result <> '' then
      Result := Result + ',';
    Result := Result + 'anthropic';
  end;
end;

procedure InitializeWizard;
begin
  Progress := CreateOutputMarqueeProgressPage('Setting up BetterMarkItDown',
    'Downloading its own Python and libraries. This takes a minute or two.');
end;

{ Run install.ps1 without waiting on it, so the progress page keeps moving: the script
  writes install.log as it goes and its exit code to install.done at the end, and Setup
  watches both. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode, Waited: Integer;
  Params, Done, Log, Line: String;
  Codes: TArrayOfString;
begin
  if CurStep <> ssPostInstall then
    exit;
  Done := ExpandConstant('{app}\install.done');
  Log := ExpandConstant('{app}\install.log');
  DeleteFile(Done);
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
            ExpandConstant('{app}\install.ps1') + '"';
  if Extras <> '' then
    Params := Params + ' -Extras "' + Extras + '"';
  ResultCode := -1;
  Progress.Show;
  try
    if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params,
            ExpandConstant('{app}'), SW_HIDE, ewNoWait, ResultCode) then
    begin
      Waited := 0;
      while (not FileExists(Done)) and (Waited < 30 * 60 * 1000) do
      begin
        Sleep(250);
        Waited := Waited + 250;
        Line := LastLine(Log);
        if Line <> '' then
          Progress.Msg2Label.Caption := Copy(Line, 1, 90);
        Progress.Animate;
      end;
      ResultCode := -1;
      Sleep(250);                              { let the script finish writing it }
      if LoadStringsFromFile(Done, Codes) and (GetArrayLength(Codes) > 0) then
        ResultCode := StrToIntDef(Trim(Codes[0]), -1);
    end;
    InstallOK := ResultCode = 0;
  finally
    Progress.Hide;
  end;
  if InstallOK then
  begin
    if WizardIsTaskSelected('addtopath') then
      AddToPath(BinDir);
  end
  else
  begin
    { The log's last line says what went wrong; guessing ("the internet") misled. }
    Line := LastLine(Log);
    if Line <> '' then
      Line := #13#10#13#10 + 'What went wrong: ' + Copy(Line, 1, 300);
    SuppressibleMsgBox('BetterMarkItDown could not finish setting up (code ' +
      IntToStr(ResultCode) + ').' + Line + #13#10#13#10 + 'Run this installer again to ' +
      'retry. All the details are in ' + Log + '.', mbError, MB_OK, IDOK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    RemoveFromPath(BinDir);
    DeleteData := (not UninstallSilent) and (MsgBox(
      'Also delete your BetterMarkItDown library, settings and saved API keys?' + #13#10#13#10 +
      'Your converted files in Documents\BetterMarkItDown are kept either way.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES);
    if DeleteData and FileExists(BinDir + '\bettermarkitdown.exe') then
      Exec(BinDir + '\bettermarkitdown.exe', 'key forget all', '', SW_HIDE,
           ewWaitUntilTerminated, ResultCode);
  end;
  if (CurUninstallStep = usPostUninstall) and DeleteData then
  begin
    DelTree(ExpandConstant('{localappdata}\BetterMarkItDown'), True, True, True);
    DelTree(ExpandConstant('{userappdata}\BetterMarkItDown'), True, True, True);
  end;
end;

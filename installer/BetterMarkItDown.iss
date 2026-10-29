; The Windows installer for BetterMarkItDown (Inno Setup 6). Built by installer/build.py,
; which passes AppVersion, WheelFile, SourceDir and OutputDir (absolute paths):
;   ISCC /DAppVersion=1.5.0 /DWheelFile=bettermarkitdown-1.5.0-py3-none-any.whl
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
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
LicenseFile={#SourceDir}\LICENSE.txt
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
  if (Paths <> '') and (Copy(Paths, Length(Paths), 1) <> ';') then
    Paths := Paths + ';';
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Paths + Dir);
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

procedure OnInstallLine(const S: String; const Error, FirstLine: Boolean);
begin
  SaveStringToFile(ExpandConstant('{app}\install.log'), S + #13#10, True);
  if Trim(S) <> '' then
    Progress.Msg2Label.Caption := Copy(Trim(S), 1, 90);
  Progress.Animate;
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

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Params: String;
begin
  if CurStep <> ssPostInstall then
    exit;
  DeleteFile(ExpandConstant('{app}\install.log'));
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
            ExpandConstant('{app}\install.ps1') + '"';
  if Extras <> '' then
    Params := Params + ' -Extras "' + Extras + '"';
  Progress.Show;
  try
    InstallOK := ExecAndLogOutput(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
                                  Params, ExpandConstant('{app}'), SW_HIDE,
                                  ewWaitUntilTerminated, ResultCode, @OnInstallLine)
                 and (ResultCode = 0);
  finally
    Progress.Hide;
  end;
  if InstallOK then
  begin
    if WizardIsTaskSelected('addtopath') then
      AddToPath(BinDir);
  end
  else
    SuppressibleMsgBox('BetterMarkItDown could not finish setting up (code ' +
      IntToStr(ResultCode) + '). Most often the internet connection dropped. Run this ' +
      'installer again to retry; the details are in ' + ExpandConstant('{app}\install.log') +
      '.', mbError, MB_OK, IDOK);
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

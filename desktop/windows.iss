; Per-user installation. User data is outside {app}.
[Setup]
AppId={{9D4214C0-CFD8-4D82-93A3-449B6DE6A26A}
AppName=NovelCraft
AppVersion=0.1.0
DefaultDirName={localappdata}\Programs\NovelCraft
DefaultGroupName=NovelCraft
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=NovelCraft-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\NovelCraft\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "build\assets\WebView2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{group}\NovelCraft"; Filename: "{app}\NovelCraft.exe"
Name: "{autodesktop}\NovelCraft"; Filename: "{app}\NovelCraft.exe"

[Run]
Filename: "{app}\NovelCraft.exe"; Description: "启动 NovelCraft"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  ExtractTemporaryFile('WebView2Setup.exe');
  if not Exec(ExpandConstant('{tmp}\WebView2Setup.exe'), '/silent /install', '',
              SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    Result := '无法准备窗口组件。请连接网络后重新运行安装程序。';
end;

; ============================================================
; Backtest ICT/SMC -- script de Inno Setup
;
; Genera un instalador tipo asistente (BacktestICT_Setup.exe) a
; partir del ejecutable ya compilado con PyInstaller.
;
; Requisitos:
;   1) Haber corrido antes packaging\build_exe.bat (debe existir
;      ..\dist\BacktestICT.exe).
;   2) Tener instalado Inno Setup (gratis):
;      https://jrsoftware.org/isinfo.php
;
; Uso:
;   Abre este archivo con "Inno Setup Compiler" y presiona
;   Build > Compile (o F9). El instalador queda en:
;      ..\installer_output\BacktestICT_Setup.exe
;   Ese es el archivo que le compartes a otras personas.
; ============================================================

#define MyAppName "Backtest ICT/SMC"
#define MyAppVersion "1.0"
#define MyAppPublisher "TraderMind MC"
#define MyAppExeName "BacktestICT.exe"

[Setup]
AppId={{9F1B7C2A-4E2D-4B0E-9C7A-2F5D6E8A1B30}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\installer_output
OutputBaseFilename=BacktestICT_Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el Escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\BacktestICT.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} ahora"; Flags: nowait postinstall skipifsilent

; Instalador do Sinopse Editor (Inno Setup 6, gratuito).
; Gerado por gerar_instalador.bat a partir da pasta dist\Sinopse Editor.
; Instala só para o usuário (sem pedir administrador), numa pasta onde o programa
; pode gravar os dados e se atualizar sozinho.

#ifndef Versao
  #define Versao "0.0"
#endif

[Setup]
AppId={{6F1B6C1E-3C55-4C1B-9B7E-5A1E0C2D9F41}
AppName=Sinopse Editor
AppVersion={#Versao}
AppVerName=Sinopse Editor {#Versao}
AppPublisher=KalidoraBR
AppPublisherURL=https://github.com/KalidoraBR/sinopse-editor
AppSupportURL=https://github.com/KalidoraBR/sinopse-editor/issues
AppUpdatesURL=https://github.com/KalidoraBR/sinopse-editor/releases
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Sinopse Editor
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Sinopse Editor.exe
SetupIconFile=icone.ico
OutputDir=dist
OutputBaseFilename=Sinopse-Editor-Setup-v{#Versao}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalho"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "dist\Sinopse Editor\Sinopse Editor.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Sinopse Editor\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Sinopse Editor"; Filename: "{app}\Sinopse Editor.exe"
Name: "{autodesktop}\Sinopse Editor"; Filename: "{app}\Sinopse Editor.exe"; Tasks: atalho

[Run]
Filename: "{app}\Sinopse Editor.exe"; Description: "Abrir o Sinopse Editor"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; Atualizando por cima: tira as peças antigas antes de copiar as novas.
Type: filesandordirs; Name: "{app}\_internal"

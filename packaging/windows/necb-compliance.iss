; Inno Setup script for the NECB Compliance CLI.
;
; Build:  rake windows:stage OPENSTUDIO_WINDOWS=<unpacked windows sdk>
;         iscc packaging\windows\necb-compliance.iss
;
; The payload carries its own OpenStudio, so this installer does NOT probe for
; one, gate on its version, or touch PATH or the registry. Everything it needs
; is under {app}.

#define AppName    "NECB Compliance"
#define AppVersion "0.1.0"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=CanmetENERGY, Natural Resources Canada
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename=necb-compliance-setup-{#AppVersion}
LicenseFile=stage\LICENSE-gems.txt
Compression=lzma2/max
SolidCompression=yes
; The bundled OpenStudio is 64-bit only.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; {autopf} needs elevation.
PrivilegesRequired=admin
DisableProgramGroupPage=yes
WizardStyle=modern

[Files]
Source: "stage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; A console pre-seeded with bin\ on PATH, opened in the user's Documents so
; relative --out paths land somewhere writable. This is why no global PATH
; edit is needed.
Name: "{group}\NECB Compliance (console)"; Filename: "{cmd}"; \
  Parameters: "/K ""set PATH={app}\bin;%PATH% && echo NECB Compliance - type necb-compliance --help"""; \
  WorkingDir: "{userdocs}"
Name: "{group}\Sample compliance run"; Filename: "{app}\samples\run-demo.cmd"; \
  WorkingDir: "{app}\samples"
Name: "{group}\Read me"; Filename: "{app}\README-windows.txt"

[Run]
Filename: "{app}\README-windows.txt"; Description: "Open the read me"; \
  Flags: postinstall shellexec skipifsilent nowait
Filename: "{app}\samples\run-demo.cmd"; Description: "Run the sample compliance check (a few minutes)"; \
  Flags: postinstall skipifsilent unchecked

[UninstallDelete]
; Only what we generate; a user's --out directories are theirs and are left.
Type: filesandordirs; Name: "{app}\gems"

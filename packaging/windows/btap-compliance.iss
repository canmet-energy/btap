; Inno Setup script for the NECB Compliance CLI.
;
; Build:  rake windows:stage OPENSTUDIO_WINDOWS=<unpacked windows sdk>
;         iscc packaging\windows\btap-compliance.iss
;
; Installs PER-USER and needs NO administrator rights: no UAC prompt, and it
; works on a locked-down corporate machine where the user cannot elevate. That
; is worth more than a machine-wide install for a demo, and it is only possible
; because the payload is self-contained — nothing goes to system32, nothing
; registers a service, nothing touches HKLM.
;
; The payload carries its own OpenStudio, so this installer does NOT probe for
; one, gate on its version, or touch PATH or the registry. Everything it needs
; is under {app}.

#define AppName    "BTAP Compliance"
#define AppVersion "0.1.0"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=CanmetENERGY, Natural Resources Canada
DefaultDirName={autopf}\{#AppName}
OutputBaseFilename=btap-compliance-setup-{#AppVersion}
LicenseFile=stage\LICENSE-gems.txt
Compression=lzma2/max
SolidCompression=yes
; The bundled OpenStudio is 64-bit only.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; No elevation. With `lowest`, {autopf} resolves to {localappdata}\Programs
; rather than C:\Program Files, so the default install location follows the
; privilege level automatically and DefaultDirName needs no special-casing.
; `dialog` still lets someone who DOES have admin choose a machine-wide install.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
WizardStyle=modern

[Files]
Source: "stage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; A console pre-seeded with bin\ on PATH, opened in the user's Documents so
; relative --out paths land somewhere writable. This is why no global PATH
; edit is needed.
Name: "{autoprograms}\NECB Compliance\NECB Compliance (console)"; Filename: "{cmd}"; \
  Parameters: "/K ""set PATH={app}\bin;%PATH% && echo NECB Compliance - type btap-compliance --help"""; \
  WorkingDir: "{userdocs}"
Name: "{autoprograms}\NECB Compliance\Sample compliance run"; Filename: "{app}\samples\run-demo.cmd"; \
  WorkingDir: "{app}\samples"
Name: "{autoprograms}\NECB Compliance\Read me"; Filename: "{app}\README-windows.txt"

[Run]
Filename: "{app}\README-windows.txt"; Description: "Open the read me"; \
  Flags: postinstall shellexec skipifsilent nowait
Filename: "{app}\samples\run-demo.cmd"; Description: "Run the sample compliance check (a few minutes)"; \
  Flags: postinstall skipifsilent unchecked

[UninstallDelete]
; Only what we generate; a user's --out directories are theirs and are left.
Type: filesandordirs; Name: "{app}\gems"

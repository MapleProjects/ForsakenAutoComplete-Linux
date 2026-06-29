; Script NSIS para ForsakenAC
; Autor: RicKStylesProyects

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

;--------------------------------
; Configuracion General
Name "ForsakenAC"
OutFile "ForsakenAC_Installer.exe"

; Instalar en Local AppData del usuario (No requiere admin)
InstallDir "$LOCALAPPDATA\ForsakenAC"
InstallDirRegKey HKCU "Software\ForsakenAC" "InstallPath"

RequestExecutionLevel user
SetCompressor /SOLID lzma

; Iconos
Icon "ForsakenAC.ico"
UninstallIcon "ForsakenAC.ico"

;--------------------------------
; Configuracion de la Interfaz
!define MUI_ABORTWARNING
!define MUI_ICON "ForsakenAC.ico"
!define MUI_UNICON "ForsakenAC.ico"

; Paginas
!define MUI_WELCOMEPAGE_TITLE "Bienvenido al instalador de ForsakenAC"
!define MUI_WELCOMEPAGE_TEXT "Este asistente le guiara en la instalacion de ForsakenAC.$\r$\n$\r$\nCreado por RicKStylesProyects.$\r$\n$\r$\nHaga clic en Siguiente para continuar."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES

; Finalizacion
!define MUI_FINISHPAGE_TITLE "Instalacion completada"
!define MUI_FINISHPAGE_TEXT "ForsakenAC se ha instalado correctamente."
!define MUI_FINISHPAGE_RUN "$INSTDIR\ForsakenAC.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Ejecutar ForsakenAC"

!insertmacro MUI_PAGE_FINISH

; Desinstalador
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Spanish"

;--------------------------------
; Seccion Principal
Section "ForsakenAC" SecMain

    ; Limpieza previa
    RMDir /r "$INSTDIR"
    
    SetOutPath "$INSTDIR"
    
    ; Copiar archivos del build (asegurate de haber compilado antes)
    File /r "dist\ForsakenAC\*.*"
    File "ForsakenAC.ico" 
    
    ; Crear uninst
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    
    ; Accesos directos
    CreateDirectory "$SMPROGRAMS\ForsakenAC"
    CreateShortcut "$SMPROGRAMS\ForsakenAC\ForsakenAC.lnk" "$INSTDIR\ForsakenAC.exe" "" "$INSTDIR\ForsakenAC.ico"
    CreateShortcut "$SMPROGRAMS\ForsakenAC\Desinstalar.lnk" "$INSTDIR\Uninstall.exe"
    CreateShortcut "$DESKTOP\ForsakenAC.lnk" "$INSTDIR\ForsakenAC.exe" "" "$INSTDIR\ForsakenAC.ico"
    
    ; Registro
    WriteRegStr HKCU "Software\ForsakenAC" "InstallPath" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ForsakenAC" "DisplayName" "ForsakenAC"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ForsakenAC" "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ForsakenAC" "DisplayIcon" "$INSTDIR\ForsakenAC.ico"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ForsakenAC" "Publisher" "RicKStylesProyects"
    
SectionEnd

;--------------------------------
; Seccion de Desinstalacion
Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$DESKTOP\ForsakenAC.lnk"
    RMDir /r "$SMPROGRAMS\ForsakenAC"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ForsakenAC"
    DeleteRegKey HKCU "Software\ForsakenAC"
SectionEnd

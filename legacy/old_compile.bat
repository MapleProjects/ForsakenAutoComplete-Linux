@echo off
echo ========================================================
echo  Compilando Flow Solver - Forsaken Edition
echo ========================================================
echo.
echo Limpiando builds anteriores...
rmdir /s /q build
rmdir /s /q dist
del /q *.spec

echo.
echo Ejecutando PyInstaller...
echo Incluyendo iconos e imagenes...

pyinstaller --onedir --noconsole ^
 --icon="ForsakenAC.ico" ^
 --add-data "VanityInst.png;." ^
 --add-data "ForsakenAC.ico;." ^
 --name "ForsakenAC" ^
 flow_solver.py

echo.
if exist "dist\ForsakenAC\ForsakenAC.exe" (
    echo ========================================================
    echo  COMPILACION EXITOSA!
    echo ========================================================
    echo  La carpeta del programa esta en 'dist\ForsakenAC'.
    echo.
    explorer dist\ForsakenAC
) else (
    echo ========================================================
    echo  ERROR DE COMPILACION
    echo ========================================================
)

pause

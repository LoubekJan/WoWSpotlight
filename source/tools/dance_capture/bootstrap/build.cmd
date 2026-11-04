@echo off
setlocal
if "%~1"=="" (
    echo Usage: %~nx0 path-to-output-dinput8.dll
    exit /b 2
)

set "output=%~f1"
set "out_dir=%~dp1"
set "vswhere=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%vswhere%" (
    echo Install Visual Studio with Desktop development with C++.
    exit /b 1
)
for /f "usebackq delims=" %%V in (`"%vswhere%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "vs=%%V"
if not defined vs (
    echo Visual Studio C++ x86 build tools were not found.
    exit /b 1
)
if not exist "%out_dir%" mkdir "%out_dir%" || exit /b 1
call "%vs%\Common7\Tools\VsDevCmd.bat" -no_logo -arch=x86 -host_arch=x64 || exit /b 1
cl /nologo /LD /O2 /MT /W4 /WX /DUNICODE /D_UNICODE /Fo"%out_dir%spotlight_bootstrap.obj" "%~dp0dinput8.c" /link /DEF:"%~dp0dinput8.def" /MACHINE:X86 /OUT:"%output%" /IMPLIB:"%out_dir%spotlight_bootstrap.lib"
exit /b %errorlevel%

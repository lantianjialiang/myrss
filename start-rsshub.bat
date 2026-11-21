@echo off
setlocal
set "ROOT=%~dp0"
set "NODE_DIR=%ROOT%node24"
set "PATH=%NODE_DIR%;%PATH%"
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "http_proxy="
set "https_proxy="
set "ALL_PROXY="
set "COREPACK_NPM_REGISTRY=https://registry.npmmirror.com"
cd /d "%ROOT%RSSHub"
echo.
echo   RSSHub  :  http://127.0.0.1:1200
echo   Health  :  http://127.0.0.1:1200/healthz
echo   Stop    :  Ctrl+C
echo.
call "%NODE_DIR%\corepack.cmd" pnpm start
echo.
echo RSSHub exited. Press any key to close.
pause >nul

$ErrorActionPreference = "Stop"

# Build EXE
pyinstaller --clean --noconfirm --onefile --name momentum_companion ..\src\momentum_companion\ui\__main__.py

# Smoke run with mock LLM (no network)
$env:LLM_MODE = "mock"
$exePath = "dist\momentum_companion.exe"
if (-Not (Test-Path $exePath)) {
    Write-Error "EXE not found at $exePath"
}
$proc = Start-Process -FilePath $exePath -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3
Try {
    Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue
} Catch {
    # ignore if already exited
}
exit 0

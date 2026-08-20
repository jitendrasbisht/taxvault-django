# Starts everything TaxVault needs for a live demo (Postgres, Redis, Django, the
# background worker, and a public Cloudflare tunnel) and prints/copies the share URL.
# Safe to re-run -- skips anything that's already running instead of starting duplicates.

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Test-ProcessRunning($commandlineMatch) {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'cloudflared.exe'" |
        Where-Object { $_.CommandLine -like $commandlineMatch } |
        Select-Object -First 1
}

Write-Host "== Docker (Postgres + Redis) ==" -ForegroundColor Cyan
$dockerUp = $false
try { docker info *>$null; if ($LASTEXITCODE -eq 0) { $dockerUp = $true } } catch {}
if (-not $dockerUp) {
    Write-Host "Starting Docker Desktop, this can take ~30s..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    $timeout = 60
    while ($timeout -gt 0) {
        Start-Sleep -Seconds 3; $timeout -= 3
        try { docker info *>$null; if ($LASTEXITCODE -eq 0) { break } } catch {}
    }
}
docker compose up -d | Out-Null
Write-Host "Postgres + Redis up." -ForegroundColor Green

$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

Write-Host "== Django server ==" -ForegroundColor Cyan
if (Test-ProcessRunning "*manage.py runserver*") {
    Write-Host "Already running, skipping."
} else {
    Start-Process -FilePath $python -ArgumentList "manage.py","runserver","0.0.0.0:8000" `
        -RedirectStandardOutput "server_out.log" -RedirectStandardError "server_err.log" -WindowStyle Hidden
    Write-Host "Started." -ForegroundColor Green
}

Write-Host "== Background worker (qcluster) ==" -ForegroundColor Cyan
if (Test-ProcessRunning "*manage.py qcluster*") {
    Write-Host "Already running, skipping."
    Write-Host "  Reminder: if you edited documents/pipeline.py, models.py, or extraction.py" -ForegroundColor Yellow
    Write-Host "  since this worker last started, kill it and re-run this script -- it does" -ForegroundColor Yellow
    Write-Host "  not hot-reload like the Django server does." -ForegroundColor Yellow
} else {
    Start-Process -FilePath $python -ArgumentList "manage.py","qcluster" `
        -RedirectStandardOutput "qcluster_out.log" -RedirectStandardError "qcluster_err.log" -WindowStyle Hidden
    Write-Host "Started." -ForegroundColor Green
}

Start-Sleep -Seconds 3

Write-Host "== Cloudflare tunnel ==" -ForegroundColor Cyan
if (Test-ProcessRunning "*cloudflared*tunnel*") {
    Write-Host "A tunnel is already running -- check cloudflared_err.log for its URL, or close" -ForegroundColor Yellow
    Write-Host "that cloudflared.exe process first if you want a fresh one." -ForegroundColor Yellow
} else {
    Remove-Item cloudflared_err.log -ErrorAction SilentlyContinue
    Start-Process -FilePath "cloudflared" -ArgumentList "tunnel","--url","http://localhost:8000" `
        -RedirectStandardError "cloudflared_err.log" -WindowStyle Hidden

    Write-Host "Waiting for tunnel URL..."
    $url = $null
    $timeout = 30
    while ($timeout -gt 0 -and -not $url) {
        Start-Sleep -Seconds 2; $timeout -= 2
        if (Test-Path cloudflared_err.log) {
            $match = Select-String -Path cloudflared_err.log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
            if ($match) { $url = $match.Matches[0].Value }
        }
    }

    if ($url) {
        $url | Set-Content TUNNEL_URL.txt
        try { $url | Set-Clipboard } catch {}
        Write-Host ""
        Write-Host "=================================================================" -ForegroundColor Green
        Write-Host " TaxVault is live at: $url" -ForegroundColor Green
        Write-Host " (copied to clipboard, also saved to TUNNEL_URL.txt)" -ForegroundColor Green
        Write-Host "=================================================================" -ForegroundColor Green
    } else {
        Write-Host "Could not detect the tunnel URL yet -- check cloudflared_err.log manually." -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Everything's running in the background. Closing this window is safe."
Read-Host "Press Enter to close"

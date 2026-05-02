# xpoz-cli installer for Windows.
#
# Usage (PowerShell):
#   iwr -useb https://raw.githubusercontent.com/XPOZpublic/xpoz-cli/main/install.ps1 | iex
#
# Environment overrides:
#   $env:XPOZ_VERSION       — release tag (default: "latest"), e.g. "v0.2.0"
#   $env:XPOZ_INSTALL_DIR   — install directory (default: "$env:LOCALAPPDATA\xpoz-cli")
#   $env:XPOZ_REPO          — GitHub repo (default: "XPOZpublic/xpoz-cli")

$ErrorActionPreference = 'Stop'

$Repo = if ($env:XPOZ_REPO) { $env:XPOZ_REPO } else { 'XPOZpublic/xpoz-cli' }
$Version = if ($env:XPOZ_VERSION) { $env:XPOZ_VERSION } else { 'latest' }
$InstallDir = if ($env:XPOZ_INSTALL_DIR) { $env:XPOZ_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'xpoz-cli' }

# Detect arch
$arch = switch ($env:PROCESSOR_ARCHITECTURE) {
  'AMD64' { 'amd64' }
  'ARM64' { 'arm64' }
  default { Write-Error "Unsupported architecture: $env:PROCESSOR_ARCHITECTURE"; exit 1 }
}

if ($arch -eq 'arm64') {
  Write-Error "No prebuilt binary for Windows arm64 yet. Install via 'pip install xpoz-cli' instead."
  exit 1
}

$asset = "xpoz-cli-windows-$arch.exe"
$urlBase = if ($Version -eq 'latest') {
  "https://github.com/$Repo/releases/latest/download"
} else {
  "https://github.com/$Repo/releases/download/$Version"
}

$tmpDir = Join-Path $env:TEMP "xpoz-install-$(Get-Random)"
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

try {
  Write-Host "Downloading $asset (version: $Version)..."
  $tmpBinary = Join-Path $tmpDir $asset
  Invoke-WebRequest -Uri "$urlBase/$asset" -OutFile $tmpBinary -UseBasicParsing

  Write-Host "Verifying integrity..."
  $tmpSums = Join-Path $tmpDir 'SHA256SUMS'
  $verified = $false
  try {
    Invoke-WebRequest -Uri "$urlBase/SHA256SUMS" -OutFile $tmpSums -UseBasicParsing
    $line = (Get-Content $tmpSums | Where-Object { $_ -match "  $([regex]::Escape($asset))$" }) | Select-Object -First 1
    if ($line) {
      $expected = ($line -split '\s+')[0].ToLower()
      $actual = (Get-FileHash -Algorithm SHA256 $tmpBinary).Hash.ToLower()
      if ($expected -ne $actual) {
        Write-Error "SHA256 mismatch for $asset (expected $expected, got $actual)"
        exit 1
      }
      Write-Host "  $actual  (verified)"
      $verified = $true
    }
  } catch {
    # SHA256SUMS not available on older releases — proceed with a warning.
  }
  if (-not $verified) {
    Write-Warning "Could not verify SHA256; continuing"
  }

  if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
  }
  $dest = Join-Path $InstallDir 'xpoz-cli.exe'
  Move-Item $tmpBinary $dest -Force
}
finally {
  if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
}

Write-Host ""
Write-Host "Installed: $dest"

# Add to user PATH if not already present
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$InstallDir*") {
  Write-Host ""
  Write-Warning "$InstallDir is not on your PATH."
  Write-Host "Add it permanently with:"
  Write-Host "  [Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';$InstallDir', 'User')"
  Write-Host "Then open a new terminal."
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  xpoz-cli auth login    # store your API key"
Write-Host "  xpoz-cli --help        # see commands"

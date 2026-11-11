$ErrorActionPreference = "Stop"
function Test-Command {
    param (
        [string]$command
    )
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        Write-Host "Please install $command"
        exit 1
    }
}


Test-Command git
Test-Command python3

# Exit when $env:ISSUE_NUMBER is not defined
if (-not $env:ISSUE_NUMBER) {
    Write-Host "ISSUE_NUMBER is not defined. Exiting script."
    exit 1
}

$userFolder = [System.Environment]::GetFolderPath('UserProfile')
$projectPath = Join-Path $userFolder "update-softwares"

New-Item -ItemType Directory -Force -Path $projectPath | Out-Null
Set-Location -Path $projectPath -ErrorAction Stop
$env:UPDATE_SOFTWARES_LOG_DIR = Join-Path $projectPath "logs"

# clone repository
if (-not (Test-Path "$projectPath\.git")) {
    git clone https://github.com/book000/update-softwares.git .
}
else {
    git pull
}

# install dependencies (native command failures are not caught by $ErrorActionPreference)
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to install requirements.txt"
    exit 1
}

python -m src $env:ISSUE_NUMBER

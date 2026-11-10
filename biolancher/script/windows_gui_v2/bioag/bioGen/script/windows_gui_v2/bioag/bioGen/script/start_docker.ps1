#Requires -RunAsAdministrator

# PowerShell Script: Install WSL and Docker in Ubuntu/Debian Distribution
# Reference: GitHub Gist - https://gist.github.com/dehsilvadeveloper/c3bdf0f4cdcc5c177e2fe9be671820c7

param(
    [string]$Mode = "interactive"
)

# Function to create a one-time scheduled task for post-reboot execution
function New-PostRebootTask {
    $taskName = "WSL-Docker-PostReboot"
    
    # Determine the script/EXE path
    if ($PSCommandPath) {
        $scriptPath = $PSCommandPath
    } else {
        $scriptPath = [Environment]::GetCommandLineArgs()[0]
        if (-not $scriptPath) {
            $scriptPath = $PWD.Path
        }
    }
    
    # Create action based on whether it's a .ps1 script or .exe
    if ($scriptPath -match '\.ps1$') {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File `"$scriptPath`" -Mode reboot"
    } else {
        $action = New-ScheduledTaskAction -Execute "`"$scriptPath`"" -Argument "-Mode reboot"
    }
    
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -User $env:USERNAME -Force -RunLevel Highest | Out-Null
    Write-Host "Scheduled task '$taskName' created to run script after reboot." -ForegroundColor Yellow
}

# Function to remove the post-reboot scheduled task
function Remove-PostRebootTask {
    $taskName = "WSL-Docker-PostReboot"
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    Write-Host "Scheduled task removed." -ForegroundColor Green
}

# Function to open uninstall guide
function Show-UninstallGuide {
    Start-Process "https://learn.microsoft.com/en-us/windows/wsl/faq#how-do-i-uninstall-a-wsl-distribution-"
    Write-Host "Opening WSL uninstall guide in your default browser." -ForegroundColor Yellow
}

# Windows Terminal Installation and Default Setup
Write-Host "Checking for Windows Terminal..." -ForegroundColor Yellow
$wtInstalled = $false
$changesMade = $false

if (Get-AppxPackage *WindowsTerminal*) {
    $wtInstalled = $true
    Write-Host "Windows Terminal is already installed." -ForegroundColor Green
} else {
    $response = Read-Host "Windows Terminal is not installed. Do you want to install it? (y/n)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        Write-Host "Installing Windows Terminal..." -ForegroundColor Yellow
        winget install --id Microsoft.WindowsTerminal --source msstore --accept-source-agreements --accept-package-agreements --silent
        if ($LASTEXITCODE -eq 0) {
            $wtInstalled = $true
            $changesMade = $true
            Write-Host "Windows Terminal installed successfully." -ForegroundColor Green
        } else {
            Write-Host "Windows Terminal installation failed. Proceeding without it." -ForegroundColor Red
        }
    } else {
        Write-Host "Skipping Windows Terminal installation." -ForegroundColor Yellow
    }
}

if ($wtInstalled) {
    # Set Windows Terminal as default terminal via registry
    $regPath = "HKCU:\Console\%%Startup"
    if (!(Test-Path $regPath)) {
        New-Item -Path $regPath -Force | Out-Null
    }
    Set-ItemProperty -Path $regPath -Name "DelegationConsole" -Value "{2EACA947-7F5F-4CFA-BA87-8F7FBEEFBE69}" -Type String -Force
    Set-ItemProperty -Path $regPath -Name "DelegationTerminal" -Value "{E12CFF52-A866-4C77-9A90-F570A7AA2C6B}" -Type String -Force
    $changesMade = $true
    Write-Host "Windows Terminal set as default terminal." -ForegroundColor Green
}

if ($changesMade) {
    $reopenResponse = Read-Host "To use the new default terminal, please close this PowerShell window and reopen the script in Windows Terminal. Do you want to continue anyway? (y/n)"
    if ($reopenResponse -ne 'y' -and $reopenResponse -ne 'Y') {
        Write-Host "Exiting. Please rerun after reopening in Windows Terminal." -ForegroundColor Yellow
        exit 0
    }
}

# Main menu for interactive mode
if ($Mode -eq "interactive") {
    Write-Host "=== WSL and Docker Management Script ===" -ForegroundColor Green
    Write-Host "1. Install WSL and Docker" -ForegroundColor Cyan
    Write-Host "2. Show Uninstall Guide" -ForegroundColor Cyan
    #Write-Host "Exit: Press Ctrl + C" -ForegroundColor Cyan
    Write-Host "Before you start, recommended read: https://learn.microsoft.com/en-us/windows/wsl/faq" -ForegroundColor Cyan
    $choice = Read-Host "Select an option (1 or 2)"
    
    if ($choice -eq "2") {
        Show-UninstallGuide
        exit 0
    } elseif ($choice -ne "1") {
        Write-Host "Invalid option. Exiting." -ForegroundColor Red
        exit 1
    }
    # Fall through to install mode
}

# Clean up any existing post-reboot task if in reboot mode or fresh run
if ($Mode -eq "reboot") {
    Remove-PostRebootTask
    Write-Host "Post-reboot execution detected. Continuing installation..." -ForegroundColor Green
} else {
    Remove-PostRebootTask  # Clean up if any leftover
}

# Step 2: Check WSL installation status
try {
    $wslStatus = wsl --status 2>$null
    if ($LASTEXITCODE -ne 0 -or $wslStatus -match "WSL 2 kernel is not installed") {
        Write-Host "WSL is not installed or not properly configured, installing WSL..." -ForegroundColor Yellow
        wsl --install --no-distribution
        if ($LASTEXITCODE -eq 0) {
            Write-Host "WSL installation initiated. A reboot is required." -ForegroundColor Yellow
            New-PostRebootTask
            Write-Host "Script will automatically continue after reboot. Please restart your computer now." -ForegroundColor Red
            Read-Host "Press Enter to reboot (or Ctrl+C to cancel)"
            Restart-Computer -Force
        } else {
            Write-Host "WSL installation failed. Please check manually." -ForegroundColor Red
            exit 1
        }
        exit 0
    }
    Write-Host "WSL is installed." -ForegroundColor Green
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Check distributions
$distros = wsl --list --verbose | Out-String
if ($distros -match "\*\s+(Ubuntu|Debian)") {
    $defaultDistro = ($distros | Select-String "\*\s+(\S+)").Matches.Groups[1].Value
    Write-Host "Default distribution is Debian-based: $defaultDistro, continuing installation." -ForegroundColor Green
} else {
    # Check if Ubuntu or Debian distribution is available
    $ubuntuAvailable = $distros -match "Ubuntu"
    $debianAvailable = $distros -match "Debian"
    if ($ubuntuAvailable -or $debianAvailable) {
        Write-Host "Ubuntu/Debian distribution detected, but default is not Debian-based." -ForegroundColor Yellow
        Write-Host "Available distributions:`n$distros" -ForegroundColor Yellow
        $response = Read-Host "Switch default distribution to Ubuntu? (y/n)"
        if ($response -eq 'y' -or $response -eq 'Y') {
            $newDefault = if ($ubuntuAvailable) { "Ubuntu" } else { "Debian" }
            wsl --set-default $newDefault
            Write-Host "Switched default distribution to $newDefault" -ForegroundColor Green
            $defaultDistro = $newDefault
        } else {
            Write-Host "Default distribution is not Debian-based, script stopping. Please switch default distribution manually." -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "No Debian-based distribution detected, installing Ubuntu..." -ForegroundColor Yellow
        wsl --install -d Ubuntu
        Start-Sleep -Seconds 10  # Wait for installation
        $defaultDistro = "Ubuntu"
        Write-Host "Ubuntu installation completed, default distribution: $defaultDistro" -ForegroundColor Green
    }
}

# If no distribution is installed, install Ubuntu
if (-not ($distros -match "Ubuntu|Debian")) {
    Write-Host "No Debian-based distribution installed, installing Ubuntu..." -ForegroundColor Yellow
    wsl --install -d Ubuntu
    Start-Sleep -Seconds 30  # Wait for installation and initialization
    $defaultDistro = "Ubuntu"
}

# Step 3: Install Docker in the default distribution (run as root)
Write-Host "Installing Docker in $defaultDistro..." -ForegroundColor Green

# Update packages and install dependencies
wsl -d $defaultDistro -u root bash -c "apt update && apt upgrade -y && apt install apt-transport-https ca-certificates curl software-properties-common -y"

# Add Docker GPG key
wsl -d $defaultDistro -u root bash -c "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg"

# Add Docker repository (using Ubuntu repo, as it's similar for Debian)
wsl -d $defaultDistro -u root bash -c "echo 'deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable' | tee /etc/apt/sources.list.d/docker.list > /dev/null"

# Update packages and install Docker
wsl -d $defaultDistro -u root bash -c "apt update && apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y"

# Start Docker service
wsl -d $defaultDistro -u root bash -c "systemctl start docker"

# Add current user to docker group (get current WSL user)
$currentUser = wsl -d $defaultDistro whoami
wsl -d $defaultDistro -u root bash -c "usermod -aG docker $currentUser"

# Verify installation
$dockerVersion = wsl -d $defaultDistro docker --version
Write-Host "Docker Version: $dockerVersion" -ForegroundColor Green

# Test running hello-world (may require exiting and re-entering WSL to apply group changes)
Write-Host "Testing Docker... (If it fails, please exit WSL and re-enter)" -ForegroundColor Yellow
try {
    wsl -d $defaultDistro docker run hello-world
} catch {
    Write-Host "Test failed (expected if group changes not applied). Run as root for now." -ForegroundColor Yellow
}

Write-Host "=== Installation Completed! ===" -ForegroundColor Green
Write-Host "Note: To use Docker, please exit WSL and log back in to apply user group changes." -ForegroundColor Yellow
Write-Host "To run as root: wsl -d $defaultDistro -u root docker run hello-world" -ForegroundColor Cyan
Write-Host "For uninstallation, run the script and select option 2." -ForegroundColor Cyan
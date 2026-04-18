#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Enables OpenSSH Server on a Windows Server 2016 VPS so the dashboard can be
    reached from a laptop via `ssh -L 8080:localhost:8080 Administrator@<vps>`.

.DESCRIPTION
    Idempotent. Re-running is safe. Does NOT:
      - open any port other than 22
      - install code-server, Cloudflare tunnel, or any third-party software
      - modify RDP, the Administrator password, or user accounts
      - touch the Multilogin service on :45001

.NOTES
    Run once via RDP as Administrator:
        powershell -ExecutionPolicy Bypass -File setup-vps-ssh.ps1
#>

$ErrorActionPreference = 'Stop'
$results = [ordered]@{}

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg"   -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "  [!!] $msg"   -ForegroundColor Yellow }

Write-Step 'Step 1: Check OpenSSH Server capability'
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*'
if ($cap.State -eq 'Installed') {
    Write-Ok "Already installed ($($cap.Name))"
    $results['openssh_installed'] = 'already present'
} else {
    Write-Host "  Installing $($cap.Name) ..."
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
    Write-Ok 'Installed'
    $results['openssh_installed'] = 'installed now'
}

Write-Step 'Step 2: Start sshd service'
$svc = Get-Service -Name sshd -ErrorAction SilentlyContinue
if (-not $svc) { throw 'sshd service not found after install.' }
if ($svc.Status -ne 'Running') {
    Start-Service sshd
    Write-Ok 'Started'
} else {
    Write-Ok 'Already running'
}
$results['sshd_status'] = (Get-Service sshd).Status

Write-Step 'Step 3: Set sshd to auto-start on boot'
Set-Service -Name sshd -StartupType Automatic
Write-Ok 'StartupType = Automatic'
$results['sshd_startup'] = (Get-Service sshd).StartType

Write-Step 'Step 4: Ensure inbound TCP 22 firewall rule exists'
$rule = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' `
        -DisplayName 'OpenSSH Server (sshd)' `
        -Enabled True -Direction Inbound -Protocol TCP `
        -Action Allow -LocalPort 22 | Out-Null
    Write-Ok 'Rule created'
    $results['firewall_22'] = 'created'
} else {
    if (-not $rule.Enabled) { Enable-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' }
    Write-Ok "Rule present (enabled=$($rule.Enabled))"
    $results['firewall_22'] = 'already present'
}

Write-Step 'Step 5: Check that Multilogin port 45001 is not exposed externally'
$ml = Get-NetFirewallPortFilter -Protocol TCP | Where-Object { $_.LocalPort -eq '45001' } |
      ForEach-Object { Get-NetFirewallRule -AssociatedNetFirewallPortFilter $_ -ErrorAction SilentlyContinue } |
      Where-Object { $_.Enabled -eq $true -and $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' }
if ($ml) {
    Write-Warn2 "Found inbound-allow rule(s) on :45001 — Multilogin should NOT be internet-facing."
    $ml | ForEach-Object { Write-Warn2 "  rule: $($_.DisplayName) [$($_.Name)]" }
    $results['port_45001'] = 'EXPOSED — review required'
} else {
    Write-Ok 'No inbound-allow rule for :45001 (good)'
    $results['port_45001'] = 'not exposed'
}

Write-Step 'Summary'
$results.GetEnumerator() | ForEach-Object { '  {0,-20} {1}' -f $_.Key, $_.Value }

Write-Host ''
Write-Host 'Next step — from your laptop:' -ForegroundColor Cyan
Write-Host '  ssh -L 8080:localhost:8080 Administrator@194.31.142.127'
Write-Host '  (then open http://localhost:8080 in your browser)'

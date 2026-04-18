# Remote access to the Vidora VPS

This folder contains the minimal setup needed to reach the Vidora dashboard
from a laptop without using Remote Desktop as the primary interface.

- **Dev happens on the laptop.** Claude Code edits code locally and pushes to
  GitHub. The VPS is a runtime, not an IDE.
- **The dashboard at `http://localhost:8080` is viewed through an SSH tunnel**
  from the laptop's browser. No ports other than 22 are exposed.
- **Multilogin keeps running inside the existing RDP session** in the
  background. The SSH tunnel is independent of RDP.

## One-time VPS setup

1. RDP into the VPS as `Administrator`.
2. Copy `setup-vps-ssh.ps1` to the VPS (or `git pull` on the VPS so it lands
   under `C:\vidora\scripts\`).
3. Open PowerShell **as Administrator** and run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\vidora\scripts\setup-vps-ssh.ps1
   ```

The script is idempotent — re-running it is safe. It will:

- install OpenSSH Server (if missing)
- start `sshd` and set it to auto-start on boot
- ensure an inbound-allow firewall rule on TCP 22
- warn if Multilogin's port 45001 is exposed to the internet (it shouldn't be)

## Daily workflow from the laptop

### View the dashboard in your laptop browser

```bash
ssh -L 8080:localhost:8080 Administrator@194.31.142.127
```

Leave that terminal open, then visit `http://localhost:8080` in your browser.
Traffic is forwarded over SSH; port 8080 is never exposed on the VPS's public
interface.

### Pull latest code onto the VPS

```bash
ssh Administrator@194.31.142.127
cd C:\vidora
git pull
```

Start the app the way you already do (Claude Code terminal or the dashboard's
start button). No service restart logic is automated — the app is still
started manually.

## What this setup does NOT do

- No code-server / browser IDE on the VPS.
- No Cloudflare Tunnel.
- No auto-deploy GitHub Action.
- No SSH key provisioning — password auth only, as requested.

Any of the above can be added later if the workflow outgrows the minimal
setup. For now, SSH + `git pull` + `ssh -L` covers everything.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `ssh: connect ... Connection refused` | `sshd` not running | `Get-Service sshd` on the VPS; `Start-Service sshd` |
| `ssh: ... Connection timed out` | Firewall / hosting provider blocking 22 | Check the hoster's network-level firewall; `setup-vps-ssh.ps1` only handles the Windows firewall |
| `Permission denied (password)` | Wrong password or account locked | Verify the `Administrator` password via RDP |
| `localhost:8080` shows nothing | App not running on VPS, or tunnel dropped | Confirm the dashboard is started on the VPS; reconnect `ssh -L` |

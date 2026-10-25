<div align="center">

# clean_webOS

**Take control of your LG TV — one guided step at a time.**

Community-led, multilingual setup for LG webOS. Root guidance, Homebrew installation, selected apps, remote-button remapping, Aerial screensaver, reversible ad filtering, and cautious management of apps and background services.

**English · Français · Español · Deutsch · Italiano · Português**  
**Release 5.1.0**

[Get started](#quick-start) · [Installation order](#the-guided-workflow) · [Safety](#important-safety-rules) · [Credits](#credits--thanks)

</div>

> [!IMPORTANT]
> **Independent community project.** Not affiliated with LG, Apple, or any upstream developers. Firmware and hardware behavior vary. The root procedure can leave a TV unbootable or cause loss of settings. **You are responsible for your own device.**
>
> clean_webOS is an **orchestrator**, not an original rooting exploit. It obtains third-party tools from their credited repositories, pins reviewed revisions where appropriate, and asks for permission before changes.

## What you get

| Feature | What happens | Root needed? |
|---|---|---|
| Guided security checks | Check SSH, local connectivity, current privileges; optional read-only test mode | No |
| **SlopBro** root guidance | Optional, separately confirmed upstream root attempt only if needed and the user states the TV is not already rooted | For the procedure, no |
| **Homebrew Channel** | Detect existing install; offer the official installer with verified package checksum | Rooted install path |
| **LG Input Hook** | Select and install from Homebrew, then configure shortcut buttons | Yes |
| **Aerial** | Install the Apple TV-style moving screensaver; choose resolution/autostart in the app | Yes |
| **YouTube AdFree** | Detect existing version and protect the LG official YouTube app from silent replacement | See Homebrew requirements |
| **LG Ad Killer** | Optional `ads`-only profile, persistent but reversible; full rollback menu item | Yes |
| **Glasshouse** | Web dashboard for installed apps, system tiles, background services, remote and privacy settings | Yes |
| **Installed applications** | Enumerate and optionally remove **removable** apps after individual confirmation | Yes + Glasshouse |
| **Built-in LG apps** | List and optionally **hide / unhide** system tiles without deleting system packages | Yes + Glasshouse |
| **Background services** | Disable/restore only known **optional** services offered by Glasshouse | Yes + Glasshouse |

**Not included:** silent app deletions, automatic firmware-update blocking, automatic removal of Developer Mode, unauthenticated Telnet setup, or installation of Auto Dev Token Refresh on a rooted TV. We never uninstall Jellyfin or Homebrew automatically.

## Quick start

### Linux / Bazzite / Fedora / Ubuntu / Debian

From a terminal on a computer connected to the **same local network** as the TV:

```bash
# Requires git to clone; alternatively download GitHub's ZIP and extract it.
git clone https://github.com/Maxime3d77/clean_webOS.git
cd clean_webOS
bash install.sh
```

The first screen asks you to **choose a language**, then **TEST / APPLY**, and finally the features you want. Arrow keys navigate, **Space** selects/deselects, **Enter** advances, **B** goes back and **Q** exits. If your terminal does not support the fullscreen interface, run `bash install.sh --text`.

To prefill your TV address:

```bash
bash install.sh --ip 192.168.1.24
```

For a **read-only check without menus**, useful when reporting problems:

```bash
python3 clean_webos.py --lang en --mode test --ip 192.168.1.24 --modules glasshouse,mapper,aerial,ads,system,services
```

**Do not run the launcher with `sudo`.** Root access to the TV is negotiated using SSH; your PC should stay under your ordinary user account. The installer's dependency helper **never runs `dnf` on Bazzite's immutable host**. If missing Python/OpenSSH binaries are detected on an Atomic installation, it offers to create an isolated Toolbx and install them there with consent. On ordinary Fedora/Debian Linux, system package installation is similarly opt-in.

### macOS

Install Python 3 (`brew install python` if needed) and use the same commands. OpenSSH is normally included. The curses menu may fall back to the numbered menu, which offers the same actions.

### Windows

Use **WSL2 with Ubuntu**, install `git`, `python3`, `openssh-client`, and run the Linux commands above from the WSL terminal. Windows native CMD/PowerShell is not yet supported directly.

## The guided workflow

The wizard always processes setup in dependency order. Nothing changes on the TV in **TEST** mode. **APPLY** requires another confirmation for each sensitive action.

### Step 1 — TV ownership, diagnosis and root (only if missing)

1. Turn on the TV and connect it to the same LAN as the PC. Identify its IPv4 address in the LG network settings; keep it stable with a DHCP reservation if practical.
2. Choose **TEST** first. The assistant checks local ports, the root SSH account and a safe inventory, when available.
3. **Already rooted?** Open Homebrew Channel → Settings and confirm **Root status: OK**, ideally after a full system reboot. Then enable **SSH** there. **Do not re-run SlopBro** on a TV that is already rooted.
4. **Not rooted?** The wizard can offer the **official SlopBro** tool by [throwaway96](https://github.com/throwaway96/slopbro). It downloads a pinned upstream revision and requires two explicit confirmations. The actual exploit executes **on your PC**, pairing with the TV only when you accept its on-screen prompt. Firmware compatibility is not guaranteed. **Read the upstream documentation before proceeding.**
5. **After a successful SlopBro root:** verify **Root status: OK** in Homebrew Channel, **uninstall the official LG Developer Mode app before rebooting** as advised by the SlopBro author, then use Homebrew's proper system reboot function and confirm the root status again. If root is lost, stop and diagnose instead of blindly retrying.

> **Credit:** SlopBro and the `jsserver` technique belong to **throwaway96** and the upstream contributors. Thanks also to **raws0kil** (`jsbro-autoroot`) and the webOS Homebrew community. SlopBro is licensed **AGPL-3.0-or-later**. This repository does **not** copy or relicense its source. See [CREDITS.md](CREDITS.md).

### Step 2 — Homebrew Channel and secure SSH

**SlopBro normally installs Homebrew Channel as part of rooting.** The wizard detects it first; if it is missing on an already rooted TV, APPLY can offer the **official pinned Homebrew installer**, which downloads its IPK and verifies the SHA-256 from its official manifest. It never overwrites Homebrew without confirmation.

In **Homebrew Channel → Settings**:

- Confirm **Root status: OK** after reboot.
- Enable **SSH**. Verify the **SSH host key fingerprint** the first time you connect. The wizard can offer `ssh-copy-id` to install your Ed25519 **public** key (your private key stays on the PC).
- Disable **Telnet** (port 23) *only after* SSH key access works. Homebrew's Telnet may expose an unauthenticated root shell to your LAN.
- Do **not** reinstall LG Developer Mode after rooted setup. You no longer need its expiring token or Auto Dev Token Refresh.

For an independent SSH check:

```bash
ssh root@192.168.1.24 'id -u'
# Expected: 0
```

**Default root password (Homebrew Channel): `alpine`.** When Homebrew creates the initial root SSH account *and no `authorized_keys` file exists*, its boot script may enable this known default password. This is **not** your LG account password, and the actual password may have been changed. If `ssh-copy-id` prompts for `root@TV_IP` password before keys are set up, try `alpine`. Do not publish this password or reuse it on other devices. **After authorizing an SSH key and rebooting**, Homebrew no longer applies its fallback password when `authorized_keys` exists; use SSH key authentication instead. Test `ssh root@TV_IP 'id -u'` before switching off Telnet.

If key-based SSH fails, the wizard will guide you through enabling SSH and key provisioning. It **never accepts a password in a command-line argument** or stores one in a log.

### Step 3 — Choose applications to install

Select only what you want, then APPLY. Existing apps are detected and kept. Downloads come from official project repositories or the Homebrew catalog (with published SHA-256 validation where provided).

**LG Input Hook (remote shortcuts):** install, open the app **at least once**, choose **Add keybind**, press the desired physical key and consult the app logs for the key ID, choose Disable / Execute / Replace, then **Save changes**. Typical candidates: Netflix, Prime Video, Disney+, Rakuten. Actual IDs depend on the remote and firmware.

**Aerial screensaver:** install, open Aerial, choose the video source (Full HD or 4K depending on bandwidth/decoding), set **Autostart**, press **Apply**, then **Test screensaver**. It replaces the default LG screensaver. Avoid activating Glasshouse's alternative screensaver at the same time.

**YouTube AdFree:** uses the **same application ID** as official LG YouTube (`youtube.leanback.v4`). The wizard **never silently replaces** the LG Store version. Jellyfin official is left alone.

### Step 4 — Remove Home ads (reversible)

The wizard offers [nurikk/lg-webos-ad-killer](https://github.com/nurikk/lg-webos-ad-killer). It uses **only** the smaller `ads` profile, to suppress promotional home shelves, recommendations/ACR and related telemetry while preserving voice/ThinQ functions where possible. The startup wrapper forces the `ads` profile on each boot — not the upstream script's broader `privacy` default.

**TEST** now checks the installed hook and post-boot status **without running the upstream tool**. **APPLY** retrieves the pinned source, shows a preview and asks permission. The installed Homebrew startup hook runs the narrow `ads` profile at boot and re-applies it approximately **35 seconds** later, after LG services may have recreated advertising state. It logs both passes in `/var/lib/webosbrew/ad_killer_boot.log`. A status check after a *real* restart is still essential: LG firmware and failsafe boot paths can bypass hooks.

Use this **read-only diagnosis after reboot**:

```bash
python3 clean_webos.py --ip 192.168.1.24 --ads-status
```

Look for `hook=executable`, `upstream=executable`, `disabled=no`, `run_parts_hook=recognized`, and `DELAYED PASS exit=0` in the log. `ads_mount=present` indicates that a configuration override was mounted, but **does not by itself guarantee that every promotional tile is gone**. If the hook is missing, rerun **APPLY → LG ad blocker** to repair it. If `homebrew_failsafe=PRESENT`, diagnose the underlying startup issue rather than forcing changes. To undo, select **Restore LG ads/settings**; it invokes upstream `--disable`, rolls back runtime mounts and disables future applications. Some recommendations can still be delivered by LG services; total ad removal is not guaranteed.

> Only use one home-ad blocker at a time. Glasshouse also offers privacy/ad controls: avoid applying overlapping blockers without understanding their interactions.

### Step 5 — Manage apps and optional background services

**Install Glasshouse** first. Open its dashboard on `http://TV_IP:8080/` **only over your trusted local network**. The wizard generates an access token and saves it in a `0600` file on the PC. If Glasshouse is already installed, the wizard does **not** replace its settings or token.

- **Removable apps:** inspect title/version and select uninstall candidates. **Jellyfin, Homebrew and core LG apps are protected**. Each uninstall requires confirmation and is permanent.
- **Built-in apps:** choose the system-app section. Glasshouse can **hide/reveal their Home icons**, not delete their built-in packages. This is **experimental**, must be enabled in Glasshouse settings, and can restart LG's application manager. Core TV controls cannot be selected.
- **Background services:** choose a known optional service from the Glasshouse catalog, inspect its description and decide whether to **disable or restore** it. Some optional functionality may stop working; restoration is always offered.
- **Remote buttons:** Glasshouse can also remap buttons; **do not map the same key in both Glasshouse and LG Input Hook**.

## Important safety rules

- **Never** execute this on a TV you do not own or administer with permission.
- There is **no universal root method**: an exploit known to work on one firmware may fail or brick another.
- **Never factory-reset or reboot in the middle of a rooting attempt.** Follow SlopBro's instructions about Developer Mode before the first reboot.
- Never enable Telnet on an untrusted network. Do not port-forward root SSH (22), the Glasshouse dashboard (8080), or webOS debugging (9998). Use VLAN/firewall boundaries if other devices are not trusted.
- Disabling firmware updates can prevent security patches; the wizard **does not** alter update settings or block LG servers. Check compatibility before applying updates.
- Read the warnings for experimental app hiding: the HOME app, settings, HDMI inputs and recovery components are **never** available as deletion targets.
- **TEST is read-only with respect to the TV**. It makes harmless network/SSH/API queries, but performs no installations, service disabling or root attempts.
- Upstream applications may change their behavior. Our source pins snapshots/revisions where possible; inspect and test them before using APPLY.

For security details and known limitations: [SECURITY.md](SECURITY.md).

## Documentation and development

All on-screen navigation, mode selection, module names and follow-up guidance are available in six languages. Some upstream technical logs and error messages may appear in English or French while those projects evolve.

Source layout:

```text
clean_webos.py           multilingual terminal wizard, orchestration
engine.py                TV SSH, SlopBro, Homebrew, apps/services, ads
catalog.py               Homebrew index lookup + SHA256/IPK checks
install.sh               Bash bootstrap, prerequisites, Atomic/Toolbx handling
locales/*.json           six language packs
CREDITS.md               upstream authors and license links
SECURITY.md              risks, rollback, attack surface
.github/workflows/ci.yml static tests
```

Run local tests:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile clean_webos.py engine.py catalog.py
bash -n install.sh
```

Tests mock the TV. **Passing local tests does not prove a particular TV or firmware is compatible**. `--mode test` must be used on the real device before APPLY.

Contributions and translations welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

## Credits & thanks

This repository is a community orchestrator, **not a fork or rebrand of upstream work**. We warmly thank:

- **[throwaway96 / SlopBro](https://github.com/throwaway96/slopbro)** — original `jsserver` root tool, **AGPL-3.0-or-later**, with upstream jsbro and dangbro contributors.
- **[webOS Homebrew Project / Homebrew Channel](https://github.com/webosbrew/webos-homebrew-channel)** — package manager and root integration.
- **[Simon34545 / LG Input Hook](https://github.com/Simon34545/lginputhook)** — button remapping, with credited upstream collaborators.
- **[aabytt / Aerial](https://github.com/aabytt/custom-screensaver-aerial)** — moving screensaver, based on webOS custom-screensaver.
- **[nurikk / LG Ad Killer](https://github.com/nurikk/lg-webos-ad-killer)** — reversible LG Home ad filtering.
- **[Rory Gallagher / Glasshouse](https://github.com/rorygallagher2024/glasshouse)** — app/system service management and local dashboard.
- **[webosbrew / YouTube AdFree](https://github.com/webosbrew/youtube-webos)** — community YouTube client.

Each upstream component retains **its own license and copyright**. clean_webOS code is distributed under the [MIT License](LICENSE) and does not bundle AGPL source. See [CREDITS.md](CREDITS.md) for attribution and revision details.

---

**Made for LG TV owners who want a quieter, more private Home screen — and the freedom to choose what runs on their own device.**

## Troubleshooting: Glasshouse archives and boot-time ads

Earlier versions rejected GitHub archives containing symlinks with `Links and special entries forbidden`. As of **v5.1.0**, the safe extractor **skips symlink/hardlink entries entirely** while extracting normal files and preserving their executable bits. No unsafe links are created on your computer. Run the Glasshouse step again after updating.

If promotions return after a real TV reboot, the most useful evidence is the read-only `--ads-status` report. The Homebrew `run-parts` hook must run during normal root startup, and LG may recreate Home data later. An available root SSH connection is not evidence that your advertising filter ran successfully.

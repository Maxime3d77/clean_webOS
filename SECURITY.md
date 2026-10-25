# Security, rollback and safe operation

clean_webOS controls a rooted embedded Linux device. Treat a rooted TV as a privileged server and **keep it on a trusted LAN**.

## Threat model and defaults

- Run the launcher as your **normal PC account**, never using host sudo. TV root authentication is provided through OpenSSH.
- `--mode test` performs only network connections, SSH/Luna queries and catalogue reads. It never installs packages or touches system services.
- The SlopBro exploit is not executed without explicit user consent and the upstream compatibility/ownership warning.
- Homebrew's boot scripts may assign the **publicly known initial root password `alpine`** if SSH authorized keys have not been provisioned. It is intended as a temporary bootstrap only; do not rely on it after key provisioning.
- Root SSH should use key authentication. On first connection **verify the host fingerprint**. Do not expose ports 22, 23, 8080, or 9998 on the Internet.
- **Telnet (port 23) must be disabled** after root SSH is working. Homebrew may start an unauthenticated root telnet service; configure network isolation immediately.
- Glasshouse is deployed with a randomly generated token stored under `~/.config/webos-easy-setup/` (`0600`). If installed previously, its existing config is preserved. Protect any browser URLs containing access tokens.
- Homebrew, Jellyfin and critical TV applications are excluded from uninstall selection. System tiles are **hidden using overlays**, not deleted. Optional service management uses Glasshouse's named catalog, not arbitrary shell commands.
- Ad filtering is installed as a Homebrew startup hook with the **narrow `ads` profile**, a delayed follow-up pass and persistent diagnostic logs. This does not guarantee that every LG Home promotion stays hidden after every boot. `privacy` (which disables additional voice/IoT features) is not applied by this installer.

## Recovery and reversibility

| Change | Undo |
|---|---|
| LG ad blocking | Select **Restore LG ads/settings**, equivalent to Ad Killer `--disable`. It removes its runtime overrides and disables the boot hook. |
| System app hidden | Select **System apps → Restore** or **Unhide All** in Glasshouse. Core system apps are protected. |
| Optional background service disabled | Select **Background services → Restore** (Glasshouse). |
| LG Input Hook key remapped | Open Input Hook, delete the binding or restore the default. |
| Aerial replacing the screensaver | Turn off Autostart and restore original screensaver in the Aerial app. |
| YouTube AdFree | Reinstall the official app from LG Content Store if preferred. The same app ID cannot exist simultaneously. |
| Permanent app uninstall | Reinstall from its original publisher/store. This is **not** reversible without reinstalling. |

**Do not delete `/var/lib/webosbrew`, remove Homebrew Channel, or edit the built-in read-only system partition to achieve a cleanup.** Do not combine competing home or remote-key hooks without checking conflicts.

## Firmware, unsupported devices and privacy

The existence of a root exploit does not mean an update is safe, nor that withholding updates is safe. The installer **never disables firmware updates**. Root success can be firmware/model specific; instructions describe only observed paths and cannot guarantee recovery from a failed exploit. SlopBro has its own license and warnings.

Please remove IP addresses, MAC addresses, SSH keys, passwords and authorization tokens from GitHub bug reports. Use the read-only mode first and share redacted logs.

## Reporting a vulnerability

Open a private security report through GitHub's security advisories, if available. Do not include device credentials or tokens. For vulnerabilities in SlopBro, Glasshouse, Homebrew or other upstream apps, contact their respective maintainers directly.

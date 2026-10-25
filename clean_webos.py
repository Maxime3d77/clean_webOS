#!/usr/bin/env python3
"""clean_webOS: guided multilingual wizard for a TV the user owns.

No remote modification before APPLY + per-action confirmation.
Only upstream projects provide root, catalog apps and system overrides.
"""
from __future__ import annotations

import argparse
import curses
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from dataclasses import dataclass

import engine

VERSION = "5.1.0"
BASE = Path(__file__).resolve().parent
LANGUAGES = ("en", "fr", "es", "de", "it", "pt")
MODULES = ("glasshouse", "mapper", "aerial", "youtube", "ads", "undo_ads", "apps", "system", "services")
# Preserve order of prerequisite-sensitive modules: Glasshouse before app management.
ORDER = ("glasshouse", "mapper", "aerial", "youtube", "ads", "undo_ads", "apps", "system", "services")
DEFAULT_IP = ""


def locale_data(lang: str) -> dict[str, str]:
    if lang not in LANGUAGES:
        raise ValueError(f"Unsupported language: {lang}")
    path = BASE / "locales" / f"{lang}.json"
    english = json.loads((BASE / "locales/en.json").read_text(encoding="utf-8"))
    english.update(json.loads(path.read_text(encoding="utf-8")))
    return english


def validate_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).version == 4
    except ValueError:
        return False


def plan_modules(selected: set[str] | list[str]) -> list[str]:
    result = [name for name in ORDER if name in selected]
    if "ads" in result and "undo_ads" in result:
        raise ValueError("Select either ad blocking or restoring, not both")
    return result


@dataclass(frozen=True)
class Plan:
    language: str
    mode: str
    ip: str
    modules: tuple[str, ...]

    def validate(self) -> None:
        if self.language not in LANGUAGES:
            raise ValueError("Unsupported language")
        if self.mode not in ("test", "apply"):
            raise ValueError("Invalid mode")
        if not validate_ip(self.ip):
            raise ValueError("Invalid TV IPv4 address")
        if len(self.modules) != len(set(self.modules)):
            raise ValueError("Duplicate modules")
        if any(x not in MODULES for x in self.modules):
            raise ValueError("Unknown module")
        plan_modules(self.modules)


def ask_yes(message: str, locale: dict[str, str]) -> bool:
    if not sys.stdin.isatty():
        return False
    v = input(f"\n  {message} [y/n]: ").strip().casefold()
    return v in {"yes", "y", "oui", "o", "si", "sí", "s", "ja", "j", "sim"}


def section(title: str, index: int) -> None:
    print("\n" + "━" * 72)
    print(f"  {title}")
    print("━" * 72)


def pause_text() -> None:
    if sys.stdin.isatty():
        input("\n  Enter ↵ / Entrée ↵ ...")


class TerminalWizard:
    """Keyboard-driven TUI. No shell/TV command is invoked inside curses."""
    def __init__(self, screen, address: str, initial_lang: str | None, initial_mode: str | None):
        self.screen = screen
        self.language = initial_lang or "en"
        self.lang_locked = initial_lang is not None
        self.mode = initial_mode or "test"
        self.mode_locked = initial_mode is not None
        self.ip = address
        self.selected: set[str] = set()
        self.focus = 0
        self.top = 0
        self.message = ""
        self.steps = (["language"] if not self.lang_locked else []) + (["mode"] if not self.mode_locked else []) + ["modules", "review"]
        self.step = 0
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.screen.keypad(True)
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                pass
            for idx, color in ((1, curses.COLOR_CYAN), (2, curses.COLOR_GREEN), (3, curses.COLOR_YELLOW)):
                try:
                    curses.init_pair(idx, color, -1)
                except curses.error:
                    pass

    def put(self, y: int, x: int, message: str, color: int = 0) -> None:
        h, w = self.screen.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w - 1:
            return
        try:
            self.screen.addnstr(y, x, message, max(0, w - x - 2), curses.color_pair(color))
        except curses.error:
            pass

    def screen_step(self) -> str:
        return self.steps[self.step]

    def draw(self) -> None:
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        d = locale_data(self.language)
        self.put(1, 3, "◆  " + d["title"] + "  /  v" + VERSION, 1)
        self.put(2, 3, d["subtitle"] + ("  •  " + self.ip if self.ip else ""))
        self.put(4, 3, "━" * max(5, w - 7), 1)
        step = self.screen_step()
        titles = {"language": "Language / Langue / Idioma / Sprache / Lingua",
                  "mode": d["mode"], "modules": d["modules"], "review": d["summary"]}
        self.put(6, 4, f"{self.step + 1}/{len(self.steps)}  •  {titles[step]}", 1)
        if h < 18 or w < 50:
            self.put(9, 4, "Terminal too small. Enlarge window or use --text.", 3)
            self.screen.refresh()
            return
        if step == "language":
            for idx, key in enumerate(LANGUAGES):
                self.put(9 + idx * 2, 5, ("▶ " if self.focus == idx else "  ") + locale_data(key)["language"], 1 if self.focus == idx else 0)
        elif step == "mode":
            for idx, key in enumerate(("test", "apply")):
                self.put(10 + idx * 4, 5, ("▶ " if self.focus == idx else "  ") + d[key], 1 if self.focus == idx else 0)
        elif step == "modules":
            visible = max(3, min(len(MODULES), h - 14))
            self.top = min(self.top, self.focus)
            self.top = max(self.top, self.focus - visible + 1)
            for idx in range(self.top, min(len(MODULES), self.top + visible)):
                key = MODULES[idx]
                prefix = "▶ " if self.focus == idx else "  "
                checkbox = "[x]" if key in self.selected else "[ ]"
                self.put(9 + idx - self.top, 5, f"{prefix}{checkbox} {d['module_' + key]}", 1 if idx == self.focus else 0)
            key = MODULES[self.focus]
            self.put(h - 5, 5, d.get("guide_" + key, "")[:max(w-8, 0)], 3)
            self.put(h - 4, 5, d["select"])
        else:
            self.put(9, 5, d["mode"] + ": " + d[self.mode])
            self.put(11, 5, d["address"] + ": " + (self.ip or "—"))
            if not self.ip:
                self.put(12, 5, d["ip_help"], 3)
            if self.selected:
                rows = max(1, h - 19)
                keys = plan_modules(self.selected)
                for i, key in enumerate(keys[:rows]):
                    self.put(14+i, 6, "• " + d["module_" + key])
                if len(keys) > rows:
                    self.put(14+rows, 6, f"… +{len(keys)-rows} more")
            else:
                self.put(14, 6, "• " + d["step_root"] + " / " + d["step_homebrew"])
        self.put(h-2, 4, d["continue"])
        if self.message:
            self.put(h-3, 4, self.message, 3)
        self.screen.refresh()

    def run(self):
        while True:
            self.draw()
            key = self.screen.getch()
            if key in (ord("q"), ord("Q"), 27):
                return None
            if key in (ord("b"), ord("B")) and self.step > 0:
                self.step -= 1
                self.focus = 0
                continue
            part = self.screen_step()
            if part in ("language", "mode"):
                total = len(LANGUAGES) if part == "language" else 2
                if key in (curses.KEY_DOWN, ord("j")):
                    self.focus = (self.focus + 1) % total
                elif key in (curses.KEY_UP, ord("k")):
                    self.focus = (self.focus - 1) % total
                elif key in (10, 13, curses.KEY_ENTER):
                    if part == "language":
                        self.language = LANGUAGES[self.focus]
                    else:
                        self.mode = ("test", "apply")[self.focus]
                    self.step += 1
                    self.focus = 0
            elif part == "modules":
                if key in (curses.KEY_DOWN, ord("j")):
                    self.focus = (self.focus + 1) % len(MODULES)
                elif key in (curses.KEY_UP, ord("k")):
                    self.focus = (self.focus - 1) % len(MODULES)
                elif key == 32:
                    name = MODULES[self.focus]
                    self.selected.symmetric_difference_update({name})
                elif key in (10, 13, curses.KEY_ENTER):
                    try:
                        plan_modules(self.selected)
                    except ValueError as exc:
                        self.message = str(exc)
                    else:
                        self.message = ""
                        self.step += 1
                        self.focus = 0
            elif key in (10, 13, curses.KEY_ENTER):
                return (self.language, self.mode, tuple(plan_modules(self.selected)))


def text_wizard(address: str, initial_lang: str | None, initial_mode: str | None):
    if not initial_lang:
        print("\n  CLEAN WEBOS — Language / Langue / Idioma / Sprache / Lingua / Idioma")
        for i, lang in enumerate(LANGUAGES, 1):
            print(f"  {i}. {locale_data(lang)['language']}")
        raw = input("  Language [1]: ").strip() or "1"
        if not raw.isdigit() or not 1 <= int(raw) <= len(LANGUAGES):
            raise ValueError("Invalid language")
        language = LANGUAGES[int(raw)-1]
    else:
        language = initial_lang
    d = locale_data(language)
    if not initial_mode:
        print("\n" + d["mode"])
        print("  1. " + d["test"])
        print("  2. " + d["apply"])
        raw = input("  [1]: ").strip() or "1"
        if raw not in ("1", "2"):
            raise ValueError("Invalid mode")
        mode = "test" if raw == "1" else "apply"
    else:
        mode = initial_mode
    if not address:
        address = input("\n  " + d["address"] + ": ").strip()
    print("\n" + d["modules"])
    for i, key in enumerate(MODULES, 1):
        print(f"  {i:2}. {d['module_' + key]}")
        description = d.get("guide_"+key)
        if description:
            print("      " + description)
    raw = input("\n  1,2,3 ... (empty = diagnostic only): ").strip()
    selected = set()
    if raw:
        for bit in raw.split(","):
            val = bit.strip()
            if not val.isdigit() or int(val) not in range(1, len(MODULES)+1):
                raise ValueError("Invalid option")
            selected.add(MODULES[int(val)-1])
    modules = tuple(plan_modules(selected))
    print("\n" + d["summary"])
    print("  " + d["mode"] + ": " + d[mode])
    print("  " + d["address"] + ": " + address)
    for key in modules:
        print("  - " + d["module_" + key])
    if not ask_yes(d["confirm"], d):
        return None
    return language, mode, address, modules


def environment_check(d: dict[str,str], mode: str) -> bool:
    missing = [p for p in ("ssh", "scp") if not shutil.which(p)]
    if missing:
        print("  Missing SSH prerequisites: " + ", ".join(missing))
        print("  Run ./install.sh (it helps install them) or install OpenSSH.")
        return False
    if mode == "apply" and not shutil.which("git"):
        print("  INFO: Git unavailable; SlopBro/Glasshouse are downloaded as verified pinned snapshots.")
    return True


def guide_ssh_pair(ip: str, locale: dict[str,str] | None = None) -> bool:
    """Owner-approved SSH key provisioning. No password recorded by Python."""
    if not shutil.which("ssh-copy-id"):
        print("  ssh-copy-id unavailable. Install OpenSSH client or provision your public key manually.")
        return False
    key = Path.home()/".ssh"/"id_ed25519"
    pub = Path(str(key)+".pub")
    if not pub.is_file():
        print("  New Ed25519 key; choose a strong passphrase in ssh-keygen.")
        key.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        result=subprocess.run(["ssh-keygen","-t","ed25519","-f",str(key)],check=False)
        if result.returncode != 0 or not pub.is_file():
            return False
    print("  Verify the TV's SSH host fingerprint before accepting it.")
    locale = locale or {}
    print("  " + locale.get('ssh_default_password', 'Homebrew default root password: alpine (before SSH keys are installed).'))
    print("  Type the root password only in the SSH prompt; do not paste it into ChatGPT.")
    result=subprocess.run(["ssh-copy-id","-i",str(pub),"root@"+ip],check=False)
    if result.returncode != 0:
        return False
    print("  If your key has a passphrase, use ssh-agent and ssh-add before running the wizard.")
    return engine.root_ok(ip)


def show_aftercare(d: dict[str, str], selected: tuple[str, ...]) -> None:
    for item in selected:
        guide = d.get("guide_" + item)
        if guide:
            print("\n  ▸ " + guide)
    print("\n  " + d["guide_complete"])
    print("  " + d["root_credits"])


def execute(plan: Plan) -> int:
    plan.validate()
    d = locale_data(plan.language)
    section(d["step_root"], 1)
    print("  " + d["root_credits"])
    if not environment_check(d, plan.mode):
        return 2
    for port, label in ((22,"SSH"),(23,"Telnet"),(3001,"SSAP")):
        print(f"  {label} {port}: " + ("open" if engine.tcp(plan.ip,port) else "closed"))
    if engine.tcp(plan.ip,23):
        print("  " + d["port_telnet"])
    rooted = engine.root_ok(plan.ip)
    if rooted:
        print("  ✓ " + d["root_ok"])
    else:
        print("  ! " + d["root_missing"])
        print("  " + d["root_needed"])
        print("  " + d["root_risk"])
        print("  " + d["root_next"])
        if plan.mode == "test":
            print("  TEST: no exploit, no root installation, no writes.")
            section(d["step_homebrew"],2)
            print("  " + d["homebrew_absent"])
            section(d["step_finish"],4)
            show_aftercare(d,plan.modules)
            return 0
        # Never misinterpret missing SSH credentials as a missing root.
        if ask_yes(d["root_yes"],d):
            print("  SSH needs to be enabled in Homebrew Channel Settings.")
            print("  Ensure key-based login before disabling Telnet.")
            if engine.tcp(plan.ip,22) and ask_yes("Configure an Ed25519 SSH key on this computer now?", d):
                if guide_ssh_pair(plan.ip,d):
                    print("  SSH root verified. Resume Homebrew setup.")
                    rooted = True
                else:
                    print("  SSH still unavailable: check your TV credentials and try again.")
                    return 2
            else:
                print("  Enable SSH in Homebrew first, then re-run this assistant.")
                return 2
        if not rooted:
            result=engine.slopbro_bootstrap(plan.ip,"apply")
            print("  SlopBro result: "+str(result))
            print("  " + d["root_next"])
            print("  Re-run clean_webOS after Root status OK and root SSH are confirmed.")
            return 0 if result == "A VERIFIER SUR TV" else 2

    section(d["step_homebrew"], 2)
    apps=engine.cached_apps(plan.ip)
    try:
        outcome=engine.ensure_homebrew(plan.ip,plan.mode,apps)
    except Exception as exc:
        print("  ERROR: "+str(exc))
        return 2
    print("  Homebrew: "+outcome)
    if plan.mode == "apply" and outcome not in ("ALREADY INSTALLED", "INSTALLED"):
        print("  No verified Homebrew installation. Stop before modifying system apps.")
        return 2
    section(d["step_apps"], 3)
    if not plan.modules:
        print("  No optional modules selected. Read-only inventory complete.")
        code=0
    else:
        try:
            code=engine.run_plan(plan.mode,list(plan.modules),plan.ip)
        except Exception as exc:
            print("  ERROR: "+str(exc))
            code=2
    section(d["step_finish"], 4)
    show_aftercare(d,plan.modules)
    return code


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="clean_webOS v5 guided TV owner assistant")
    parser.add_argument("--ip",default=DEFAULT_IP,help="Local TV IPv4 address")
    parser.add_argument("--lang",choices=LANGUAGES,help="Language code")
    parser.add_argument("--mode",choices=("test","apply"),help="Skip mode choice")
    parser.add_argument("--modules",help="Comma-separated module ids; enables non-interactive plan")
    parser.add_argument("--text",action="store_true",help="Simple numbered menu")
    parser.add_argument("--dry-run",action="store_true",help="Alias for --mode test")
    parser.add_argument("--ads-status",action="store_true",help="Read-only check of ad blocker and startup hook after reboot")
    args=parser.parse_args(argv)
    if args.ads_status:
        if not args.ip or not validate_ip(args.ip):
            parser.error("--ads-status requires --ip with the TV IPv4 address")
        if not engine.root_ok(args.ip):
            print("SSH root unavailable; activate SSH and install your public key in Homebrew.")
            return 2
        try:
            engine.ad_status(args.ip)
            return 0
        except Exception as exc:
            print("Ad blocker audit failed: " + str(exc))
            return 2
    if args.dry_run:
        if args.mode == "apply":
            parser.error("--dry-run and --mode apply conflict")
        args.mode="test"
    if args.modules is not None:
        if not args.ip:
            parser.error("--ip is required with --modules")
        raw=[x.strip() for x in args.modules.split(",") if x.strip()]
        unknown = set(raw) - set(MODULES)
        if unknown:
            parser.error("Unknown modules: " + ", ".join(sorted(unknown)))
        plan=Plan(args.lang or "en",args.mode or "test",args.ip,tuple(plan_modules(raw)))
    else:
        if not sys.stdin.isatty():
            parser.error("Interactive session required without --modules")
        if args.text or not sys.stdout.isatty() or os.getenv("TERM", "dumb") == "dumb":
            choice=text_wizard(args.ip,args.lang,args.mode)
        else:
            try:
                choice=curses.wrapper(lambda screen: TerminalWizard(screen,args.ip,args.lang,args.mode).run())
            except (curses.error, UnicodeError):
                choice=text_wizard(args.ip,args.lang,args.mode)
        if choice is None:
            print("Cancelled")
            return 0
        if len(choice) == 3:
            language,mode,mods=choice
            ip=args.ip or input("\n  " + locale_data(language)["address"] + ": ").strip()
        else:
            language,mode,ip,mods=choice
        plan=Plan(language,mode,ip,tuple(mods))
    try:
        return execute(plan)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        return 130
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())

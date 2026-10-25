#!/usr/bin/env python3
"""clean_webOS v5.1: rooted LG installer, no system package removal.

All TV changes go through owner-approved, authenticated root SSH.
Third-party code is referenced by pinned upstream revisions; not vendored.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import select
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import tarfile
import io
import time
import urllib.error
import urllib.request

import catalog as lg_setup

VERSION = '5.1.0'
HB_INSTALL_REV = '1a2b969e992617c9ba4b8a891542cb93a9e07b0a'
HB_INSTALL_URL = 'https://raw.githubusercontent.com/webosbrew/webos-homebrew-channel/' + HB_INSTALL_REV + '/tools/install.sh'
GIT_SLOPBRO = 'https://github.com/throwaway96/slopbro'
SLOPBRO_COMMIT = '21023d56ca424607bb03d2939609cc658c655fc7'
GLASS_REPO = 'https://github.com/rorygallagher2024/glasshouse.git'
GLASS_COMMIT = 'a1b93a218222034934004d502aeff3f111dfd411'
AD_REV = '7f669e24e49fb082dc27a1cf4a76b6c20c390084'
AD_URL = 'https://raw.githubusercontent.com/nurikk/lg-webos-ad-killer/' + AD_REV + '/ad_killer'
CATALOG = {
    'mapper': 'org.webosbrew.inputhook',
    'aerial': 'org.aabytt.webos.custom-screensaver-aerial',
    'youtube': 'youtube.leanback.v4',
}
MODULES = [
    ('mapper', 'LG Input Hook', 'Remapper Netflix, Prime Video, Disney+ et les autres touches. Premiere ouverture dans Homebrew obligatoire.'),
    ('aerial', 'Aerial Apple TV', 'Economiseur video Aerial. La configuration finale se fait dans son application.'),
    ('ads', 'Supprimer pubs LG', 'Installe lg-webos-ad-killer (profil ads uniquement). Modifications volatiles et reversibles.'),
    ('undo_ads', 'Restaurer pubs LG', 'Arrete ad-killer et desactive son demarrage automatique.'),
    ('glasshouse', 'Glasshouse (tableau de bord)', 'Interface locale pour applications LG, services, confidentialite et telecommande.'),
    ('system', 'Applications systeme', 'Liste toutes les apps LG, permet de masquer/retablir des tuiles via Glasshouse.'),
    ('apps', 'Applications installees', 'Inventaire et desinstallation sur selection des applications NON systeme via Glasshouse.'),
    ('services', 'Services secondaires LG', 'Lister et desactiver/restaurer des services catalogues par Glasshouse; confirmations explicites.'),
    ('youtube', 'YouTube AdFree', 'Verifie si la variante sans pub est installee. Ne retire jamais YouTube officiel.'),
    ('slopbro', 'SlopBro / root', 'Si la TV n’est pas rootée : lancer la méthode officielle après consentement. Sinon, diagnostic et crédits.'),
]
DEFAULTS = {'mapper', 'aerial', 'ads', 'glasshouse', 'system'}
PROTECTED = {
    'com.webos.app.home', 'com.webos.app.livetv', 'com.webos.app.settings',
    'com.webos.app.inputpicker', 'com.webos.app.browser', 'com.webos.app.tv',
    'com.palm.app.settings', 'org.webosbrew.hbchannel', 'org.jellyfin.webos', 'com.jellyfin.webos',
}
PROTECT_PATTERNS = ('jellyfin', 'settings', 'inputpicker', 'launcher', 'devmode', 'keyserver', 'factory', 'update', 'recovery', 'systemui')
SSH_FLAGS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6',
             '-o', 'StrictHostKeyChecking=accept-new', '-o', 'IdentitiesOnly=no']


def note(tag, value):
    palette = {'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m', 'INFO': '\033[36m', 'TEST': '\033[35m'}
    c = palette.get(tag, '') if sys.stdout.isatty() else ''
    reset = '\033[0m' if c else ''
    print(f' {c}[{tag:4}]{reset} {value}', flush=True)


def confirm(prompt):
    if not sys.stdin.isatty():
        return False
    return input(f'\n  {prompt} [o/N] : ').strip().casefold() in ('o', 'oui', 'y', 'yes')


def valid_ip(value):
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False


def tcp(ip, port):
    try:
        with socket.create_connection((ip, port), 2):
            return True
    except OSError:
        return False


def local(command, **kwargs):
    return subprocess.run(command, text=True, capture_output=True, check=False, **kwargs)


def ssh_cmd(ip, command):
    return ['ssh', *SSH_FLAGS, 'root@'+ip, command]


def ssh(ip, command, timeout=35):
    return local(ssh_cmd(ip, command), timeout=timeout)


def ssh_exists(ip, path):
    r = ssh(ip, 'test -e '+shlex.quote(path), timeout=15)
    return r.returncode == 0


def root_ok(ip):
    try:
        r = ssh(ip, 'id -u', timeout=13)
        return r.returncode == 0 and r.stdout.strip() == '0'
    except (subprocess.TimeoutExpired, OSError):
        return False


def remote_json(ip, command):
    r = ssh(ip, command, timeout=55)
    if r.returncode != 0:
        raise RuntimeError('Commande TV refusée : ' + r.stderr[-350:].strip())
    raw = r.stdout.strip()
    try:
        return json.loads(raw)
    except ValueError:
        i = raw.find('{')
        j = raw.rfind('}')
        if i >= 0 and j > i:
            return json.loads(raw[i:j+1])
        raise RuntimeError('Format de réponse LG non reconnu')


def luna_apps(ip):
    """List all apps via root Luna; no filesystem changes."""
    data = remote_json(ip, "luna-send -n 1 -f 'luna://com.webos.applicationManager/listApps' '{}' ")
    if not isinstance(data, dict) or data.get('returnValue') is False:
        raise RuntimeError('Liste des applications indisponible')
    apps = data.get('apps') or data.get('launchPoints')
    if not isinstance(apps, list):
        raise RuntimeError('Réponse sans liste applications')
    return [a for a in apps if isinstance(a, dict) and isinstance(a.get('id'), str)]


def protected(item):
    appid = item.get('id', '')
    if appid in PROTECTED:
        return True
    lower = appid.casefold()
    return any(p in lower for p in PROTECT_PATTERNS)


def system_app(item):
    path = item.get('folderPath', '') or ''
    return bool(item.get('systemApp')) or path.startswith(('/usr/palm/', '/media/system/', '/mnt/otn', '/mnt/lg/'))


def installed_ids(apps):
    return {a['id'] for a in apps}


def print_inventory(apps):
    systems = sorted([a for a in apps if system_app(a)], key=lambda a: a.get('title', a['id']).casefold())
    users = sorted([a for a in apps if not system_app(a)], key=lambda a: a.get('title', a['id']).casefold())
    note('INFO', f'{len(apps)} applications : {len(systems)} système, {len(users)} autres')
    for a in systems:
        mark = 'PROTEGEE' if protected(a) else 'SYSTEME'
        print(f'  {mark:9} {str(a.get("title") or a["id"])[:35]:35}  {a["id"]}')
    return systems


def json_from_glass(ip, path, payload=None):
    """Use remote loopback and TV-local token; token never leaves TV.

    The TV owns config.json. JS runs there and sends the HTTP request locally.
    This intentionally avoids publishing the token or binding the service to LAN.
    """
    if not path.startswith('/api/') or not re.fullmatch(r'/api/[a-z0-9/\-]+', path):
        raise ValueError('Chemin API interdit')
    js = """var fs=require('fs'),http=require('http');
var c=JSON.parse(fs.readFileSync('/var/lib/tvweb/config.json','utf8'));
var d=process.argv[2], p=process.argv[1], opts={host:'127.0.0.1',port:c.port||8080,path:p,method:d?'POST':'GET',headers:{'Content-Type':'application/json'}};
if(c.token)opts.headers.Authorization='Bearer '+c.token;
var r=http.request(opts,function(res){var a='';res.on('data',function(x){a+=x;});res.on('end',function(){console.log(a);if(res.statusCode>=400)process.exitCode=2;});});r.on('error',function(e){console.error(e.message);process.exitCode=3;});if(d)r.write(d);r.end();
""".strip().replace('\n','')
    arguments = ['node', '-e', js, path, json.dumps(payload) if payload is not None else '']
    return remote_json(ip, shlex.join(arguments))


def cached_apps(ip):
    try:
        return luna_apps(ip)
    except Exception as e:
        note('WARN', 'Inventaire Luna impossible : ' + str(e))
        return None


def glass_state(ip):
    try:
        return json_from_glass(ip, '/api/apps')
    except Exception:
        return None


def choice_of_apps(items, prompt, *, allow_restore=False):
    """Text selection by displayed numbers; no default selection."""
    if not items or not sys.stdin.isatty():
        return []
    print('\n  '+prompt)
    for i, a in enumerate(items, 1):
        status = 'MASQUE' if a.get('hidden') else 'VISIBLE'
        print(f'  {i:3}. {str(a.get("title") or a["id"])[:30]:30}  {status:7}  {a["id"]}')
    raw = input('  Numeros separes par virgules (Entree pour annuler) : ').strip()
    if not raw:
        return []
    fields = [x.strip() for x in raw.split(',')]
    if not fields or any(not re.fullmatch(r'\d{1,3}', f) for f in fields):
        note('WARN', 'Choix incorrect, aucune modification')
        return []
    nums = [int(f) for f in fields]
    if len(set(nums)) != len(nums) or any(n < 1 or n > len(items) for n in nums):
        note('WARN', 'Choix hors liste, aucune modification')
        return []
    return [items[n-1] for n in nums]


def manage_system(ip, mode, apps):
    systems = print_inventory(apps)
    if mode == 'test':
        note('TEST', 'Aucune application modifiée. Masquage via Glasshouse si disponible.')
        return 'INVENTAIRE'
    state = glass_state(ip)
    if not state or state.get('ok') is False:
        note('WARN', 'Glasshouse absent ou non accessible : installer Glasshouse, puis revenir dans ce menu.')
        return 'GLASSHOUSE REQUIS'
    tiles = state.get('systemTiles') or []
    available = bool(state.get('tileHidingAvailable'))
    if not available:
        note('WARN', 'Masquage expérimental non autorisé. Dans Glasshouse : Serveur > Fonctions expérimentales > Masquer apps système.')
        note('WARN', 'Le masquage peut redémarrer SAM et perturber temporairement HDMI/son. Aucun changement effectué.')
        return 'OPTION EXPERIMENTALE DESACTIVEE'
    candidates = [a for a in tiles if isinstance(a, dict) and not protected(a) and re.fullmatch('[A-Za-z0-9_.-]+',a.get('id',''))]
    if not candidates:
        note('INFO', 'Aucune tuile système masquable proposée par Glasshouse.')
        return 'AUCUNE TUILE'
    action = input('  1 Masquer, 2 Restaurer, Entree Annuler : ').strip()
    if action not in ('1','2'):
        return 'ANNULE'
    candidates = [a for a in candidates if (not a.get('hidden')) == (action == '1')]
    selected = choice_of_apps(candidates, 'Selectionner les tuiles LG à ' + ('masquer' if action=='1' else 'restaurer'))
    if not selected:
        return 'ANNULE'
    note('WARN','Cette opération expérimentale peut redémarrer le gestionnaire SAM.')
    if not confirm('Confirmer '+('le masquage' if action=='1' else 'la restauration')+' des '+str(len(selected))+' tuiles ?'):
        return 'ANNULE'
    route = '/api/apps/hide' if action == '1' else '/api/apps/unhide'
    done = 0
    for item in selected:
        result = json_from_glass(ip, route, {'id':item['id']})
        if result.get('ok'):
            note('OK', item['id']+' : '+('masquee' if action=='1' else 'restauree'))
            done += 1
        else:
            note('ERR', item['id']+' : '+str(result.get('error','echec')))
    return f'MODIFIEES {done}/{len(selected)}'



def ensure_homebrew(ip, mode, apps=None):
    """Install official HBC's pinned installer only after explicit approval.

    SlopBro normally already installs HBC. We do not re-run its installer in
    that case. The upstream installer validates the release IPK's SHA256.
    """
    known = installed_ids(apps) if apps is not None else None
    if known is not None and 'org.webosbrew.hbchannel' in known:
        note('OK','Homebrew Channel already installed; preserved.')
        return 'ALREADY INSTALLED'
    if mode == 'test':
        note('TEST','Homebrew Channel absent or inventory unavailable; no installation.')
        return 'CHECK'
    if known is None:
        note('WARN','Unable to confirm whether Homebrew Channel exists. Refusing installation.')
        return 'UNKNOWN'
    note('WARN','Upstream: webosbrew/webos-homebrew-channel; installation may restart webOS services.')
    if not confirm('Install Homebrew Channel from the OFFICIAL pinned installer?'):
        return 'CANCELLED'
    if not shutil.which('scp'):
        raise RuntimeError('scp executable required')
    script=lg_setup.get_bytes(HB_INSTALL_URL,max_bytes=300_000)
    if not script.startswith(b'#!/bin/sh') or b'IPK_SHA256' not in script or b'sha256sum -c' not in script:
        raise RuntimeError('Unexpected official installer; refusing to execute')
    with tempfile.TemporaryDirectory(prefix='clean-webos-homebrew-') as td:
        src=Path(td)/'install.sh'
        src.write_bytes(script)
        stage='/tmp/clean-webos-homebrew-install.sh'
        sc=local(['scp',*SSH_FLAGS,str(src),'root@'+ip+':'+stage],timeout=60)
        if sc.returncode:
            raise RuntimeError('Unable to copy Homebrew installer: '+sc.stderr[-350:])
        r=ssh(ip,'sh '+shlex.quote(stage)+'; result=$?; rm -f '+shlex.quote(stage)+'; exit $result',timeout=240)
        if r.returncode:
            raise RuntimeError('Official Homebrew installer failed: '+r.stderr[-600:]+' '+r.stdout[-600:])
    check=luna_apps(ip)
    if 'org.webosbrew.hbchannel' not in installed_ids(check):
        raise RuntimeError('Homebrew installer returned success but app not listed. Check TV.')
    note('OK','Homebrew Channel present. Open its Settings and check Root status OK.')
    return 'INSTALLED'


def manage_installed(ip, mode):
    """Removable applications only, with a fresh inventory and opt-in.

    Only Glasshouse handles app uninstall. Never invoke rm on TV paths.
    """
    state=glass_state(ip)
    if not state or state.get('ok') is False:
        note('WARN','Install Glasshouse to list/remove store and homebrew apps safely.')
        return 'GLASSHOUSE REQUIRED'
    entries=state.get('installed') or []
    candidates=[a for a in entries if isinstance(a,dict) and a.get('removable') is True
                and not protected(a) and re.fullmatch(r'[A-Za-z0-9_.-]+',a.get('id',''))]
    print('\n   INSTALLED APPS (protected apps excluded)')
    for a in candidates:
        print('    - '+str(a.get('title') or a['id'])+' ['+a['id']+']')
    if mode=='test':
        note('TEST','Inventory only, nothing removed')
        return 'INVENTORY'
    if not candidates:
        return 'NO REMOVABLE APPS'
    selected=choice_of_apps(candidates,'Choose apps to permanently uninstall (Jellyfin/Homebrew protected)')
    if not selected:
        return 'CANCELLED'
    if not confirm('PERMANENTLY UNINSTALL '+str(len(selected))+' selected apps?'):
        return 'CANCELLED'
    deleted=0
    for a in selected:
        # Refresh remote inventory before each irreversible action.
        fresh=glass_state(ip)
        valid=(fresh or {}).get('installed') or []
        if not any(x.get('id')==a['id'] and x.get('removable') is True for x in valid) or protected(a):
            note('WARN','Skipped, app no longer verified removable: '+a['id']);continue
        res=json_from_glass(ip,'/api/apps/uninstall',{'id':a['id']})
        if res.get('ok'):
            deleted+=1;note('OK','Uninstalled '+a['id'])
        else:
            note('ERR','Could not uninstall '+a['id']+': '+str(res.get('error','unknown')))
    return f'REMOVED {deleted}/{len(selected)}'


GLASSHOUSE_SERVICE_ALLOWLIST = frozenset({
    'mycar', 'camera', 'uploadd', 'rdxd', 'crashreportd',
    'contentminer', 'nudge', 'remotelogger',
})


def manage_services(ip, mode):
    """Disable/enable only Glasshouse's vetted non-core service catalog.

    Uses reversible upstream API. No arbitrary systemctl calls or wildcards.
    """
    try:
        state=json_from_glass(ip,'/api/services')
    except Exception as exc:
        note('WARN','Glasshouse unavailable for service management: '+str(exc))
        return 'GLASSHOUSE REQUIRED'
    if not state.get('ok') or not state.get('supported'):
        note('WARN','Service control not supported on this firmware')
        return 'UNAVAILABLE'
    entries=state.get('services') or []
    candidates=[x for x in entries if isinstance(x,dict)
                and x.get('id') in GLASSHOUSE_SERVICE_ALLOWLIST]
    print('\n  OPTIONAL LG BACKGROUND SERVICES (reversible):')
    for idx,item in enumerate(candidates,1):
        print(f'  {idx:2}. {item.get("title") or item["id"]} / '
              f'{"DISABLED" if item.get("disabled") else "ACTIVE"}')
        if item.get('desc'):
            print('      '+str(item['desc'])[:150])
    if mode=='test':
        note('TEST','No services changed')
        return 'INVENTORY'
    if not candidates:
        return 'EMPTY'
    action=input('  1 Disable / 2 Restore / Enter Cancel: ').strip() if sys.stdin.isatty() else ''
    if action not in ('1','2'):
        return 'CANCELLED'
    disabling=(action=='1')
    choices=[a for a in candidates if bool(a.get('disabled')) != disabling]
    selected=choice_of_apps(choices,'Choose background services (one or more)')
    if not selected:
        return 'CANCELLED'
    if not confirm(('Disable' if disabling else 'Restore')+' '+str(len(selected))+' background services? Some features may be affected.'):
        return 'CANCELLED'
    changed=0
    for item in selected:
        fresh=json_from_glass(ip,'/api/services')
        current=next((x for x in fresh.get('services',[])
                      if x.get('id')==item['id'] and x.get('id') in GLASSHOUSE_SERVICE_ALLOWLIST),None)
        if not current:
            note('WARN','Service no longer offered: '+item['id']);continue
        result=json_from_glass(ip,'/api/services/toggle',{'id':item['id'],'disabled':disabling})
        if result.get('ok'):
            changed+=1
            note('OK',item['id']+(' disabled' if disabling else ' restored'))
        else:
            note('WARN',item['id']+' failed: '+str(result.get('error','unknown')))
    return f'CHANGED {changed}/{len(selected)}'

def install_homebrew_package(ip, pkg, appid):
    """Use the Homebrew Channel root installation service, which handles
    verification, installation and root elevation of supported services.
    Re-verify SHA256 locally first for independent integrity checking.
    """
    blob = lg_setup.get_bytes(pkg['url'])
    lg_setup.check_ipk(blob, pkg['sha256'])
    note('OK', f'Paquet {appid} vérifié localement SHA256')
    payload = json.dumps({'ipkUrl':pkg['url'], 'ipkHash':pkg['sha256'], 'subscribe':True}, separators=(',', ':'))
    remote_command = shlex.join(['luna-send','-i','luna://org.webosbrew.hbchannel.service/install',payload])
    proc=subprocess.Popen(ssh_cmd(ip,remote_command),stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    output=bytearray()
    finished=False
    deadline=time.monotonic()+190
    try:
        while time.monotonic()<deadline and len(output)<150000:
            ready,_,_=select.select([proc.stdout],[],[],2)
            if ready:
                chunk=os.read(proc.stdout.fileno(),8192)
                if not chunk:break
                output+=chunk
                recent=output[-25000:].decode('utf8','replace').lower()
                if re.search(r'"finished"\s*:\s*true',recent):
                    finished=True;break
                if re.search(r'"returnvalue"\s*:\s*false',recent) or re.search(r'"error"\s*:\s*"',recent):
                    break
            elif proc.poll() is not None:
                break
    finally:
        if proc.poll() is None:proc.terminate()
        try:proc.wait(timeout=3)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
    if not finished:
        raise RuntimeError('Installation Homebrew non confirmée. Verifier le catalogue sur la TV. Réponse: '+output[-900:].decode('utf8','replace'))
    # Confirm application in LG Luna inventory. Do not falsely claim success.
    apps=luna_apps(ip)
    if appid not in installed_ids(apps):
        raise RuntimeError('Homebrew a signalé finished, mais l’app est absente de listApps; vérifier sur la TV')
    note('OK','Application installée via le service Homebrew, inventaire confirmé')
    return True


def install_catalog_app(ip, name, mode, apps):
    appid = CATALOG[name]
    installed = installed_ids(apps) if apps is not None else set()
    pkg = lg_setup.package_details(appid)
    note('INFO', f'{name} : catalogue webOS Brew v{pkg["version"]} (SHA256 fourni)')
    if appid in installed:
        if name == 'youtube' and apps is not None and any(a['id']==appid and not str(a.get('folderPath','')).startswith('/media/developer') for a in apps):
            note('WARN','YouTube LG officiel présent : aucun remplacement automatique')
            return 'OFFICIEL CONSERVE'
        note('OK', 'Application déjà présente : aucun changement')
        return 'DEJA INSTALLE'
    if mode == 'test':
        note('TEST', 'Paquet disponible; aucune installation')
        return 'PRET'
    if name == 'youtube':
        # Do not replace an unknown store install or an unexamined state.
        if apps is None:
            note('WARN','Inventaire indisponible : YouTube conservé, installation refusée')
            return 'ATTENTE'
        if any(a['id']==appid and not str(a.get('folderPath','')).startswith('/media/developer') for a in apps):
            note('WARN','YouTube officiel présent. Retirer manuellement avant toute installation AdFree.')
            return 'OFFICIEL PRESENT'
        if not confirm('Confirmer installation YouTube AdFree sans suppression automatique de l’officiel ?'):
            return 'ANNULE'
    if name in ('mapper','aerial') and not confirm(f'Installer {name} sur la TV rootée ?'):
        return 'ANNULE'
    install_homebrew_package(ip,pkg,appid)
    note('INFO','Ouvrir l’application sur la TV pour l’activer/configurer.')
    return 'INSTALLE'


AD_BOOT_WRAPPER = """#!/bin/sh
# clean_webOS: ad-only Homebrew boot integration (no firmware edits).
# Attribution: nurikk/lg-webos-ad-killer; see CREDITS.md.
UPSTREAM=/var/lib/webosbrew/ad_killer_upstream
DISABLED=/var/lib/webosbrew/ad-killer.disabled
LOG=/var/lib/webosbrew/ad_killer_boot.log
[ -e "$DISABLED" ] && exit 0
[ -x "$UPSTREAM" ] || { echo 'ERROR: missing upstream' > "$LOG"; exit 0; }
{
    echo "BOOT $(date -u '+%Y-%m-%dT%H:%M:%SZ') profile=ads"
    "$UPSTREAM" --profile ads
    echo "FIRST PASS exit=$?"
} > "$LOG" 2>&1
# LG can repopulate its recommendations after Homebrew's early-boot hooks.
# Run a second, detached, ad-only pass once system services have settled.
# Never hold up or make Homebrew's startup depend on the blocker.
(
    sleep 35
    [ -e "$DISABLED" ] && exit 0
    {
        echo "DELAYED $(date -u '+%Y-%m-%dT%H:%M:%SZ') profile=ads"
        "$UPSTREAM" --profile ads
        echo "DELAYED PASS exit=$?"
    } >> "$LOG" 2>&1
) </dev/null >/dev/null 2>&1 &
exit 0
"""


def ad_status(ip, *, verbose=True):
    """Purely read-only boot-hook/status audit over authenticated root SSH."""
    script = r"""PATH=/usr/sbin:/usr/bin:/sbin:/bin
h=/var/lib/webosbrew/init.d/ad_killer
u=/var/lib/webosbrew/ad_killer_upstream
l=/var/lib/webosbrew/ad_killer_boot.log
if [ -x "$h" ]; then echo 'hook=executable'; else echo 'hook=missing_or_not_executable'; fi
if [ -x "$u" ]; then echo 'upstream=executable'; else echo 'upstream=missing_or_not_executable'; fi
if [ -e /var/lib/webosbrew/ad-killer.disabled ]; then echo 'disabled=yes'; else echo 'disabled=no'; fi
if [ -e /tmp/webosbrew_startup ]; then echo 'homebrew_startup=detected'; else echo 'homebrew_startup=unknown'; fi
if [ -e /var/luna/preferences/webosbrew_failsafe ]; then echo 'homebrew_failsafe=PRESENT'; else echo 'homebrew_failsafe=absent'; fi
if command -v run-parts >/dev/null 2>&1; then
  matches=$(run-parts --test /var/lib/webosbrew/init.d 2>/dev/null)
  if [ "$?" -ne 0 ]; then echo 'run_parts_hook=unknown';
  elif printf '%s\n' "$matches" | grep -Fx "$h" >/dev/null; then echo 'run_parts_hook=recognized';
  else echo 'run_parts_hook=NOT_RECOGNIZED'; fi
else echo 'run_parts_hook=unknown'; fi
if grep -F '/mnt/lg/cmn_data/sdp/sdx/detailconfig.json' /proc/self/mountinfo >/dev/null 2>&1; then echo 'ads_mount=present'; else echo 'ads_mount=absent'; fi
if [ -f "$l" ]; then echo 'boot_log=present'; tail -n 12 "$l"; else echo 'boot_log=absent'; fi"""
    r=ssh(ip,script,timeout=25)
    if r.returncode:
        raise RuntimeError('Diagnostic antipub impossible : '+r.stderr[-500:])
    if verbose:
        print('  ─── Ad Killer / boot diagnostics ───')
        print(r.stdout[-2400:])
    return r.stdout


def ad_killer(ip, mode, undo=False):
    path = '/var/lib/webosbrew/init.d/ad_killer'
    upstream = '/var/lib/webosbrew/ad_killer_upstream'
    if mode=='test':
        note('TEST','Diagnostic antipub en lecture seule (aucun lancement du bloqueur).')
        ad_status(ip)
        return 'DIAGNOSTIC'
    if undo:
        if not ssh_exists(ip,upstream):
            note('INFO','Script antipub absent. Rien à restaurer.')
            return 'ABSENT'
        if not confirm('Désactiver ad-killer et ses hooks de démarrage ?'):
            return 'ANNULE'
        r=ssh(ip,shlex.join([upstream,'--disable']),timeout=90)
        # The wrapper has no args side effects: upstream --disable handles
        # rolling back mounts and places the persistent disable marker.
        if r.returncode:
            raise RuntimeError('Rollback ad-killer : '+r.stderr[-500:])
        note('OK','Antipub désactivée ; réactivation possible depuis le menu.')
        return 'DESACTIVE'
    note('INFO','Source upstream nurikk/lg-webos-ad-killer ('+AD_REV[:12]+')')
    payload=lg_setup.get_bytes(AD_URL,max_bytes=2000000)
    if not payload.startswith(b'#!/') or len(payload)<200:
        raise RuntimeError('Script distant invalide : installation refusée')
    note('INFO','SHA256 source : '+ __import__('hashlib').sha256(payload).hexdigest())
    if not confirm('Installer ou réparer le blocage LG profil ads UNIQUEMENT, y compris après redémarrage ?'):
        return 'ANNULE'
    with tempfile.TemporaryDirectory(prefix='ad-killer-') as td:
        f=Path(td)/'ad_killer';f.write_bytes(payload)
        sc=local(['scp',*SSH_FLAGS,str(f),'root@'+ip+':/tmp/webos-easy-ad-killer.new'],timeout=90)
        if sc.returncode:raise RuntimeError('Copie du script impossible : '+sc.stderr[-300:])
    # A previous hook is preserved once only. Never edit read-only firmware.
    remote_script=(
        'set -e; mkdir -p /var/lib/webosbrew/init.d; '
        'test ! -e '+shlex.quote(path)+' || test -e /var/lib/webosbrew/ad-killer.pre-webos-easy || '
        'cp -p '+shlex.quote(path)+' /var/lib/webosbrew/ad-killer.pre-webos-easy; '
        'cp /tmp/webos-easy-ad-killer.new '+shlex.quote(upstream)+'; chmod 700 '+shlex.quote(upstream)+'; '
        'printf %s '+shlex.quote(AD_BOOT_WRAPPER)+' > '+shlex.quote(path)+'; chmod 700 '+shlex.quote(path)+'; '
        'rm -f /tmp/webos-easy-ad-killer.new; '+shlex.quote(upstream)+' --profile ads --dry-run'
    )
    r=ssh(ip,remote_script,timeout=100)
    if r.returncode:
        raise RuntimeError('Préparation antipub impossible : '+r.stderr[-500:])
    note('INFO','Aperçu du profil ads :\n'+r.stdout[-1250:])
    if not confirm('Appliquer maintenant et activer le hook au démarrage (avec deuxième passage différé) ?'):
        # Explicit cancellation also prevents the boot hook from unexpectedly
        # applying changes during the next restart.
        ssh(ip,shlex.join([upstream,'--disable']),timeout=35)
        note('WARN','Installation préparée mais désactivée ; rien ne sera appliqué au prochain démarrage.')
        return 'INSTALLE MAIS DESACTIVE'
    r=ssh(ip,shlex.join([upstream,'--profile','ads','--enable']),timeout=120)
    if r.returncode:
        ssh(ip,shlex.join([upstream,'--disable']),timeout=45)
        raise RuntimeError('Application antipub échouée (désactivée) : '+r.stderr[-500:])
    # Ensure run-parts actually accepts this hook filename.
    check=ad_status(ip,verbose=False)
    if 'run_parts_hook=NOT_RECOGNIZED' in check or 'hook=missing_or_not_executable' in check:
        raise RuntimeError('Antipub active seulement pour cette session : le hook ne sera pas exécuté au boot. Vérifier run-parts.')
    note('OK','Antipub ads activée. Hook enregistré, avec relance après démarrage. Vérifier après le prochain reboot via --ads-status.')
    return 'ACTIVE (BOOT À VÉRIFIER)'


def extract_pinned_github_tree(owner, repo, revision, directory):
    """HTTPS GitHub commit archive; extract regular files only, never links.

    Files are downloaded at the original author's pinned commit, not bundled
    into this MIT distribution. Revisions can be reviewed before upgrading.
    """
    if not re.fullmatch(r'[a-f0-9]{40}',revision):
        raise RuntimeError('Commit GitHub non epingle')
    url='https://api.github.com/repos/'+owner+'/'+repo+'/tarball/'+revision
    archive=lg_setup.get_bytes(url, max_bytes=60*1024*1024)
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tf:
        members=tf.getmembers()
        if len(members)>15000 or sum(m.size for m in members)>200*1024*1024:
            raise RuntimeError('Archive amont trop volumineuse')
        parents={m.name.split('/')[0] for m in members}
        if len(parents)!=1 or not next(iter(parents)).startswith(owner+'-'+repo+'-'):
            raise RuntimeError('Répertoire amont inattendu')
        for m in members:
            if m.isdir():continue
            if m.issym() or m.islnk():
                # Upstream archives may contain harmless symlinks (images, docs, etc.).
                # Never materialize links: preventing link-based path escapes is crucial.
                continue
            if not m.isfile():
                raise RuntimeError('Entrée spéciale d’archive interdite')
            parts=Path(m.name).parts
            if len(parts)<2 or m.name.startswith('/') or any(i in ('.','..') for i in parts):
                raise RuntimeError('Chemin archive interdit')
            dest=Path(directory).joinpath(*parts[1:])
            dest.parent.mkdir(parents=True,exist_ok=True)
            with tf.extractfile(m) as input_file, open(dest,'wb') as output:
                shutil.copyfileobj(input_file,output)
            # Preserve only the executable bit from the upstream archive.
            # Avoid setuid/setgid/sticky permission bits and writable-by-all files.
            dest.chmod(0o755 if (m.mode & 0o111) else 0o644)
    return Path(directory)


def slopbro_bootstrap(ip,mode):
    note('INFO','Projet officiel par throwaway96, AGPL-3.0-or-later : '+GIT_SLOPBRO)
    if mode=='test':
        note('TEST','Aucun exploit lancé. Vérifier SSAP (3000/3001) et compatibilité webOS sur le site de l’auteur.')
        return 'DIAGNOSTIC'
    if not sys.stdin.isatty():
        return 'ANNULE'
    note('WARN','SlopBro exploite une vulnérabilité privilégiée et peut modifier Homebrew et la persistance.')
    note('WARN','Ne pas utiliser sur une TV déjà rootée ; ne jamais redémarrer avant vérification.')
    if not confirm('La télévision est-elle à toi, encore NON ROOTÉE, et autorises-tu la tentative ?'):
        return 'ANNULE'
    version=input('  Version majeure webOS affichée sur la TV (ex: 6) : ').strip()
    if not re.fullmatch(r'(?:[4-9]|10|11)',version):
        note('WARN','Version non renseignée ou hors plage étudiée : abandon sans exploit.')
        return 'ANNULE'
    if not confirm('Dernière confirmation : lancer SlopBro officiel (peut modifier la TV) ?'):
        return 'ANNULE'
    with tempfile.TemporaryDirectory(prefix='slopbro-upstream-') as td:
        extract_pinned_github_tree('throwaway96','slopbro',SLOPBRO_COMMIT,td)
        source=Path(td)/'slopbro.py'
        copying=Path(td)/'COPYING'
        if not source.is_file() or not copying.is_file():
            raise RuntimeError('Sources/licence SlopBro absentes, exploitation refusée')
        proc=subprocess.run([sys.executable,str(source),'--webos-version',version,'--debug',ip],cwd=td,check=False)
        if proc.returncode:
            note('WARN','SlopBro s’est arrêté avec erreur ; examiner son journal et l’écran de la TV.')
            return 'ECHEC'
    note('WARN','Ne pas présumer que root est installé : Homebrew → Root status doit afficher OK.')
    note('WARN','Si root OK : enlever l’app LG Developer Mode avant le premier redémarrage, suivant l’amont.')
    return 'A VERIFIER SUR TV'


def install_glasshouse(ip, mode):
    if ssh_exists(ip,'/var/lib/tvweb/tvwebctl'):
        note('OK','Glasshouse déjà déployé.')
        return 'DEJA INSTALLE'
    if mode=='test':
        note('TEST','Glasshouse : clonage d’un commit épinglé et installation sous /var/lib/tvweb')
        return 'PRET'
    note('WARN','Glasshouse est un service web root. Un token fort sera généré et requis pour toute API.')
    if not confirm('Deployer Glasshouse depuis le GitHub de Rory Gallagher ?'):
        return 'ANNULE'
    with tempfile.TemporaryDirectory(prefix='glasshouse-') as td:
        extract_pinned_github_tree('rorygallagher2024', 'glasshouse', GLASS_COMMIT, td)
        token=secrets.token_urlsafe(32)
        folder=Path(td)/'server'
        if not (folder/'deploy.sh').is_file():
            raise RuntimeError('Deploy Glasshouse absent du snapshot')
        conf=folder/'config.json'
        conf.write_text(json.dumps({'port':8080,'host':'0.0.0.0','token':token,
                                    'allowControl':True,'update':{'check':False}},indent=2)+'\n')
        conf.chmod(0o600)
        run=subprocess.run(['bash',str(folder/'deploy.sh'),ip],cwd=folder,check=False,
                           text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
        if run.returncode:
            raise RuntimeError('Déploiement Glasshouse échoué : '+run.stdout[-1000:])
        # Never display token or put it on the clipboard automatically.
        creds=Path.home()/'.config'/'webos-easy-setup'
        creds.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=creds/('glasshouse-'+ip+'.json')
        target.write_text(json.dumps({'ip':ip,'port':8080,'token':token},indent=2)+'\n')
        target.chmod(0o600)
        note('OK','Glasshouse installé. Jeton conservé en 0600 : '+str(target))
        note('INFO','Dashboard : http://'+ip+':8080/ ; saisir le jeton une seule fois via l’interface.')
        note('WARN','Ne jamais rediriger le port 8080 vers Internet.')
    return 'INSTALLE'


def root_diagnostic(ip):
    note('INFO','Root déjà confirmé via SSH ; SlopBro par throwaway96 : '+GIT_SLOPBRO)
    note('INFO','Crédits : throwaway96 (AGPL-3.0-or-later), webOS Homebrew et contributeurs jsbro-autoroot.')
    note('INFO','La TV possède déjà root via SSH; SlopBro ne sera pas relancé.')
    return 'OK'


def run_plan(mode, selected, ip):
    if not valid_ip(ip):
        raise ValueError('Adresse IPv4 invalide')
    print('\n'+'='*70)
    print(' webOS EASY SETUP v'+VERSION+' | '+('TEST' if mode=='test' else 'APPLIQUER')+' | TV '+ip)
    print(' Modules : '+', '.join(name for name in selected))
    print('='*70)
    if 'ads' in selected and 'undo_ads' in selected:
        note('ERR','Modules antipub et restauration sélectionnés ensemble : choix incompatibles. Aucun changement effectué.')
        return 2
    for port,title in ((22,'SSH root'),(23,'Telnet'),(9922,'SSH developpeur')):
        note('INFO',f'{title} port {port} : '+('ouvert' if tcp(ip,port) else 'ferme'))
    if tcp(ip,23):
        note('WARN','Port 23 ouvert : Telnet root sans authentification possible. Désactiver après mise en place des clés SSH.')
    if not root_ok(ip):
        # An owner intentionally selecting the exploit can run it while SSH
        # root is absent, but no other module runs in this state.
        if 'slopbro' in selected and not tcp(ip,22):
            note('WARN','Aucun SSH root sur la TV; seule l’option SlopBro sera envisagée.')
            return 0 if slopbro_bootstrap(ip,mode)!='ECHEC' else 2
        note('WARN','Root SSH par clé non disponible. Root status Homebrew est indépendant de SSH.')
        note('INFO','Active SSH dans Homebrew et verifie la clé hôte SSH de la TV.')
        if mode=='apply' and shutil.which('ssh-copy-id') and confirm('Configurer une clé SSH root pour cette TV ?'):
            key=Path.home()/'.ssh/id_ed25519'
            if not key.with_suffix('.pub').is_file():
                note('INFO','Generation d’une clé Ed25519 sur le PC (phrase de passe recommandée).')
                key.parent.mkdir(parents=True,exist_ok=True)
                subprocess.run(['ssh-keygen','-t','ed25519','-f',str(key)],check=False)
            if key.with_suffix('.pub').is_file():
                note('INFO','Mot de passe root initial Homebrew : alpine (si aucune clé SSH autorisée ; peut être modifié).')
                note('WARN','Saisir le mot de passe UNIQUEMENT dans ssh-copy-id ; ne jamais le publier.')
                subprocess.run(['ssh-copy-id','-i',str(key.with_suffix('.pub')),'root@'+ip],check=False)
        if not root_ok(ip):
            note('ERR','SSH root toujours indisponible. Aucune modification de la TV.')
            note('INFO','Tester manuellement: ssh root@'+ip+' "id -u"')
            note('INFO','Pour sécuriser: redemarrer apres ajout de la clé; puis couper Telnet.')
            return 2
    note('OK','SSH root authentifié (UID 0).')
    apps = cached_apps(ip)
    if apps:
        note('OK',str(len(apps))+' applications inventoriées, aucun effacement automatique.')
    results = []
    for mod in selected:
        label=next((name for k,name,_ in MODULES if k==mod),mod)
        print('\n'+'-'*70+'\n '+label+'\n'+'-'*70)
        try:
            if mod in CATALOG:
                result=install_catalog_app(ip,mod,mode,apps)
            elif mod=='ads':result=ad_killer(ip,mode)
            elif mod=='undo_ads':result=ad_killer(ip,mode,undo=True)
            elif mod=='glasshouse':result=install_glasshouse(ip,mode)
            elif mod=='system':result=manage_system(ip,mode,apps or [])
            elif mod=='apps':result=manage_installed(ip,mode)
            elif mod=='services':result=manage_services(ip,mode)
            elif mod=='slopbro':result=root_diagnostic(ip)
            else:result='IGNORE'
            results.append((label,result))
        except (Exception,KeyboardInterrupt) as exc:
            note('ERR',str(exc)); results.append((label,'ERREUR'))
    print('\n'+'='*70+'\n  BILAN\n'+'='*70)
    for label,result in results:
        note('OK' if result not in ('ERREUR', 'GLASSHOUSE REQUIS','OPTION EXPERIMENTALE DESACTIVEE') else 'WARN', f'{label:34} {result}')
    print('  Jellyfin LG officiel et systeme : aucune desinstallation automatique.')
    print('='*70)
    return 2 if any(x=='ERREUR' for _,x in results) else 0


if __name__ == '__main__':
    print('Use: python3 clean_webos.py [--ip TV_IP]')
    sys.exit(2)

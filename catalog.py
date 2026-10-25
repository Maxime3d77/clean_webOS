#!/usr/bin/env python3
"""webOS TV Easy Setup — safe, community-driven deployment via LG's ares CLI.

Python >= 3.9, standard library only. Does NOT root a TV or uninstall TV apps.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

CATALOG = 'https://repo.webosbrew.org/api/apps.json'
APP_IDS = {
    'homebrew': 'org.webosbrew.hbchannel',
    'youtube': 'youtube.leanback.v4',
    'token': 'com.pirate.refresh',
    'mapper': 'org.webosbrew.inputhook',
    'aerial': 'org.aabytt.webos.custom-screensaver-aerial',
}
ROOT_ONLY = {'mapper', 'aerial'}
MAX_IPK_BYTES = 120 * 1024 * 1024
USER_AGENT = 'webos-tv-easy-setup/2.3 (community installer)'
AD_KILLER_SOURCE = 'https://raw.githubusercontent.com/nurikk/lg-webos-ad-killer/master/ad_killer'
GUARDED = ('youtube.leanback.v4', 'org.webosbrew.hbchannel', 'org.jellyfin.webos')


class SetupError(Exception):
    pass


# Installer CLI menu: all network operations and TV changes happen AFTER selection.
MENU_ITEMS = (
    ('homebrew', 'Homebrew Channel', 'Catalogue communautaire. Deja installe ? L installateur le detecte.', 'Sans root'),
    ('youtube', 'YouTube AdFree', 'YouTube sans pub ; preparation possible sans supprimer YouTube officiel.', 'Sans root'),
    ('token', 'Auto Dev Token Refresh', 'Renouvelle le mode developpeur ; utilise un service tiers pour le token.', 'Sans root'),
    ('mapper', 'LG Input Hook', 'Reattribuer les touches Netflix/Prime/etc. ; configuration sur la TV ensuite.', 'Root necessaire'),
    ('aerial', 'Aerial Screensaver', 'Videos panoramiques style Apple TV. Remplace l economiseur LG.', 'Root necessaire'),
    ('ads', 'Reduction pubs accueil', 'Module antipub externe : revue du script + consentement obligatoires.', 'Root necessaire'),
    ('cleanup', 'Nettoyage des applications', 'Voir les applications developpeur ; aucune suppression automatique.', 'Mode guide'),
    ('guide', 'Diagnostic / guide root', 'Compatibilite firmware et liens de methodes verifiees, sans exploit.', 'Lecture seule'),
)


def interactive_choice(input_fn=input, output=None):
    """Ask exactly once for one or more installer modules; stdout stays machine-readable."""
    out = output if output is not None else sys.stderr
    print('\n=== webOS Easy Setup : que souhaitez-vous installer ? ===', file=out)
    print('Selection multiple : 2,3,5 ; Entree = YouTube + renouvellement ; 0 = annuler', file=out)
    for i, (key, title, description, need) in enumerate(MENU_ITEMS, 1):
        print(f'  {i}. {title} [{need}]\n     {description}', file=out)
    if not sys.stdin.isatty() and input_fn is input:
        raise SetupError('Menu interactif indisponible ; utiliser --apps youtube,token (ou --all).')
    print('\nVos choix [2,3] : ', end='', file=out, flush=True)
    raw = input_fn('').strip()
    if raw == '0':
        return []
    if not raw:
        return ['youtube', 'token']
    parts = [item.strip() for item in raw.replace(';', ',').split(',')]
    if any(not item.isdigit() or not 1 <= int(item) <= len(MENU_ITEMS) for item in parts):
        raise SetupError('Choix incorrect : saisir des numeros entre 1 et 8 separes par des virgules.')
    return list(dict.fromkeys(MENU_ITEMS[int(n)-1][0] for n in parts))


def show_root_guide():
    note('\n=== ROOT : ETAT ET PRECAUTIONS ===')
    note('Exemple LG 75NANO926PB (webOS 6.5.3, firmware 03.53.45) : root NON etabli.')
    note('RootMyTV v2 est corrige sur les firmwares webOS 6 recents.')
    note('faultmanager-autoroot : le mainteneur signale que la quasi-totalite des derniers firmwares webOS 6 sont corriges.')
    note('Verifier modele, OTAID et version EXACTE avant toute tentative :')
    note('  https://cani.rootmy.tv/')
    note('  https://www.webosbrew.org/rooting/')
    note('  https://github.com/throwaway96/faultmanager-autoroot')
    note('Pas de root automatique, pas de downgrade, aucune modification systeme ici.')


def show_cleanup_guide():
    note('\n=== NETTOYAGE SANS RISQUE ===')
    note('Inventaire applications developpeur : ./install.sh --list')
    note('Suppression une par une : ./install.sh --remove-id IDENTIFIANT')
    note('Les applications LG/du Content Store et Jellyfin officiel sont preserves.')
    note('Masquer les apps et recommandations LG dans les menus natifs de la TV.')


def note(message):
    print(message, flush=True)


def ask_exact(question, expected, *, provided=False):
    """Never bypass an important consent by --yes."""
    if provided:
        return True
    if not sys.stdin.isatty():
        raise SetupError(f'{question} — validation interactive requise, voir --help')
    response = input(f'{question}\nConfirmer ? [o/N] : ').strip().casefold()
    return response in ('o','oui','y','yes')


def https_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise SetupError('URL HTTPS valide nécessaire : ' + str(url))
    return url


def get_bytes(url, *, max_bytes=MAX_IPK_BYTES):
    https_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json, application/octet-stream'})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if urllib.parse.urlsplit(response.geturl()).scheme != 'https':
                raise SetupError('Redirection non HTTPS refusée')
            length = response.headers.get('Content-Length')
            if length and int(length) > max_bytes:
                raise SetupError('Téléchargement trop volumineux')
            chunks = []
            total = 0
            while True:
                part = response.read(1024 * 1024)
                if not part:
                    break
                total += len(part)
                if total > max_bytes:
                    raise SetupError('Taille maximale dépassée')
                chunks.append(part)
            return b''.join(chunks)
    except SetupError:
        raise
    except Exception as exc:
        raise SetupError(f'Téléchargement impossible ({url}) : {exc}') from exc


def get_json(url):
    try:
        data = json.loads(get_bytes(url, max_bytes=5 * 1024 * 1024).decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError('objet JSON attendu')
        return data
    except (ValueError, UnicodeDecodeError) as exc:
        raise SetupError(f'JSON invalide ({url}) : {exc}') from exc


def lookup_package(app_id, *, catalog=CATALOG, loader=get_json):
    """Support webOS Brew's paginated package index and inline/external manifests."""
    first = loader(catalog)
    collections = [(catalog, first)]
    paging = first.get('paging') or {}
    try:
        total_pages = min(max(int(paging.get('maxPage', 1)), 1), 20)
    except (TypeError, ValueError):
        total_pages = 1
    # The official index advertises additional pages at apps/{n}.json.
    for page in range(2, total_pages + 1):
        page_url = urllib.parse.urljoin(catalog, f'apps/{page}.json')
        collections.append((page_url, loader(page_url)))
    for source_url, collection in collections:
        for entry in collection.get('packages', []):
            if not isinstance(entry, dict) or entry.get('id') != app_id:
                continue
            if isinstance(entry.get('manifest'), dict):
                return entry['manifest'], source_url
            manifest_url = entry.get('manifestUrl')
            if manifest_url:
                resolved = urllib.parse.urljoin(source_url, manifest_url)
                https_url(resolved)
                return loader(resolved), resolved
            # Some mirrors expose flat package records.
            if entry.get('ipkUrl'):
                return entry, source_url
    raise SetupError(f'Application {app_id} absente du catalogue webOS Brew')


def package_details(app_id, *, catalog=CATALOG, loader=get_json):
    manifest, base_url = lookup_package(app_id, catalog=catalog, loader=loader)
    if manifest.get('id') != app_id:
        raise SetupError('Identifiant d’application incohérent dans le manifeste')
    ipk = manifest.get('ipkUrl')
    if not isinstance(ipk, str) or not ipk:
        raise SetupError('Manifeste sans ipkUrl')
    url = urllib.parse.urljoin(base_url, ipk)
    https_url(url)
    hashes = manifest.get('ipkHash') or {}
    digest = hashes.get('sha256') if isinstance(hashes, dict) else None
    if not digest:
        digest = manifest.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-fA-F]{64}', digest):
        raise SetupError(f'Aucun SHA-256 fiable pour {app_id} : installation refusée')
    return {'id': app_id, 'version': str(manifest.get('version', '?')),
            'url': url, 'sha256': digest.lower(), 'root_required': bool(manifest.get('rootRequired', False))}


def check_ipk(blob, expected_sha256):
    if not blob.startswith(b'!<arch>\n'):
        raise SetupError('Fichier reçu non reconnu comme paquet IPK (archive ar)')
    got = hashlib.sha256(blob).hexdigest()
    if got.lower() != expected_sha256.lower():
        raise SetupError(f'SHA-256 incorrect : attendu {expected_sha256}, obtenu {got}')
    return got


def run(command, *, env=None, timeout=120, capture=False):
    note('$ ' + ' '.join(command))
    try:
        return subprocess.run(command, check=True, env=env, timeout=timeout,
                              text=True, stdout=subprocess.PIPE if capture else None,
                              stderr=subprocess.PIPE if capture else None)
    except FileNotFoundError as exc:
        raise SetupError('Commande introuvable : ' + command[0]) from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        extra = ((getattr(exc, 'stderr', None) or '')[-1000:]).strip()
        raise SetupError(f'Commande échouée : {command[0]} {extra}') from exc


def cli_env(args):
    env = os.environ.copy()
    conf = args.openssl_conf
    if conf:
        config_path = Path(conf).expanduser()
        if not config_path.is_file():
            raise SetupError(f'Configuration OpenSSL introuvable : {config_path}')
        env['OPENSSL_CONF'] = str(config_path.resolve())
    return env


def installed_dev_apps(device, env):
    response = run(['ares-install', '-d', device, '--list'], env=env, capture=True)
    output = response.stdout or ''
    # Supports both simple ID list and 'id : <id>' output.
    return set(re.findall(r'(?m)^\s*(?:id\s*:\s*)?([a-zA-Z][\w-]*(?:\.[\w-]+)+)\s*$', output))


def root_available(target):
    if not target:
        return False
    if target.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.@-]+', target):
        raise SetupError('--root-target doit être un alias SSH ou user@host valide')
    if not target.startswith('root@') and target != 'root':
        # Named SSH alias is allowed, but we validate uid=0 remotely.
        note('Vérification UID=0 sur la cible SSH spécifiée…')
    completed = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                                '-o', 'StrictHostKeyChecking=yes', target, 'id', '-u'],
                               capture_output=True, text=True, timeout=12, check=False)
    return completed.returncode == 0 and completed.stdout.strip() == '0'


def install_one(name, args, env, installed, root=False):
    app_id = APP_IDS[name]
    if app_id in installed and not args.force_update:
        note(f'✓ {name} déjà présent parmi les applications développeur (utiliser --force-update pour réinstaller).')
        return True
    if name == 'youtube' and app_id not in installed and not args.dry_run:
        if not ask_exact('YouTube officiel doit être désinstallé sur la TV avant cette étape. Est-ce fait ?',
                         'YOUTUBE SUPPRIME', provided=args.youtube_official_removed):
            note('⏭ YouTube ignoré : désinstallation officielle non confirmée.')
            return False
    if name == 'youtube' and args.dry_run and not args.youtube_official_removed:
        note('Attention : YouTube officiel devra être désinstallé/confirmé avant l’installation.')
    pkg = package_details(app_id)
    if pkg['root_required'] and not root:
        raise SetupError('Le manifeste webOS Brew exige root : aucune installation effectuée')
    note(f'📦 {name} : version {pkg["version"]} — {pkg["url"]}')
    if args.dry_run:
        note('Mode simulation : aucun téléchargement IPK ni installation.')
        return True
    data = get_bytes(pkg['url'])
    digest = check_ipk(data, pkg['sha256'])
    note(f'✓ SHA-256 vérifié : {digest}')
    with tempfile.TemporaryDirectory(prefix='webos-easy-') as tmp:
        path = Path(tmp) / f'{app_id}.ipk'
        path.write_bytes(data)
        run(['ares-install', '-d', args.device, str(path)], env=env, timeout=180)
    if args.launch and name in {'youtube', 'token', 'homebrew', 'mapper', 'aerial'}:
        try:
            run(['ares-launch', '-d', args.device, app_id], env=env)
        except SetupError as exc:
            note(f'ℹ Installation OK, lancement non confirmé : {exc}')
    return True


def ad_cleanup(args):
    """Root-only, explicit opt-in. Keep this module entirely separate from ares installs."""
    if not args.ad_cleanup:
        return
    if not args.root_target:
        note('⏭ Antipub d’accueil : --root-target absent, aucune modification.')
        return
    note('Antipub LG : profil ads (pas le profil privacy qui coupe aussi la voix et ThinQ).')
    script = get_bytes(AD_KILLER_SOURCE, max_bytes=2 * 1024 * 1024)
    if not script.startswith(b'#!'):
        raise SetupError('Script amont inattendu : aucun fichier appliqué')
    digest = hashlib.sha256(script).hexdigest()
    note(f'Script source : {AD_KILLER_SOURCE}\nSHA256 : {digest}')
    if args.dry_run:
        note('Simulation : aucun transfert et aucune modification.')
        return
    # A dedicated SSH root session is required; the script is not executed from a URL.
    with tempfile.TemporaryDirectory(prefix='webos-ad-') as tmp:
        local = Path(tmp) / 'ad_killer'
        local.write_bytes(script)
        run(['scp', '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
             str(local), args.root_target + ':/tmp/webos_ad_killer_review'], timeout=90)
    run(['ssh', '-o', 'BatchMode=yes', args.root_target,
         'sh /tmp/webos_ad_killer_review --dry-run'], timeout=120)
    if not ask_exact('Appliquer ces changements réversibles au démarrage de la TV ?',
                     'APPLIQUER PUBS', provided=args.apply_ad_cleanup):
        note('⏭ Aucun changement sur le système. Fichier de revue présent dans /tmp.')
        return
    # Preserve any existing startup hook for rollback.
    remote = ('set -eu; mkdir -p /var/lib/webosbrew/init.d; '
              'd=/var/lib/webosbrew/init.d/ad_killer; '
              'if [ -e "$d" ]; then cp -p "$d" "$d.backup"; fi; '
              'cp /tmp/webos_ad_killer_review "$d"; chmod 700 "$d"; '
              '"$d" --profile ads')
    run(['ssh', '-o', 'BatchMode=yes', args.root_target, 'sh -c ' + shlex.quote(remote)], timeout=180)
    note('✓ Module antipub exécuté. Pour revenir en arrière : ssh root@TV /var/lib/webosbrew/init.d/ad_killer --disable')


def remove_dev_app(args, env, installed):
    app_id = args.remove_id
    if not app_id:
        return
    if app_id in GUARDED or app_id.startswith(('com.webos.', 'com.palm.', 'com.lge.')):
        raise SetupError(f'Application protégée : {app_id}')
    if app_id not in installed:
        raise SetupError('Suppression refusée : application absente de la liste développeur (apps LG préservées)')
    if not ask_exact(f'Supprimer uniquement l’application développeur {app_id} ?',
                     f'SUPPRIMER {app_id}'):
        note('Suppression annulée.')
        return
    if args.dry_run:
        note('Simulation : rien à supprimer.')
    else:
        run(['ares-install', '-d', args.device, '--remove', app_id], env=env)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Configuration prudente LG webOS via Developer Mode')
    parser.add_argument('--choose', action='store_true', help='Menu interactif de selection (sans connexion TV)')
    parser.add_argument('--root-guide', action='store_true', help='Guide de compatibilite root sans exploit')
    parser.add_argument('--cleanup-guide', action='store_true', help='Conseils de nettoyage sans supprimer d application')
    parser.add_argument('--skip-connection', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--device', default='lg-tv', help='Nom du device ares (défaut lg-tv)')
    parser.add_argument('--openssl-conf', help='Fichier OpenSSL isolé si SSH RSA historique')
    parser.add_argument('--all', action='store_true', help='Youtube + token + mapper + aerial (+ publicité si root et --ad-cleanup)')
    parser.add_argument('--apps', default='youtube,token', help='Liste homebrew,youtube,token,mapper,aerial (défaut youtube,token)')
    parser.add_argument('--dry-run', action='store_true', help='Simulation : aucune modification de la TV')
    parser.add_argument('--launch', action='store_true', help='Lancer chaque application installée')
    parser.add_argument('--force-update', action='store_true', help='Réinstaller également les apps déjà présentes en mode développeur')
    parser.add_argument('--youtube-official-removed', action='store_true', help='Confirmer explicitement la désinstallation préalable du YouTube LG officiel')
    parser.add_argument('--root-target', help='Cible SSH root sur port 22, ex. root@192.168.1.50 (clé et host key déjà configurées)')
    parser.add_argument('--ad-cleanup', action='store_true', help='Module antipub LG réversible (root et approbation indispensables)')
    parser.add_argument('--apply-ad-cleanup', action='store_true', help='Consentement explicite à installer ad_killer après dry-run, exige aussi --ad-cleanup')
    parser.add_argument('--renew', action='store_true', help='Renouveler la session développeur via ares-extend-dev')
    parser.add_argument('--list', action='store_true', help='Lister les applications développeur')
    parser.add_argument('--remove-id', help='Désinstaller une application développeur non protégée, après confirmation exacte')
    parser.add_argument('--doctor', action='store_true', help='Tester les prérequis locaux et afficher les paramètres')
    args = parser.parse_args(argv)

    if args.choose:
        names_chosen = interactive_choice()
        print(','.join(names_chosen))
        return 0
    if args.root_guide:
        show_root_guide()
    if args.cleanup_guide:
        show_cleanup_guide()
    if (args.root_guide or args.cleanup_guide) and not (args.apps != 'youtube,token' or args.all or args.ad_cleanup or args.list or args.renew or args.remove_id):
        return 0
    if args.skip_connection and not args.dry_run:
        parser.error('--skip-connection exige --dry-run')

    if args.apply_ad_cleanup and not args.ad_cleanup:
        parser.error('--apply-ad-cleanup nécessite --ad-cleanup')
    if args.all:
        names = list(APP_IDS)
    else:
        names = [s.strip() for s in args.apps.split(',') if s.strip()]
    bad = set(names) - set(APP_IDS)
    if bad:
        parser.error('Application inconnue : ' + ', '.join(sorted(bad)))
    names = list(dict.fromkeys(names))
    env = cli_env(args)

    if args.doctor:
        note('=== webOS Easy Setup | Diagnostic local ===')
        for command in ('ares-install', 'ares-launch', 'ares-device', 'ares-extend-dev', 'ssh', 'scp'):
            note(f'{command}: {shutil.which(command) or "ABSENT"}')
        note(f'Device : {args.device} | OpenSSL_CONF : {env.get("OPENSSL_CONF", "hérité / non défini")}')
        return 0
    if args.renew:
        if args.dry_run:
            note(f'Simulation : ares-extend-dev -d {args.device}')
        else:
            run(['ares-extend-dev', '-d', args.device], env=env)
        return 0

    if not shutil.which('ares-install'):
        raise SetupError('Installer Node.js puis : npm install -g @webos-tools/cli')
    if args.dry_run:
        note('=== SIMULATION (aucune suppression ni installation) ===')
    else:
        note('=== webOS TV Easy Setup ===')
    if args.skip_connection:
        note('Simulation hors connexion : TV non authentifiee ; inventaire inconnu.')
        installed = set()
    else:
        run(['ares-device', '-i', '-d', args.device], env=env, timeout=40)
        installed = installed_dev_apps(args.device, env)
    note('Applications développeur : ' + (', '.join(sorted(installed)) or '(aucune)'))
    if args.list:
        return 0
    if args.remove_id:
        remove_dev_app(args, env, installed)
        return 0

    root = False
    if args.root_target:
        root = root_available(args.root_target)
        note('Accès SSH root : ' + ('confirmé' if root else 'non confirmé'))
    outcome = []
    for name in names:
        if name in ROOT_ONLY and not root:
            note(f'⏭ {name} nécessite root : installation ignorée sans modification.')
            outcome.append((name, 'root requis'))
            continue
        try:
            ok = install_one(name, args, env, installed, root=root)
            outcome.append((name, 'OK' if ok else 'ignoré'))
        except SetupError as exc:
            note(f'✗ {name} : {exc}')
            outcome.append((name, 'ERREUR'))

    if args.ad_cleanup:
        if not root:
            note('⏭ Antipub LG requiert root ; opération ignorée.')
        else:
            ad_cleanup(args)
    note('\n=== RÉCAPITULATIF ===')
    for name, state in outcome:
        note(f'{name:10s} {state}')
    note('Jellyfin LG et les applications système n’ont pas été modifiées.')
    if not root:
        note('Sans root : désactiver les recommandations et mises à jour automatiques dans les menus LG (voir docs).')
    if 'token' in names and not args.dry_run:
        note('Auto Dev Token Refresh : ouvrir l’app et approuver « Renew Automatically » ; service externe tiers.')
    return 1 if any(state == 'ERREUR' for _, state in outcome) else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SetupError, KeyboardInterrupt) as exc:
        note('ERREUR / ANNULATION : ' + str(exc))
        sys.exit(2)

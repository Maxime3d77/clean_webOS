# Guide de démarrage en français

Ce guide complète le [README principal en anglais](../README.md). L'assistant s'affiche en français si tu sélectionnes **Français** au démarrage.

## Démarrage

Depuis un terminal **Bazzite avec ton compte normal**, pas `root` :

```bash
git clone https://github.com/Maxime3d77/clean_webOS.git
cd clean_webOS
bash install.sh --ip 192.168.1.24
```

Le lanceur cherche Python 3, SSH et SCP. Il propose de préparer les prérequis si nécessaire. Sur Bazzite, il n'installe **rien sur le système immuable** : il peut utiliser Toolbx avec ton accord.

Au démarrage, choisis **Français**, puis **TESTER** (recommandé) ou **APPLIQUER**. Utilise les **flèches** pour naviguer, **Espace** pour cocher des modules, **Entrée** pour avancer, `B` pour revenir et `Q` pour quitter. Si le menu s'affiche mal, utilise `bash install.sh --text`.

## Ordre des étapes

1. **Diagnostic / root** : l'assistant recherche l'accès SSH root. Si Homebrew indique déjà **Root status OK** après un redémarrage, ne relance **jamais** SlopBro. Active SSH depuis Homebrew, installe ta clé SSH et coupe Telnet. **Mot de passe root initial : `alpine`** (uniquement avant la mise en place des clés SSH, et seulement s’il n’a pas été modifié). Si la TV n'est pas rootée, le programme propose facultativement [SlopBro de throwaway96](https://github.com/throwaway96/slopbro), avec avertissements et confirmations ; aucune compatibilité n'est garantie.
2. **Homebrew Channel** : SlopBro l'installe normalement. Sinon, le programme peut proposer l'installateur officiel sur une TV rootée. Dans Homebrew : vérifie Root OK, active SSH, configure une clé puis coupe Telnet. L'application LG **Developer Mode doit être désinstallée après un root réussi et avant le premier redémarrage**, conformément aux consignes SlopBro.
3. **Applications** : choisis LG Input Hook, Aerial, YouTube AdFree, Glasshouse. Le script n'efface ni Jellyfin ni YouTube LG d'office.
4. **Pubs** : active le profil restreint et réversible `ads` de LG Ad Killer ; sélectionne **Restaurer** dans le menu en cas de besoin.
5. **Apps système** : utilise Glasshouse pour inventorier et **masquer/démasquer** des icônes LG, sans supprimer les composants système. Active l'option expérimentale seulement si tu acceptes le risque de redémarrage du gestionnaire d'applications.
6. **Services secondaires** : liste ceux proposés par Glasshouse, coche ceux à désactiver et valide. Tu peux aussi les réactiver.

## Après l'installation

- **LG Input Hook** : ouvre l'app au moins une fois, ajoute un raccourci et lis le code du bouton dans les logs ; associe l'action souhaitée et sauvegarde.
- **Aerial** : ouvre l'app, sélectionne les vidéos (Full HD / 4K), active **Autostart**, appuie sur **Apply** puis **Test**.
- **Glasshouse** : ouvre `http://IP_DE_LA_TV:8080/` sur ton réseau local. Protège ton jeton et ne redirige jamais ce port sur Internet.
- **Antipub** : il peut falloir recharger l'accueil. Le blocage est réversible ; toutes les pubs futures ne sont pas garanties supprimées.
  Si les pubs réapparaissent au redémarrage, relance **APPLIQUER → Antipub** avec la v5.1, puis redémarre et vérifie que le hook s’est exécuté en lançant :

  ```bash
  python3 clean_webos.py --ip 192.168.1.24 --ads-status
  ```

  Le rapport doit indiquer `hook=executable`, `disabled=no` et les lignes `FIRST PASS` / `DELAYED PASS exit=0`. Le fichier `/var/lib/webosbrew/ad_killer_boot.log` conserve les résultats. **N’utilise pas le profil `privacy`** si tu souhaites conserver les commandes vocales et ThinQ.

Le programme **ne bloque pas les mises à jour LG** : conserver une ancienne version de firmware comporte aussi des risques de sécurité. Ne connecte jamais SSH root ou Telnet à Internet.

## Remerciements

Un grand merci à **throwaway96** pour SlopBro (AGPL-3.0-or-later), à **webOS Homebrew**, ainsi qu'à **Simon34545**, **aabytt**, **nurikk**, **Rory Gallagher** et à leurs contributeurs pour les outils originaux. Consulte [CREDITS.md](../CREDITS.md) et leurs licences.

## Aide SSH : mot de passe par défaut

Lorsqu’Homebrew Channel est utilisé pour la première fois et que `authorized_keys` n’existe pas, il peut activer **`root` / `alpine`** pour la première authentification SSH. Ce n’est pas le mot de passe de ton compte LG. Une fois ta clé publique copiée et la TV redémarrée, utilise **la clé SSH** plutôt que de compter sur ce mot de passe connu.

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@192.168.1.24
ssh root@192.168.1.24 'id -u'
```

La réponse attendue est `0`. Il faut ensuite **couper Telnet** dans Homebrew : il peut exposer un terminal root sans authentification sur le réseau local.

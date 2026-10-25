"""Offline unit tests. No TV or Internet is required."""
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import clean_webos as w
import engine as e


class WizardTests(unittest.TestCase):
    def test_six_complete_locales(self):
        en=set(w.locale_data('en'))
        for lang in w.LANGUAGES:
            self.assertEqual(set(w.locale_data(lang)),en)
            self.assertTrue(w.locale_data(lang)['root_credits'])
        self.assertEqual(len(w.LANGUAGES),6)

    def test_ip_validation(self):
        self.assertTrue(w.validate_ip('192.168.1.24'))
        for text in ('', 'example.com', '256.1.2.3','[::1]','192.168.1.24; reboot'):
            self.assertFalse(w.validate_ip(text))

    def test_plan_module_order(self):
        result=w.plan_modules(['ads','mapper','glasshouse','system'])
        self.assertEqual(result,['glasshouse','mapper','ads','system'])
        with self.assertRaises(ValueError):
            w.plan_modules(['ads','undo_ads'])

    def test_invalid_plan(self):
        with self.assertRaises(ValueError):
            w.Plan('en','apply','192.168.1.24',('unknown',)).validate()
        with self.assertRaises(ValueError):
            w.Plan('en','apply','192.168.1.24',('ads','undo_ads')).validate()

    def test_no_exploit_or_homebrew_writes_in_test_without_root(self):
        plan=w.Plan('en','test','192.168.1.24',('mapper','ads'))
        with patch.object(w,'environment_check',return_value=True), \
             patch.object(e,'tcp',return_value=False), \
             patch.object(e,'root_ok',return_value=False), \
             patch.object(e,'slopbro_bootstrap') as exploit, \
             patch.object(e,'ensure_homebrew') as hbc, \
             patch.object(e,'run_plan') as runner, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(w.execute(plan),0)
            exploit.assert_not_called()
            hbc.assert_not_called()
            runner.assert_not_called()

    def test_rooted_apply_flow_hbc_before_apps(self):
        plan=w.Plan('fr','apply','192.168.1.24',('mapper','ads'))
        events=[]
        with patch.object(w,'environment_check',return_value=True), \
             patch.object(e,'tcp',return_value=False), \
             patch.object(e,'root_ok',return_value=True), \
             patch.object(e,'cached_apps',side_effect=lambda ip: events.append('inventory') or []), \
             patch.object(e,'ensure_homebrew',side_effect=lambda ip,mode,apps: events.append('homebrew') or 'INSTALLED'), \
             patch.object(e,'run_plan',side_effect=lambda mode,mods,ip: events.append('modules') or 0), \
             patch.object(e,'slopbro_bootstrap') as exploit, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(w.execute(plan),0)
            exploit.assert_not_called()
            self.assertEqual(events,['inventory','homebrew','modules'])

    def test_test_mode_homebrew_not_installed(self):
        with patch.object(e,'lg_setup') as package,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(e.ensure_homebrew('192.168.1.24','test',[]),'CHECK')
            package.get_bytes.assert_not_called()

    def test_apps_protected(self):
        for appid in ('com.webos.app.home','org.webosbrew.hbchannel','org.jellyfin.webos','org.unknown.jellyfin'):
            self.assertTrue(e.protected({'id':appid}))
        self.assertFalse(e.protected({'id':'com.webos.app.music'}))

    def test_no_token_refresh_module(self):
        self.assertNotIn('token', w.MODULES)
        self.assertNotIn('token',[k for k,_,_ in e.MODULES])

    def test_pinned_revisions(self):
        import re
        for value in (e.SLOPBRO_COMMIT,e.GLASS_COMMIT,e.AD_REV,e.HB_INSTALL_REV):
            self.assertRegex(value,r'^[a-f0-9]{40}$')

    def test_ads_test_does_not_download_or_apply(self):
        with patch.object(e,'ssh_exists',return_value=False), \
             patch.object(e,'ssh',return_value=type('R',(),{'returncode':0,'stdout':'hook=executable\n','stderr':''})()) as ssh, \
             patch.object(e.lg_setup,'get_bytes') as download, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(e.ad_killer('192.168.1.24','test'),'DIAGNOSTIC')
            self.assertEqual(ssh.call_count,1)
            self.assertIn('run-parts --test',ssh.call_args.args[1])
            download.assert_not_called()

    def test_manage_services_test_only_read(self):
        state={'ok':True,'supported':True,'services':[{'id':'nudge','title':'Promotions','disabled':False,'desc':'Tips'}]}
        with patch.object(e,'json_from_glass',return_value=state) as client, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(e.manage_services('192.168.1.24','test'),'INVENTORY')
            client.assert_called_once_with('192.168.1.24','/api/services')

    def test_service_allowlist_excludes_critical(self):
        self.assertIn('nudge',e.GLASSHOUSE_SERVICE_ALLOWLIST)
        self.assertNotIn('sam',e.GLASSHOUSE_SERVICE_ALLOWLIST)
        self.assertNotIn('surface-manager',e.GLASSHOUSE_SERVICE_ALLOWLIST)

    def test_ssh_requires_uid_zero(self):
        with patch.object(e,'ssh',return_value=type('Result',(),{'returncode':0,'stdout':'6877\n'})()):
            self.assertFalse(e.root_ok('192.168.1.24'))
        with patch.object(e,'ssh',return_value=type('Result',(),{'returncode':0,'stdout':'0\n'})()):
            self.assertTrue(e.root_ok('192.168.1.24'))

    def test_youtube_store_preserved(self):
        apps=[{'id':'youtube.leanback.v4','folderPath':'/media/cryptofs/apps/usr/palm/applications/youtube.leanback.v4'}]
        with patch.object(e.lg_setup,'package_details',return_value={'version':'0.5.3'}), \
             patch.object(e,'install_homebrew_package') as install, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(e.install_catalog_app('192.168.1.24','youtube','apply',apps),'OFFICIEL CONSERVE')
            install.assert_not_called()

    def test_glasshouse_api_path_validation(self):
        for path in ('http://example.com','/api/../etc','/api/apps?url=bad'):
            with self.assertRaises(ValueError):
                e.json_from_glass('192.168.1.24',path)


    def test_upstream_extraction_ignores_symlinks_and_preserves_safe_executable_bit(self):
        import tarfile, io, tempfile
        data=io.BytesIO()
        prefix='testorigin-demoroot-0123456/'
        with tarfile.open(fileobj=data,mode='w:gz') as tar:
            for path,payload,mode in [('run.sh',b'#!/bin/sh\necho ok\n',0o755),('README.md',b'hello',0o644)]:
                info=tarfile.TarInfo(prefix+path)
                info.size=len(payload);info.mode=mode
                tar.addfile(info,io.BytesIO(payload))
            link=tarfile.TarInfo(prefix+'evil-link')
            link.type=tarfile.SYMTYPE;link.linkname='/etc/shadow'
            tar.addfile(link)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(e.lg_setup,'get_bytes',return_value=data.getvalue()):
            e.extract_pinned_github_tree('testorigin','demoroot','a'*40,folder)
            self.assertTrue((Path(folder)/'run.sh').is_file())
            self.assertTrue((Path(folder)/'run.sh').stat().st_mode & 0o100)
            self.assertFalse((Path(folder)/'evil-link').exists())

    def test_reject_traversal_from_upstream_tar(self):
        import tarfile, io, tempfile
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w:gz') as tar:
            payload=b'exit 0'
            info=tarfile.TarInfo('testorigin-demoroot-abc/../../escape')
            info.size=len(payload)
            tar.addfile(info,io.BytesIO(payload))
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(e.lg_setup,'get_bytes',return_value=buf.getvalue()):
            with self.assertRaises(RuntimeError):
                e.extract_pinned_github_tree('testorigin','demoroot','a'*40,folder)

    def test_ad_boot_wrapper_profile_and_disable_marker(self):
        import subprocess
        self.assertIn('--profile ads',e.AD_BOOT_WRAPPER)
        self.assertIn('sleep 35',e.AD_BOOT_WRAPPER)
        self.assertIn('ad-killer.disabled',e.AD_BOOT_WRAPPER)
        self.assertEqual(subprocess.run(['sh','-n'],input=e.AD_BOOT_WRAPPER,text=True).returncode,0)

    def test_root_password_help_in_all_six_languages(self):
        for lang in w.LANGUAGES:
            self.assertIn('alpine',w.locale_data(lang)['ssh_default_password'])

    def test_ads_status_cli_requires_ip(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                w.main(['--ads-status'])

if __name__=='__main__':
    unittest.main()

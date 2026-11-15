import io
from pathlib import Path
import sys
import tempfile
import shutil
import subprocess
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from package_audit import audit_deb, audit_bundle, check_stream, excluded, rules, safe_name


class PackagePolicyTests(unittest.TestCase):
    def bundle(self,root):
        (root/'_internal').mkdir();(root/'ClassroomPlus').write_bytes(b'application runtime')
        with zipfile.ZipFile(root/'_internal/base_library.zip','w') as archive:archive.writestr('standard_library.pyc',b'public runtime')
        return root
    def test_policy_blocks_private_files_and_development_tools(self):
        policy=rules()
        for name in ['.env','_internal/.env.local','data/roster.csv','_internal/lecture.json','_internal/.secrets/key.txt',
                     '_internal/student_templates.npz','_internal/models/weights.onnx','_internal/screenshot.png',
                     '_internal/IPython/__init__.py','_internal/notebook/app.py','_internal/.codex/config.toml',
                     '_internal/package.dist-info/direct_url.json','_internal/private.zip']:
            self.assertTrue(excluded(name,policy),name)
        for name in ['ClassroomPlus.exe','_internal/base_library.zip','_internal/certifi/cacert.pem','_internal/web/icon.svg']:
            self.assertFalse(excluded(name,policy),name)
    def test_bundle_manifest_contains_hashes_not_machine_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            report=audit_bundle(self.bundle(Path(folder)))
            self.assertEqual(report['kind'],'standalone');self.assertEqual(len(report['files']),2)
            self.assertEqual(len(report['files'][0]['sha256']),64)
            self.assertTrue(all(not Path(row['path']).is_absolute() for row in report['files']))
    def test_private_files_stop_a_distribution_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.bundle(Path(folder));(root/'_internal/.env').write_text('private configuration')
            with self.assertRaisesRegex(RuntimeError,'excluded by installer policy'):audit_bundle(root)
    def test_credentials_and_key_material_are_blocked(self):
        credential=('ghp_'+'a'*36).encode()
        with self.assertRaisesRegex(RuntimeError,'GitHub credential'):check_stream('runtime.dat',io.BytesIO(credential))
        header=b'-----BEGIN '+b'PRIVATE KEY-----'
        check_stream('crypto-parser.dll',io.BytesIO(header+b'\x00parser label'))
        with self.assertRaisesRegex(RuntimeError,'private key material'):check_stream('private.pem',io.BytesIO(header+b'\n'+b'a'*64))
    def test_runtime_zip_cannot_hide_a_photo_or_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.bundle(Path(folder))
            with zipfile.ZipFile(root/'_internal/base_library.zip','a') as archive:archive.writestr('students/roster.csv','private fixture')
            with self.assertRaisesRegex(RuntimeError,'excluded by installer policy'):audit_bundle(root)
    def test_unexpected_root_files_and_external_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.bundle(Path(folder));(root/'personal-notes.txt').write_text('private')
            with self.assertRaisesRegex(RuntimeError,'unexpected file'):audit_bundle(root)
        with tempfile.TemporaryDirectory() as folder:
            root=self.bundle(Path(folder));outside=Path(folder).parent/'outside-privacy-fixture'
            try:(root/'_internal/external').symlink_to(outside)
            except OSError:self.skipTest('Symlinks are unavailable')
            with self.assertRaisesRegex(RuntimeError,'external or broken'):audit_bundle(root)
    def test_unsafe_archive_paths_and_missing_policy_fail_closed(self):
        for name in ['/absolute/file','../private','nested/../../private','C:/private']:
            with self.assertRaises(RuntimeError):safe_name(name)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,'policy is missing'):audit_bundle(self.bundle(Path(folder)),Path(folder)/'missing')

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'Debian build tool unavailable')
    def test_debian_payload_and_installer_hooks_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'stage';(stage/'DEBIAN').mkdir(parents=True)
            (stage/'DEBIAN/control').write_text('Package: privacy-fixture\nVersion: 1.0\nArchitecture: all\nMaintainer: Test <test@localhost>\nDescription: Synthetic privacy check\n')
            (stage/'usr/bin').mkdir(parents=True);(stage/'usr/bin/classroom-plus').write_text('public launcher')
            target=root/'fixture.deb'
            def build():subprocess.run(['dpkg-deb','--build',str(stage),str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
            build();self.assertEqual(audit_deb(target)['kind'],'deb')
            (stage/'usr/bin/private-file').write_text('synthetic fixture');build()
            with self.assertRaisesRegex(RuntimeError,'outside approved'):audit_deb(target)
            (stage/'usr/bin/private-file').unlink()
            (stage/'DEBIAN/postinst').write_text('#!/bin/sh\nexit 0\n');(stage/'DEBIAN/postinst').chmod(0o755);build()
            with self.assertRaisesRegex(RuntimeError,'installer script'):audit_deb(target)

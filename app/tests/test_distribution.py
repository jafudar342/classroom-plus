import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine import Engine
from workspace import initialize, InstanceLock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from public_source import audit, approved, export, inspect


class DistributionTests(unittest.TestCase):
    def test_fresh_workspace_is_empty_and_existing_records_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=initialize(Path(folder)/'workspace');engine=Engine(root)
            self.assertEqual(engine.registry()[0],[]);self.assertEqual(engine.registry()[1].shape,(0,512))
            files={path:path.read_bytes() for path in root.rglob('*') if path.is_file()}
            initialize(root)
            self.assertEqual(files,{path:path.read_bytes() for path in root.rglob('*') if path.is_file()})
    def test_partial_or_nonempty_workspace_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'notes.txt').write_text('keep')
            with self.assertRaises(RuntimeError):initialize(root)
            self.assertEqual((root/'notes.txt').read_text(),'keep')
        with tempfile.TemporaryDirectory() as folder:
            root=initialize(Path(folder)/'workspace');(root/'embeddings/student_templates.npz').unlink()
            with self.assertRaises(RuntimeError):initialize(root)
            self.assertFalse((root/'embeddings/student_templates.npz').exists())
    def test_instance_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lock';first=InstanceLock(path)
            try:
                with self.assertRaises(RuntimeError):InstanceLock(path)
            finally:first.close()
            second=InstanceLock(path);second.close()
    def test_export_never_copies_private_trees(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'source';root.mkdir()
            for name in ['app/engine.py','README.md','data/roster.csv','.secrets/kaggle.json','work/debug.py','app/notes.txt','Attendance.ipynb','.gitignore','app/web/snapshot.jpg']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            target=export(Path(folder)/'public',root)
            self.assertEqual({p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()},{'app/engine.py','README.md'})
    def test_known_credentials_and_private_paths_fail_audit(self):
        value=('ghp_'+'a'*36).encode()
        self.assertTrue(any('GitHub credential' in issue for issue in inspect('app/example.py',value)))
        self.assertFalse(approved('app/tests/integration_check.py'))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'app').mkdir();(root/'app/example.py').write_bytes(value)
            with self.assertRaises(RuntimeError):audit(root)
    @unittest.skipUnless(shutil.which('git') and (ROOT/'.gitignore').is_file(),'Local-only ignore policy is not included in public exports')
    def test_gitignore_excludes_private_data_but_allows_public_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);shutil.copy2(ROOT/'.gitignore',root/'.gitignore')
            subprocess.run(['git','init','--quiet',str(root)],check=True)
            for name in ['data/reference/1/photo.jpg','config/reference_face_selections.json','.secrets/kaggle.json','models/weights.onnx','work/backups.json','Attendance_System_V3.ipynb','preview.png','requirements-local.txt','.build-venv/a.py','app/student-data.csv','app/notes.txt','.aws/config']:
                result=subprocess.run(['git','-C',str(root),'check-ignore','--no-index','--quiet',name])
                self.assertEqual(result.returncode,0,name)
            for name in ['app/engine.py','app/web/icon.svg','app/tests/test_engine.py','scripts/public_source.py','.github/workflows/build.yml','packaging/classroom-plus.spec','requirements-app.txt']:
                result=subprocess.run(['git','-C',str(root),'check-ignore','--no-index','--quiet',name])
                self.assertEqual(result.returncode,1,name)

    @unittest.skipUnless(shutil.which('git'),'Git is required for tracked-content checks')
    def test_forced_private_file_fails_both_git_audits(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);subprocess.run(['git','init','--quiet',str(root)],check=True)
            path=root/'data/roster.csv';path.parent.mkdir();path.write_text('synthetic fixture')
            subprocess.run(['git','-C',str(root),'add','-f','data/roster.csv'],check=True)
            for mode in ['staged','tracked']:
                with self.assertRaisesRegex(RuntimeError,'outside the public source allowlist'):audit(root,mode)

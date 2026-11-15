import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from build_snap import audit_stage, metadata, LAUNCHER


class SnapPackageTests(unittest.TestCase):
    def test_snap_metadata_uses_strict_confinement_and_minimal_permissions(self):
        data=metadata('0.1.0')
        self.assertEqual(data['confinement'],'strict')
        self.assertEqual(data['base'],'core24')
        self.assertNotIn('website',data)
        self.assertEqual(data['links']['website'],['https://github.com/jafudar342/classroom-plus'])
        self.assertEqual(data['apps']['classroom-plus']['plugs'],['network','network-bind','desktop'])
        self.assertIn('$SNAP_USER_COMMON',LAUNCHER)
        self.assertNotIn('/home/',LAUNCHER)

    def test_snap_audit_checks_exact_bytes_and_rejects_extra_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);internal=root/'application/_internal';internal.mkdir(parents=True)
            (root/'application/ClassroomPlus').write_bytes(b'synthetic executable')
            with zipfile.ZipFile(internal/'base_library.zip','w') as archive:
                archive.writestr('stdlib.pyc',b'synthetic runtime')
            manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(audit_stage(root,manifest),manifest)
            (root/'application/ClassroomPlus').write_bytes(b'changed bytes')
            with self.assertRaisesRegex(RuntimeError,'differs from'):audit_stage(root,manifest)
            (root/'private-note.txt').write_text('synthetic fixture')
            with self.assertRaisesRegex(RuntimeError,'Unexpected Snap payload'):audit_stage(root,manifest)

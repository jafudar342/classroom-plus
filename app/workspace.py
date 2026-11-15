"""Private, per-user workspaces for installed and portable Classroom+ builds."""
import json
import os
import sys
from pathlib import Path


def user_workspace():
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    return base / 'classroom-plus'


def initialize(root):
    import numpy as np
    root = Path(root).expanduser().resolve()
    required = ['data/roster.csv', 'embeddings/student_templates.npz', 'embeddings/metadata.json', 'config/demo_matching_settings.json']
    present = [(root / name).exists() for name in required]
    if any(present) and not all(present):
        raise RuntimeError('This workspace is incomplete. Restore its backup or choose a new, empty workspace; existing records were not replaced.')
    if not any(present) and root.exists() and any(root.iterdir()):
        raise RuntimeError('Choose an empty folder for a new workspace. Existing files were not replaced.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not any(present) and os.name != 'nt':root.chmod(0o700)
    for name in ['data/reference', 'data/classroom', 'data/validation', 'data/test', 'data/ground_truth', 'embeddings', 'config', 'models', 'results', 'logs', 'work']:
        (root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    if all(present):
        return root
    from engine import atomic_write
    import io
    buffer = io.BytesIO()
    np.savez_compressed(buffer, embeddings=np.empty((0, 512), dtype=np.float32), embedding_sums=np.empty((0, 512), dtype=np.float32),
                        roll_numbers=np.array([], dtype=str), names=np.array([], dtype=str), reference_counts=np.array([], dtype=int))
    settings = dict(model='Facenet512', detector='retinaface', normalization='base', cosine_distance_threshold=.3, minimum_gap=.05, calibrated=False)
    metadata = dict(model='Facenet512', detector='retinaface', reference_detector='retinaface', input_normalization='base',
                    embedding_normalization='L2', dimensions=512, registered_students=0, template_method='sum_of_unit_embeddings_then_L2')
    for name, content in [('data/roster.csv', b'roll_number,name\n'), ('embeddings/student_templates.npz', buffer.getvalue()),
                          ('embeddings/metadata.json', json.dumps(metadata, indent=2).encode()),
                          ('config/demo_matching_settings.json', json.dumps(settings, indent=2).encode())]:
        atomic_write(root / name, content)
    return root


class InstanceLock:
    """Keep the existing workspace lock, including on Windows where fcntl is absent."""
    def __init__(self, path):
        self.file = Path(path).open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if self.file.seek(0, 2) == 0:
                    self.file.write(b'0'); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            raise RuntimeError('Classroom+ is already running for this workspace. Use its existing browser tab.') from error
    def close(self):
        self.file.close()

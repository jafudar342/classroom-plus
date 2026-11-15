"""Supported local ONNX models and safe reconstruction of enrolled templates."""
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from engine import AppError, now

DETECTORS = [
    dict(id='retinaface', name='RetinaFace', description='Detailed landmarks; the original detector.'),
    dict(id='opencv', name='OpenCV', description='Lightweight Haar detector; best with clear frontal faces.'),
    dict(id='yunet', name='YuNet', description='Compact detector designed for fast local inference.'),
    dict(id='centerface', name='CenterFace', description='Anchor-free detection with facial landmarks.'),
    dict(id='mtcnn', name='MTCNN', description='Three-stage detection and alignment.'),
]
EMBEDDINGS = [
    dict(id='Facenet512', name='FaceNet512', dimensions=512, description='The original 512-value face representation.'),
    dict(id='ArcFace', name='ArcFace', dimensions=512, description='Angular-margin face recognition.'),
    dict(id='GhostFaceNet', name='GhostFaceNet', dimensions=512, description='Compact face recognition network.'),
    dict(id='Buffalo_L', name='Buffalo_L', dimensions=512, description='InsightFace ResNet50 face recognition.'),
]


def prepare(detector, model):
    """Load weights before activation. DeepFace caches successful model builds."""
    from deepface import DeepFace
    DeepFace.build_model(detector, task='face_detector')
    DeepFace.build_model(model, task='facial_recognition')


def reference_face(engine, path, approval=None, detector='retinaface'):
    """Retain the explicitly approved identity, regardless of the runtime detector."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with Image.open(io.BytesIO(raw)) as image:
        rgb = np.array(ImageOps.exif_transpose(image).convert('RGB'))
    audit_path = engine.root / 'logs/app-registration' / (path.stem + '.json')
    if path.stem.startswith('app_') and audit_path.exists():
        audit = json.loads(audit_path.read_text())
        if (Path(audit.get('photo', '')).name == path.name
                and audit.get('action') in ('register', 'add_reference')):
            if audit.get('photo_sha256', digest) != digest:
                raise AppError(f'The saved registration crop changed: {path.name}.')
            return rgb, digest
    applies = approval and Path(approval.get('photo', path.name)).name == path.name
    if applies and approval.get('photo_sha256') != digest:
        raise AppError(f'The approved reference photo changed: {path.name}. Confirm its face again first.')
    faces = engine.detect(rgb, detector=approval.get('detector', 'retinaface') if applies else detector)
    if applies:
        box = approval['bounding_box']
        faces = [face for face in faces if all(int(face['facial_area'][key]) == box[key] for key in ('x', 'y', 'w', 'h'))]
    if len(faces) != 1:
        raise AppError(f'Cannot identify the approved reference face in {path.name}. Register a clear, selected face first.')
    return faces[0]['face'], digest


def rebuild_entry(engine, roll, name, folder, model, approval=None, detector='retinaface'):
    photos = sorted(path for path in folder.glob('*') if path.is_file() and path.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'))
    if not photos:
        raise AppError(f'Roll {roll} has no saved reference photos. Add a photo before switching embedding models.')
    vectors, sources = [], []
    for path in photos:
        try:
            face, digest = reference_face(engine, path, approval, detector)
            vectors.append(engine.encode(face, model_name=model))
            sources.append(dict(photo=str(path.relative_to(engine.root)), sha256=digest))
        except Exception as error:
            raise AppError(f'Roll {roll}: {error} The current model and templates were kept.') from error
    total = np.sum(vectors, axis=0).astype(np.float32)
    length = np.linalg.norm(total)
    if not np.isfinite(total).all() or length < 1e-6:
        raise AppError(f'Roll {roll} has conflicting reference photos. The current templates were kept.')
    return dict(name=name, vector=total / length, sum=total, count=len(vectors)), sources


def verify_sources(root, sources):
    for source in sources:
        path = root / source['photo']
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise AppError('A reference photo changed during rebuilding. No model changes were saved. Try again.')


def rebuild_gallery(engine, model, progress):
    _, _, rolls, names, _, _ = engine.registry()
    selections = engine.selections()
    detector = engine.metadata.get('reference_detector', engine.metadata.get('detector', 'retinaface'))
    entries, sources = {}, []
    for index, (roll, name) in enumerate(zip(rolls, names)):
        progress(f'Rebuilding student {index + 1} of {len(rolls)}', index, len(rolls))
        entries[str(roll)], used = rebuild_entry(engine, str(roll), str(name), engine.root / 'data/reference' / str(roll), model, selections.get(str(roll)), detector)
        sources.extend(used)
    buffer = io.BytesIO()
    np.savez_compressed(buffer,
        embeddings=np.stack([entries[str(r)]['vector'] for r in rolls]) if len(rolls) else np.empty((0, 512), dtype=np.float32),
        roll_numbers=np.asarray(rolls, dtype=str), names=np.asarray(names, dtype=str),
        embedding_sums=np.stack([entries[str(r)]['sum'] for r in rolls]) if len(rolls) else np.empty((0, 512), dtype=np.float32),
        reference_counts=np.asarray([entries[str(r)]['count'] for r in rolls], dtype=int))
    manifest = dict(model=model, input_normalization='base', reference_detector=detector, created_utc=now(), sources=sources)
    return buffer.getvalue(), manifest

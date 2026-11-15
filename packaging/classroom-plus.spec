# Build from an audited clean export, never from a personal workspace.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, copy_metadata
root=Path(os.environ['CLASSROOM_SOURCE_ROOT']).resolve()
backend=['deepface.models.facial_recognition.onnx.Facenet','deepface.models.facial_recognition.onnx.ArcFace',
         'deepface.models.facial_recognition.onnx.GhostFaceNet','deepface.models.facial_recognition.onnx.Buffalo_L',
         'deepface.models.face_detection.opencv.OpenCv','deepface.models.face_detection.onnx.YuNet',
         'deepface.models.face_detection.onnx.CenterFace','deepface.models.face_detection.onnx.MtCnn',
         'deepface.models.face_detection.external.RetinaFace']
hidden=backend+collect_submodules('retinaface')+collect_submodules('onnxruntime')
datas=[(str(root/'app/web'),'web'),(str(root/'THIRD_PARTY_NOTICES.md'),'.')]
for distribution in ['deepface','retina-face','gdown','onnxruntime','numpy','pandas','pillow','tornado','tzdata']:
    datas+=copy_metadata(distribution)
# Carry available license notices for the runtime dependency closure only.
from importlib.metadata import distribution
from packaging.requirements import Requirement
queue=[line.strip().split('==')[0] for line in (root/'requirements-app.txt').read_text().splitlines() if line.strip() and not line.startswith('#')]
seen=set()
while queue:
    name=queue.pop()
    if name.lower() in seen:continue
    seen.add(name.lower());dist=distribution(name)
    for requirement in dist.requires or []:
        dependency=Requirement(requirement)
        if dependency.marker is None or dependency.marker.evaluate({'extra':''}):queue.append(dependency.name)
    for resource in dist.files or []:
        if any(word in Path(resource).name.lower() for word in ['license','copying','notice']):
            path=Path(dist.locate_file(resource))
            if path.is_file():datas.append((str(path),'dependency-licenses/'+name+'/'+Path(resource).parent.as_posix()))
a=Analysis([str(root/'app/launcher.py')],pathex=[str(root/'app')],binaries=collect_dynamic_libs('onnxruntime'),
           datas=datas,hiddenimports=hidden,excludes=['tensorflow','torch','keras','IPython','jupyterlab','notebook','pytest','matplotlib'])
# Drop build-machine installation receipts; keep runtime metadata and licenses.
a.datas=[entry for entry in a.datas if Path(entry[0]).name not in {'direct_url.json','uv_cache.json'}
         and not ('.dist-info/' in entry[0].replace('\\','/') and Path(entry[0]).name in {'INSTALLER','REQUESTED'})]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='ClassroomPlus',console=True)
coll=COLLECT(exe,a.binaries,a.datas,name='ClassroomPlus')

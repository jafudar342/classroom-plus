"""Pack only an audited standalone app and explicit Ubuntu runtime libraries."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from public_source import ROOT
from package_audit import audit_bundle, check_stream, excluded, rules

PACKAGES = ['libgomp1', 'libglib2.0-0t64', 'libpcre2-8-0', 'libmount1', 'libselinux1', 'libblkid1']
DESKTOP = """[Desktop Entry]
Version=1.0
Type=Application
Name=Classroom+
Comment=Local attendance with teacher review
Exec=classroom-plus
Icon=${SNAP}/meta/gui/icon.svg
Terminal=true
Categories=Education;
StartupNotify=false
"""
LAUNCHER = """#!/bin/sh
set -eu
export XDG_DATA_HOME="$SNAP_USER_COMMON"
export LD_LIBRARY_PATH="$SNAP/runtime-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export BROWSER=xdg-open
exec "$SNAP/application/ClassroomPlus" "$@"
"""


def metadata(version):
    return dict(name='classroom-plus', title='Classroom+', version=version, base='core24',
                architectures=['amd64'], grade='stable', confinement='strict', license='Proprietary',
                summary='Local classroom attendance with teacher-reviewed face matching',
                description=('Academic prototype by Jafar Irfan under Dr. Rayees Dar. Register students, '
                             'capture photo or webcam attendance, organize classes and subjects, and review lecture records. '
                             'Processing stays local. Starts with zero students. Internet is required for model downloads. '
                             'Recognition thresholds are provisional; teacher review is required. Reliable recognition '
                             'through face coverings and liveness detection have not been established.'),
                links={'website':['https://github.com/jafudar342/classroom-plus'],
                       'source-code':['https://github.com/jafudar342/classroom-plus'],
                       'issues':['https://github.com/jafudar342/classroom-plus/issues']},
                apps={'classroom-plus':dict(command='bin/classroom-plus', plugs=['network','network-bind','desktop'])})


def audit_stage(stage, expected):
    # Require exact staged bytes, not just filename exclusions.
    actual={}
    for path in stage.rglob('*'):
        if path.is_symlink():raise RuntimeError('Unexpected link in Snap payload.')
        if not path.is_file():continue
        name=path.relative_to(stage).as_posix()
        if not (name.startswith(('application/','runtime-libs/','meta/')) or name=='bin/classroom-plus'):
            raise RuntimeError('Unexpected Snap payload path: '+name)
        if name.startswith('application/') and excluded(name[len('application/'):],rules()):
            raise RuntimeError('Excluded file in Snap application: '+name)
        with path.open('rb') as stream:record=check_stream(name,stream)
        actual[name]=record['sha256']
    if actual!=expected:raise RuntimeError('Snap payload differs from the reviewed staging manifest.')
    audit_bundle(stage/'application')
    return actual


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',default='0.2.0')
    args=parser.parse_args()
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}',args.version):parser.error('Use a three-part numeric version.')
    if platform.machine()!='x86_64':parser.error('This recipe currently supports amd64 only.')
    bundle=ROOT/'dist/ClassroomPlus';audit_bundle(bundle)
    output=ROOT/'dist';output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='classroom-snap-build-') as temporary:
        temporary=Path(temporary);stage=temporary/'stage';stage.mkdir()
        shutil.copytree(bundle,stage/'application',symlinks=False)
        (stage/'meta/gui').mkdir(parents=True);(stage/'bin').mkdir()
        (stage/'meta/snap.yaml').write_text(json.dumps(metadata(args.version),indent=2))
        (stage/'meta/gui/classroom-plus.desktop').write_text(DESKTOP)
        shutil.copy2(ROOT/'app/web/icon.svg',stage/'meta/gui/icon.svg')
        (stage/'bin/classroom-plus').write_text(LAUNCHER);(stage/'bin/classroom-plus').chmod(0o755)
        downloads=temporary/'dependencies';downloads.mkdir()
        subprocess.run(['apt','download',*PACKAGES],cwd=downloads,check=True)
        libraries=stage/'runtime-libs';libraries.mkdir()
        dependency_records=[]
        for deb in sorted(downloads.glob('*.deb')):
            extracted=temporary/('unpack-'+deb.stem);extracted.mkdir()
            subprocess.run(['dpkg-deb','-x',str(deb),str(extracted)],check=True)
            dependency_records.append(dict(file=deb.name,sha256=hashlib.sha256(deb.read_bytes()).hexdigest()))
            for library in sorted((extracted/'usr/lib/x86_64-linux-gnu').glob('*.so*')):
                if library.is_file():shutil.copy2(library,libraries/library.name,follow_symlinks=True)
            for notice in (extracted/'usr/share/doc').glob('*/copyright'):
                target=stage/'application/_internal/dependency-licenses/ubuntu'/notice.parent.name
                target.mkdir(parents=True,exist_ok=True);shutil.copy2(notice,target/'copyright')
        expected={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.rglob('*') if p.is_file()}
        audit_stage(stage,expected)
        subprocess.run(['snap','pack','--check-skeleton',str(stage)],check=True)
        candidate=temporary/f'classroom-plus_{args.version}_amd64.snap'
        subprocess.run(['snap','pack',str(stage),str(temporary),'--compression=xz'],check=True)
        unpacked=temporary/'unpacked'
        subprocess.run(['unsquashfs','-no-progress','-d',str(unpacked),str(candidate)],stdout=subprocess.DEVNULL,check=True)
        actual=audit_stage(unpacked,expected)
        report=dict(schema=1,kind='snap',name='classroom-plus',version=args.version,confinement='strict',
                    snap_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    policy_sha256=hashlib.sha256((ROOT/'.packageignore').read_bytes()).hexdigest(),
                    dependencies=dependency_records,files=actual)
        target=output/candidate.name;shutil.copy2(candidate,target)
        (output/(candidate.name+'.audit.json')).write_text(json.dumps(report,indent=2))
        print('Audited Snap:',target)


if __name__=='__main__':main()

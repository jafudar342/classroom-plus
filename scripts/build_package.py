"""Build a clean standalone folder, and optionally a Linux Debian package."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from public_source import ROOT, audit, export
from package_audit import audit_bundle, audit_deb


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deb',action='store_true');parser.add_argument('--version',default='0.2.0')
    args=parser.parse_args()
    import re
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}',args.version):parser.error('Use a numeric version such as 0.1.0')
    if args.deb and sys.platform!='linux':parser.error('Debian packages must be built on Linux.')
    audit()
    output=ROOT/'dist';output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='classroom-public-build-') as temporary:
        temporary=Path(temporary);source=export(temporary/'source')
        env=dict(os.environ,CLASSROOM_SOURCE_ROOT=str(source),DEEPFACE_BACKEND_ENGINE='onnx')
        frozen=temporary/'frozen'
        subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm','--distpath',str(frozen),
                        '--workpath',str(temporary/'build'),str(source/'packaging/classroom-plus.spec')],env=env,check=True)
        bundle=frozen/'ClassroomPlus'
        bundle_report=audit_bundle(bundle,source/'.packageignore')
        (output/'ClassroomPlus-package-audit.json').write_text(json.dumps(bundle_report,indent=2))
        if args.deb:
            stage=temporary/'deb';application=stage/'opt/classroom-plus'
            for link in bundle.rglob('*'):
                if link.is_symlink() and not link.resolve().is_relative_to(bundle.resolve()):
                    raise RuntimeError('A bundled runtime link points outside the application.')
            shutil.copytree(bundle,application,symlinks=True)
            executable=stage/'usr/bin/classroom-plus';executable.parent.mkdir(parents=True)
            executable.write_text('#!/bin/sh\nexec /opt/classroom-plus/ClassroomPlus "$@"\n');executable.chmod(0o755)
            desktop=stage/'usr/share/applications';desktop.mkdir(parents=True)
            shutil.copy2(source/'packaging/classroom-plus.desktop',desktop)
            icons=stage/'usr/share/icons/hicolor/scalable/apps';icons.mkdir(parents=True)
            shutil.copy2(source/'app/web/icon.svg',icons/'classroom-plus.svg')
            documentation=stage/'usr/share/doc/classroom-plus';documentation.mkdir(parents=True)
            for name in ['README.md','THIRD_PARTY_NOTICES.md']:shutil.copy2(source/name,documentation/name)
            if (source/'docs').is_dir():shutil.copytree(source/'docs',documentation/'docs')
            control=stage/'DEBIAN/control';control.parent.mkdir()
            architecture=subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()
            size=sum(path.stat().st_size for path in stage.rglob('*') if path.is_file())//1024
            control.write_text(f'Package: classroom-plus\nVersion: {args.version}\nSection: education\nPriority: optional\nArchitecture: {architecture}\nMaintainer: Classroom+ local build <noreply@localhost>\nDepends: libc6 (>= 2.39), libstdc++6, libgcc-s1, libgomp1, zlib1g, libglib2.0-0t64\nInstalled-Size: {size}\nDescription: Classroom+ local attendance studio\n Local face matching with teacher-reviewed attendance.\n Starts with an empty, private per-user workspace.\n Model weights download on first use; no student data is bundled.\n')
            target=output/f'classroom-plus_{args.version}_{architecture}.deb'
            candidate=temporary/target.name
            subprocess.run(['dpkg-deb','--build','--root-owner-group',str(stage),str(candidate)],check=True)
            report=audit_deb(candidate,source/'.packageignore')
            (output/(target.name+'.audit.json')).write_text(json.dumps(report,indent=2))
            staged=output/(target.name+'.verified-tmp')
            shutil.copy2(candidate,staged);staged.replace(target)
            print('Audited Debian package:',target)
        # Only inspected artifacts are copied into the public output directory.
        staged=output/'ClassroomPlus.verified-tmp'
        if staged.exists():shutil.rmtree(staged)
        shutil.copytree(bundle,staged,symlinks=True)
        if (output/'ClassroomPlus').exists():shutil.rmtree(output/'ClassroomPlus')
        staged.rename(output/'ClassroomPlus')
        print('Audited standalone application:',output/'ClassroomPlus')


if __name__=='__main__':main()

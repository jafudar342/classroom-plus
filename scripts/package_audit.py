"""Enforce .packageignore against actual bundles and Debian payloads; fail closed."""
import argparse
import fnmatch
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import tarfile
import zipfile
from public_source import ROOT, SIGNATURES


def rules(path=None):
    path=Path(path or ROOT/'.packageignore')
    if not path.is_file():raise RuntimeError('The installer exclusion policy is missing.')
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]


def excluded(name,policy):
    name=name.replace('\\','/').removeprefix('./').lower();blocked=False
    for rule in policy:
        allow=rule.startswith('!');pattern=rule.lstrip('!').lstrip('/').lower()
        candidates=[pattern]
        if pattern.startswith('**/'):candidates.append(pattern[3:])
        if any(fnmatch.fnmatchcase(name,item) or (item.endswith('/**') and fnmatch.fnmatchcase(name+'/',item)) for item in candidates):blocked=not allow
    return blocked


def safe_name(name):
    path=PurePosixPath(name.replace('\\','/'))
    if path.is_absolute() or '..' in path.parts or not path.parts or ':' in path.parts[0]:
        raise RuntimeError('Unsafe path in distribution payload.')
    return path.as_posix().removeprefix('./')


def check_stream(name,stream):
    digest=hashlib.sha256();tail=b'';size=0;found=set()
    # Third-party native libraries may contain their own public compiler paths.
    # Block this private project path and known credential signatures.
    signatures=[(label,pattern) for label,pattern in SIGNATURES if label not in ('local home path','private key')]
    # Cryptography libraries contain PEM parser labels; a label alone is not a key.
    signatures.append(('private key material',re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----[\r\n ]+[A-Za-z0-9+/=]{40,}')))
    home=str(ROOT).encode()+b'/'
    while True:
        chunk=stream.read(1024*1024)
        if not chunk:break
        size+=len(chunk);digest.update(chunk);data=tail+chunk
        for label,pattern in signatures:
            if pattern.search(data):found.add(label)
        if home in data:found.add('private project path')
        tail=data[-4096:]
    if found:raise RuntimeError(f'{name}: possible '+', '.join(sorted(found))+' (values withheld)')
    return dict(path=name,size=size,sha256=digest.hexdigest())


def check_zip(name,stream,policy):
    # Only the explicitly admitted Python standard-library archive is expected.
    with zipfile.ZipFile(stream) as archive:
        total=0
        for member in archive.infolist():
            nested=safe_name(member.filename)
            if member.is_dir():continue
            total+=member.file_size
            if total>100_000_000 or member.file_size>20_000_000:raise RuntimeError('Unexpectedly large runtime library archive.')
            if excluded(nested,policy):raise RuntimeError(f'{name}!{nested}: excluded by installer policy')
            with archive.open(member) as source:check_stream(name+'!'+nested,source)


def audit_bundle(root,policy_path=None):
    root=Path(root).resolve();policy=rules(policy_path);records=[]
    if not root.is_dir():raise RuntimeError('Application bundle not found.')
    if not any((root/name).is_file() for name in ['ClassroomPlus','ClassroomPlus.exe']) or not (root/'_internal/base_library.zip').is_file():
        raise RuntimeError('Expected an onedir application with its runtime archive; self-extracting packages need a separate audit.')
    for path in sorted(root.rglob('*')):
        name=safe_name(path.relative_to(root).as_posix())
        if '/' not in name and name not in ['ClassroomPlus','ClassroomPlus.exe','_internal']:
            raise RuntimeError(f'{name}: unexpected file at bundle root')
        if excluded(name,policy):raise RuntimeError(f'{name}: excluded by installer policy')
        if path.is_symlink():
            if not path.resolve().is_relative_to(root) or not path.exists():raise RuntimeError(f'{name}: external or broken runtime link')
            continue
        if not path.is_file():continue
        with path.open('rb') as source:records.append(check_stream(name,source))
        if path.suffix.lower()=='.zip':check_zip(name,path,policy)
    if not records:raise RuntimeError('Refusing an empty application bundle.')
    return dict(schema=1,kind='standalone',policy_sha256=hashlib.sha256(Path(policy_path or ROOT/'.packageignore').read_bytes()).hexdigest(),files=records)


def audit_deb(package,policy_path=None):
    policy=rules(policy_path);records=[];links=[];members=set();bundle='opt/classroom-plus/'
    # Installer hooks run during installation; this package deliberately has none.
    control=subprocess.run(['dpkg-deb','--ctrl-tarfile',str(package)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True)
    with tarfile.open(fileobj=io.BytesIO(control.stdout)) as archive:
        controls=set()
        for member in archive:
            if member.name in ('.','./'):continue
            name=safe_name(member.name)
            if name!='control' or not member.isfile():raise RuntimeError('Unexpected Debian installer script or control file.')
            check_stream('DEBIAN/'+name,archive.extractfile(member));controls.add(name)
        if controls!={'control'}:raise RuntimeError('Debian control metadata is missing.')
    exact={'usr/bin/classroom-plus','usr/share/applications/classroom-plus.desktop','usr/share/icons/hicolor/scalable/apps/classroom-plus.svg'}
    process=subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(package)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
            for member in archive:
                if member.name in ('.','./'):continue
                name=safe_name(member.name);members.add(name)
                if member.isdir():continue
                if name.startswith(bundle):relative=name[len(bundle):]
                elif name in exact:relative=name
                elif name.startswith('usr/share/doc/classroom-plus/'):
                    relative=name
                    if not name.endswith(('.md','.txt','.json')):raise RuntimeError('Unexpected package documentation file.')
                else:raise RuntimeError(f'{name}: outside approved installation paths')
                if excluded(relative,policy):raise RuntimeError(f'{name}: excluded by installer policy')
                if member.issym() or member.islnk():
                    target=member.linkname.replace('\\','/')
                    resolved=posixpath.normpath(posixpath.join(posixpath.dirname(name),target)) if member.issym() else target.removeprefix('./')
                    if target.startswith('/') or not resolved.startswith(bundle):raise RuntimeError(f'{name}: external package link')
                    links.append(resolved);continue
                if not member.isfile():raise RuntimeError(f'{name}: unsupported package entry type')
                source=archive.extractfile(member)
                if relative.endswith('.zip'):
                    payload=source.read(100_000_001)
                    if len(payload)>100_000_000:raise RuntimeError('Unexpectedly large bundled archive.')
                    check_zip(relative,io.BytesIO(payload),policy);source=io.BytesIO(payload)
                records.append(check_stream(name,source))
        if process.wait()!=0:raise RuntimeError('Could not inspect Debian payload.')
    finally:
        process.stdout.close()
        if process.poll() is None:process.terminate();process.wait()
    if any(target not in members for target in links):raise RuntimeError('Broken link in Debian payload.')
    if 'usr/bin/classroom-plus' not in members:raise RuntimeError('The Debian launcher is missing.')
    return dict(schema=1,kind='deb',policy_sha256=hashlib.sha256(Path(policy_path or ROOT/'.packageignore').read_bytes()).hexdigest(),files=records)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact',type=Path);parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    try:
        result=audit_bundle(args.artifact) if args.artifact.is_dir() else audit_deb(args.artifact)
        if args.report:args.report.write_text(json.dumps(result,indent=2))
        print('Installer privacy check passed:',len(result['files']),'files.')
    except (RuntimeError,OSError,ValueError,zipfile.BadZipFile,tarfile.TarError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()

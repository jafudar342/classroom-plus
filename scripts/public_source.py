"""Allowlist-only source export and staged/tracked-content privacy checks."""
import argparse
import fnmatch
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXACT = {'.packageignore', '.gitattributes', 'LICENSE', 'LICENSE.txt', 'README.md', 'requirements-app.txt', 'start-app.sh', 'THIRD_PARTY_NOTICES.md',
         'app/README.md', 'app/web/vendor/chess.mjs', 'app/web/vendor/chess-LICENSE.txt',
         'packaging/requirements-build.txt', '.github/workflows/build.yml',
         'docs/PACKAGING.md', 'docs/PUBLIC_RELEASE.md', 'docs/PERFORMANCE_REVIEW.md'}
PATTERNS = ['app/*.py', 'app/tests/test_*.py', 'app/tests/*_checks.mjs', 'scripts/*.py',
            'packaging/*.spec', 'packaging/*.desktop'] + ['app/web/*'+suffix for suffix in ('.js','.mjs','.css','.html','.svg')]
BAD_PARTS = {'.git','.secrets','.aws','.ssh','.codex','.agents','__pycache__','data','embeddings','models','results','logs','work','backups','node_modules'}
SIGNATURES = [
    ('private key', re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
    ('GitHub credential', re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})')),
    ('cloud access key', re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}')),
    ('API credential', re.compile(rb'\bsk-[A-Za-z0-9_-]{24,}')),
    ('literal credential', re.compile(rb'''["'](?:api[_-]?key|access[_-]?token|password|secret[_-]?key)["']\s*[:=]\s*["'][^"'\r\n]{16,}["']''', re.I)),
    ('Kaggle-style key', re.compile(rb'''["']key["']\s*:\s*["'][0-9a-f]{32,}["']''', re.I)),
    ('local home path', re.compile(rb'/(?:home|Users)/[A-Za-z0-9_.-]+/')),
    ('embedded image', re.compile(rb'data:image/[^;]+;base64,[A-Za-z0-9+/=]{512,}')),
]


def approved(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or any(part in BAD_PARTS for part in path.parts):return False
    if name in EXACT:return True
    # fnmatch's * also matches slash, so constrain each pattern to its own depth.
    return any(name.count('/')==pattern.count('/') and fnmatch.fnmatchcase(name,pattern) for pattern in PATTERNS)


def inspect(name,content):
    issues=[]
    if not approved(name):issues.append(f'{name}: outside the public source allowlist')
    if len(content)>2_000_000:issues.append(f'{name}: unexpectedly large source file')
    for label,pattern in SIGNATURES:
        if pattern.search(content):issues.append(f'{name}: possible {label}; review locally (value withheld)')
    return issues


def files(root=ROOT):
    # Inspect reviewed source folders only; never walk private/runtime trees.
    candidates={root/name for name in EXACT}
    for name in ['app','app/web','app/web/vendor','app/tests','scripts','packaging','docs','.github/workflows']:
        folder=root/name
        if folder.is_symlink():raise RuntimeError(f'Symlink not allowed in public source: {name}')
        if folder.is_dir():candidates.update(folder.iterdir())
    for path in sorted(candidates):
        name=path.relative_to(root).as_posix()
        if approved(name) and path.is_file():
            if path.is_symlink():raise RuntimeError(f'Symlink not allowed in public source: {name}')
            yield name,path


def audit(root=ROOT,mode=None):
    issues=[]
    if mode:
        command=['git','-C',str(root)]
        names=subprocess.check_output(command+(['diff','--cached','--name-only','--diff-filter=ACMR','-z'] if mode=='staged' else ['ls-files','-z'])).decode().split('\0')
        for name in filter(None,names):
            content=subprocess.check_output(command+['show',':'+name])
            issues.extend(inspect(name,content))
    else:
        for name,path in files(root):issues.extend(inspect(name,path.read_bytes()))
    if issues:raise RuntimeError('\n'.join(issues))


def export(destination,root=ROOT):
    audit(root)
    destination=Path(destination)
    if destination.exists():raise RuntimeError('Export destination already exists. Choose a new empty destination.')
    destination.mkdir(parents=True)
    for name,path in files(root):
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    audit(destination)
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged',action='store_true');parser.add_argument('--tracked',action='store_true')
    parser.add_argument('--export',type=Path);parser.add_argument('--zip',type=Path)
    args=parser.parse_args()
    try:
        if args.export:
            public=export(args.export)
            if args.zip:
                args.zip.parent.mkdir(parents=True,exist_ok=True)
                with zipfile.ZipFile(args.zip,'x',compression=zipfile.ZIP_DEFLATED) as archive:
                    for name,path in files(public):archive.write(path,'ClassroomPlus/'+name)
                print('Public source archive:',args.zip)
        else:audit(mode='staged' if args.staged else 'tracked' if args.tracked else None)
        print('Public-source checks passed. Private/runtime folders were not read or exported.')
    except (RuntimeError,subprocess.CalledProcessError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()

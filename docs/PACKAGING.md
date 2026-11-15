**Build and install Classroom+**

The application code and personal workspace are separate. New installations contain zero students. Models download on first use; photos, embeddings, reports, settings and backups are never copied from the developer's workspace into a package.

On Linux, user data lives in `$XDG_DATA_HOME/classroom-plus` (normally `~/.local/share/classroom-plus`). On Windows it lives in `%LOCALAPPDATA%/classroom-plus`. `--workspace` can select a different private folder. Upgrading or removing the application does not delete this data. Back it up separately.

**Linux package**

The current local build targets 64-bit Ubuntu 24.04/Zorin 18 or a compatible Linux system with glibc 2.39 or newer. The `.deb` includes Python and runtime dependencies, but no model weights. It needs internet access for the first model download. It launches the local browser UI and a console; close the console or press Ctrl+C to stop.

Install using your distribution's package installer, or:

```sh
sudo apt install ./classroom-plus_0.1.0_amd64.deb
classroom-plus
```

Build on Linux using Python 3.12 and `dpkg-deb`:

```sh
python -m venv .build-venv
.build-venv/bin/python -m pip install -r requirements-app.txt -r packaging/requirements-build.txt
.build-venv/bin/python scripts/build_package.py --deb
```

The output is under `dist/`. Do not install build tools into your personal application environment. The builder first exports an audited source allowlist into a temporary directory; it never copies personal workspace trees. Linux system compatibility depends on the build host, so use Ubuntu 24.04 for the declared package target.

**Windows application**

Build on 64-bit Windows with Python 3.12:

```powershell
py -3.12 -m venv .build-venv
.build-venv\Scripts\python.exe -m pip install -r requirements-app.txt -r packaging\requirements-build.txt
.build-venv\Scripts\python.exe scripts\build_package.py
```

Share the **entire** `dist/ClassroomPlus` folder, normally as a ZIP. It contains `ClassroomPlus.exe` and its `_internal` runtime folder. Copying the EXE alone will not work. This portable folder is used instead of a self-extracting single file to keep startup faster and avoid repeatedly extracting the large runtime. The executable is unsigned; code signing and an installer can be added later.

PyInstaller builds for the operating system it runs on; this Linux computer cannot verify a Windows EXE. The manual **Build clean Classroom+ packages** GitHub Actions workflow builds both platforms after you upload a clean repository and explicitly run it. It uploads build artifacts, not GitHub Releases, and does not publish source or artifacts automatically on push. See the [PyInstaller platform requirements](https://pyinstaller.org/en/stable/).

**Verification**

`ClassroomPlus --workspace <empty-folder> --check-runtime` checks dependencies and web assets without downloading weights. `--initialize-only` creates a new empty workspace. `--no-browser --port 8766` starts a local test instance without opening the browser. Do not point a smoke test at your real workspace.

The packaged application still uses the browser's camera permission and device support. Pretrained-model terms remain separate from application packaging; model weights are deliberately excluded. Review `THIRD_PARTY_NOTICES.md` before redistribution. A project-wide source license remains your decision.

**Installer privacy policy**

`.packageignore` is enforced by `scripts/package_audit.py`; it is separate from `.gitignore`. The builder starts from the reviewed source allowlist and checks the actual standalone bundle before placing it in `dist/`. For Debian it also checks the completed package, including installation paths, links, control metadata and the absence of installer hooks. A failed check stops publication of the new artifact.

The policy excludes existing student photos, rosters, embeddings, attendance records, private settings, model weights, notebooks, screenshots, credentials, backups, editor/assistant files and local development environments. Required Python runtime libraries, public CA certificates, licenses and the inspected standard-library ZIP remain included. These are needed to run the application. Build-machine installation receipts are removed.

Audit reports beside the artifacts list relative paths, sizes and SHA-256 hashes. Both Linux and Windows builds use the same standalone audit; the Debian build has the additional installer audit. To check existing outputs:

```sh
python scripts/package_audit.py dist/ClassroomPlus
python scripts/package_audit.py dist/classroom-plus_0.1.0_amd64.deb
```

New installations create their own empty private workspace. The policy controls what is distributed; it does not prevent users from registering students after installation. No credential scanner can detect every possible kind of private text, so review the clean source and audit report before sharing a release.

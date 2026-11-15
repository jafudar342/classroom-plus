**Prepare a public Classroom+ repository**

Use the clean source export rather than uploading the existing project directory or a ZIP made by your file manager. The personal workspace includes biometric data, student records and credentials that must remain local.

```sh
python scripts/public_source.py
python scripts/public_source.py --export dist/ClassroomPlus-source --zip dist/ClassroomPlus-source.zip
```

The exporter admits reviewed application code, web assets, tests with synthetic fixtures, build scripts, dependency requirements and documentation only. It refuses symlinks and checks for common credential signatures, private keys, absolute home paths, large embedded images and unexpectedly large source files. It does not traverse private/runtime folders.

The local `.gitignore` stays on the development machine and is excluded from the public source export. It defaults to ignoring root files and permits only source formats in reviewed directories. It excludes student photos, rosters, embeddings, models, reports, notebooks and their embedded outputs, screenshots, private configuration, credentials, local environments, assistant/editor tools and build output. The legacy integration script requiring personal reports is excluded too.

Before committing inside a newly created repository, run:

```sh
git add .
python scripts/public_source.py --staged
python scripts/public_source.py --tracked
git diff --cached --stat
git diff --cached
```

Review the exact staged content. Do not use `git add -f` on ignored files. `.gitignore` cannot remove files already tracked or erase previous commits; the tracked/staged checks are included to catch that situation. If a credential has ever been committed, remove it from history and revoke it before publishing. Student data must also be removed from history, not merely ignored in the latest version.

No scanner can identify every kind of private information. The allowlist, ignore rules and credential checks reduce accidental inclusion; they do not replace review. Select a project-wide license before inviting source reuse. Keep the existing third-party license notices.

Nothing in these scripts creates a GitHub repository, pushes commits or publishes a release. The included build workflow runs only when you explicitly start it on GitHub.

Installer contents have a separate enforced `.packageignore` policy and actual-artifact checks. `.gitignore` alone does not protect `.deb` or Windows bundles. See `docs/PACKAGING.md` for the checks and audit reports.

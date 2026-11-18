# Classroom+

**Local classroom attendance, with face matching and teacher-reviewed records.**

Built by **Jafar Irfan**, under the supervision of **Dr. Rayees Dar**.

Classroom+ brings student registration, photo and webcam attendance, classes, subjects and lecture reports into one browser interface running on your own computer. Photos and face embeddings are processed locally; recognition does not use a cloud API.

[Download the Linux package](https://github.com/jafudar342/classroom-plus/releases) · [Usage guide](app/README.md) · [Packaging guide](docs/PACKAGING.md)

## Features

- Register students from uploaded photos or a webcam, explicitly selecting the correct face.
- Edit student profiles, add reference photos, archive registrations and restore deleted students.
- Organize separate classes and subjects, with recurring timetables and late-arrival markers.
- Capture attendance from photos or connected browser-compatible cameras, with live matching previews.
- Combine captures in draft lectures, review video proposals, correct decisions and finalize attendance.
- Download attendance sheets, annotated images and photo reports.
- Evaluate independent photos and configure matching thresholds and model profiles.
- Choose Light, Dark, Pop or true-black OLED appearance.
- Save notes as cards and pin draggable sticky notes across app sections.
- Use the built-in calculator with keyboard controls.
- Schedule local reminders with editing, completion tracking, and due alerts while the app is open.
- Take a break with chess, a 16-color spinner or Sudoku.

## Install on Linux

The **v0.2.0** package targets **64-bit Ubuntu 24.04, Zorin OS 18, or compatible systems with glibc 2.39 or newer**. Other distributions and older versions have not been verified.

1. Download `classroom-plus_0.2.0_amd64.deb` from [Releases](https://github.com/jafudar342/classroom-plus/releases).
2. Open it with your software installer, or run in the download directory:

   ```bash
   sudo apt install ./classroom-plus_0.2.0_amd64.deb
   ```

3. Open **Classroom+** from the applications menu, or run `classroom-plus`.

The package includes Python and its runtime dependencies. Internet access is needed to download model weights on first use. Keep the application terminal open; press **Ctrl+C** there to stop the server.

To uninstall:

```bash
sudo apt remove classroom-plus
```

Uninstalling the application leaves your personal attendance workspace intact.

## Snap Store beta

A strictly confined **amd64 beta** is available through the [Snap Store](https://snapcraft.io/classroom-plus):

```bash
sudo snap install classroom-plus --beta
classroom-plus
```

Snap handles the `core24` base and runtime dependencies. First use downloads model weights. The app opens a console and a local browser interface; Ctrl+C in the console stops it. Snap records are stored separately under `~/snap/classroom-plus/common/classroom-plus`. The browser requests webcam permission. This beta has the same academic-prototype limits described below.

To remove the Snap, use `sudo snap remove classroom-plus`. Keep a separate backup of important workspace data before removal.

## Run from source

Use **Python 3.12**. On Linux:

```bash
git clone https://github.com/jafudar342/classroom-plus.git
cd classroom-plus
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-app.txt
python app/launcher.py
```

The launcher opens the local browser interface. Allow camera access when using a webcam. To choose a different port or start without opening the browser:

```bash
python app/launcher.py --no-browser --port 8766
```

Windows source installations use `.venv\Scripts\Activate.ps1` to activate the environment. A Windows executable is **not included in this release**; the [packaging guide](docs/PACKAGING.md) explains building it on Windows.

## Attendance workflow

1. Register students and add clear reference photos.
2. Create a class, assign students and add subjects.
3. Start a lecture directly or from a timetable slot.
4. Upload a group photo or capture frames with the webcam.
5. Review matches, confirm video proposals and resolve uncertain students.
6. Finalize the lecture and download the attendance sheet.

A live matching preview does not save attendance. Use a saved capture or a reviewed lecture for records. Unmatched students remain **Unconfirmed**; teachers must resolve Unconfirmed and Review entries before finalizing a lecture.

## Recognition pipeline

```text
Photo or webcam frame
        ↓
Detect faces and bounding boxes
        ↓
Align faces and extract embeddings
        ↓
Compare against registered student templates
        ↓
Apply distance, ambiguity and duplicate-match checks
        ↓
Teacher review → finalized attendance
```

The recommended defaults are **RetinaFace** for detection and **FaceNet512** for 512-dimensional embeddings. The app compares normalized embeddings using cosine distance and checks the gap between candidate matches.

Settings also offer OpenCV, YuNet, CenterFace and MTCNN detectors, plus ArcFace, GhostFaceNet and Buffalo_L embeddings. Switching the embedding model rebuilds registered templates from saved references. Thresholds are model-dependent and need independent evaluation.

## Data and privacy

A new installation starts with **zero students**. This repository and the release package contain no existing student photos, rosters, face embeddings, attendance reports, credentials or model weights.

Private workspaces are stored separately from installed code:

| System | Default workspace |
| --- | --- |
| Linux | `$XDG_DATA_HOME/classroom-plus`, normally `~/.local/share/classroom-plus` |
| Windows | `%LOCALAPPDATA%/classroom-plus` |

Use `--workspace <folder>` to select another workspace. Back up your workspace separately. Registration photos, face crops, reports and review evidence remain there; video attendance does not save the full video.

The server listens on `127.0.0.1`. Keep it local. First-time model downloads contact upstream providers; student photos and embeddings are not sent to cloud recognition services.

Public source is prepared with an allowlist-based exporter and credential checks. Installer contents are separately checked against the enforced `.packageignore`. The developer's `.gitignore` is deliberately excluded from the public repository; contributors should configure local exclusions before creating personal data. See [public-release checks](docs/PUBLIC_RELEASE.md).

## Prototype limits

Classroom+ is an academic prototype, not a validated production biometric system. Matching thresholds are provisional. A synthetic 20-person demonstration reused registration images; its result does **not** establish independent classroom accuracy.

Masks, niqabs, poor lighting, small faces, pose changes and unfamiliar people can cause missed or incorrect matches. Reliable recognition through face coverings, liveness detection and spoof resistance have not been established. Teacher review remains necessary.

## Development and packaging

Run the Python tests from the project directory:

```bash
python -m unittest discover -s app/tests -p 'test_*.py'
```

See [packaging](docs/PACKAGING.md), [release privacy checks](docs/PUBLIC_RELEASE.md) and [performance review](docs/PERFORMANCE_REVIEW.md). The included GitHub Actions build workflow runs manually and does not publish releases automatically.

The Linux package has been installed, started with an empty test workspace and uninstalled on the development machine. Compatibility and camera behavior should also be tested on the target computer.

## Credits and licensing

**Builder:** Jafar Irfan  
**Supervisor:** Dr. Rayees Dar

A project-wide source license has not yet been selected; this repository does not grant an open-source license. Dependencies retain their own licenses. See [third-party notices](THIRD_PARTY_NOTICES.md), and review model terms separately before redistribution or other use.

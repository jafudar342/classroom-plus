# Classroom+

Start the local app from the project directory:

```bash
./start-app.sh
```

Open http://localhost:8765 in your browser. Keep the terminal open; Ctrl+C stops the app. If that port is occupied, run `./start-app.sh --port 8766` and use the printed address. For source installations, install the runtime-only requirements first. The installed desktop package carries its own Python runtime and dependencies; downloaded model weights and user records stay in the private workspace.

## Take attendance

Upload a JPG, PNG, or WebP photo, or select **Webcam → Enable camera** and allow the browser's camera request. **Capture & save attendance** processes one camera frame and saves the results. **Start live check** repeatedly checks a frame after the previous request finishes; its results are previews, not saved attendance sessions. Stop live checking and capture a frame to save a report. Live checking speed depends on your CPU and the number of faces; it is not a full-frame-rate video tracker.

The camera turns off when you change pages, switch to upload, open registration, hide the browser tab, or close the app page. Delayed permission responses are discarded if you have left the capture screen. Live checking keeps waiting automatically when no face is visible. Audio is never requested. Camera access works on localhost in supported browsers; an embedded app browser may not expose the laptop webcam. If so, open the same address in your normal browser.

## Register a student

Choose **Register a student**, enter the roll number and name, then upload or capture a reference photo. Choose **Find faces**, explicitly select the correct face, and confirm registration. Multiple detected people require choosing the intended student; no face is selected automatically. A preview expires after 15 minutes.

Use **Add reference photo** in the directory to add another photo for an existing student. The name must match the existing roster entry. New references are combined as sums of unit embeddings and L2-normalized. Each imported notebook template is treated as one effective reference, because its original unnormalized sum was not stored.

The app writes compatible `data/roster.csv`, `embeddings/student_templates.npz`, and `embeddings/metadata.json`, and saves the selected aligned face under `data/reference/<roll>/app_<id>.jpg`. Existing source photos are preserved. Before registration writes, the previous registry files are backed up under `work/app-backups/`. Registration audit records are under `logs/app-registration/`. The demonstration notebook reads the current roster and photos and saves its own templates and reports in `work/notebook-demo/`.

## Reports and matching

Saved sessions live under `results/app/<session-id>/`: labeled image, attendance CSV, detection details CSV, matching settings, and result JSON. **Photo reports** provides previous reports and downloads. Live previews do not write reports. Single-photo reports retain a labeled image. Lecture sessions also retain their original captures locally for face review and corrected annotations.

The matching settings come from `config/demo_matching_settings.json`: maximum cosine distance 0.30, minimum distance gap 0.05. They are provisional and uncalibrated. Duplicate identity claims and faces smaller than 32 pixels require review. Detection or embedding failures are surfaced, not silently accepted. A photo with no detectable faces does not generate an all-absent session. A student with no registered embedding remains **Review**. **Absent** means not matched in the supplied photo.

This app preserves the prototype's scope: the 20-person synthetic test reused reference images. Independent classroom accuracy, unfamiliar-person rejection, and spoof resistance have not been established. Webcam capture is not a liveness check. Use the app for demonstration and review; it does not automatically submit attendance to another system.

## Local access

The app listens only on 127.0.0.1, does not serve the project root, restricts report download paths, checks request origins via XSRF protection, and does not send photos or embeddings to cloud recognition APIs. Cached model weights are reused; a missing model may be downloaded from its upstream release on first use. Do not expose this development app publicly.

## Checks

```bash
.venv/bin/python -m unittest discover -s app/tests -v
```

## Registration session recovery

The app uses its own `classroom_attendance_xsrf` cookie so Jupyter and other localhost apps cannot replace its session token. A rejected stale token is refreshed once before retrying the request. XSRF protection stays enabled. If an older app tab still shows Forbidden after an update, reload the page to load the new client code.

## Interface and reliability update

The refreshed interface adds larger controls, a camera framing guide, visible selected filenames, reference counts, student-photo fallbacks, a workspace refresh control, and offline status. Registration previews are invalidated when their photo or dialog changes. Saving a student or attendance record is reported as successful even if a subsequent workspace refresh fails. Database checks reject inconsistent arrays and duplicate roster entries before registration can overwrite saved data; incomplete history entries are skipped.

Validation: 20 Python checks, 8 JavaScript checks with a simulated DOM, and a real-model integration run using the synthetic test photo. Registration integration tests use a disposable registry copy and verify original file hashes afterward. The independent-photo accuracy limits remain unchanged.

## Manage students

Open **Student directory → Manage profile** on a student card. You can edit their name and numeric roll number; department, course, semester, section, email, phone, and notes; and up to 20 named custom fields. Profile details are stored separately in `data/student_profiles.json`, keeping the notebook-compatible roster at two columns. Changing a roll number also moves its reference folder and updates template labels and manual face-selection metadata. Duplicate roll numbers and stale edits from another window are rejected. Previously saved attendance sessions retain their original names and roll numbers.

Use **Add photos** to upload up to 10 photos at a time (maximum 50 MB combined, 15 MB per photo), or capture a new photo with the webcam. Confirm the correct face in each photo and save each reference in turn. Each successful photo updates the student's normalized template. Unsaved profile changes must be saved before switching to photo registration. Closing a batch discards only the remaining unsaved photos; references already saved remain registered.

**Delete student** requires typing the exact roll number. This removes the student from the active roster and matching templates and moves their reference photos, profile, and face template into `data/student_archive/<id>/`. In the directory, choose **Recently deleted → Restore student** to restore the same registration. Restoration refuses to overwrite an active student or folder with the same roll number. Historical attendance reports are not changed. There is no permanent-purge action.

Management actions back up the registry before writing, log edits under `logs/student-management/`, and roll back file and folder changes if a save fails. Tests use temporary databases; no real student is deleted or edited during QA.

## Light and dark mode

Use the sun/moon button in the top bar. The app follows the operating system's appearance until a manual choice is made. The chosen light/dark preference is saved in browser-local storage, survives reloads, and synchronizes with other app tabs. Blocked storage does not prevent toggling within the current tab. Theme colors are applied before the main stylesheet paints; photos, webcam frames, and downloaded reports are not recolored.

## Classes and subjects

Open **Classes & subjects → Create class**. Name the class, optionally add department/semester/section details, and select its enrolled students. Search the roster, use **Select shown** to add search results, or **Clear selection** to start again. A student can belong to multiple classes; roll numbers remain unique across the whole student directory. Use **Edit class & roster** to change a class or its enrollment.

Choose a class and select **Add subject**. Subject names and optional codes must be distinct within that class. The same subject code may be used in another class. A teacher name is optional. Subject editing keeps the subject in its original class; create a new subject to offer it to another class.

On **Take attendance**, choose a class and its subject. Face comparisons and the generated roster include only that class's enrolled students. An enrolled student without a face template remains **Review**, not silently absent. For a roster with one registered candidate, the distance threshold still applies but there is no second candidate and the gap is shown as unavailable. **All students · demo / general** preserves the earlier whole-directory workflow and does not require a subject.

New student registration has an **Enroll in class** field. Existing students are enrolled through the class roster editor. Editing a student's roll number updates memberships; deleting them removes active memberships; restoring them restores their previous class memberships. Global student photos and face embeddings are reused across classes.

Every new saved report snapshots class and subject IDs, names, and subject code. Attendance CSVs include those labels. Photo reports can be filtered by class and subject; old sessions without class metadata appear under All students / General attendance. Renaming a class or subject does not rewrite historical reports.

Classes, subjects, enrollments, and their edit revision are stored in `data/academics.json`. Edits use backups and stale-edit checks. UI tests use a temporary copy; no example class or subject is added to the actual workspace during QA.


## Lecture sessions

Choose **Lecture sessions → Start lecture**, or **Start lecture** beside the class and subject controls. Enter the lecture title, date and local time. The browser time zone is saved with the lecture. The class, subject labels and roster are frozen at creation, so later enrollment and name changes do not rewrite that lecture.

Open **Add capture** to upload photos or use **Webcam → Enable camera → Capture & add to lecture**. Add as many different captures as needed; a student counts once across all captures. The same exact photo is rejected if added again. Continuous live checks remain available outside lecture capture. Drafts save after each successful operation and can be reopened from Lecture sessions.

Choose **Review lecture** to inspect the combined attendance. Each capture has face crops and a labeled image. Unknown or uncertain faces must be assigned to a student in this lecture or explicitly ignored with a reason. A wrong automatic match can also be reassigned. Two faces in one capture cannot claim the same student; the same student may appear in several captures. Correct the other face first if a reassignment conflicts.

The roster offers **Automatic**, **Present** and **Absent** corrections. Enter a reason and save each change. An explicit attendance correction takes priority over face matches, including future captures; select Automatic with a reason to remove it. Students who lacked templates at lecture creation need an accepted face or teacher attendance decision. A lecture without captures can be finalized only after every student's attendance is decided manually.

**Finalize attendance** becomes available once all face and student reviews are resolved. Confirm the totals to lock the lecture. Finalized lectures cannot accept captures or corrections. Download one **Attendance CSV** with lecture date/time/time zone, class, subject, student, final status, evidence count and correction note. The **Correction log** records additions, decisions, reasons and previous values; this is a local change log, not authenticated teacher identity or a tamper-proof record.

Lecture files are under `results/lectures/<id>/lecture.json` with original photos under `captures/<id>/source.png`. Updates replace the manifest atomically; a failed capture save removes its new evidence folder. Revisions prevent stale tabs from overwriting newer decisions; use **Reload lecture** when prompted. Students have durable internal IDs, so roll/name edits preserve their original lecture identity and a newly registered person reusing a deleted roll is not treated as that former student. Lecture recognition uses current active face templates for the frozen identities; deleting a registration removes it from future matching. Previously recorded evidence and final sheets remain historical records.

Existing single-photo reports remain under **Photo reports** and `results/app/`. No test lectures are added to the real workspace during verification.

Lecture validation: 52 Python checks, 21 frontend checks, and browser testing on a disposable registry copy. A two-capture real-model demo identified the same 20 students once each, retained a teacher correction, finalized the lecture, and downloaded the CSV. These checks verify the application workflow; the independent-photo accuracy limits described above still apply.


## Attendance dashboard

Choose **Dashboard** to view student, class and subject attendance, weekly and monthly trends, and students below an editable target (75% by default). Filters select a month, class and subject. **View history** lists the student's lectures, recorded roll number, status and correction notes for that selection. Clear the filters to see the complete history. A renamed roll keeps its internal identity, while a new registration reusing a deleted roll stays separate.

Only finalized lectures count. Each student's denominator is the number of included lectures whose saved roster contains them. Overall attendance is total present records divided by total roster records, weighted by lecture roster size. Students without finalized records have no percentage and appear once attendance is finalized. Unreadable lecture records produce an exclusion notice.

Select a month to download **Monthly CSV**, summarized per student, class and subject with present/absent counts, attendance percentage and target status. The target is stored locally in `config/dashboard_settings.json`. Dashboard calculations do not rewrite lecture records.


## Recognition evaluation

Open **Evaluation → Add test photo**. Choose a separate photo, draw non-overlapping boxes around every person's face and visible eyes (or enter pixel coordinates), and choose an expected student or **Unregistered person** for every box. Confirm complete labels and independent capture. Exact copies of enrollment photos and duplicate evaluation images are rejected. Labels can be edited later, with revision checks.

Use the **Validation** split for tuning and **Test** for final measurements. Select 1–10 photos from one split and choose **Compare selected photos**. Full-face results measure accepted matches; eye-only results measure review suggestions. Correct, wrong, missed, unfamiliar-person rejections/false accepts and extra predictions appear separately, with precision, recall and per-photo details. Method failures are shown and excluded from their denominators. No-face results count enrolled labels as missed. The page explains spatial pairing and metric definitions.

The threshold explorer replays saved distances and eye correlations without rerunning models. It supports cosine distance and candidate-gap limits plus stricter eye correlations from 0.70 to 1.00. Eye search generates its proposals at a fixed 0.70 floor, so lower values cannot be replayed. The app's attendance settings are not modified by experiments. Measurements require correctly labeled independent data; synthetic enrollment-derived demos verify workflow only.

Local evaluation images and labels are stored in `data/evaluation/photos/<id>/`, and experiments in `data/evaluation/runs/<id>/`. Experiments preserve label revisions, settings, raw predictions, a face-gallery digest and the reference-photo hash manifest. Editing labels affects future experiments. Saved experiments retain their original labels and predictions.

## Model selection

Settings offers RetinaFace, OpenCV, YuNet, CenterFace and MTCNN detectors, and FaceNet512, ArcFace, GhostFaceNet and Buffalo_L embedding models. All embedding choices produce 512 values, but their embedding spaces differ. Choose models, confirm the rebuild when changing embeddings, then choose **Activate & rebuild templates**. The first activation may download published model weights. Inference and student photos stay local.

Embedding changes rebuild every registered student's template from saved reference photos, preserving manually approved face selections using the original enrollment detector. App registration crops are already selected and aligned. Every saved reference must remain usable; missing or ambiguous sources stop activation with the old gallery intact. Configuration, metadata and templates are backed up and committed together. Detector-only changes retain templates. Restoring an archive from another embedding model re-encodes its saved photos rather than mixing vectors. Saved attendance and evaluation experiments retain their original results.

Matching thresholds are model-dependent and remain provisional until evaluated using independent captures. Existing threshold values are retained for explicit teacher adjustment. A different model does not guarantee better recognition of covered faces.

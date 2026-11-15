**Classroom+ performance review**

Reviewed the recognition and registration paths, model settings and rebuilds, lecture/video storage, timetable, analytics, evaluation, camera lifecycle, frontend refresh/render behavior, themes, clocks and mini-game integration. The vendored chess library remains unchanged.

**Changes made**

- The validated student registry is retained in memory between reads. Changes to either roster or template files invalidate it, including atomic replacement and same-size edits with restored modification times. Returned arrays and dictionaries are independent copies, so callers cannot corrupt cached templates.
- Photo-report and lecture lists cache only their small summaries. Unchanged sessions no longer require parsing all their attendance/evidence JSON on each workspace refresh. New, changed and deleted records are reflected automatically.
- Finalized lectures use their frozen attendance and summary directly instead of aggregating historical evidence before discarding that calculation.
- Student thumbnails are cached at their display sizes. Thumbnail decoding and JPEG encoding run on a separate bounded worker pool, rather than blocking the HTTP event loop. File changes and deletions invalidate cached images.
- Workspace collection runs on the existing serialized worker, preserving its exclusion of simultaneous mutations while keeping the HTTP loop responsive. Dashboard calculations run on the separate read pool. Model inference still uses one worker.
- The clock reuses its timezone information and avoids updating hidden tabs.

**Local benchmark**

These are median repeated-call times with warm caches and a synthetic fixture: 500 registered students, 101 lecture files and 100 photo reports. Both measurements warm the operation before sampling. Results measure storage/list/view work; they are not end-to-end face recognition measurements.

| Operation | Before | After |
| --- | ---: | ---: |
| Read and validate 500-student registry | 6.843 ms | 0.737 ms |
| List 101 lectures | 203.384 ms | 3.136 ms |
| List 100 photo reports | 62.429 ms | 2.177 ms |
| View a finalized lecture with historical evidence | 0.554 ms | 0.002 ms |

Reproduce with `.venv/bin/python scripts/benchmark_performance.py <label>`. The script uses a temporary fixture and writes measurements under `work/`; it does not modify student records.

**Validation and limits**

125 Python tests pass, including new cache-isolation, bounded-memory, external-edit, deletion, frozen-attendance and nonblocking-thumbnail checks. All frontend suites also pass, including camera lifecycle, model settings, video, timetable, themes, spinner and Sudoku checks.

Memory retention is bounded: one registry version, 512 photo-report summaries, 512 lecture summaries, 128 small thumbnails and 32 larger thumbnails. Sources are checked using device/inode, size, modification time and change time. A value whose source changes during loading is not retained. Failed reads are not cached. Browser photo caching and saved biometric data formats are unchanged.

The first read still loads and validates files. Histories exceeding cache capacity may reload older entries. Recognition accuracy, matching thresholds, detection resolution, enrollment photos and finalized attendance are unchanged. Actual face detection/embedding and experimental eye-region searches remain the main compute costs.

An exploratory 20-face FaceNet512 batch check measured 308 ms individually versus 272 ms in a batch, with small floating-point differences. The production inference path was retained: that limited gain did not justify changing the numeric behavior across all supported models during this pass. For much larger deployments, pagination and indexed storage are the next architectural improvements; they require separate migration and interface work.

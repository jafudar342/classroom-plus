"""Lecture snapshots, reviewed face decisions and immutable final attendance."""
import hashlib
import json
import re
import shutil
import uuid
from collections import Counter
from datetime import date, time, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from PIL import Image
from engine import AppError, atomic_write, csv_bytes, image_bytes, now
from file_cache import FileCache


class LectureStore:
    def __init__(self, root, engine):
        self.root = root / 'results/lectures'
        self.engine = engine
        self._summary_cache = FileCache(512)

    def directory(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise AppError('Lecture not found.')
        return self.root / identifier

    def load(self, identifier):
        try:
            return json.loads((self.directory(identifier) / 'lecture.json').read_text())
        except (OSError, ValueError) as error:
            raise AppError('Lecture not found or could not be read.') from error

    def save(self, item):
        item['updated_utc'] = now()
        item['revision'] += 1
        view = self.view(item)
        atomic_write(self.directory(item['id']) / 'lecture.json', json.dumps(item, indent=2).encode())
        return view

    def draft(self, identifier, payload):
        item = self.load(identifier)
        if item['state'] != 'draft':
            raise AppError('This lecture is finalized. Its attendance cannot be changed.')
        if type(payload.get('revision')) is not int or payload['revision'] != item['revision']:
            raise AppError('This lecture changed in another tab. Reload the lecture before saving.', 'stale_revision')
        return item

    @staticmethod
    def reason(payload):
        value = payload.get('reason', '')
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500:
            raise AppError('Enter a reason for this correction (1–500 characters).')
        return value.strip()

    def create(self, payload, schedule=None):
        title = payload.get('title', '')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise AppError('Enter a lecture title (1–120 characters).')
        try:
            day, clock, zone = payload['lecture_date'], payload['lecture_time'], payload['timezone']
            if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
                raise ValueError()
            if not isinstance(clock, str) or not re.fullmatch(r'\d{2}:\d{2}', clock):
                raise ValueError()
            date.fromisoformat(day)
            time.fromisoformat(clock)
            ZoneInfo(zone)
        except (KeyError, ValueError, TypeError, ZoneInfoNotFoundError) as error:
            raise AppError('Choose a valid lecture date, time and time zone.') from error
        context, members = self.engine.attendance_context(payload.get('class_id'), payload.get('subject_id'))
        roster, _, rolls, _, _, _ = self.engine.registry()
        profiles = self.engine.profiles()
        roster = [{**row, 'identity_id': self.engine.student_identity(row['roll_number'], row['name'], profiles),
                   'initial_registered': row['roll_number'] in rolls}
                  for row in roster if members is None or row['roll_number'] in members]
        if not roster:
            raise AppError('Enroll students before starting a lecture.')
        item = dict(id=uuid.uuid4().hex, title=title.strip(), lecture_date=day, lecture_time=clock,
                    timezone=zone, context=context, roster=roster, captures=[], overrides={},
                    face_resolutions={}, audit=[], state='draft', revision=0, created_utc=now())
        if schedule is not None:
            item['schedule']=dict(schedule)
            item['audit'].append(dict(action='scheduled_started',created_utc=now()))
        return self.save(item)

    @staticmethod
    def effective(item, capture, face):
        resolution = item['face_resolutions'].get(f"{capture['id']}:{face['face_id']}")
        if resolution:
            return resolution.get('roll_number') if resolution['action'] == 'assign' else None, False
        return (face['candidate_roll'], False) if face['decision'] == 'Matched' else (None, True)

    def aggregate(self, item):
        evidence = {row['roll_number']: set() for row in item['roster']}
        first_seen = {roll: [] for roll in evidence}
        reviews, pending = set(), 0
        for capture in item['captures']:
            for face in capture['detections']:
                roll, unresolved = self.effective(item, capture, face)
                if roll in evidence:
                    evidence[roll].add(capture['id'])
                    first_seen[roll].append(capture['created_utc'])
                if unresolved:
                    pending += 1
                    if face['decision'] == 'Review':
                        reviews.add(face['candidate_roll'])
        video_pending = 0
        scans = item.get('video_scans', [])
        for scan in scans:
            for track in scan['tracks']:
                roll = track.get('proposed_roll')
                if track['decision'] == 'accepted' and roll in evidence:
                    evidence[roll].add('video:' + scan['id'])
                    first_seen[roll].extend(sample['created_utc'] for sample in track.get('evidence',[]) if sample.get('roll_number')==roll)
                elif track['decision'] == 'pending':
                    video_pending += 1
                    if roll: reviews.add(roll)
        rows = []
        only_eye_search = not scans and bool(item['captures']) and all(
            capture['summary'].get('eye_search', False) for capture in item['captures']
        )
        for student in item['roster']:
            roll = student['roll_number']
            override = item['overrides'].get(roll)
            status = ('Present' if evidence[roll] else 'Review' if only_eye_search or roll in reviews or not student['initial_registered'] else 'Unconfirmed')
            rows.append(dict(roll_number=roll, name=student['name'],
                             status=override['status'] if override else status,
                             note=override['reason'] if override else 'Accepted in lecture evidence.' if evidence[roll] else 'Needs review.' if status == 'Review' else 'Not matched in lecture evidence; confirm Present or Absent after checking the student.',
                             source='Teacher correction' if override else 'Face recognition / reviewed faces',
                             capture_count=len(evidence[roll]), override=override))
        for row in rows:
            recorded=first_seen[row['roll_number']]
            if row.get('override') and row['status']=='Present':
                recorded=recorded+[row['override']['updated_utc']]
            row.update(self.arrival(item,row['status'],recorded))
        counts = Counter(row['status'] for row in rows)
        summary = dict(present=counts['Present'], absent=counts['Absent'], unconfirmed=counts['Unconfirmed'], review=counts['Review'],
                       pending_faces=pending, students=len(rows), captures=len(item['captures']),
                       video_pending=video_pending, video_scans=len(scans), video_frames=sum(scan['frame_count'] for scan in scans), late=sum(row.get('arrival_status')=='Late' for row in rows))
        return rows, summary

    @staticmethod
    def arrival(item,status,recorded):
        schedule=item.get('schedule')
        if not schedule:return {}
        result=dict(first_seen_utc=None,arrival_status=None)
        if status!='Present':return result
        samples=[]
        for value in recorded:
            try:
                instant=datetime.fromisoformat(value.replace('Z','+00:00'))
                if instant.tzinfo is not None:samples.append(instant.astimezone(timezone.utc))
            except (ValueError,TypeError,AttributeError):continue
        result['arrival_status']='Not assessed'
        if not samples:return result
        first=min(samples)
        result['first_seen_utc']=first.isoformat()
        try:
            if first.astimezone(ZoneInfo(schedule['timezone'])).date().isoformat()!=schedule['date']:return result
            cutoff=datetime.fromisoformat(schedule['cutoff_utc'])
            result['arrival_status']='Late' if first>cutoff else 'On time'
        except (ValueError,KeyError,TypeError,ZoneInfoNotFoundError):pass
        return result

    def view(self, item):
        if item['state'] == 'finalized':
            rows, summary = item['final_rows'], item['final_summary']
        else:
            rows, summary = self.aggregate(item)
        blockers = []
        if summary['pending_faces']:
            blockers.append(f"Review {summary['pending_faces']} unresolved face(s).")
        if summary.get('unconfirmed'):
            blockers.append(f"Confirm Present or Absent for {summary['unconfirmed']} unconfirmed student(s).")
        if summary['review']:
            blockers.append(f"Decide attendance for {summary['review']} student(s) needing review.")
        if any(scan['state'] == 'active' for scan in item.get('video_scans', [])):
            blockers.append('Stop video sampling before finalizing.')
        if summary.get('video_pending'):
            blockers.append(f"Review {summary['video_pending']} video track(s).")
        has_video_faces = any(scan['tracks'] for scan in item.get('video_scans', []))
        if not item['captures'] and not has_video_faces and len(item['overrides']) != len(item['roster']):
            blockers.append('Add a capture or manually decide every student’s attendance.')
        # Internal identity keys stay on disk; browser receives frozen display details only.
        public = {key: value for key, value in item.items() if key not in {'roster', 'final_rows', 'final_summary'}}
        public['video_scans'] = [{key: value for key, value in scan.items()
                                  if key not in {'frames', 'last_frame_at', 'gallery_hash', 'next_track'}}
                                 for scan in item.get('video_scans', [])]
        return {**public, 'attendance': rows, 'summary': summary, 'blockers': blockers,
                'can_finalize': item['state'] == 'draft' and not blockers}

    def list(self):
        result = []
        for path in self.root.glob('*/lecture.json'):
            try:
                result.append(self._summary_cache.get((path,), lambda: self._list_summary(path.parent.name)))
            except (AppError, OSError, KeyError, TypeError, ValueError):
                continue
        return sorted(result, key=lambda item: item['updated_utc'], reverse=True)

    def _list_summary(self, identifier):
        item = self.view(self.load(identifier))
        return {**{key: item[key] for key in ('id', 'title', 'lecture_date', 'lecture_time', 'timezone', 'context', 'state', 'summary', 'updated_utc', 'revision')}, **({'schedule': item['schedule']} if item.get('schedule') else {})}

    def snapshot(self, item):
        roster, vectors, rolls, _, _, _ = self.engine.registry()
        profiles = self.engine.profiles()
        identities = {self.engine.student_identity(row['roll_number'], row['name'], profiles): row['roll_number'] for row in roster}
        available = {str(roll): index for index, roll in enumerate(rolls)}
        frozen_vectors, frozen_rolls, frozen_names = [], [], []
        for row in item['roster']:
            active_roll = identities.get(row['identity_id'])
            if active_roll in available:
                frozen_vectors.append(vectors[available[active_roll]])
                frozen_rolls.append(row['roll_number'])
                frozen_names.append(row['name'])
        return (item['roster'], np.asarray(frozen_vectors, dtype=np.float32).reshape(-1, 512),
                np.asarray(frozen_rolls), np.asarray(frozen_names), item['context'])

    def capture(self, identifier, payload, rgb):
        item = self.draft(identifier, payload)
        source = payload.get('source', 'upload')
        if source not in ('upload', 'webcam'):
            raise AppError('Choose a photo or webcam capture.')
        fingerprint = hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()
        if any(row['fingerprint'] == fingerprint for row in item['captures']):
            raise AppError('This exact photo is already in the lecture. Choose another capture.')
        captured_at = now()
        report = self.engine.recognize(rgb, save=False, source=source, snapshot=self.snapshot(item),
                                       extra_detection=payload.get("extra_detection") is True, eye_search=payload.get("eye_search") is True)
        capture = dict(id=uuid.uuid4().hex, fingerprint=fingerprint, source=source, created_utc=captured_at,
                       summary=report['summary'], detections=report['detections'])
        directory = self.directory(identifier) / 'captures' / capture['id']
        try:
            atomic_write(directory / 'source.png', image_bytes(rgb, 'PNG'))
            item['captures'].append(capture)
            item['audit'].append(dict(action='capture_added', capture_id=capture['id'], created_utc=now()))
            view = self.save(item)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        report['lecture_capture'] = dict(lecture_id=identifier, capture_id=capture['id'])
        return dict(lecture=view, capture_report=report)

    def correct(self, identifier, payload):
        item = self.draft(identifier, payload)
        roll, status = payload.get('roll_number'), payload.get('status')
        if not isinstance(roll, str) or roll not in {row['roll_number'] for row in item['roster']} or status not in ('Present', 'Absent', 'auto'):
            raise AppError('Choose a student in this lecture and a valid attendance status.')
        reason = self.reason(payload)
        old = item['overrides'].pop(roll, None)
        if status != 'auto':
            item['overrides'][roll] = dict(status=status, reason=reason, updated_utc=now())
        item['audit'].append(dict(action='attendance_corrected', roll_number=roll, before=old,
                                  after=item['overrides'].get(roll), reason=reason, created_utc=now()))
        return self.save(item)

    def resolve(self, identifier, payload):
        item = self.draft(identifier, payload)
        capture = next((row for row in item['captures'] if row['id'] == payload.get('capture_id')), None)
        if not capture or type(payload.get('face_id')) is not int or not any(row['face_id'] == payload['face_id'] for row in capture['detections']):
            raise AppError('Choose a face in this lecture.')
        action, roll = payload.get('action'), payload.get('roll_number')
        if not isinstance(action, str) or action not in ('assign', 'ignore', 'auto') or (action == 'assign' and (not isinstance(roll, str) or roll not in {row['roll_number'] for row in item['roster']})):
            raise AppError('Choose a valid face decision and student.')
        reason = self.reason(payload)
        key = f"{capture['id']}:{payload['face_id']}"
        old = item['face_resolutions'].pop(key, None)
        if action != 'auto':
            item['face_resolutions'][key] = dict(action=action, roll_number=roll if action == 'assign' else None, reason=reason, updated_utc=now())
        assigned = [self.effective(item, capture, face)[0] for face in capture['detections']]
        counts = Counter(roll for roll in assigned if roll)
        if any(count > 1 for count in counts.values()):
            raise AppError('Two faces in this capture cannot be assigned to the same student. Correct the other face first.')
        item['audit'].append(dict(action='face_reviewed', capture_id=capture['id'], face_id=payload['face_id'],
                                  before=old, after=item['face_resolutions'].get(key), reason=reason, created_utc=now()))
        return self.save(item)

    def finalize(self, identifier, payload):
        item = self.draft(identifier, payload)
        view = self.view(item)
        if payload.get('confirm') is not True:
            raise AppError('Confirm that you have reviewed this attendance sheet.')
        if view['blockers']:
            raise AppError(' '.join(view['blockers']))
        item.update(state='finalized', finalized_utc=now(), final_rows=view['attendance'], final_summary=view['summary'])
        item['audit'].append(dict(action='finalized', created_utc=now()))
        return self.save(item)

    def export(self, identifier, kind):
        item = self.load(identifier)
        if kind == 'audit':
            rows = [{**row, 'before': json.dumps(row.get('before')), 'after': json.dumps(row.get('after'))} for row in item['audit']]
            return csv_bytes(rows, ['created_utc', 'action', 'roll_number', 'capture_id', 'face_id', 'reason', 'before', 'after'])
        if item['state'] != 'finalized':
            raise AppError('Finalize the lecture before downloading attendance.')
        rows = [{**item['context'], **{key: item[key] for key in ('title', 'lecture_date', 'lecture_time', 'timezone')}, **row} for row in item['final_rows']]
        columns=['title', 'lecture_date', 'lecture_time', 'timezone', 'class_name', 'subject_name', 'subject_code', 'roll_number', 'name', 'status', 'note', 'source', 'capture_count']
        if item.get('schedule'):
            columns+=['first_seen_utc','arrival_status','late_cutoff_utc']
            for row in rows:row['late_cutoff_utc']=item['schedule']['cutoff_utc']
        return csv_bytes(rows,columns)

    def media(self, identifier, capture_id, face_id=None):
        item = self.load(identifier)
        capture = next((row for row in item['captures'] if row['id'] == capture_id), None)
        if not capture:
            raise AppError('Capture not found.')
        with Image.open(self.directory(identifier) / 'captures' / capture_id / 'source.png') as image:
            rgb = np.array(image.convert('RGB'))
        if face_id is not None:
            face = next((row for row in capture['detections'] if row['face_id'] == int(face_id)), None)
            if not face:
                raise AppError('Face not found.')
            x, y, w, h = (face[key] for key in ('x', 'y', 'w', 'h'))
            crop = Image.fromarray(rgb).crop((max(0,x), max(0,y), min(rgb.shape[1],x+w), min(rgb.shape[0],y+h)))
            crop.thumbnail((240,240))
            return image_bytes(np.array(crop))
        records = []
        names = {row['roll_number']: row['name'] for row in item['roster']}
        for face in capture['detections']:
            roll, pending = self.effective(item, capture, face)
            records.append({**face, 'decision': 'Matched' if roll else 'Review' if pending else 'Unknown',
                            'display_label': f'{roll} · {names[roll]}' if roll else f"Face {face['face_id']} · {'Needs review' if pending else 'Ignored (reviewed)'}"})
        return image_bytes(self.engine.annotate(rgb, records))

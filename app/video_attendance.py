"""Sampled-frame tracking and teacher-reviewed temporal attendance proposals."""
import hashlib
import json
import re
import time
import uuid

import cv2
import numpy as np
from PIL import Image
from engine import AppError, atomic_write, image_bytes, now


REQUIRED_SAMPLES = 3
MIN_INTERVAL = 1.0


def quality(face, settings=None):
    settings=settings or {}
    pixels = np.asarray(face['face'],dtype=np.uint8)
    gray = cv2.cvtColor(pixels,cv2.COLOR_RGB2GRAY)
    sharpness = float(cv2.Laplacian(gray,cv2.CV_64F).var())
    brightness = float(gray.mean())
    area = face['facial_area']
    clear = min(area['w'],area['h']) >= settings.get('minimum_face_pixels',48) and sharpness >= settings.get('minimum_sharpness',35) and 20 <= brightness <= 235
    score = min(sharpness/250,1) * min(min(area['w'],area['h'])/120,1)
    return dict(clear=clear, sharpness=round(sharpness,1), brightness=round(brightness,1), score=round(score,4))


def overlap(a,b):
    intersection = max(0,min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])) * max(0,min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))
    return intersection / max(a[2]*a[3]+b[2]*b[3]-intersection,1e-9)


def associate(tracks, boxes, frame_number):
    """Conservative overlap assignment. Ambiguous crossings start new tracks."""
    candidates = []
    for index,box in enumerate(boxes):
        for track in tracks:
            if track.get('ended') or frame_number-track['last_seen_frame'] > 2:
                continue
            value = overlap(box,track['box'])
            if value >= .15:
                candidates.append((value,index,track['id']))
    result = {}
    used = set()
    for score,index,identifier in sorted(candidates,reverse=True):
        if index in result or identifier in used:
            continue
        ambiguous = any((other_index==index or other_id==identifier) and (other_index,other_id)!=(index,identifier)
                        and abs(other_score-score)<.1 for other_score,other_index,other_id in candidates)
        if not ambiguous:
            result[index]=identifier
            used.add(identifier)
    return result


class VideoAttendance:
    def __init__(self, lectures):
        self.lectures=lectures
        self.engine=lectures.engine

    def scan(self,item,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):
            raise AppError('Choose a video scan in this lecture.')
        scan=next((scan for scan in item.get('video_scans',[]) if scan['id']==identifier),None)
        if scan is None:
            raise AppError('Video scan not found.')
        return scan

    def gallery_hash(self):
        rules={key:self.engine.settings.get(key,default) for key,default in [('detector','retinaface'),('model','Facenet512'),('normalization','base'),('cosine_distance_threshold',.3),('minimum_gap',.05)]}
        return hashlib.sha256((self.engine.root/'embeddings/student_templates.npz').read_bytes()+json.dumps(rules,sort_keys=True).encode()).hexdigest()

    def start(self,identifier,payload):
        item=self.lectures.draft(identifier,payload)
        if any(scan['state']=='active' for scan in item.get('video_scans',[])):
            raise AppError('Stop the active video scan before starting another.')
        if not len(self.lectures.snapshot(item)[2]):
            raise AppError('Register reference photos for this lecture before scanning.')
        scan=dict(id=uuid.uuid4().hex,state='active',started_utc=now(),frame_count=0,
                  empty_frames=0,frames=[],last_frame_at=None,tracks=[],next_track=1,
                  gallery_hash=self.gallery_hash(),required_samples=self.engine.settings.get('video_required_samples',REQUIRED_SAMPLES),
                  quality_settings=dict(minimum_face_pixels=self.engine.settings.get('video_min_face_pixels',48),minimum_sharpness=self.engine.settings.get('video_min_sharpness',35)),
                  sample_interval_ms=self.engine.settings.get('video_sample_interval_ms',1500),
                  matching_settings={key:self.engine.settings.get(key,default) for key,default in [('detector','retinaface'),('model','Facenet512'),('normalization','base'),('cosine_distance_threshold',.3),('minimum_gap',.05)]})
        item.setdefault('video_scans',[]).append(scan)
        item['audit'].append(dict(action='video_started',capture_id=scan['id'],created_utc=now()))
        return dict(lecture=self.lectures.save(item),scan_id=scan['id'])

    def frame(self,identifier,scan_id,payload,rgb):
        frame_id=payload.get('frame_id')
        if not isinstance(frame_id,str) or not re.fullmatch(r'[a-f0-9]{32}',frame_id):
            raise AppError('Provide a valid frame identifier.')
        item=self.lectures.load(identifier)
        scan=self.scan(item,scan_id)
        if any(frame['id']==frame_id for frame in scan['frames']):
            return dict(lecture=self.lectures.view(item),scan_id=scan_id,note='Frame already processed.')
        item=self.lectures.draft(identifier,payload)
        scan=self.scan(item,scan_id)
        if scan['state']!='active':
            raise AppError('This video scan has stopped.')
        if scan['gallery_hash']!=self.gallery_hash():
            raise AppError('Student templates changed or matching rules changed. Stop this scan and start another before collecting more evidence.')
        if scan['frame_count'] >= 600 or len(scan['tracks']) >= 500:
            raise AppError('This scan reached its limit. Stop and review it, then start another scan if needed.')
        timestamp=time.time()
        if scan['last_frame_at'] is not None and timestamp-scan['last_frame_at']<MIN_INTERVAL:
            return dict(lecture=self.lectures.view(item),scan_id=scan_id,note='Waiting for the next sample.')
        digest=hashlib.sha256(str(rgb.shape).encode()+rgb.tobytes()).hexdigest()
        if any(frame['sha256']==digest for frame in scan['frames']):
            return dict(lecture=self.lectures.view(item),scan_id=scan_id,note='Repeated frame skipped. Move slightly or wait for a new view.')
        observed_at=now()
        try:
            faces=self.engine.detect(rgb)
        except AppError as error:
            if error.code!='face_not_found':raise
            faces=[]
        records=self.engine.match(rgb,faces,snapshot=self.lectures.snapshot(item))[0] if faces else []
        height,width=rgb.shape[:2]
        number=scan['frame_count']+1
        boxes=[[record['x']/width,record['y']/height,record['w']/width,record['h']/height] for record in records]
        assignments=associate(scan['tracks'],boxes,number)
        tracks={track['id']:track for track in scan['tracks']}
        new_files=[]
        old_files=[]
        try:
            for index,(face,record,box) in enumerate(zip(faces,records,boxes)):
                details=quality(face,scan.get('quality_settings'))
                accepted=record['decision']=='Matched' and details['clear']
                roll=record['candidate_roll'] if accepted else None
                track=tracks.get(assignments.get(index))
                # A conflicting accepted identity never inherits the former person's votes.
                if track and roll and track.get('last_valid_roll') and track['last_valid_roll']!=roll:
                    track['ended']=True
                    track=None
                if track is None:
                    track=dict(id=scan['next_track'],box=box,last_seen_frame=number,observations=[],seen=0,
                               proposed_roll=None,decision='pending',best=None,last_valid_roll=None)
                    scan['next_track']+=1
                    scan['tracks'].append(track)
                track.update(box=box,last_seen_frame=number)
                track['seen']+=1
                sample=dict(frame=number,created_utc=observed_at,roll_number=roll,
                            candidate_roll=record['candidate_roll'],candidate_name=record['candidate_name'],
                            cosine_distance=record['cosine_distance'],gap=record['gap'],quality=details,
                            reason=record['reason'] if details['clear'] else 'Move closer, pause, or improve the lighting for a clearer face.')
                track['observations']=(track['observations']+[sample])[-max(5,scan['required_samples']):]
                if roll:track['last_valid_roll']=roll
                required=scan['required_samples']
                recent=track['observations'][-required:]
                if len(recent)==required and roll and all(row['roll_number']==roll and row['frame']==number-required+1+offset for offset,row in enumerate(recent)):
                    track['proposed_roll']=roll
                    if track['decision']=='pending':track['evidence']=recent
                if track['decision']=='pending' and (not track.get('last_valid_roll') or roll) and (track['best'] is None or (roll and track['best'].get('roll_number') != roll) or details['score']>track['best']['quality']):
                    directory=self.lectures.directory(identifier)/'video'/scan_id
                    name=f"track-{track['id']}-{frame_id}.jpg"
                    path=directory/name
                    patch=Image.fromarray(np.asarray(face['face'],dtype=np.uint8))
                    patch.thumbnail((256,256))
                    atomic_write(path,image_bytes(np.array(patch)))
                    new_files.append(path)
                    if track['best']:old_files.append(directory/track['best']['filename'])
                    track['best']=dict(filename=name,quality=details['score'],frame=number,roll_number=roll)
            for track in scan['tracks']:
                if number-track['last_seen_frame']>2:track['ended']=True
            scan['frame_count']=number
            scan['empty_frames']+=not bool(faces)
            scan['last_frame_at']=timestamp
            scan['width'],scan['height']=width,height
            scan['frames'].append(dict(id=frame_id,sha256=digest,created_utc=now()))
            view=self.lectures.save(item)
        except Exception:
            for path in new_files:path.unlink(missing_ok=True)
            raise
        for path in old_files:
            try: path.unlink(missing_ok=True)
            except OSError: pass
        return dict(lecture=view,scan_id=scan_id,note='No faces visible. Sampling will continue.' if not faces else 'Frame processed.')

    def stop(self,identifier,scan_id,payload):
        item=self.lectures.draft(identifier,payload)
        scan=self.scan(item,scan_id)
        if scan['state']=='active':
            scan.update(state='stopped',stopped_utc=now())
            item['audit'].append(dict(action='video_stopped',capture_id=scan_id,created_utc=now()))
            return dict(lecture=self.lectures.save(item),scan_id=scan_id)
        return dict(lecture=self.lectures.view(item),scan_id=scan_id)

    def review(self,identifier,scan_id,payload):
        item=self.lectures.draft(identifier,payload)
        scan=self.scan(item,scan_id)
        if scan['state']=='active':raise AppError('Stop sampling before reviewing its evidence.')
        action=payload.get('action')
        if action not in ('accept','ignore','reset','ignore_unverified'):
            raise AppError('Choose a video review decision.')
        if action=='ignore_unverified':
            selected=[track for track in scan['tracks'] if track['decision']=='pending' and not track['proposed_roll']]
        else:
            track_id=payload.get('track_id')
            if type(track_id) is not int:raise AppError('Choose a video track.')
            selected=[track for track in scan['tracks'] if track['id']==track_id]
            if not selected:raise AppError('Video track not found.')
        for track in selected:
            if action=='accept' and not track['proposed_roll']:
                raise AppError('This track does not have enough consistent clear samples. Use teacher roll call if needed.')
            before=track['decision']
            track['decision']='accepted' if action=='accept' else 'pending' if action=='reset' else 'ignored'
            track['reviewed_utc']=now()
            item['audit'].append(dict(action='video_'+action,capture_id=scan_id,face_id=track['id'],
                                      roll_number=track.get('proposed_roll'),before=before,after=track['decision'],created_utc=now()))
        return dict(lecture=self.lectures.save(item),scan_id=scan_id)

    def photo(self,identifier,scan_id,track_id):
        item=self.lectures.load(identifier)
        scan=self.scan(item,scan_id)
        track=next((track for track in scan['tracks'] if track['id']==int(track_id)),None)
        if track is None or track['best'] is None:raise AppError('Video face crop not found.')
        path=self.lectures.directory(identifier)/'video'/scan_id/track['best']['filename']
        try:return path.read_bytes()
        except OSError as error:raise AppError('Video face crop could not be read.') from error

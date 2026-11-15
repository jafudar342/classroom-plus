"""Independent-photo experiments and threshold replay, isolated from attendance."""
import hashlib
import json
import math
import re
import uuid
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from engine import AppError, atomic_write, image_bytes, now


def fingerprint(rgb):
    return hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()


def score_photo(truth, detections, mode, distance=.3, gap=.05, eye=.7):
    predictions = []
    for face in detections:
        if mode == 'full':
            value = face.get('cosine_distance')
            accepted = (value is not None and value <= distance and
                        (face.get('gap') is None or face['gap'] >= gap) and min(face['w'],face['h']) >= 32)
            strength = -value if value is not None else -2
        else:
            strength = face.get('eye_similarity', 0)
            accepted = strength >= eye
        if accepted:
            predictions.append((strength,face))
    if mode == 'full':
        claims = Counter(face['candidate_identity'] for _,face in predictions)
        predictions = [(s,f) for s,f in predictions if claims[f['candidate_identity']] == 1]
    assigned = {}
    extras = []
    for strength,face in sorted(predictions, key=lambda pair:pair[0], reverse=True):
        cx,cy = face['x']+face['w']/2, face['y']+face['h']/2
        index = next((i for i,row in enumerate(truth) if row['x']<=cx<row['x']+row['w'] and row['y']<=cy<row['y']+row['h']), None)
        if index is None or index in assigned:
            extras.append(face)
        else:
            assigned[index] = face
    counts = dict(correct=0, wrong=0, missed=0, unknown_rejected=0, unknown_false_accept=0,
                  extra_predictions=len(extras), known=sum(row['identity'] is not None for row in truth))
    details = []
    for i,row in enumerate(truth):
        prediction = assigned.get(i)
        if row['identity'] is None:
            outcome = 'unknown_false_accept' if prediction else 'unknown_rejected'
        else:
            outcome = 'missed' if not prediction else 'correct' if prediction['candidate_identity'] == row['identity'] else 'wrong'
        counts[outcome] += 1
        details.append(dict(expected_roll=row['roll_number'], expected_name=row['name'], outcome=outcome,
                            predicted_roll=prediction['candidate_roll'] if prediction else '',
                            predicted_name=prediction['candidate_name'] if prediction else ''))
    return counts, details


class Evaluation:
    def __init__(self, root, engine):
        self.root = Path(root) / 'data/evaluation'
        self.engine = engine

    def path(self, category, identifier, filename):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):
            raise AppError('Evaluation record not found.')
        return self.root / category / identifier / filename

    def read(self, category, identifier):
        try:
            return json.loads(self.path(category,identifier,'record.json').read_text())
        except (OSError,ValueError) as error:
            raise AppError('Evaluation record could not be read.') from error

    def catalog(self):
        photos, runs = [], []
        for category, collection in [('photos',photos),('runs',runs)]:
            for path in (self.root/category).glob('*/record.json'):
                try:
                    record = self.read(category,path.parent.name)
                    if category == 'photos':
                        collection.append({key:record[key] for key in ('id','title','split','labels','revision','created_utc')})
                    else:
                        collection.append({key:record[key] for key in ('id','created_utc','photo_ids','gallery_sha256')})
                except (AppError,KeyError,TypeError):
                    continue
        return dict(photos=sorted(photos,key=lambda p:p['created_utc'],reverse=True),
                    runs=sorted(runs,key=lambda p:p['created_utc'],reverse=True))

    def labels(self, payload, width, height, originals=None):
        labels = payload.get('labels')
        if not isinstance(labels,list) or not 1 <= len(labels) <= 100:
            raise AppError('Label every person in the photo (1–100 boxes).')
        students = {row['roll_number']:row for row in self.engine.registry()[0]}
        profiles = self.engine.profiles()
        result, seen = [], set()
        for row in labels:
            if not isinstance(row,dict) or any(type(row.get(k)) is not int for k in ('x','y','w','h')):
                raise AppError('Draw valid rectangular labels.')
            x,y,w,h = (row[k] for k in ('x','y','w','h'))
            if x<0 or y<0 or w<8 or h<8 or x+w>width or y+h>height:
                raise AppError('Draw a box of at least 8 pixels inside the photo.')
            roll = row.get('roll_number')
            source_index = row.get('source_index')
            if source_index is not None:
                if (originals is None or type(source_index) is not int or not 0 <= source_index < len(originals)):
                    raise AppError('Reopen this photo before editing its saved labels.')
                original = originals[source_index]
                original_roll = original['roll_number'] if original['identity'] is not None else 'unknown'
                if roll != original_roll:
                    raise AppError('Reselect the expected identity for this box.')
                name, identity = original['name'], original['identity']
                if identity is not None:
                    if identity in seen:
                        raise AppError('A student can have only one label per photo.')
                    seen.add(identity)
            elif roll == 'unknown':
                name, identity = 'Unregistered person', None
            elif isinstance(roll,str) and roll in students:
                identity = self.engine.student_identity(roll,students[roll]['name'],profiles)
                if identity in seen:
                    raise AppError('A student can have only one label per photo.')
                seen.add(identity)
                name = students[roll]['name']
                identity = self.engine.student_identity(roll,name,profiles)
            else:
                raise AppError('Choose a registered roster entry or Unregistered person.')
            for other in result:
                if min(x+w,other['x']+other['w'])>max(x,other['x']) and min(y+h,other['y']+other['h'])>max(y,other['y']):
                    raise AppError('Label boxes must not overlap. Use one box around each person’s face and visible eyes.')
            result.append(dict(x=x,y=y,w=w,h=h,roll_number='' if roll=='unknown' else roll,name=name,identity=identity))
        return result

    def add(self, payload, rgb):
        title = payload.get('title','')
        if not isinstance(title,str) or not 1 <= len(title.strip()) <= 120:
            raise AppError('Enter a photo title of 1–120 characters.')
        if payload.get('split') not in ('validation','test') or payload.get('independent') is not True or payload.get('complete') is not True:
            raise AppError('Choose a split and confirm separate photos with every person labeled.')
        labels = self.labels(payload,rgb.shape[1],rgb.shape[0])
        digest = fingerprint(rgb)
        for path in (self.engine.root/'data/reference').glob('*/*'):
            if path.suffix.lower() not in ('.jpg','.jpeg','.png','.webp'):
                continue
            try:
                with Image.open(path) as image:
                    if fingerprint(np.array(ImageOps.exif_transpose(image).convert('RGB'))) == digest:
                        raise AppError('This is an enrollment photo. Choose a separate test photo.')
            except OSError:
                continue
        for record in self.catalog()['photos']:
            if self.read('photos',record['id'])['sha256'] == digest:
                raise AppError('This photo is already saved. Use its existing labels.')
        identifier = uuid.uuid4().hex
        record = dict(id=identifier,title=title.strip(),split=payload['split'],labels=labels,sha256=digest,
                      created_utc=now(),revision=1,width=rgb.shape[1],height=rgb.shape[0])
        directory = self.path('photos',identifier,'record.json').parent
        try:
            atomic_write(directory/'image.png',image_bytes(rgb,'PNG'))
            atomic_write(directory/'record.json',json.dumps(record).encode())
        except Exception:
            import shutil
            shutil.rmtree(directory,ignore_errors=True)
            raise
        return record

    def relabel(self, identifier, payload):
        record = self.read('photos',identifier)
        if type(payload.get('revision')) is not int or payload['revision'] != record['revision']:
            raise AppError('Labels changed in another tab. Reopen this photo.')
        if payload.get('complete') is not True:
            raise AppError('Confirm that every person is labeled.')
        record['labels'] = self.labels(payload,record['width'],record['height'],record['labels'])
        record['revision'] += 1
        atomic_write(self.path('photos',identifier,'record.json'),json.dumps(record).encode())
        return record

    def run(self, payload):
        ids = payload.get('photo_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=10 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
            raise AppError('Select 1–10 different labeled photos.')
        selected = [self.read('photos',identifier) for identifier in ids]
        if len({photo['split'] for photo in selected}) != 1:
            raise AppError('Compare one split at a time. Select validation photos or test photos.')
        roster = self.engine.registry()[0]
        profiles = self.engine.profiles()
        identities = {row['roll_number']:self.engine.student_identity(row['roll_number'],row['name'],profiles) for row in roster}
        results = []
        for photo in selected:
            item = dict(photo_id=photo['id'],title=photo['title'],labels=photo['labels'],revision=photo['revision'],methods={})
            try:
                with Image.open(self.path('photos',photo['id'],'image.png')) as image:
                    rgb = np.array(image.convert('RGB'))
            except (OSError, Image.DecompressionBombError):
                item['methods'] = {mode:dict(detections=[],error='The saved test image could not be read. Restore it from a backup.')
                                   for mode in ('full','eye')}
                results.append(item)
                continue
            for mode in ('full','eye'):
                try:
                    report = self.engine.recognize(rgb,save=False,eye_search=mode=='eye')
                    detections = [{**face,'candidate_identity':identities.get(face['candidate_roll'])} for face in report['detections']]
                    item['methods'][mode] = dict(detections=detections,error=None)
                except AppError as error:
                    if error.code == 'face_not_found':
                        item['methods'][mode] = dict(detections=[],error=None)
                    else:
                        item['methods'][mode] = dict(detections=[],error=str(error))
            results.append(item)
        reference_manifest = {str(path.relative_to(self.engine.root)):hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted((self.engine.root/'data/reference').glob('*/*')) if path.is_file()}
        record = dict(id=uuid.uuid4().hex,created_utc=now(),photo_ids=ids,split=selected[0]['split'],reference_manifest=reference_manifest,
                      settings=self.engine.settings,model=self.engine.metadata['model'],
                      gallery_sha256=hashlib.sha256((self.engine.root/'embeddings/student_templates.npz').read_bytes()).hexdigest(),photos=results)
        atomic_write(self.path('runs',record['id'],'record.json'),json.dumps(record).encode())
        return self.view(record,self.engine.settings.get("cosine_distance_threshold",.3),self.engine.settings.get("minimum_gap",.05),.7)

    def view(self, record, distance=.3, gap=.05, eye=.7):
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in (distance,gap,eye)) or not 0<=distance<=2 or not 0<=gap<=2 or not .7<=eye<=1:
            raise AppError('Use cosine distance/gap between 0 and 2 and eye correlation between 0.70 and 1.')
        methods = {}
        for mode in ('full','eye'):
            totals = Counter(); photos=[]; errors=0
            for photo in record['photos']:
                method = photo['methods'][mode]
                if method['error']:
                    errors += 1
                    photos.append(dict(photo_id=photo['photo_id'],title=photo['title'],error=method['error']))
                    continue
                counts,details = score_photo(photo['labels'],method['detections'],mode,distance,gap,eye)
                totals.update(counts)
                photos.append(dict(photo_id=photo['photo_id'],title=photo['title'],counts=counts,details=details))
            proposed = totals['correct']+totals['wrong']+totals['unknown_false_accept']+totals['extra_predictions']
            methods[mode] = dict(counts=dict(totals),photos=photos,errors=errors,
                recall=round(100*totals['correct']/totals['known'],1) if totals['known'] else None,
                precision=round(100*totals['correct']/proposed,1) if proposed else None)
        return {**{k:record[k] for k in ('id','created_utc','photo_ids','split','model','gallery_sha256')},
                'thresholds':dict(distance=distance,gap=gap,eye=eye),'methods':methods}

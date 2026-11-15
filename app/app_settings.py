"""Validated settings backed by the existing matching and dashboard configuration."""
import hashlib
import json
import math
import re
from engine import AppError
from model_catalog import DETECTORS, EMBEDDINGS, prepare, rebuild_gallery, verify_sources

FIELDS={
    'detector':dict(kind='enum',default='retinaface',choices=[model['id'] for model in DETECTORS]),
    'model':dict(kind='enum',default='Facenet512',choices=[model['id'] for model in EMBEDDINGS]),
    'cosine_distance_threshold':dict(kind='number',default=.3,minimum=0,maximum=2),
    'minimum_gap':dict(kind='number',default=.05,minimum=0,maximum=2),
    'default_extra_detection':dict(kind='bool',default=False),
    'default_eye_search':dict(kind='bool',default=False),
    'live_interval_ms':dict(kind='int',default=2500,minimum=1000,maximum=10000),
    'video_sample_interval_ms':dict(kind='int',default=1500,minimum=1000,maximum=10000),
    'video_required_samples':dict(kind='int',default=3,minimum=3,maximum=8),
    'video_min_face_pixels':dict(kind='int',default=48,minimum=48,maximum=256),
    'video_min_sharpness':dict(kind='number',default=35,minimum=10,maximum=1000),
    'default_late_after_minutes':dict(kind='int',default=10,minimum=0,maximum=180),
    'default_start_time':dict(kind='time',default='09:00'),
    'default_end_time':dict(kind='time',default='10:00'),
    'default_directory_view':dict(kind='enum',default='grid',choices=['grid','list']),
    'attendance_target':dict(kind='number',default=75,minimum=0,maximum=100),
}

class AppSettings:
    def __init__(self,root,engine,lectures,analytics):
        self.root,self.engine,self.lectures,self.analytics=root,engine,lectures,analytics
        self.path=root/'config/demo_matching_settings.json'
        self.dashboard_path=root/'config/dashboard_settings.json'
        self.status=dict(running=False,message='',current=0,total=0)

    def revision(self):
        digest=hashlib.sha256()
        for path in (self.path,self.dashboard_path):
            digest.update(str(path.name).encode()+b'\0')
            digest.update(path.read_bytes() if path.exists() else b'<missing>')
        return digest.hexdigest()

    @staticmethod
    def validate(values):
        if not isinstance(values,dict) or set(values)!=set(FIELDS):raise AppError('Reload Settings before saving the complete form.')
        for key,field in FIELDS.items():
            value=values[key];kind=field['kind'];valid=True
            if kind=='bool':valid=type(value) is bool
            elif kind in ('number','int'):
                valid=type(value) in ((int,) if kind=='int' else (int,float)) and field['minimum']<=value<=field['maximum'] and math.isfinite(value)
            elif kind=='enum':valid=isinstance(value,str) and value in field['choices']
            elif kind=='time':valid=isinstance(value,str) and bool(re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value))
            if not valid:
                if key in ('detector','model'):raise AppError('Choose one of the supported models listed in Settings.')
                raise AppError(f"Choose a valid {key.replace('_',' ')}.")
        if values['default_start_time']>=values['default_end_time']:raise AppError('The default end time must follow the default start time on the same day.')

    def read(self):
        try:
            raw=json.loads(self.path.read_text())
            if not isinstance(raw,dict):raise ValueError()
            if raw!=self.engine.settings:
                raise AppError('Matching settings changed outside the app. Restart Classroom+ before editing project settings.')
            values={key:raw.get(key,field['default']) for key,field in FIELDS.items()}
            values['attendance_target']=self.analytics.target()
            self.validate(values)
            if raw.get('normalization')!='base' or self.engine.metadata.get('model')!=values['model'] or self.engine.metadata.get('input_normalization')!='base':
                raise AppError('The selected embedding model does not match the saved student templates. Restore compatible matching metadata.')
            return raw,values
        except (OSError,ValueError,TypeError) as error:raise AppError('Settings could not be read. Restore the saved configuration before editing.') from error

    def active_scans(self):
        active=[]
        for lecture in self.lectures.list():
            if lecture['state']!='draft':continue
            stored=self.lectures.load(lecture['id'])
            if any(scan['state']=='active' for scan in stored.get('video_scans',[])):
                active.append(dict(id=lecture['id'],title=lecture['title']))
        return active

    def profiles(self,raw):
        stored=raw.get('model_profiles',{})
        if not isinstance(stored,dict) or set(stored)-set(FIELDS['model']['choices']):
            raise AppError('Saved model matching profiles need repair before editing Settings.')
        profiles={model:dict(cosine_distance_threshold=.3,minimum_gap=.05,calibrated=False) for model in FIELDS['model']['choices']}
        for model,profile in stored.items():
            if (not isinstance(profile,dict) or set(profile)!=set(profiles[model])
                    or type(profile.get('calibrated')) is not bool
                    or any(type(profile.get(key)) not in (int,float) or not 0<=profile[key]<=2 for key in ('cosine_distance_threshold','minimum_gap'))):
                raise AppError('Saved model matching profiles need repair before editing Settings.')
            profiles[model]=dict(profile)
        # The active flat settings also support existing notebooks and capture code.
        profiles[raw['model']]=dict(cosine_distance_threshold=raw.get('cosine_distance_threshold',.3),minimum_gap=raw.get('minimum_gap',.05),calibrated=raw.get('calibrated',False))
        return profiles

    def view(self):
        raw,values=self.read()
        return dict(revision=self.revision(),values=values,defaults={key:field['default'] for key,field in FIELDS.items()},
                    model_profiles=self.profiles(raw),
                    models=dict(detectors=DETECTORS,embeddings=EMBEDDINGS),
                    gallery=dict(model=self.engine.metadata['model'],dimensions=512,normalization='base',templates=len(self.engine.registry()[2])),
                    active_scans=self.active_scans())

    def save(self,payload):
        try:
            return self._save(payload)
        except Exception as error:
            self.status=dict(running=False,message=str(error),current=0,total=0)
            raise

    def _save(self,payload):
        if payload.get('revision')!=self.revision():raise AppError('Settings changed in another tab. Discard and reload before saving.','stale_revision')
        raw,current=self.read();values=payload.get('values');self.validate(values)
        if values==current:return self.view()
        if self.active_scans():raise AppError('Stop active video scans in their lecture review screens before changing project settings.')
        model_changed=current['model']!=values['model']
        pipeline_changed=model_changed or current['detector']!=values['detector']
        if model_changed and payload.get('confirm_model_change') is not True:
            raise AppError('Confirm rebuilding registered student templates before activating another embedding model.')
        def progress(message,current=0,total=0):
            self.status=dict(running=True,message=message,current=current,total=total)
        gallery=None
        source_paths=[self.engine.root/path for path in ('embeddings/student_templates.npz','embeddings/metadata.json','data/roster.csv','config/reference_face_selections.json')]
        originals={path:path.read_bytes() if path.exists() else None for path in source_paths}
        if pipeline_changed:
            progress('Preparing models. The first activation may download weights; keep this page open.')
            try:prepare(values['detector'],values['model'])
            except Exception as error:
                raise AppError(f'Model preparation failed: {error}. The current models and templates were kept. Check your connection and try again.') from error
        if model_changed:
            gallery=rebuild_gallery(self.engine,values['model'],progress)
        updated=dict(raw)
        updated.pop('attendance_target',None)
        updated.update({key:value for key,value in values.items() if key!='attendance_target'})
        if any(current[key]!=values[key] for key in ('detector','model','cosine_distance_threshold','minimum_gap')):updated['calibrated']=False
        profiles=self.profiles(raw)
        if current['detector']!=values['detector']:
            for profile in profiles.values():profile['calibrated']=False
        profiles[values['model']]=dict(cosine_distance_threshold=values['cosine_distance_threshold'],minimum_gap=values['minimum_gap'],calibrated=updated.get('calibrated',False))
        updated['model_profiles']=profiles
        files={self.path:json.dumps(updated,indent=2).encode(),self.dashboard_path:json.dumps(dict(target=values['attendance_target'])).encode()}
        metadata=dict(self.engine.metadata)
        if pipeline_changed:
            metadata.update(model=values['model'],detector=values['detector'],reference_detector=metadata.get('reference_detector',metadata.get('detector','retinaface')))
            if gallery is not None:
                content,manifest=gallery
                verify_sources(self.root,manifest['sources'])
                metadata.update(dimensions=512,input_normalization='base',embedding_normalization='L2',template_method='sum_of_unit_embeddings_then_L2',updated_utc=manifest['created_utc'])
                files[self.root/'embeddings/student_templates.npz']=content
                files[self.root/'embeddings/template_sources.json']=json.dumps(manifest,indent=2).encode()
            files[self.root/'embeddings/metadata.json']=json.dumps(metadata,indent=2).encode()
        # Recheck after slow downloads/rebuilding so external edits cannot be overwritten.
        if payload.get('revision')!=self.revision():raise AppError('Settings changed during model preparation. No changes were saved. Reload and try again.','stale_revision')
        if any((path.read_bytes() if path.exists() else None)!=content for path,content in originals.items()):
            raise AppError('Student templates or face selections changed during model preparation. No changes were saved. Reload and try again.')
        self.engine._commit_management(files,[],dict(action='save_app_settings',changed_fields=[key for key in FIELDS if current[key]!=values[key]]))
        self.engine.settings=updated
        self.engine.metadata=metadata
        if any(current[key]!=values[key] for key in ('detector','model')):
            self.engine.previews.clear()
            self.engine.eye_patch_cache.clear()
        self.status=dict(running=False,message='Models activated and templates rebuilt.' if model_changed else 'Project settings saved.',current=0,total=0)
        return self.view()

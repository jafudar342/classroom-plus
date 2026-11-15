import hashlib
import json
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
import test_app_settings as fixtures
from engine import AppError
from model_catalog import reference_face


class ModelSwitchTests(unittest.TestCase):
    setup_engine=fixtures.SettingsTests.setup_engine
    setUp=fixtures.SettingsTests.setUp
    tearDown=fixtures.SettingsTests.tearDown
    save=fixtures.SettingsTests.save
    def photos(self):
        for roll in ('1','2'):
            folder=self.root/'data/reference'/roll;folder.mkdir(parents=True,exist_ok=True)
            Image.new('RGB',(64,64),(110,120,130)).save(folder/'reference.jpg')
        self.engine.detect=lambda rgb,detector=None:[self.face()]
        self.engine.encode=lambda rgb,model_name=None:np.eye(512,dtype=np.float32)[10]
    face=staticmethod(lambda:dict(face=np.zeros((64,64,3),dtype=np.uint8),facial_area=dict(x=1,y=2,w=64,h=64)))
    def activate(self,**values):
        current=self.store.view()
        return self.store.save(dict(revision=current['revision'],values={**current['values'],**values},confirm_model_change=True))
    def test_confirmation_required_before_model_work(self):
        with patch('app_settings.prepare') as prepare:
            with self.assertRaisesRegex(AppError,'Confirm rebuilding'):self.save(model='ArcFace')
            prepare.assert_not_called()
    def test_rebuild_switch_and_switch_back(self):
        self.photos()
        with patch('app_settings.prepare'):
            for model in ('ArcFace','GhostFaceNet','Buffalo_L','Facenet512'):
                result=self.activate(model=model,detector='yunet')
                self.assertEqual(result['gallery']['model'],model)
                self.assertEqual(self.engine.registry()[1].shape,(2,512))
                self.assertEqual(self.engine.registry()[1][0,10],1)
                self.assertEqual(self.engine.metadata['reference_detector'],'retinaface')
                self.assertEqual(json.loads((self.root/'embeddings/template_sources.json').read_text())['model'],model)
        self.assertFalse(self.store.status['running'])
    def test_missing_photo_never_drops_student_or_changes_files(self):
        self.photos();(self.root/'data/reference/2/reference.jpg').unlink()
        paths=[self.store.path,self.root/'embeddings/student_templates.npz',self.root/'embeddings/metadata.json']
        before=[path.read_bytes() for path in paths]
        with patch('app_settings.prepare'):
            with self.assertRaisesRegex(AppError,'Roll 2 has no saved'):self.activate(model='ArcFace')
        self.assertEqual(before,[path.read_bytes() for path in paths]);self.assertEqual(self.engine.settings['model'],'Facenet512')
        self.assertFalse(self.store.status['running'])
    def test_detector_switch_keeps_gallery_and_enrollment_detector(self):
        path=self.root/'embeddings/student_templates.npz';before=path.read_bytes()
        with patch('app_settings.prepare') as prepare,patch.object(self.engine,'encode',side_effect=AssertionError()):
            self.activate(detector='opencv')
            prepare.assert_called_once_with('opencv','Facenet512')
        self.assertEqual(path.read_bytes(),before);self.assertEqual(self.engine.metadata['reference_detector'],'retinaface')
    def test_models_keep_separate_matching_profiles(self):
        self.photos();self.save(cosine_distance_threshold=.21,minimum_gap=.08)
        with patch('app_settings.prepare'):
            self.activate(model='ArcFace',cosine_distance_threshold=.44,minimum_gap=.12)
            saved=self.store.view()['model_profiles']
            self.assertEqual(saved['Facenet512']['cosine_distance_threshold'],.21)
            self.assertEqual(saved['Facenet512']['minimum_gap'],.08)
            self.assertEqual(saved['ArcFace']['cosine_distance_threshold'],.44)
            self.assertFalse(saved['ArcFace']['calibrated'])
            self.activate(model='Facenet512',cosine_distance_threshold=saved['Facenet512']['cosine_distance_threshold'],minimum_gap=saved['Facenet512']['minimum_gap'])
        self.assertEqual(self.engine.settings['cosine_distance_threshold'],.21)
        self.assertEqual(self.store.view()['model_profiles']['ArcFace']['minimum_gap'],.12)
        from app_settings import AppSettings
        reloaded=AppSettings(self.root,self.engine,self.lectures,self.analytics)
        self.assertEqual(reloaded.view()['model_profiles'],self.store.view()['model_profiles'])
    def test_failed_download_keeps_pipeline(self):
        before=self.store.path.read_bytes()
        with patch('app_settings.prepare',side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(AppError,'current models and templates were kept'):self.activate(model='ArcFace')
        self.assertEqual(self.store.path.read_bytes(),before);self.assertFalse(self.store.status['running'])
    def test_failed_commit_restores_gallery_and_model(self):
        self.photos();before=self.store.path.read_bytes();gallery=(self.root/'embeddings/student_templates.npz').read_bytes()
        from engine import atomic_write
        def fail(path,content):
            if path.name=='template_sources.json':raise OSError('full disk')
            atomic_write(path,content)
        with patch('app_settings.prepare'),patch('engine.atomic_write',side_effect=fail):
            with self.assertRaises(OSError):self.activate(model='ArcFace')
        self.assertEqual(self.store.path.read_bytes(),before);self.assertEqual((self.root/'embeddings/student_templates.npz').read_bytes(),gallery)
        self.assertEqual(self.engine.metadata['model'],'Facenet512')
    def test_approved_box_uses_original_detector_and_refuses_changed_source(self):
        self.photos();path=self.root/'data/reference/1/reference.jpg'
        approval=dict(photo=str(path),photo_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bounding_box=dict(x=1,y=2,w=64,h=64))
        with patch.object(self.engine,'detect',return_value=[self.face(),dict(face=None,facial_area=dict(x=80,y=2,w=64,h=64))]) as detect:
            reference_face(self.engine,path,approval,detector='yunet');self.assertEqual(detect.call_args.kwargs['detector'],'retinaface')
        approval['bounding_box']['x']=99
        with self.assertRaisesRegex(AppError,'approved reference face'):reference_face(self.engine,path,approval)
        approval['photo_sha256']='changed'
        with self.assertRaisesRegex(AppError,'approved reference photo changed'):reference_face(self.engine,path,approval)
    def test_audited_selected_crop_is_not_redetected_and_hash_enforced(self):
        self.photos();old=self.root/'data/reference/1/reference.jpg';path=old.with_name('app_abc.jpg');old.rename(path)
        audit=self.root/'logs/app-registration/app_abc.json';audit.parent.mkdir(parents=True)
        record=dict(action='register',photo='data/reference/99/app_abc.jpg',photo_sha256=hashlib.sha256(path.read_bytes()).hexdigest());audit.write_text(json.dumps(record))
        with patch.object(self.engine,'detect',side_effect=AssertionError('already aligned')):reference_face(self.engine,path)
        record['photo_sha256']='changed';audit.write_text(json.dumps(record))
        with self.assertRaisesRegex(AppError,'registration crop changed'):reference_face(self.engine,path)
    def test_reference_mutation_during_encoding_aborts_activation(self):
        self.photos();path=self.root/'data/reference/1/reference.jpg';before=self.store.path.read_bytes()
        def encode(*args,**kwargs):
            Image.new('RGB',(64,64),'white').save(path)
            return np.eye(512,dtype=np.float32)[10]
        with patch('app_settings.prepare'),patch.object(self.engine,'encode',side_effect=encode):
            with self.assertRaisesRegex(AppError,'reference photo changed during'):self.activate(model='ArcFace')
        self.assertEqual(self.store.path.read_bytes(),before)
    def test_restore_archive_from_other_model_reencodes_saved_photos(self):
        self.photos();item=self.engine.delete_student('1',dict(confirmation='1'))
        with patch('app_settings.prepare'):self.activate(model='ArcFace')
        self.engine.encode=lambda rgb,model_name=None:np.eye(512,dtype=np.float32)[20]
        self.engine.restore_student(item['archive_id'])
        _,vectors,rolls,*_=self.engine.registry();self.assertEqual(vectors[list(rolls).index('1'),20],1)
    def test_restore_other_model_without_photos_keeps_archive(self):
        item=self.engine.delete_student('1',dict(confirmation='1'));self.engine.settings['model']='ArcFace'
        with self.assertRaisesRegex(AppError,'no saved reference'):self.engine.restore_student(item['archive_id'])
        self.assertNotIn('1',self.engine.registry()[2]);self.assertFalse(json.loads((self.root/'data/student_archive'/item['archive_id']/'manifest.json').read_text()).get('restored_utc'))

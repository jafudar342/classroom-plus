import hashlib
import json
import unittest
import uuid
from unittest.mock import patch
import numpy as np
import test_engine as fixtures
from engine import AppError
from lectures import LectureStore
from analytics import Analytics
from app_settings import AppSettings, FIELDS
from timetable import Timetable
from video_attendance import VideoAttendance

class SettingsTests(unittest.TestCase):
    setup_engine=fixtures.EngineTests.setUp
    tearDown=fixtures.EngineTests.tearDown
    def setUp(self):
        self.setup_engine();self.lectures=LectureStore(self.root,self.engine);self.analytics=Analytics(self.root,self.lectures)
        self.store=AppSettings(self.root,self.engine,self.lectures,self.analytics)
    def save(self,**changes):
        data=self.store.view();return self.store.save(dict(revision=data['revision'],values={**data['values'],**changes}))
    def lecture(self):return self.lectures.create(dict(title='Settings test',lecture_date='2026-11-15',lecture_time='09:00',timezone='Asia/Kolkata',class_id='all-students'))
    def test_catalog_single_supported_models_and_no_write_on_read(self):
        before=self.store.path.read_bytes();data=self.store.view()
        self.assertEqual([row['id'] for row in data['models']['detectors']],['retinaface','opencv','yunet','centerface','mtcnn'])
        self.assertEqual([row['id'] for row in data['models']['embeddings']],['Facenet512','ArcFace','GhostFaceNet','Buffalo_L'])
        self.assertEqual(data['gallery']['templates'],2);self.assertEqual(data['values']['video_required_samples'],3)
        self.assertEqual(data['values']['attendance_target'],75);self.assertEqual(before,self.store.path.read_bytes())
        self.assertFalse(self.store.dashboard_path.exists())
    def test_settings_persist_apply_and_keep_embeddings_and_previews(self):
        path=self.root/'embeddings/student_templates.npz';before=hashlib.sha256(path.read_bytes()).hexdigest()
        self.engine.previews['test']={'example':True}
        with patch.object(self.engine,'encode',side_effect=AssertionError('No model work on save')):
            data=self.save(cosine_distance_threshold=.2,minimum_gap=.08,attendance_target=80,default_directory_view='list',default_late_after_minutes=20)
        self.assertEqual(self.engine.settings['cosine_distance_threshold'],.2);self.assertEqual(self.analytics.target(),80)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before);self.assertIn('test',self.engine.previews)
        self.assertEqual(data['values']['default_directory_view'],'list')
        self.assertEqual(json.loads(self.store.path.read_text())['default_late_after_minutes'],20)
        self.assertTrue(list((self.root/'work/app-backups').glob('manage_*')))
    def test_matching_threshold_has_runtime_effect(self):
        self.engine.encode=lambda _:np.array([.8,.6]+[0]*510,dtype=np.float32)
        self.assertEqual(self.engine.match(None,[fixtures.EngineTests.face()])[0][0]['decision'],'Matched')
        self.save(cosine_distance_threshold=.1)
        self.assertEqual(self.engine.match(None,[fixtures.EngineTests.face()])[0][0]['decision'],'Unknown')
    def test_invalid_ranges_types_and_other_models_do_not_write(self):
        before=self.store.path.read_bytes()
        for changes in [dict(model='NotAModel'),dict(detector='NotADetector'),dict(video_required_samples=1),dict(video_required_samples=9),dict(video_min_face_pixels=16),dict(video_min_sharpness=0),dict(cosine_distance_threshold=True),dict(minimum_gap=float('nan')),dict(minimum_gap=10**1000),dict(live_interval_ms=500),dict(default_extra_detection='yes'),dict(default_directory_view='other'),dict(default_end_time='08:00'),dict(default_start_time='0१:00'),dict(attendance_target=101)]:
            with self.assertRaises(AppError):self.save(**changes)
            self.assertEqual(self.store.path.read_bytes(),before)
        data=self.store.view()
        with self.assertRaises(AppError):self.store.save(dict(revision=data['revision'],values={**data['values'],'normalization':'raw'}))
    def test_dashboard_change_invalidates_old_editor(self):
        old=self.store.view();self.analytics.save_target(dict(target=88))
        with self.assertRaisesRegex(AppError,'changed in another tab'):self.store.save(dict(revision=old['revision'],values=old['values']))
        self.assertEqual(self.store.view()['values']['attendance_target'],88)
    def test_transaction_failure_restores_files_and_memory(self):
        self.analytics.save_target(dict(target=76));original=self.store.path.read_bytes();original_target=self.store.dashboard_path.read_bytes();settings=dict(self.engine.settings)
        import engine
        writer=engine.atomic_write
        def fail_once(path,content):
            if path==self.store.dashboard_path and not getattr(fail_once,'failed',False):fail_once.failed=True;raise OSError('disk full')
            writer(path,content)
        with patch('engine.atomic_write',side_effect=fail_once):
            with self.assertRaises(OSError):self.save(attendance_target=90,minimum_gap=.1)
        self.assertEqual(self.store.path.read_bytes(),original);self.assertEqual(self.store.dashboard_path.read_bytes(),original_target);self.assertEqual(self.engine.settings,settings)
    def test_active_scan_blocks_changes_then_stop_allows_save(self):
        item=self.lecture();video=VideoAttendance(self.lectures);started=video.start(item['id'],dict(revision=item['revision']))
        self.assertEqual(len(self.store.view()['active_scans']),1)
        with self.assertRaisesRegex(AppError,'Stop active video scans'):self.save(minimum_gap=.1)
        video.stop(item['id'],started['scan_id'],dict(revision=started['lecture']['revision']))
        self.assertEqual(self.save(minimum_gap=.1)['values']['minimum_gap'],.1)
    def test_required_samples_eight_and_quality_rules_are_used(self):
        self.save(video_required_samples=8,video_sample_interval_ms=3000,video_min_face_pixels=48,video_min_sharpness=35)
        pixels=np.random.default_rng(3).integers(25,230,(64,64,3),dtype=np.uint8)
        self.engine.detect=lambda _:[dict(fixtures.EngineTests.face(),face=pixels)];self.engine.encode=lambda _:self.vectors[0]
        item=self.lecture();video=VideoAttendance(self.lectures);started=video.start(item['id'],dict(revision=item['revision']));item=started['lecture'];identifier=started['scan_id']
        for index in range(8):
            with patch('video_attendance.time.time',return_value=100+index*2):
                item=video.frame(item['id'],identifier,dict(revision=item['revision'],frame_id=uuid.uuid4().hex),np.full((100,100,3),index,dtype=np.uint8))['lecture']
            track=item['video_scans'][0]['tracks'][0]
            if index<7:self.assertIsNone(track['proposed_roll'])
        self.assertEqual(track['proposed_roll'],'1');self.assertEqual(len(track['evidence']),8)
        scan=item['video_scans'][0];self.assertEqual(scan['sample_interval_ms'],3000);self.assertEqual(scan['matching_settings']['model'],'Facenet512')
        self.assertEqual(scan['quality_settings']['minimum_face_pixels'],48)
    def test_defaults_only_affect_new_timetable_slots(self):
        self.save(default_late_after_minutes=25)
        group=self.engine.save_class(dict(name='Class A',student_rolls=['1','2'],revision=''))['class']
        subject=self.engine.save_subject(dict(name='AI',class_id=group['id'],revision=self.engine.academics()['revision']))['subject']
        table=Timetable(self.root,self.engine,self.lectures)
        catalog=table.save(dict(revision=0,class_id=group['id'],subject_id=subject['id'],weekdays=[0],start_time='09:00',end_time='10:00',starts_on='2026-11-15'))
        self.assertEqual(catalog['entries'][0]['late_after_minutes'],25)
        self.save(default_late_after_minutes=5)
        self.assertEqual(table.catalog()['entries'][0]['late_after_minutes'],25)
    def test_corrupt_settings_not_overwritten(self):
        self.store.path.write_text('{broken')
        with self.assertRaises(AppError):self.store.save(dict(revision=self.store.revision(),values={key:field['default'] for key,field in FIELDS.items()}))
        self.assertEqual(self.store.path.read_text(),'{broken')

    def test_external_matching_edit_requires_restart(self):
        raw=json.loads(self.store.path.read_text());raw['minimum_gap']=.15;self.store.path.write_text(json.dumps(raw))
        before=self.store.path.read_bytes()
        with self.assertRaisesRegex(AppError,'Restart Classroom'):self.store.view()
        self.assertEqual(self.store.path.read_bytes(),before)

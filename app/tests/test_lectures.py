import unittest
from unittest.mock import patch
import numpy as np
import test_engine as fixtures
from engine import AppError
from lectures import LectureStore

class LectureTests(unittest.TestCase):
    setUpFixture = fixtures.EngineTests.setUp
    tearDown = fixtures.EngineTests.tearDown
    face = staticmethod(fixtures.EngineTests.face)
    profile_payload = fixtures.EngineTests.profile_payload
    preview = fixtures.EngineTests.preview
    def setUp(self):
        self.setUpFixture()
        self.store=LectureStore(self.root,self.engine)
        self.engine.detect=lambda _: [self.face()]
        self.engine.encode=lambda _: self.vectors[0]
        self.image=np.zeros((100,100,3),dtype=np.uint8)
    def lecture(self,**changes):
        return self.store.create(dict(title='Lecture 1',lecture_date='2026-11-11',lecture_time='10:30',timezone='Asia/Kolkata',class_id='all-students')|changes)
    def add(self,item,image=None):
        return self.store.capture(item['id'],dict(revision=item['revision']),self.image if image is None else image)['lecture']
    def decide(self,item,roll='3',status='Absent'):
        return self.store.correct(item['id'],dict(revision=item['revision'],roll_number=roll,status=status,reason='Teacher verified roster.'))
    def test_eye_only_lecture_needs_decision_for_unseen_students(self):
        item = self.add(self.lecture())
        stored = self.store.load(item['id'])
        capture = stored['captures'][0]
        capture['summary']['eye_search'] = True
        capture['detections'][0]['decision'] = 'Review'
        item = self.store.save(stored)
        item = self.store.resolve(item['id'], dict(revision=item['revision'], capture_id=capture['id'],
            face_id=1, action='assign', roll_number='1', reason='Teacher confirmed'))
        self.assertEqual([r['status'] for r in item['attendance']], ['Present','Review','Review'])
        self.assertFalse(item['can_finalize'])

    def test_unique_students_and_duplicate_photo(self):
        item=self.add(self.lecture())
        with self.assertRaisesRegex(AppError,'exact photo'): self.add(item)
        item=self.add(item,np.ones_like(self.image))
        self.assertEqual(item['summary']['present'],1)
        self.assertEqual(item['attendance'][0]['capture_count'],2)
        self.assertEqual(item['summary']['captures'],2)
    def test_unmatched_is_unconfirmed_until_teacher_decides(self):
        item=self.add(self.lecture())
        self.assertEqual(item['attendance'][1]['status'],'Unconfirmed')
        self.assertEqual(item['summary']['absent'],0)
        self.assertEqual(item['summary']['unconfirmed'],1)
        item=self.decide(item,'3','Absent')
        with self.assertRaisesRegex(AppError,'unconfirmed'):
            self.store.finalize(item['id'],dict(revision=item['revision'],confirm=True))
        item=self.decide(item,'2','Absent')
        final=self.store.finalize(item['id'],dict(revision=item['revision'],confirm=True))
        self.assertEqual(final['summary']['unconfirmed'],0)
        self.assertEqual(final['summary']['absent'],2)
        self.assertNotIn(b'Unconfirmed',self.store.export(final['id'],'attendance'))
        # Finalized snapshots stay unchanged even if recognition behavior changes later.
        self.engine.encode=lambda _:self.vectors[1]
        self.assertEqual(self.store.view(self.store.load(final['id']))['attendance'],final['attendance'])
    def test_override_persists_and_reset(self):
        item=self.decide(self.add(self.lecture()),'1','Absent')
        item=self.add(item,np.ones_like(self.image))
        self.assertEqual(item['attendance'][0]['status'],'Absent')
        item=self.decide(item,'1','auto')
        self.assertEqual(item['attendance'][0]['status'],'Present')
        self.assertEqual(len([row for row in item['audit'] if row['action']=='attendance_corrected']),2)
    def test_unknown_review_and_immutable_final(self):
        self.engine.encode=lambda _: np.eye(512,dtype=np.float32)[4]
        item=self.add(self.lecture())
        self.assertEqual(item['summary']['pending_faces'],1)
        with self.assertRaises(AppError): self.store.finalize(item['id'],dict(revision=item['revision'],confirm=True))
        item=self.store.resolve(item['id'],dict(revision=item['revision'],capture_id=item['captures'][0]['id'],face_id=1,action='assign',roll_number='2',reason='Teacher recognized Bob.'))
        self.assertEqual(item['summary']['present'],1)
        item=self.decide(item)
        item=self.decide(item,'1','Absent')
        item=self.store.finalize(item['id'],dict(revision=item['revision'],confirm=True))
        self.assertEqual(item['state'],'finalized')
        for operation in (lambda:self.add(item,np.ones_like(self.image)),lambda:self.decide(item)):
            with self.assertRaisesRegex(AppError,'finalized'): operation()
        self.assertIn(b'Bob,Present',self.store.export(item['id'],'attendance'))
        self.assertIn(b'Teacher recognized Bob.',self.store.export(item['id'],'audit'))
        self.assertGreater(len(self.store.media(item['id'],item['captures'][0]['id'])),100)
        self.assertGreater(len(self.store.media(item['id'],item['captures'][0]['id'],1)),100)
    def test_ignore_and_reset(self):
        self.engine.encode=lambda _: np.eye(512,dtype=np.float32)[4]
        item=self.add(self.lecture())
        payload=dict(capture_id=item['captures'][0]['id'],face_id=1,action='ignore',reason='Person not enrolled.')
        item=self.store.resolve(item['id'],dict(payload,revision=item['revision']))
        self.assertEqual(item['summary']['pending_faces'],0)
        item=self.store.resolve(item['id'],dict(payload,revision=item['revision'],action='auto'))
        self.assertEqual(item['summary']['pending_faces'],1)
    def test_duplicate_face_assignment_rejected(self):
        self.engine.detect=lambda _: [self.face(),self.face()]
        item=self.add(self.lecture())
        payload=dict(capture_id=item['captures'][0]['id'],face_id=1,action='assign',roll_number='1',reason='Verified Alice.')
        item=self.store.resolve(item['id'],dict(payload,revision=item['revision']))
        with self.assertRaisesRegex(AppError,'Two faces'): self.store.resolve(item['id'],dict(payload,face_id=2,revision=item['revision']))
        with self.assertRaises(AppError): self.store.resolve(item['id'],dict(payload,face_id=2,roll_number='999',revision=item['revision']))
        self.assertEqual(self.store.load(item['id'])['revision'],item['revision'])
    def test_empty_and_manual_only_finalization(self):
        item=self.lecture()
        with self.assertRaises(AppError): self.store.finalize(item['id'],dict(revision=item['revision'],confirm=True))
        with self.assertRaises(AppError): self.store.export(item['id'],'attendance')
        for roll in ['1','2','3']: item=self.decide(item,roll,'Present' if roll=='1' else 'Absent')
        self.assertTrue(item['can_finalize'])
        with self.assertRaises(AppError): self.store.finalize(item['id'],dict(revision=item['revision'],confirm=False))
        final=self.store.finalize(item['id'],dict(revision=item['revision'],confirm=True))
        self.assertEqual(final['summary']['present'],1)
    def test_revision_and_validation(self):
        for changes in [dict(lecture_date='2026-02-30'),dict(lecture_time='25:00'),dict(timezone='Not/AZone'),dict(title='')]:
            with self.assertRaises(AppError): self.lecture(**changes)
        item=self.lecture()
        for revision in [0,True,None]:
            with self.assertRaisesRegex(AppError,'another tab'): self.store.correct(item['id'],dict(revision=revision,roll_number='1',status='Present',reason='Verified'))
        with self.assertRaises(AppError): self.store.correct(item['id'],dict(revision=item['revision'],roll_number='1',status='Present',reason=''))
        self.assertEqual(len(self.store.list()),1)
    def test_identity_edit_and_roll_reuse(self):
        item=self.lecture()
        self.engine.update_student('1',self.profile_payload(roll_number='101',name='Alice Updated'))
        self.assertEqual(self.store.snapshot(self.store.load(item['id']))[2].tolist(),['1','2'])
        item=self.add(item)
        self.assertEqual(item['attendance'][0]['name'],'Alice')
        self.engine.delete_student('101',dict(confirmation='101',revision=self.engine.student_detail('101')['revision']))
        self.preview()
        self.engine.register(dict(roll_number='1',name='New Person',preview_id='test',face_index=0))
        self.assertEqual(self.store.snapshot(self.store.load(item['id']))[2].tolist(),['2'])
    def test_frozen_class_roster(self):
        group=self.engine.save_class(dict(name='Class A',student_rolls=['1','3'],revision=''))['class']
        subject=self.engine.save_subject(dict(class_id=group['id'],name='AI',revision=self.engine.academics()['revision']))['subject']
        item=self.lecture(class_id=group['id'],subject_id=subject['id'])
        self.engine.save_class(dict(id=group['id'],name='Changed',student_rolls=['2'],revision=self.engine.academics()['revision']))
        stored=self.store.load(item['id'])
        self.assertEqual([r['roll_number'] for r in stored['roster']],['1','3'])
        self.assertEqual(stored['context']['class_name'],'Class A')
        self.assertEqual(self.store.snapshot(stored)[2].tolist(),['1'])
    def test_capture_failure_rolls_back(self):
        item=self.lecture()
        with patch.object(self.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.add(item)
        self.assertEqual(self.store.load(item['id'])['captures'],[])
        self.assertFalse(list((self.store.directory(item['id'])/'captures').glob('*/source.png')))

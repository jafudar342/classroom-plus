import unittest
import uuid
from unittest.mock import patch
import numpy as np
import test_lectures as fixtures
from engine import AppError
from video_attendance import VideoAttendance, associate, quality


class VideoTests(unittest.TestCase):
    setUpFixtureEngine = fixtures.LectureTests.setUpFixture
    tearDown = fixtures.LectureTests.tearDown
    face = staticmethod(fixtures.LectureTests.face)
    profile_payload = fixtures.LectureTests.profile_payload
    preview = fixtures.LectureTests.preview
    def setUp(self):
        self.setUpFixtureEngine()
        from lectures import LectureStore
        self.store = LectureStore(self.root,self.engine)
        self.video = VideoAttendance(self.store)
        self.pixels=np.random.default_rng(4).integers(25,230,(64,64,3),dtype=np.uint8)
        self.engine.detect=lambda _: [dict(self.face(),face=self.pixels)]
        self.engine.encode=lambda _:self.vectors[0]
        self.item=self.store.create(dict(title='Video test',lecture_date='2026-11-14',lecture_time='10:00',timezone='Asia/Kolkata',class_id='all-students'))
        self.scan=self.video.start(self.item['id'],dict(revision=self.item['revision']))
        self.item=self.scan['lecture']; self.scan_id=self.scan['scan_id']; self.tick=100
    def payload(self,**extra):return dict(revision=self.item['revision'],**extra)
    def frame(self,image=None,identifier=None):
        self.tick+=2
        if image is None: image=np.full((100,100,3),self.tick%255,dtype=np.uint8)
        self.last_image=image
        self.last_id=identifier or uuid.uuid4().hex
        with patch('video_attendance.time.time',return_value=self.tick):
            result=self.video.frame(self.item['id'],self.scan_id,self.payload(frame_id=self.last_id),image)
        self.item=result['lecture'];return result
    def track(self):return self.item['video_scans'][0]['tracks'][0]
    def stop(self):self.item=self.video.stop(self.item['id'],self.scan_id,self.payload())['lecture']
    def review(self,action='accept',track_id=1):
        self.item=self.video.review(self.item['id'],self.scan_id,self.payload(action=action,track_id=track_id))['lecture']
    def test_three_samples_propose_then_review_counts_once(self):
        for _ in range(2):self.frame()
        self.assertIsNone(self.track()['proposed_roll'])
        self.frame();self.assertEqual(self.track()['proposed_roll'],'1')
        self.assertEqual(self.item['attendance'][0]['status'],'Review')
        with self.assertRaises(AppError):self.review()
        self.stop();self.review()
        self.assertEqual(self.item['attendance'][0]['status'],'Present')
        self.assertGreater(len(self.video.photo(self.item['id'],self.scan_id,1)),100)
        self.assertNotIn('frames',self.item['video_scans'][0])
        self.assertEqual(self.item['summary']['video_frames'],3)
        self.review('reset');self.assertEqual(self.item['attendance'][0]['status'],'Review')
    def test_repeat_image_frame_id_and_rate_do_not_vote(self):
        self.frame();revision=self.item['revision'];first=self.last_image
        self.frame(first);self.assertEqual(self.item['revision'],revision)
        self.frame(identifier=self.last_id);self.assertEqual(self.item['revision'],revision+1)
        revision=self.item['revision'];sameid=self.last_id
        self.frame(identifier=sameid);self.assertEqual(self.item['revision'],revision)
        with patch('video_attendance.time.time',return_value=self.tick-1.5):
            result=self.video.frame(self.item['id'],self.scan_id,self.payload(frame_id=uuid.uuid4().hex),np.zeros_like(first))
        self.assertEqual(result['lecture']['revision'],revision)
    def test_blur_and_identity_switch_never_inherit_votes(self):
        self.frame();self.frame()
        self.pixels[:]=0;self.frame();self.assertIsNone(self.track()['proposed_roll'])
        self.pixels[:]=np.random.default_rng(7).integers(30,220,self.pixels.shape,dtype=np.uint8)
        self.engine.encode=lambda _:self.vectors[1]
        self.frame();self.assertEqual(len(self.item['video_scans'][0]['tracks']),2)
        self.assertIsNone(self.item['video_scans'][0]['tracks'][1]['proposed_roll'])
    def test_duplicate_faces_never_propose(self):
        self.engine.detect=lambda _: [dict(self.face(),face=self.pixels),dict(self.face(),face=self.pixels)]
        for _ in range(4):self.frame()
        self.assertTrue(all(t['proposed_roll'] is None for t in self.item['video_scans'][0]['tracks']))
    def test_empty_video_cannot_finalize_all_absent(self):
        self.engine.detect=lambda _:[]
        self.frame();self.stop()
        self.assertFalse(self.item['can_finalize'])
        self.assertEqual(self.item['summary']['video_frames'],1)
    def test_revisions_gallery_changes_and_failed_save(self):
        with self.assertRaises(AppError):self.video.frame(self.item['id'],self.scan_id,dict(revision=0,frame_id=uuid.uuid4().hex),np.zeros((100,100,3),dtype=np.uint8))
        with patch.object(self.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.frame()
        self.assertFalse(list(self.store.directory(self.item['id']).glob('video/**/*.jpg')))
        self.assertEqual(self.store.load(self.item['id'])['video_scans'][0]['frame_count'],0)
        with patch.object(self.video,'gallery_hash',return_value='changed'):
            with self.assertRaisesRegex(AppError,'templates changed'):self.frame()
        self.stop()
    def test_override_wins_and_review_blocks_finalization(self):
        for _ in range(3):self.frame()
        self.stop();self.review()
        self.item=self.store.correct(self.item['id'],self.payload(roll_number='1',status='Absent',reason='Teacher verified'))
        self.assertEqual(self.item['attendance'][0]['status'],'Absent')
        self.review('reset');self.assertFalse(self.item['can_finalize'])
        self.review('ignore');self.assertEqual(self.item['summary']['video_pending'],0)
    def test_crossing_is_ambiguous_and_quality(self):
        tracks=[dict(id=1,box=[0,0,.5,.5],last_seen_frame=1),dict(id=2,box=[0,0,.5,.5],last_seen_frame=1)]
        self.assertEqual(associate(tracks,[[0,0,.5,.5]],2),{})
        self.assertFalse(quality(self.face())['clear'])

    def test_missing_face_breaks_consecutive_sample_streak(self):
        self.frame();self.frame()
        detect=self.engine.detect;self.engine.detect=lambda _:[]
        self.frame();self.engine.detect=detect;self.frame()
        self.assertIsNone(self.track()['proposed_roll'])
        self.frame();self.frame();self.assertEqual(self.track()['proposed_roll'],'1')
    def test_student_deduplicated_across_scans(self):
        for _ in range(3):self.frame()
        self.stop();self.review()
        result=self.video.start(self.item['id'],self.payload())
        self.item=result['lecture'];self.scan_id=result['scan_id']
        for _ in range(3):self.frame()
        self.stop();self.review()
        self.assertEqual(self.item['summary']['present'],1)
        self.assertEqual(self.item['attendance'][0]['capture_count'],2)

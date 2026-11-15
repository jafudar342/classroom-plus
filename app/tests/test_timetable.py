import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import numpy as np
import test_engine as fixtures
from engine import AppError
from lectures import LectureStore
from timetable import Timetable
from analytics import Analytics


class TimetableTests(unittest.TestCase):
    setup_engine=fixtures.EngineTests.setUp
    tearDown=fixtures.EngineTests.tearDown
    def setUp(self):
        self.setup_engine()
        self.lectures=LectureStore(self.root,self.engine)
        self.table=Timetable(self.root,self.engine,self.lectures)
        self.table.clock=lambda:datetime(2026,11,16,4,0,tzinfo=timezone.utc)
        self.group=self.engine.save_class(dict(name='Class A',student_rolls=['1','2'],revision=''))['class']
        self.subject=self.engine.save_subject(dict(name='AI',class_id=self.group['id'],revision=self.engine.academics()['revision']))['subject']
        self.engine.detect=lambda _:[fixtures.EngineTests.face()]
        self.engine.encode=lambda _:self.vectors[0]
    def payload(self,**changes):
        return dict(revision=self.table.load()['revision'],class_id=self.group['id'],subject_id=self.subject['id'],weekdays=[0,2,4],start_time='09:00',end_time='10:00',starts_on='2026-11-16',ends_on='',late_after_minutes=10,active=True,**changes)
    def slot(self,**changes):
        payload=self.payload();payload.update(changes)
        data=self.table.save(payload)
        return data['entries'][-1]
    def start(self,slot=None,day='2026-11-16'):
        slot=slot or self.slot()
        return self.table.start(dict(slot_id=slot['id'],date=day,revision=self.table.load()['revision']))['lecture']
    def record(self,item,timestamp,pixels=0):
        with patch('lectures.now',return_value=timestamp):
            return self.lectures.capture(item['id'],dict(revision=item['revision']),np.full((100,100,3),pixels,dtype=np.uint8))['lecture']
    def test_recurrence_idempotent_start_and_frozen_context(self):
        slot=self.slot();self.assertEqual(self.table.catalog()['day_summary']['needs_attendance'],1)
        item=self.start(slot);self.assertEqual(item['context']['class_name'],'Class A')
        again=self.table.start(dict(slot_id=slot['id'],date='2026-11-16',revision=0))
        self.assertTrue(again['resumed']);self.assertEqual(again['lecture']['id'],item['id']);self.assertEqual(len(self.lectures.list()),1)
        self.assertEqual(self.table.catalog('2026-11-17')['occurrences'],[])
        self.assertEqual(self.table.catalog()['day_summary']['in_progress'],1)
        self.assertEqual(item['schedule']['cutoff_utc'],'2026-11-16T03:40:00+00:00')
    def test_pause_and_edit_preserve_existing_occurrence(self):
        slot=self.slot();item=self.start(slot)
        payload=self.payload();payload.update(id=slot['id'],active=False,start_time='11:00',end_time='12:00',late_after_minutes=0,weekdays=[1]);self.table.save(payload)
        row=self.table.catalog()['occurrences'][0]
        self.assertTrue(row['changed']);self.assertEqual(row['schedule']['start_time'],'09:00')
        self.assertEqual(self.table.catalog('2026-11-23')['occurrences'],[])
        self.assertEqual(self.start(slot)['id'],item['id'])
    def test_overlap_dates_days_and_class(self):
        self.slot()
        with self.assertRaisesRegex(AppError,'overlapping'):self.slot(start_time='09:30',end_time='10:30')
        self.slot(start_time='10:00',end_time='11:00')
        self.slot(weekdays=[1])
        self.slot(starts_on='2026-11-02',ends_on='2026-11-09')
        self.slot(starts_on='2026-12-01',ends_on='2026-12-03',weekdays=[0]) # No Monday in this range.
        self.assertEqual(len(self.table.load()['entries']),5)
    def test_validation_revision_and_future_start(self):
        for change in [dict(weekdays=[]),dict(weekdays=[True]),dict(weekdays=[0,0]),dict(start_time='25:00'),dict(start_time='0१:00'),dict(end_time='08:00'),dict(starts_on='2026-02-30'),dict(late_after_minutes=True),dict(late_after_minutes=-1),dict(active='yes'),dict(class_id='all-students'),dict(ends_on='2026-01-01')]:
            with self.assertRaises(AppError):self.slot(**change)
        slot=self.slot()
        payload=self.payload();payload['revision']=True
        with self.assertRaisesRegex(AppError,'another tab'):self.table.save(payload)
        with self.assertRaisesRegex(AppError,'scheduled day'):self.start(slot,'2026-11-18')
        self.assertEqual(len(self.lectures.list()),0)
        with self.assertRaisesRegex(AppError,'not scheduled'):self.start(slot,'2026-11-17')
    def test_timezone_day_boundary(self):
        self.table.clock=lambda:datetime(2026,11,15,20,0,tzinfo=timezone.utc)
        self.slot();data=self.table.catalog()
        self.assertEqual(data['today'],'2026-11-16');self.assertEqual(data['day_summary']['upcoming'],1)
    def test_missing_subject_and_invalid_storage(self):
        self.slot();path=self.root/'data/academics.json';academic=json.loads(path.read_text());academic['subjects']=[];path.write_text(json.dumps(academic))
        self.assertFalse(self.table.catalog()['occurrences'][0]['available'])
        original='{broken';self.table.path.write_text(original)
        with self.assertRaisesRegex(AppError,'could not be read'):self.table.save({})
        self.assertEqual(self.table.path.read_text(),original)
    def test_failed_writes_leave_saved_state(self):
        slot=self.slot();before=self.table.path.read_bytes()
        with patch('timetable.atomic_write',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.slot(start_time='11:00',end_time='12:00')
        self.assertEqual(self.table.path.read_bytes(),before)
        with patch.object(self.lectures,'save',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.start(slot)
        self.assertEqual(self.lectures.list(),[])
    def test_arrival_uses_first_evidence_not_processing_finish(self):
        item=self.start()
        with patch('lectures.now',side_effect=['2026-11-16T03:39:00+00:00','2026-11-16T03:55:00+00:00','2026-11-16T03:55:00+00:00']):
            item=self.lectures.capture(item['id'],dict(revision=item['revision']),np.zeros((100,100,3),dtype=np.uint8))['lecture']
        self.assertEqual(item['attendance'][0]['arrival_status'],'On time')
        item=self.record(item,'2026-11-16T04:00:00+00:00',1)
        self.assertEqual(item['attendance'][0]['arrival_status'],'On time')
        self.assertEqual(item['attendance'][0]['first_seen_utc'],'2026-11-16T03:39:00+00:00')
    def test_cutoff_boundary_late_and_backfill(self):
        item=self.record(self.start(),'2026-11-16T03:40:00+00:00')
        self.assertEqual(item['attendance'][0]['arrival_status'],'On time')
        item=self.record(self.start(self.slot(start_time='11:00',end_time='12:00')),'2026-11-16T05:40:01+00:00')
        self.assertEqual(item['attendance'][0]['arrival_status'],'Late');self.assertEqual(item['summary']['late'],1)
        item=self.record(self.start(self.slot(start_time='13:00',end_time='14:00')),'2026-11-17T07:30:00+00:00')
        self.assertEqual(item['attendance'][0]['arrival_status'],'Not assessed');self.assertEqual(item['summary']['late'],0)
    def test_video_confirmation_time_does_not_delay_arrival(self):
        item=self.start();stored=self.lectures.load(item['id'])
        stored['video_scans']=[dict(id='a'*32,state='stopped',frame_count=3,tracks=[dict(proposed_roll='1',decision='accepted',reviewed_utc='2026-11-16T04:30:00+00:00',evidence=[dict(roll_number='1',created_utc='2026-11-16T03:39:00+00:00'),dict(roll_number='1',created_utc='2026-11-16T03:41:00+00:00')])])]
        item=self.lectures.save(stored);self.assertEqual(item['attendance'][0]['arrival_status'],'On time')
        stored=self.lectures.load(item['id']);stored['video_scans'][0]['tracks'][0]['decision']='ignored';item=self.lectures.save(stored)
        self.assertIsNone(item['attendance'][0]['arrival_status'])
    def test_late_is_present_final_export_and_analytics_unchanged(self):
        item=self.record(self.start(),'2026-11-16T03:41:00+00:00')
        with patch('lectures.now',return_value='2026-11-16T03:39:00+00:00'):
            item=self.lectures.correct(item['id'],dict(revision=item['revision'],roll_number='2',status='Present',reason='Teacher verified'))
        item=self.lectures.finalize(item['id'],dict(revision=item['revision'],confirm=True))
        self.assertEqual([row['status'] for row in item['attendance']],['Present','Present'])
        self.assertEqual(self.table.catalog()['day_summary']['completed'],1)
        content=self.lectures.export(item['id'],'attendance')
        self.assertIn(b'first_seen_utc,arrival_status,late_cutoff_utc',content);self.assertIn(b'Late',content)
        report=Analytics(self.root,self.lectures).report()
        self.assertEqual(report['percentage'],100.0)
        with self.assertRaisesRegex(AppError,'finalized'):self.lectures.correct(item['id'],dict(revision=item['revision']))

    def test_subject_rename_does_not_rewrite_started_session(self):
        slot=self.slot();item=self.start(slot)
        self.engine.save_subject(dict(id=self.subject['id'],name='AI revised',class_id=self.group['id'],revision=self.engine.academics()['revision']))
        row=self.table.catalog()['occurrences'][0]
        self.assertEqual(row['subject_name'],'AI');self.assertTrue(row['changed'])
        self.assertEqual(self.start(slot)['id'],item['id'])

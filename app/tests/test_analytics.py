import unittest
import test_engine as fixtures
from analytics import Analytics
from engine import AppError
from lectures import LectureStore

class AnalyticsTests(unittest.TestCase):
    setUp = fixtures.EngineTests.setUp
    tearDown = fixtures.EngineTests.tearDown
    def analytics(self):
        return Analytics(self.root,LectureStore(self.root,self.engine))
    def lecture(self,day,present,class_id=None,subject_id=None):
        store=self.analytics().lectures
        item=store.create(dict(title='Test lecture',lecture_date=day,lecture_time='10:00',timezone='UTC',class_id=class_id,subject_id=subject_id))
        for row in item['attendance']:
            item=store.correct(item['id'],dict(revision=item['revision'],roll_number=row['roll_number'],status='Present' if row['roll_number'] in present else 'Absent',reason='Test roll call'))
        return store.finalize(item['id'],dict(revision=item['revision'],confirm=True))
    def test_identity_and_month(self):
        self.lecture('2026-10-01',['1','2'])
        self.engine.update_student('1',fixtures.EngineTests.profile_payload(self,roll_number='101'))
        self.lecture('2026-11-02',['101'])
        alice=next(row for row in self.analytics().report()['students'] if row['roll_number']=='101')
        self.assertEqual((alice['present'],alice['total'],alice['percentage']),(2,2,100))
        self.assertEqual([r['roll_number'] for r in alice['history']],['101','1'])
        november=self.analytics().report('2026-11')
        self.assertEqual((november['lectures'],november['present']),(1,1))
        self.assertIn(b'2026-11,All students,General attendance,101',self.analytics().export('2026-11'))
    def test_scope_and_incomplete_records(self):
        group=self.engine.save_class(dict(name='Small class',student_rolls=['1'],revision=''))['class']
        subject=self.engine.save_subject(dict(class_id=group['id'],name='AI',revision=self.engine.academics()['revision']))['subject']
        self.lecture('2026-11-01',['1'],group['id'],subject['id'])
        self.lecture('2026-11-02',[])
        store=self.analytics().lectures
        store.create(dict(title='Draft',lecture_date='2026-11-03',lecture_time='10:00',timezone='UTC'))
        broken=store.root/('b'*32)/'lecture.json'
        broken.parent.mkdir();broken.write_text('{}')
        report=self.analytics().report(class_id=group['id'])
        self.assertEqual((report['lectures'],report['opportunities'],report['percentage']),(1,1,100))
        self.assertEqual((report['drafts'],report['skipped']),(1,1))
    def test_reused_roll(self):
        self.lecture('2026-10-01',['1'])
        self.engine.delete_student('1',dict(confirmation='1'))
        self.engine.register_without_photo(dict(roll_number='1',name='New person'))
        self.lecture('2026-11-01',[])
        self.assertEqual(len([r for r in self.analytics().report()['students'] if r['roll_number']=='1']),2)
    def test_target_validation(self):
        self.assertIsNone(self.analytics().report()['percentage'])
        for value in [True,-1,101,'75',float('nan')]:
            with self.assertRaises(AppError):self.analytics().save_target(dict(target=value))
        self.analytics().save_target(dict(target=80))
        self.assertEqual(self.analytics().target(),80)
        for month in ['', '2026-13','2026-1','bad']:
            with self.assertRaises(AppError):self.analytics().export(month)

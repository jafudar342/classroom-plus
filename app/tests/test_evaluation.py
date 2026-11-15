import unittest
from unittest.mock import patch
import numpy as np
import test_engine as fixtures
from engine import AppError, image_bytes
from evaluation import Evaluation, score_photo


class EvaluationTests(unittest.TestCase):
    setUp = fixtures.EngineTests.setUp
    tearDown = fixtures.EngineTests.tearDown

    def store(self):
        return Evaluation(self.root,self.engine)

    def payload(self,**changes):
        return dict(title='Independent image',split='validation',independent=True,complete=True,
                    labels=[dict(x=0,y=0,w=80,h=80,roll_number='1')]) | changes

    def image(self):
        return np.random.default_rng(2).integers(0,255,(100,100,3),dtype=np.uint8)

    def test_save_labels_reference_rejection_and_duplicates(self):
        store=self.store()
        folder=self.root/'data/reference/1';folder.mkdir(parents=True)
        (folder/'original.png').write_bytes(image_bytes(self.image(),'PNG'))
        with self.assertRaisesRegex(AppError,'enrollment'):store.add(self.payload(),self.image())
        image=self.image().copy();image[0,0]=0
        photo=store.add(self.payload(),image)
        with self.assertRaisesRegex(AppError,'already saved'):store.add(self.payload(),image)
        with self.assertRaises(AppError):store.relabel(photo['id'],self.payload(revision=0))
        revised=store.relabel(photo['id'],self.payload(revision=1))
        self.assertEqual(revised['revision'],2)
        self.assertEqual(len(store.catalog()['photos']),1)

    def test_labels_require_complete_nonoverlapping_roster(self):
        store=self.store()
        for changes in [dict(complete=False),dict(independent=False),dict(split='other'),dict(labels=[]),
                        dict(labels=[dict(x=0,y=0,w=101,h=80,roll_number='1')]),
                        dict(labels=[dict(x=0,y=0,w=80,h=80,roll_number='999')]),
                        dict(labels=[dict(x=0,y=0,w=80,h=80,roll_number='1'),dict(x=1,y=1,w=80,h=80,roll_number='2')])]:
            with self.assertRaises(AppError):store.add(self.payload(**changes),self.image())

    def test_saved_label_keeps_identity_when_roll_is_reused(self):
        store=self.store()
        photo=store.add(self.payload(),self.image())
        original=photo['labels'][0]
        self.engine.delete_student('1',dict(confirmation='1'))
        self.engine.register_without_photo(dict(roll_number='1',name='Replacement student'))
        updated=store.relabel(photo['id'],self.payload(revision=1,labels=[dict(original,source_index=0)]))
        self.assertEqual(updated['labels'][0]['identity'],original['identity'])
        self.assertEqual(updated['labels'][0]['name'],'Alice')
        reselected=store.relabel(photo['id'],self.payload(revision=2))
        self.assertNotEqual(reselected['labels'][0]['identity'],original['identity'])
        self.assertEqual(reselected['labels'][0]['name'],'Replacement student')

    def test_missing_image_is_reported_as_unavailable(self):
        store=self.store()
        photo=store.add(self.payload(),self.image())
        store.path('photos',photo['id'],'image.png').unlink()
        with patch.object(self.engine,'recognize',side_effect=AssertionError('Cannot process a missing photo')):
            report=store.run(dict(photo_ids=[photo['id']]))
        for mode in ('full','eye'):
            self.assertEqual(report['methods'][mode]['errors'],1)
            self.assertIsNone(report['methods'][mode]['recall'])

    def test_metrics_and_tightened_threshold(self):
        truth=[dict(x=i*100,y=0,w=90,h=90,identity=identity,roll_number=str(i),name='Expected') for i,identity in enumerate(['alice','bob','carol',None])]
        def face(x,identity,distance=.1):
            return dict(x=x,y=10,w=40,h=40,candidate_identity=identity,candidate_roll=identity,candidate_name=identity,cosine_distance=distance,gap=.2,eye_similarity=.85)
        faces=[face(10,'alice'),face(110,'wrong'),face(310,'intruder'),face(450,'extra')]
        counts,_=score_photo(truth,faces,'full')
        self.assertEqual([counts[k] for k in ['correct','wrong','missed','unknown_false_accept','extra_predictions']],[1,1,1,1,1])
        tightened,_=score_photo(truth,faces,'full',distance=.05)
        self.assertEqual(tightened['missed'],3)
        self.assertEqual(tightened['unknown_rejected'],1)
        eyes,_=score_photo(truth,faces,'eye',eye=.9)
        self.assertEqual(eyes['correct'],0)
        duplicate,_=score_photo(truth,[face(10,'alice'),face(110,'alice')],'full')
        self.assertEqual(duplicate['correct'],0)

    def test_saved_run_replays_without_models_or_attendance_writes(self):
        store=self.store();photo=store.add(self.payload(),self.image())
        detection=dict(face_id=1,x=10,y=10,w=40,h=40,candidate_roll='1',candidate_name='Alice',cosine_distance=.2,gap=.1,eye_similarity=.8)
        def recognize(*args,**kwargs):return dict(detections=[detection])
        with patch.object(self.engine,'recognize',side_effect=recognize):report=store.run(dict(photo_ids=[photo['id']]))
        self.assertEqual(report['methods']['full']['counts']['correct'],1)
        saved=store.read('runs',report['id'])
        with patch.object(self.engine,'recognize',side_effect=AssertionError('Should not rerun')):
            strict=store.view(saved,distance=.1)
        self.assertEqual(strict['methods']['full']['counts']['missed'],1)
        self.assertFalse((self.root/'results').exists())
        store.relabel(photo['id'],self.payload(revision=1,labels=[dict(x=0,y=0,w=80,h=80,roll_number='2')]))
        self.assertEqual(store.view(saved)['methods']['full']['counts']['correct'],1)
        with self.assertRaises(AppError):store.view(saved,eye=.6)

    def test_no_faces_counts_misses_and_method_errors_are_explicit(self):
        store=self.store();photo=store.add(self.payload(),self.image())
        def recognize(*args,**kwargs):
            if kwargs.get('eye_search'):raise AppError('No reference eyes')
            raise AppError('No faces','face_not_found')
        with patch.object(self.engine,'recognize',side_effect=recognize):report=store.run(dict(photo_ids=[photo['id']]))
        self.assertEqual(report['methods']['full']['counts']['missed'],1)
        self.assertEqual(report['methods']['eye']['errors'],1)
        self.assertIsNone(report['methods']['eye']['recall'])

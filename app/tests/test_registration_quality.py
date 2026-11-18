import json
from pathlib import Path
import sys
import tempfile
import unittest
import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from registration_quality import reference_quality
from engine import AppError, Engine
from workspace import initialize


def face(size=128,seed=1):
    return dict(face=np.random.default_rng(seed).integers(60,190,(size,size,3),dtype=np.uint8),
                facial_area=dict(x=0,y=0,w=size,h=size),confidence=.99)


class ReferenceQualityTests(unittest.TestCase):
    def checks(self,quality):return {check['key']:check for check in quality['checks']}
    def test_clear_large_well_lit_face_passes(self):
        quality=reference_quality(face())
        self.assertEqual(quality['status'],'ready');self.assertTrue(quality['advisory'])
    def test_dark_and_overexposed_photos_have_lighting_advice(self):
        for value in [0,255]:
            item=face();item['face'][:]=value
            self.assertFalse(self.checks(reference_quality(item))['brightness']['ok'])
    def test_blur_is_measured_without_upscaling(self):
        item=face();item['face']=cv2.GaussianBlur(item['face'],(31,31),8)
        self.assertFalse(self.checks(reference_quality(item))['sharpness']['ok'])
        self.assertFalse(self.checks(reference_quality(face(32)))['size']['ok'])
    def test_original_face_box_avoids_alignment_padding(self):
        original=face()['face'];item=face();item['face'][:]=0
        quality=reference_quality(item,original)
        self.assertEqual(quality['status'],'ready')
        item['facial_area'].update(x=100,y=100,w=128,h=128)
        self.assertEqual(reference_quality(item,original)['metrics']['width'],28)


class RegistrationGuideIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=initialize(Path(self.temp.name)/'workspace');self.engine=Engine(self.root)
        self.engine.encode=lambda _:np.eye(512,dtype=np.float32)[0]
    def tearDown(self):self.temp.cleanup()
    def preview(self,item):
        self.engine.detect=lambda _:[item]
        return self.engine.preview_registration(item['face'])
    def save(self,preview,**changes):
        return self.engine.register(dict(roll_number='1',name='Synthetic Student',preview_id=preview['preview_id'],face_index=0,**changes))
    def test_preview_and_save_return_quality_and_reference_progress(self):
        first=self.preview(face());self.assertEqual(first['faces'][0]['quality']['status'],'ready')
        saved=self.save(first);self.assertEqual(saved['reference_count'],1)
        second=self.preview(face(32,2));self.assertEqual(second['faces'][0]['quality']['status'],'retake')
        saved=self.save(second,add_reference=True,quality_acknowledged=True)
        self.assertEqual(saved['reference_count'],2)
        audits=[json.loads(path.read_text()) for path in (self.root/'logs/app-registration').glob('*.json')]
        self.assertEqual(len(audits),2)
        self.assertTrue(any(row['quality_acknowledged'] and row['photo_quality']['status']=='retake' for row in audits))
    def test_duplicate_photo_does_not_change_template_or_roster(self):
        self.save(self.preview(face()))
        before=(self.root/'embeddings/student_templates.npz').read_bytes()
        with self.assertRaisesRegex(AppError,'already saved'):self.save(self.preview(face()),add_reference=True)
        self.assertEqual(before,(self.root/'embeddings/student_templates.npz').read_bytes())
        self.assertEqual(len(list((self.root/'data/reference/1').glob('*.jpg'))),1)
    def test_quality_acknowledgement_requires_a_boolean(self):
        with self.assertRaises(AppError):self.save(self.preview(face()),quality_acknowledged='yes')

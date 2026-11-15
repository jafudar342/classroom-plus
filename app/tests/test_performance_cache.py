import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
from PIL import Image
import test_engine as fixtures
from engine import AppError, atomic_write
from file_cache import FileCache
from lectures import LectureStore
from server import thumbnail


class CacheTests(unittest.TestCase):
    def test_atomic_replacement_same_size_and_mtime_invalidates(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'source';path.write_text('old');stamp=path.stat().st_mtime_ns
            cache=FileCache();self.assertEqual(cache.get((path,),path.read_text),'old')
            atomic_write(path,b'new');os.utime(path,ns=(stamp,stamp))
            self.assertEqual(cache.get((path,),path.read_text),'new')
            path.unlink()
            with self.assertRaises(FileNotFoundError):cache.get((path,),path.read_text)
    def test_callers_cannot_mutate_cached_results(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'source';path.write_text('ready');cache=FileCache()
            value=cache.get((path,),lambda:dict(items=[1],vectors=np.eye(2)))
            value['items'].append(2);value['vectors'][0]=0
            again=cache.get((path,),lambda:self.fail('Unchanged source should be cached'))
            self.assertEqual(again['items'],[1]);np.testing.assert_array_equal(again['vectors'],np.eye(2))
    def test_changed_during_load_is_not_retained_and_errors_are_not_cached(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'source';path.write_text('old');cache=FileCache()
            def changing():
                value=path.read_text();atomic_write(path,b'new');return value
            self.assertEqual(cache.get((path,),changing),'old')
            self.assertEqual(len(cache.entries),0)
            def bad():raise ValueError('broken')
            for _ in range(2):
                with self.assertRaises(ValueError):cache.get((path,),bad)
            self.assertEqual(len(cache.entries),0)
    def test_lru_memory_is_bounded(self):
        with TemporaryDirectory() as folder:
            cache=FileCache(2)
            for index in range(5):
                path=Path(folder)/str(index);path.write_text(str(index));cache.get((path,),path.read_text)
            self.assertEqual(len(cache.entries),2)


class PipelineCacheTests(unittest.TestCase):
    setUp=fixtures.EngineTests.setUp
    tearDown=fixtures.EngineTests.tearDown
    def test_registry_warm_reads_and_external_edits(self):
        with patch('engine.np.load',wraps=np.load) as load:
            first=self.engine.registry();first[0][0]['name']='Changed by caller';first[1][0]=0
            self.assertEqual(self.engine.registry()[0][0]['name'],'Alice')
            self.assertEqual(load.call_count,1)
            path=self.root/'data/roster.csv';path.write_text(path.read_text().replace('Alice','ALICE'))
            self.assertEqual(self.engine.registry()[3][0],'ALICE');self.assertEqual(load.call_count,2)
        path=self.root/'embeddings/student_templates.npz'
        np.savez_compressed(path,embeddings=np.zeros((2,512)),roll_numbers=np.array(['1','2']),names=np.array(['Alice','Bob']))
        with self.assertRaises(AppError):self.engine.registry()
    def test_lecture_summary_refreshes_on_save_external_edit_and_deletion(self):
        store=LectureStore(self.root,self.engine)
        item=store.create(dict(title='Original',lecture_date='2026-11-15',lecture_time='09:00',timezone='Asia/Kolkata',class_id='all-students'))
        with patch.object(store,'load',wraps=store.load) as load:
            result=store.list();result[0]['summary']['present']=99
            self.assertEqual(store.list()[0]['summary']['present'],0);self.assertEqual(load.call_count,1)
        stored=store.load(item['id']);stored['title']='Updated';store.save(stored)
        self.assertEqual(store.list()[0]['title'],'Updated')
        path=store.directory(item['id'])/'lecture.json';stored=json.loads(path.read_text());stored['title']='External';atomic_write(path,json.dumps(stored).encode())
        self.assertEqual(store.list()[0]['title'],'External');path.unlink();self.assertEqual(store.list(),[])
    def test_finalized_view_does_not_reaggregate_old_evidence(self):
        store=LectureStore(self.root,self.engine)
        item=store.create(dict(title='Final',lecture_date='2026-11-15',lecture_time='09:00',timezone='Asia/Kolkata',class_id='all-students'))
        for row in item['attendance']:
            item=store.correct(item['id'],dict(revision=item['revision'],roll_number=row['roll_number'],status='Absent',reason='Teacher confirmed'))
        final=store.finalize(item['id'],dict(revision=item['revision'],confirm=True))
        with patch.object(store,'aggregate',side_effect=AssertionError('Frozen attendance should be used')):
            self.assertEqual(store.view(store.load(item['id']))['attendance'],final['attendance'])
    def test_photo_history_cache_and_thumbnail_changes(self):
        path=self.root/'results/app'/('a'*32)/'result.json';path.parent.mkdir(parents=True)
        value=dict(summary=dict(created_utc='2026-11-15T09:00:00+00:00',present=1,faces=1,source='upload'))
        atomic_write(path,json.dumps(value).encode());self.assertEqual(self.engine.history()[0]['present'],1)
        value['summary']['present']=2;atomic_write(path,json.dumps(value).encode());self.assertEqual(self.engine.history()[0]['present'],2)
        path.unlink();self.assertEqual(self.engine.history(),[])
        photo=self.root/'reference.jpg';Image.new('RGB',(800,400),'red').save(photo)
        first=thumbnail(photo,160);self.assertEqual(thumbnail(photo,160),first)
        import io
        with Image.open(io.BytesIO(thumbnail(photo,640))) as image:self.assertEqual(image.size,(640,320))
        Image.new('RGB',(800,400),'blue').save(photo);self.assertNotEqual(thumbnail(photo,160),first)
        photo.unlink()
        with self.assertRaises(FileNotFoundError):thumbnail(photo,160)

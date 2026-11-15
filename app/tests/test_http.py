import json
import sys
import tempfile
from http.cookies import SimpleCookie
from pathlib import Path
import numpy as np

from tornado.testing import AsyncHTTPTestCase, gen_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import make_app


class SessionTests(AsyncHTTPTestCase):
    @gen_test
    async def test_slow_thumbnail_does_not_block_session_requests(self):
        import asyncio
        import threading
        from unittest.mock import patch
        from PIL import Image
        from server import thumbnail
        path=self.root/'data/reference/1/photo.jpg';path.parent.mkdir(parents=True)
        Image.new('RGB',(800,400),'red').save(path)
        started,released=threading.Event(),threading.Event()
        def slow(photo,size):
            started.set();released.wait(3);return thumbnail(photo,size)
        with patch('server.thumbnail',side_effect=slow):
            pending=self.http_client.fetch(self.get_url('/api/students/1/photo'))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait,2))
                response=await self.http_client.fetch(self.get_url('/api/session'),request_timeout=1)
                self.assertEqual(response.code,200)
                self.assertFalse(pending.done())
            finally:released.set()
            self.assertEqual((await pending).code,200)

    def get_app(self):
        self.fixture = tempfile.TemporaryDirectory()
        self.root = Path(self.fixture.name)
        for folder in ["data", "config", "embeddings"]:
            (self.root / folder).mkdir()
        (self.root / "data/roster.csv").write_text("roll_number,name\n1,Alice\n2,Bob\n")
        np.savez_compressed(self.root / "embeddings/student_templates.npz", embeddings=np.eye(512, dtype=np.float32)[:2],
                            roll_numbers=np.array(["1", "2"]), names=np.array(["Alice", "Bob"]))
        (self.root / "config/demo_matching_settings.json").write_text(json.dumps({"model": "Facenet512", "normalization": "base"}))
        (self.root / "embeddings/metadata.json").write_text(json.dumps({"model": "Facenet512", "input_normalization": "base"}))
        return make_app(self.root)

    def tearDown(self):
        super().tearDown()
        self.fixture.cleanup()

    def session(self, cookie=None):
        response = self.fetch('/api/session', headers={'Cookie': cookie} if cookie else {})
        self.assertEqual(response.code, 200)
        token = json.loads(response.body)['xsrf']
        parsed = SimpleCookie()
        for value in response.headers.get_list('Set-Cookie'):
            parsed.load(value)
        return token, f'classroom_attendance_xsrf={parsed["classroom_attendance_xsrf"].value}' if parsed else cookie

    def register(self, cookie, token=None):
        headers = {'Cookie': cookie, 'Content-Type': 'application/json'}
        if token:
            headers['X-XSRFToken'] = token
        return self.fetch('/api/register', method='POST', headers=headers, body=json.dumps({
            'roll_number': '999999', 'name': 'Session test', 'preview_id': 'nonexistent', 'face_index': 0,
        }))

    def test_jupyter_cookie_cannot_break_registration(self):
        token, cookie = self.session()
        response = self.register(cookie + '; _xsrf=unrelated-jupyter-token', token)
        self.assertEqual(response.code, 422)  # Reaches registration validation, not Forbidden.
        self.assertIn('preview expired', json.loads(response.body)['error'].lower())

    def test_stale_token_can_be_refreshed(self):
        stale_token, _ = self.session()
        _, fresh_cookie = self.session()
        self.assertEqual(self.register(fresh_cookie, stale_token).code, 403)
        refreshed_token, _ = self.session(fresh_cookie)
        self.assertEqual(self.register(fresh_cookie, refreshed_token).code, 422)

    def test_request_without_token_still_forbidden(self):
        _, cookie = self.session()
        self.assertEqual(self.register(cookie).code, 403)

    def test_sample_and_reports_use_bound_workspace(self):
        (self.root / "data/classroom").mkdir()
        (self.root / "data/classroom/synthetic_classroom.png").write_bytes(b"fixture-sample")
        self.assertEqual(self.fetch('/api/sample').body, b"fixture-sample")
        run_id = "a" * 32
        folder = self.root / "results/app" / run_id
        folder.mkdir(parents=True)
        (folder / "attendance.csv").write_bytes(b"fixture-report")
        self.assertEqual(self.fetch(f'/api/reports/{run_id}/attendance.csv').body, b"fixture-report")

    def test_malformed_recognition_options_return_validation_error(self):
        token, cookie = self.session()
        for payload in [{"source": []}, {"save": "false"}]:
            response = self.fetch('/api/recognize', method='POST',
                                  headers={'Cookie': cookie, 'X-XSRFToken': token, 'Content-Type': 'application/json'},
                                  body=json.dumps(payload))
            self.assertEqual(response.code, 400)

    def test_blank_frame_returns_retryable_no_face_code(self):
        from engine import AppError
        import base64, io
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (64, 64)).save(buffer, format='PNG')
        image = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        def no_face(_):
            raise AppError('No face was found.', 'face_not_found')
        self._app.engine.detect = no_face
        token, cookie = self.session()
        response = self.fetch('/api/recognize', method='POST',
                              headers={'Cookie': cookie, 'X-XSRFToken': token, 'Content-Type': 'application/json'},
                              body=json.dumps({'image': image}))
        self.assertEqual(response.code, 422)
        self.assertEqual(json.loads(response.body)['code'], 'face_not_found')

    def post_student(self, path, payload):
        token, cookie = self.session()
        return self.fetch(path, method='POST', headers={'Cookie': cookie, 'X-XSRFToken': token, 'Content-Type': 'application/json'}, body=json.dumps(payload))

    def test_profile_edit_delete_restore_api(self):
        response = self.fetch('/api/students/1')
        self.assertEqual(response.code, 200)
        response = self.post_student('/api/students/1/update', {'roll_number': '11', 'name': 'Alice Changed', 'course': 'AI', 'custom_fields': [{'label': 'Batch', 'value': '2026'}], 'revision': ''})
        self.assertEqual(response.code, 200)
        student = json.loads(response.body)
        self.assertEqual(student['course'], 'AI')
        self.assertEqual(student['roll_number'], '11')
        response = self.post_student('/api/students/11/delete', {'confirmation': '11', 'revision': student['revision']})
        self.assertEqual(response.code, 200)
        archived = json.loads(response.body)
        self.assertEqual(self.fetch('/api/students/11').code, 422)
        response = self.post_student('/api/students/restore', {'archive_id': archived['archive_id']})
        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body)['name'], 'Alice Changed')

    def test_profile_mutations_require_xsrf(self):
        for path in ['/api/students/1/update', '/api/students/1/delete', '/api/students/restore']:
            response = self.fetch(path, method='POST', headers={'Content-Type':'application/json'}, body='{}')
            self.assertEqual(response.code, 403)

    def test_reference_photo_path_cannot_escape(self):
        self.assertEqual(self.fetch('/api/students/1/photos/..%2F..%2Froster.csv').code, 404)

    def test_classes_and_subjects_api(self):
        response = self.post_student('/api/classes/save', {'name':'AI A','student_rolls':['1'],'revision':''})
        self.assertEqual(response.code, 200)
        saved = json.loads(response.body)
        group = saved['class']
        response = self.post_student('/api/subjects/save', {'class_id':group['id'],'name':'Deep Learning','code':'AI501','revision':saved['academics']['revision']})
        self.assertEqual(response.code, 200)
        subject = json.loads(response.body)['subject']
        state = json.loads(self.fetch('/api/state').body)
        self.assertEqual(state['academics']['classes'][0]['student_rolls'], ['1'])
        self.assertEqual(state['academics']['subjects'][0]['id'], subject['id'])

    def test_academic_mutations_require_xsrf(self):
        for path in ['/api/classes/save', '/api/subjects/save']:
            response = self.fetch(path, method='POST', headers={'Content-Type':'application/json'}, body='{}')
            self.assertEqual(response.code, 403)

    def test_lecture_workflow_and_xsrf(self):
        payload=dict(title='HTTP lecture',lecture_date='2026-11-11',lecture_time='09:00',timezone='UTC',class_id='all-students')
        self.assertEqual(self.fetch('/api/lectures/create',method='POST',headers={'Content-Type':'application/json'},body=json.dumps(payload)).code,403)
        token,cookie=self.session()
        headers={'Content-Type':'application/json','X-XSRFToken':token,'Cookie':cookie}
        def post(path,value):
            response=self.fetch(path,method='POST',headers=headers,body=json.dumps(value))
            return response,json.loads(response.body)
        response,item=post('/api/lectures/create',payload)
        self.assertEqual(response.code,200)
        path='/api/lectures/'+item['id']
        self.assertEqual(self.fetch(path).code,200)
        self.assertEqual(self.fetch(path+'/attendance.csv').code,422)
        for roll,status in [('1','Present'),('2','Absent')]:
            response,item=post(path+'/attendance',dict(roll_number=roll,status=status,reason='Manual roll call.',revision=item['revision']))
            self.assertEqual(response.code,200)
        response,item=post(path+'/finalize',dict(confirm=True,revision=item['revision']))
        self.assertEqual(item['state'],'finalized')
        self.assertEqual(self.fetch(path+'/attendance.csv').code,200)
        self.assertIn(b'Alice,Present',self.fetch(path+'/attendance.csv').body)
        self.assertIn(b'Manual roll call.',self.fetch(path+'/audit.csv').body)
        response,_=post(path+'/attendance',dict(roll_number='1',status='Absent',reason='Change',revision=item['revision']))
        self.assertEqual(response.code,422)
        self.assertEqual(len(json.loads(self.fetch('/api/state').body)['lectures']),1)
        self.assertEqual(self.fetch(path+'/captures/'+'b'*32+'/image').code,404)

    def test_dashboard_routes(self):
        response=self.fetch('/api/dashboard')
        self.assertEqual(response.code,200)
        self.assertIsNone(json.loads(response.body)['percentage'])
        self.assertEqual(self.fetch('/api/dashboard/monthly.csv').code,422)
        token,cookie=self.session()
        payload=json.dumps({'target':80})
        self.assertEqual(self.fetch('/api/dashboard',method='POST',headers={'Content-Type':'application/json'},body=payload).code,403)
        response=self.fetch('/api/dashboard',method='POST',headers={'Content-Type':'application/json','X-XSRFToken':token,'Cookie':cookie},body=payload)
        self.assertEqual(response.code,200)
        self.assertEqual(json.loads(self.fetch('/api/dashboard').body)['target'],80)
        self.assertEqual(self.fetch('/api/dashboard?month=2026-13').code,422)
        self.assertEqual(self.fetch('/api/dashboard/monthly.csv?month=2026-11').code,200)

    def test_evaluation_api_isolated_and_replayable(self):
        from engine import image_url
        payload=dict(title='HTTP evaluation',split='validation',independent=True,complete=True,
                     image=image_url(np.zeros((100,100,3),dtype=np.uint8)),
                     labels=[dict(x=0,y=0,w=80,h=80,roll_number='1')])
        self.assertEqual(self.fetch('/api/evaluation',method='POST',headers={'Content-Type':'application/json'},body=json.dumps(payload)).code,403)
        token,cookie=self.session()
        headers={'Content-Type':'application/json','X-XSRFToken':token,'Cookie':cookie}
        def post(path,value):
            response=self.fetch(path,method='POST',headers=headers,body=json.dumps(value))
            self.assertEqual(response.code,200,response.body)
            return json.loads(response.body)
        photo=post('/api/evaluation',payload)
        self.assertEqual(self.fetch('/api/evaluation/photos/'+photo['id']+'/image').code,200)
        self._app.engine.recognize=lambda *args,**kwargs:dict(detections=[dict(face_id=1,x=1,y=1,w=40,h=40,candidate_roll='1',candidate_name='Alice',cosine_distance=.2,gap=.1,eye_similarity=.8)])
        report=post('/api/evaluation/runs',dict(photo_ids=[photo['id']]))
        self.assertEqual(report['methods']['full']['counts']['correct'],1)
        strict=json.loads(self.fetch('/api/evaluation/runs/'+report['id']+'?distance=0.1').body)
        self.assertEqual(strict['methods']['full']['counts']['missed'],1)
        self.assertEqual(self.fetch('/api/evaluation/runs/'+report['id']+'?eye=nan').code,422)
        self.assertEqual(len(json.loads(self.fetch('/api/evaluation').body)['photos']),1)
        self.assertFalse((self.root/'results').exists())

    def test_video_attendance_routes_and_review(self):
        import uuid
        from unittest.mock import patch
        from engine import image_url
        settings=self.root/'config/demo_matching_settings.json'
        settings.write_text(json.dumps(dict(model='Facenet512',normalization='base',cosine_distance_threshold=.3,minimum_gap=.05)))
        self._app.engine.settings.update(cosine_distance_threshold=.3,minimum_gap=.05)
        pixels=np.random.default_rng(3).integers(30,220,(64,64,3),dtype=np.uint8)
        self._app.engine.detect=lambda _: [dict(facial_area=dict(x=1,y=2,w=64,h=64),confidence=.99,face=pixels)]
        self._app.engine.encode=lambda _:np.eye(512,dtype=np.float32)[0]
        def post(path,payload):
            response=self.post_student(path,payload)
            self.assertEqual(response.code,200,response.body)
            return json.loads(response.body)
        item=post('/api/lectures/create',dict(title='Video API',lecture_date='2026-11-14',lecture_time='10:00',timezone='Asia/Kolkata',class_id='all-students'))
        base=f"/api/lectures/{item['id']}/video"
        response=self.fetch(base+'/start',method='POST',headers={'Content-Type':'application/json'},body='{}')
        self.assertEqual(response.code,403)
        result=post(base+'/start',dict(revision=item['revision']));item=result['lecture'];scan=result['scan_id']
        for index in range(3):
            with patch('video_attendance.time.time',return_value=100+index*2):
                result=post(base+'/'+scan+'/frame',dict(revision=item['revision'],frame_id=uuid.uuid4().hex,image=image_url(np.full((100,100,3),index*60,dtype=np.uint8))))
            item=result['lecture']
        self.assertEqual(item['video_scans'][0]['tracks'][0]['proposed_roll'],'1')
        self.assertEqual(self.fetch(base+'/'+scan+'/tracks/1/photo').code,200)
        self.assertEqual(self.fetch(base+'/'+scan+'/tracks/999/photo').code,404)
        item=post(base+'/'+scan+'/stop',dict(revision=item['revision']))['lecture']
        item=post(base+'/'+scan+'/review',dict(revision=item['revision'],action='accept',track_id=1))['lecture']
        self.assertEqual(item['summary']['present'],1)
        self.assertEqual(item['summary']['unconfirmed'],1)
        self.assertFalse(item['can_finalize'])
        item=post(f"/api/lectures/{item['id']}/attendance",dict(revision=item['revision'],roll_number='2',status='Absent',reason='Teacher checked Bob is absent.'))
        self.assertTrue(item['can_finalize'])
        final=post(f"/api/lectures/{item['id']}/finalize",dict(revision=item['revision'],confirm=True))
        self.assertEqual(final['state'],'finalized')
        self.assertEqual(self.post_student(base+'/'+scan+'/review',dict(revision=final['revision'],action='reset',track_id=1)).code,422)

    def test_timetable_api_creates_one_scheduled_lecture_and_protects_writes(self):
        from datetime import date
        catalog=json.loads(self.fetch('/api/timetable').body)
        self.assertEqual(catalog['occurrences'],[])
        self.assertEqual(self.fetch('/api/timetable?date=invalid').code,422)
        self.assertEqual(self.fetch('/api/timetable',method='POST',headers={'Content-Type':'application/json'},body='{}').code,403)
        group=self._app.engine.save_class(dict(name='Schedule class',student_rolls=['1','2'],revision=''))['class']
        subject=self._app.engine.save_subject(dict(name='AI',class_id=group['id'],revision=self._app.engine.academics()['revision']))['subject']
        payload=dict(revision=0,class_id=group['id'],subject_id=subject['id'],weekdays=[date.fromisoformat(catalog['today']).weekday()],start_time='09:00',end_time='10:00',starts_on=catalog['today'],late_after_minutes=10,active=True)
        response=self.post_student('/api/timetable',payload);self.assertEqual(response.code,200,response.body)
        data=json.loads(response.body);slot=data['entries'][0]
        start=dict(slot_id=slot['id'],date=data['today'],revision=data['revision'])
        response=self.post_student('/api/timetable/start',start);self.assertEqual(response.code,200,response.body)
        first=json.loads(response.body)
        second=json.loads(self.post_student('/api/timetable/start',start).body)
        self.assertEqual(first['lecture']['id'],second['lecture']['id']);self.assertTrue(second['resumed'])
        self.assertEqual(json.loads(self.fetch('/api/timetable').body)['day_summary']['in_progress'],1)
        self.assertEqual(self.post_student('/api/timetable',{**payload,'revision':0}).code,422)
        self.assertEqual(self.fetch('/api/timetable/start',method='POST',headers={'Content-Type':'application/json'},body='{}').code,403)

    def test_project_settings_api_and_model_allowlist(self):
        self._app.busy=True
        progress=self.fetch('/api/settings/status')
        self.assertEqual(progress.code,200)
        self.assertFalse(json.loads(progress.body)['running'])
        self._app.busy=False
        response=self.fetch('/api/settings');self.assertEqual(response.code,200,response.body)
        data=json.loads(response.body)
        self.assertEqual([item['id'] for item in data['models']['detectors']],['retinaface','opencv','yunet','centerface','mtcnn'])
        self.assertEqual([item['id'] for item in data['models']['embeddings']],['Facenet512','ArcFace','GhostFaceNet','Buffalo_L'])
        payload=dict(revision=data['revision'],values={**data['values'],'attendance_target':82,'cosine_distance_threshold':.25})
        self.assertEqual(self.fetch('/api/settings',method='POST',headers={'Content-Type':'application/json'},body=json.dumps(payload)).code,403)
        response=self.post_student('/api/settings',payload);self.assertEqual(response.code,200,response.body)
        saved=json.loads(response.body)
        self.assertEqual(saved['values']['attendance_target'],82)
        self.assertEqual(self._app.engine.settings['cosine_distance_threshold'],.25)
        self.assertEqual(json.loads(self.fetch('/api/dashboard').body)['target'],82)
        invalid=dict(revision=saved['revision'],values={**saved['values'],'model':'NotAModel'})
        self.assertEqual(self.post_student('/api/settings',invalid).code,422)
        self.assertEqual(self.post_student('/api/settings',payload).code,422)
        self.assertEqual(json.loads(self.fetch('/api/settings').body)['values']['model'],'Facenet512')

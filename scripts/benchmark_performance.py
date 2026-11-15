from pathlib import Path
import copy,json,sys,tempfile,time,statistics
import numpy as np
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'app'))
from engine import Engine
from lectures import LectureStore

def measure(fn,count=15):
 fn();values=[]
 for _ in range(count):
  start=time.perf_counter();fn();values.append((time.perf_counter()-start)*1000)
 return round(statistics.median(values),3)
with tempfile.TemporaryDirectory(prefix='performance-',dir=root/'work') as folder:
 fixture=Path(folder)
 for name in ('data','config','embeddings','results/app','results/lectures'):(fixture/name).mkdir(parents=True)
 students=[dict(roll_number=str(i+1),name=f'Student {i+1}') for i in range(500)]
 (fixture/'data/roster.csv').write_text('roll_number,name\n'+''.join(f"{s['roll_number']},{s['name']}\n" for s in students))
 vectors=np.random.default_rng(42).normal(size=(500,512)).astype(np.float32);vectors/=np.linalg.norm(vectors,axis=1)[:,None]
 np.savez_compressed(fixture/'embeddings/student_templates.npz',embeddings=vectors,roll_numbers=np.array([s['roll_number'] for s in students]),names=np.array([s['name'] for s in students]))
 (fixture/'config/demo_matching_settings.json').write_text(json.dumps(dict(model='Facenet512',normalization='base',cosine_distance_threshold=.3,minimum_gap=.05)))
 (fixture/'embeddings/metadata.json').write_text(json.dumps(dict(model='Facenet512',input_normalization='base')))
 engine=Engine(fixture);store=LectureStore(fixture,engine)
 item=store.create(dict(title='Performance fixture',lecture_date='2026-11-15',lecture_time='09:00',timezone='Asia/Kolkata',class_id='all-students'))
 original=store.load(item['id']);original['overrides']={s['roll_number']:dict(status='Absent',reason='Fixture',updated_utc='2026-11-15T10:00:00+00:00') for s in students}
 # Include historical evidence so finalized views must otherwise walk old captures.
 original['captures']=[dict(id=f'{index:032x}',created_utc='2026-11-15T09:00:00+00:00',summary={},detections=[dict(face_id=n,candidate_roll=str(n),decision='Matched') for n in range(1,51)]) for index in range(10)]
 rows,summary=store.aggregate(original);original.update(state='finalized',final_rows=rows,final_summary=summary)
 for index in range(100):
  identifier=f'{index+1000:032x}';path=fixture/'results/lectures'/identifier/'lecture.json';path.parent.mkdir();path.write_text(json.dumps(dict(original,id=identifier)))
  path=fixture/'results/app'/identifier/'result.json';path.parent.mkdir();path.write_text(json.dumps(dict(summary=dict(created_utc='2026-11-15T10:00:00+00:00',present=50,faces=50,source='upload'),attendance=rows,detections=original['captures'][0]['detections'])))
 results=dict(registry_500_students_ms=measure(engine.registry,50),lecture_list_101_sessions_ms=measure(store.list),photo_history_100_reports_ms=measure(engine.history),finalized_view_ms=measure(lambda:store.view(original),50))
 print(json.dumps(results,indent=2))
 (root/'work'/('performance-'+sys.argv[1]+'.json')).write_text(json.dumps(results,indent=2))

"""Weekly schedules and idempotent links to frozen lecture occurrences."""
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from engine import AppError, atomic_write, now

DAYS=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']


class Timetable:
    def __init__(self, root, engine, lectures):
        self.path=root/'config/timetable.json'
        self.engine,self.lectures=engine,lectures

    @staticmethod
    def clock():return datetime.now(timezone.utc)

    def load(self):
        if not self.path.exists():return dict(version=1,revision=0,timezone='Asia/Kolkata',entries=[])
        try:
            data=json.loads(self.path.read_text())
            if (not isinstance(data,dict) or data['version']!=1 or type(data['revision']) is not int
                    or data['timezone']!='Asia/Kolkata' or not isinstance(data['entries'],list)):
                raise ValueError()
            ids=set()
            for entry in data['entries']:
                if (not re.fullmatch('[a-f0-9]{32}',entry['id']) or entry['id'] in ids
                        or type(entry['active']) is not bool or not isinstance(entry['weekdays'],list)
                        or not entry['weekdays'] or any(type(day) is not int or not 0<=day<=6 for day in entry['weekdays'])
                        or len(set(entry['weekdays']))!=len(entry['weekdays'])
                        or type(entry['late_after_minutes']) is not int or not 0<=entry['late_after_minutes']<=180):raise ValueError()
                self.parse_date(entry['starts_on'])
                if entry['ends_on'] and self.parse_date(entry['ends_on'])<self.parse_date(entry['starts_on']):raise ValueError()
                self.parse_time(entry['start_time']);self.parse_time(entry['end_time'])
                if entry['end_time']<=entry['start_time']:raise ValueError()
                if not all(isinstance(entry[key],str) for key in ('title','class_id','subject_id')):raise ValueError()
                ids.add(entry['id'])
            return data
        except (OSError,ValueError,KeyError,TypeError,AppError) as error:
            raise AppError('The timetable could not be read. Restore its saved configuration before editing.') from error

    @staticmethod
    def parse_date(value):
        try:
            if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
            return date.fromisoformat(value)
        except ValueError as error:raise AppError('Choose a valid timetable date.') from error

    @staticmethod
    def parse_time(value):
        if not isinstance(value,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value):raise AppError('Choose a valid start and end time.')
        return value

    @staticmethod
    def revision(data,payload):
        if type(payload.get('revision')) is not int or payload['revision']!=data['revision']:
            raise AppError('The timetable changed in another tab. Refresh it before saving.','stale_revision')

    def today(self,data=None):return self.clock().astimezone(ZoneInfo((data or self.load())['timezone'])).date()

    def decorated(self,entry):
        row=dict(entry)
        try:
            context,_=self.engine.attendance_context(entry['class_id'],entry['subject_id'])
            row.update(context,available=True)
        except AppError:
            row.update(class_name='Unavailable class',subject_name='Unavailable subject',subject_code='',available=False)
        return row

    def save(self,payload):
        data=self.load();self.revision(data,payload)
        identifier=payload.get('id')
        previous=next((row for row in data['entries'] if row['id']==identifier),None)
        if identifier is not None and (not isinstance(identifier,str) or previous is None):raise AppError('Choose an existing timetable slot.')
        class_id,subject_id=payload.get('class_id'),payload.get('subject_id')
        if not isinstance(class_id,str) or class_id=='all-students' or not isinstance(subject_id,str) or not subject_id:
            raise AppError('Choose a class and its subject. Create them in Classes & subjects first.')
        self.engine.attendance_context(class_id,subject_id)
        title=payload.get('title','')
        if not isinstance(title,str) or len(title.strip())>100 or any(ord(char)<32 for char in title):raise AppError('Use a session label of up to 100 characters.')
        weekdays=payload.get('weekdays')
        if (not isinstance(weekdays,list) or not weekdays or any(type(day) is not int or not 0<=day<=6 for day in weekdays) or len(set(weekdays))!=len(weekdays)):
            raise AppError('Choose at least one different weekday.')
        start=self.parse_time(payload.get('start_time'));end=self.parse_time(payload.get('end_time'))
        if start>=end:raise AppError('End time must be later than start time, on the same day.')
        since=self.parse_date(payload.get('starts_on'));until=self.parse_date(payload['ends_on']) if payload.get('ends_on') else None
        if until and until<since:raise AppError('The schedule end date must follow its start date.')
        grace=payload.get('late_after_minutes',self.engine.settings.get('default_late_after_minutes',10))
        if type(grace) is not int or not 0<=grace<=180:raise AppError('Set a late cutoff from 0 to 180 minutes after the start.')
        active=payload.get('active',True)
        if type(active) is not bool:raise AppError('Choose whether this timetable slot is active.')
        row=dict(id=identifier or uuid.uuid4().hex,title=title.strip(),class_id=class_id,subject_id=subject_id,
                 weekdays=sorted(weekdays),start_time=start,end_time=end,starts_on=since.isoformat(),ends_on=until.isoformat() if until else '',
                 late_after_minutes=grace,active=active,updated_utc=now())
        for other in data['entries']:
            if not active or not other['active'] or other['id']==identifier or other['class_id']!=class_id:continue
            common=set(weekdays)&set(other['weekdays'])
            if not common or start>=other['end_time'] or end<=other['start_time']:continue
            first=max(since,self.parse_date(other['starts_on']))
            last=min(until or date.max,self.parse_date(other['ends_on']) if other['ends_on'] else date.max)
            if any(first+timedelta(days=offset)<=last and (first+timedelta(days=offset)).weekday() in common for offset in range(min(7,max(0,(last-first).days+1)))):
                raise AppError('This class already has an overlapping timetable slot. Change its day or time.')
        if previous:data['entries'][data['entries'].index(previous)]=row
        else:data['entries'].append(row)
        data['revision']+=1
        atomic_write(self.path,json.dumps(data,indent=2).encode())
        return self.catalog()

    def catalog(self,day=''):
        data=self.load()
        return dict(revision=data['revision'],timezone=data['timezone'],today=self.today(data).isoformat(),
                    entries=[self.decorated(row) for row in data['entries']],**self.day(day or self.today(data).isoformat(),data))

    @staticmethod
    def applies(entry,day):return entry['active'] and day.weekday() in entry['weekdays'] and entry['starts_on']<=day.isoformat() and (not entry['ends_on'] or day.isoformat()<=entry['ends_on'])

    def snapshot(self,entry,day,data):
        start=datetime.fromisoformat(day+'T'+entry['start_time']).replace(tzinfo=ZoneInfo(data['timezone']))
        return dict(slot_id=entry['id'],date=day,start_time=entry['start_time'],end_time=entry['end_time'],timezone=data['timezone'],
                    late_after_minutes=entry['late_after_minutes'],cutoff_utc=(start+timedelta(minutes=entry['late_after_minutes'])).astimezone(timezone.utc).isoformat(),
                    occurrence_key=entry['id']+':'+day)

    def day(self,value,data=None):
        data=data or self.load();day=self.parse_date(value)
        saved={}
        for lecture in self.lectures.list():
            schedule=lecture.get('schedule')
            if schedule and schedule.get('date')==value:saved[schedule['slot_id']]=lecture
        rows=[];seen=set()
        for entry in data['entries']:
            if not self.applies(entry,day) and entry['id'] not in saved:continue
            decorated=self.decorated(entry);lecture=saved.get(entry['id'])
            schedule=lecture['schedule'] if lecture else self.snapshot(entry,value,data)
            context=lecture['context'] if lecture else {key:decorated.get(key,'') for key in ('class_id','class_name','subject_id','subject_name','subject_code')}
            rows.append(dict(**context,schedule=schedule,title=lecture['title'] if lecture else entry['title'] or decorated['subject_name'],
                             available=bool(lecture) or decorated['available'],lecture_id=lecture['id'] if lecture else None,
                             lecture_state=lecture['state'] if lecture else None,summary=lecture['summary'] if lecture else None,
                             changed=bool(lecture) and (not self.applies(entry,day) or any(schedule[key]!=entry[key] for key in ('start_time','end_time','late_after_minutes')) or any(context[key]!=decorated.get(key) for key in ('class_id','subject_id','class_name','subject_name')) or bool(entry['title'] and lecture['title']!=entry['title']))))
            seen.add(entry['id'])
        for identifier,lecture in saved.items():
            if identifier not in seen:rows.append(dict(**lecture['context'],schedule=lecture['schedule'],title=lecture['title'],available=True,lecture_id=lecture['id'],lecture_state=lecture['state'],summary=lecture['summary'],changed=True))
        instant=self.clock()
        for row in rows:
            start=datetime.fromisoformat(value+'T'+row['schedule']['start_time']).replace(tzinfo=ZoneInfo(data['timezone']))
            row['status']='Completed' if row['lecture_state']=='finalized' else 'In progress' if row['lecture_id'] else 'Upcoming' if instant<start else 'Needs attendance'
        rows.sort(key=lambda row:(row['schedule']['start_time'],row['class_name'],row['schedule']['slot_id']))
        return dict(date=value,occurrences=rows,day_summary={key:sum(row['status']==label for row in rows) for key,label in [('completed','Completed'),('in_progress','In progress'),('upcoming','Upcoming'),('needs_attendance','Needs attendance')]})

    def start(self,payload):
        data=self.load();day=self.parse_date(payload.get('date'));identifier=payload.get('slot_id')
        if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):raise AppError('Choose a scheduled class.')
        for lecture in self.lectures.list():
            if lecture.get('schedule',{}).get('occurrence_key')==identifier+':'+day.isoformat():
                return dict(lecture=self.lectures.view(self.lectures.load(lecture['id'])),resumed=True)
        self.revision(data,payload)
        entry=next((row for row in data['entries'] if row['id']==identifier),None)
        if entry is None or not self.applies(entry,day):raise AppError('This slot is not scheduled for the selected date. Refresh the timetable.')
        if day>self.today(data):raise AppError('Start attendance on the scheduled day or later.')
        context,_=self.engine.attendance_context(entry['class_id'],entry['subject_id'])
        lecture=self.lectures.create(dict(title=entry['title'] or context['subject_name'],lecture_date=day.isoformat(),lecture_time=entry['start_time'],timezone=data['timezone'],class_id=entry['class_id'],subject_id=entry['subject_id']),schedule=self.snapshot(entry,day.isoformat(),data))
        return dict(lecture=lecture,resumed=False)

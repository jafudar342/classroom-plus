"""Attendance totals computed from each finalized lecture's frozen roster."""
import json
import re
from datetime import date, timedelta
from engine import AppError, atomic_write, csv_bytes


def percentage(present, total):
    return round(100 * present / total, 1) if total else None


class Analytics:
    def __init__(self, root, lectures):
        self.root = root
        self.lectures = lectures

    def target(self):
        path = self.root / 'config/dashboard_settings.json'
        if not path.exists():
            return 75
        try:
            target = json.loads(path.read_text())['target']
            if type(target) not in (int, float) or not 0 <= target <= 100:
                raise ValueError()
            return target
        except (OSError, KeyError, ValueError, TypeError) as error:
            raise AppError('The attendance target could not be read. Save the target again.') from error

    def save_target(self, payload):
        target = payload.get('target')
        if type(target) not in (int, float) or not 0 <= target <= 100:
            raise AppError('Choose an attendance target between 0 and 100 percent.')
        atomic_write(self.root / 'config/dashboard_settings.json', json.dumps({'target': target}).encode())
        return {'target': target}

    def report(self, month='', class_id='', subject_id=''):
        if month:
            try:
                if not re.fullmatch(r'\d{4}-\d{2}', month):
                    raise ValueError()
                date.fromisoformat(month + '-01')
            except ValueError as error:
                raise AppError('Choose a valid report month.') from error
        target = self.target()
        records, classes, subjects, months = [], {}, {}, set()
        skipped, drafts, lectures = 0, 0, 0
        for path in self.lectures.root.glob('*/lecture.json'):
            try:
                item = self.lectures.load(path.parent.name)
                if item['state'] != 'finalized':
                    drafts += 1
                    continue
                day = date.fromisoformat(item['lecture_date'])
                context = item['context']
                group, subject = context['class_id'], context['subject_id']
                identities = {row['roll_number']: row['identity_id'] for row in item['roster']}
                rows = item['final_rows']
                if (not rows or len({r['roll_number'] for r in rows}) != len(rows)
                        or {r['roll_number'] for r in rows} != set(identities)
                        or any(r['status'] not in ('Present', 'Absent') for r in rows)):
                    raise ValueError()
                classes[group] = context['class_name']
                subjects[(group, subject)] = dict(id=subject, class_id=group, name=context['subject_name'])
                months.add(day.isoformat()[:7])
                if ((month and day.isoformat()[:7] != month) or (class_id and group != class_id)
                        or (subject_id and subject != subject_id)):
                    continue
                lecture_records = []
                for row in rows:
                    lecture_records.append(dict(identity=identities[row['roll_number']],
                        roll_number=row['roll_number'], name=row['name'], status=row['status'],
                        note=row.get('note', ''), source=row.get('source', ''),
                        date=day.isoformat(), time=item['lecture_time'], title=item['title'],
                        lecture_id=item['id'], **context))
                records.extend(lecture_records)
                lectures += 1
            except (AppError, KeyError, TypeError, ValueError):
                skipped += 1
        records.sort(key=lambda row: (row['date'], row['time'], row['lecture_id']))
        students, groups, offerings, weekly, monthly = {}, {}, {}, {}, {}
        for record in records:
            identity = record['identity']
            student = students.setdefault(identity, dict(identity=identity, present=0, total=0, history=[]))
            student.update(name=record['name'], roll_number=record['roll_number'])
            student['present'] += record['status'] == 'Present'
            student['total'] += 1
            student['history'].append(record)
            day = date.fromisoformat(record['date'])
            week = (day - timedelta(days=day.weekday())).isoformat()
            for collection, key, label in (
                (groups, record['class_id'], record['class_name']),
                (offerings, (record['class_id'], record['subject_id']), record['class_name'] + ' · ' + record['subject_name']),
                (weekly, week, week), (monthly, record['date'][:7], record['date'][:7])):
                bucket = collection.setdefault(key, dict(label=label, present=0, total=0))
                bucket['present'] += record['status'] == 'Present'
                bucket['total'] += 1
        for student in students.values():
            student['percentage'] = percentage(student['present'], student['total'])
            student['below_target'] = 100 * student['present'] / student['total'] < target
            student['history'].reverse()
        def totals(collection):
            return [dict(row, percentage=percentage(row['present'], row['total'])) for row in collection.values()]
        present = sum(r['status'] == 'Present' for r in records)
        return dict(target=target, month=month, lectures=lectures, opportunities=len(records),
            present=present, percentage=percentage(present, len(records)), skipped=skipped, drafts=drafts,
            students=sorted(students.values(), key=lambda s: (s['percentage'], s['name'].casefold())),
            classes=[dict(id=key, name=value) for key,value in sorted(classes.items(), key=lambda pair: pair[1])],
            subjects=list(subjects.values()), months=sorted(months, reverse=True),
            class_totals=totals(groups), subject_totals=totals(offerings),
            weekly=totals(weekly), monthly=totals(monthly))

    def export(self, month, class_id='', subject_id=''):
        if not month:
            raise AppError('Choose a month before downloading a monthly report.')
        report = self.report(month, class_id, subject_id)
        grouped = {}
        for student in report['students']:
            for row in student['history']:
                key = (student['identity'], row['class_id'], row['subject_id'])
                entry = grouped.setdefault(key, dict(month=month, roll_number=student['roll_number'],
                    name=student['name'], class_name=row['class_name'], subject_name=row['subject_name'],
                    present=0, total=0, target=report['target']))
                entry['total'] += 1
                entry['present'] += row['status'] == 'Present'
        rows = [dict(row, absent=row['total']-row['present'], percentage=percentage(row['present'],row['total']),
                     below_target=100*row['present']/row['total'] < row['target']) for row in grouped.values()]
        return csv_bytes(rows, ['month','class_name','subject_name','roll_number','name','present','absent','total','percentage','target','below_target'])

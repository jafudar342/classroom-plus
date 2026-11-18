"""Local reminder records with optimistic concurrency checks."""
import json
import uuid
from datetime import datetime, timezone
from engine import AppError, atomic_write


class Reminders:
    def __init__(self, root):
        self.path = root / 'data/reminders.json'

    def read(self):
        if not self.path.exists():
            return {'revision': '', 'reminders': []}
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or not isinstance(data['revision'], str) or not isinstance(data['reminders'], list):
                raise ValueError()
            for item in data['reminders']:
                if (not isinstance(item, dict) or not isinstance(item['id'], str)
                        or not isinstance(item['text'], str) or type(item['completed']) is not bool
                        or datetime.fromisoformat(item['due']).utcoffset() is None):
                    raise ValueError()
            return data
        except (ValueError, TypeError, KeyError, OSError) as error:
            raise AppError('Reminders could not be read. Restore the reminders file from a backup.') from error

    def save(self, payload):
        data = self.read()
        if payload.get('revision') != data['revision']:
            raise AppError('Reminders changed in another window. Reload reminders before saving.')
        action = payload.get('action')
        item = next((r for r in data['reminders'] if r['id'] == payload.get('id')), None)
        if action == 'create':
            if len(data['reminders']) >= 500:
                raise AppError('You can save up to 500 reminders.')
            item = {'id': uuid.uuid4().hex, 'completed': False}
        elif item is None:
            raise AppError('This reminder no longer exists. Reload reminders.')
        if action in ('create', 'edit'):
            text = payload.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 500:
                raise AppError('Write a reminder of 1–500 characters.')
            try:
                due = datetime.fromisoformat(payload.get('due', ''))
                if due.utcoffset() is None:
                    raise ValueError()
            except (ValueError, TypeError):
                raise AppError('Choose a valid reminder date and time.')
            item.update(text=text.strip(), due=due.astimezone(timezone.utc).isoformat())
        elif action == 'complete':
            if type(payload.get('completed')) is not bool:
                raise AppError('Choose a valid completion status.')
            item['completed'] = payload['completed']
        elif action != 'delete':
            raise AppError('Choose a valid reminder action.')
        if action == 'create':
            data['reminders'].append(item)
        if action == 'delete':
            data['reminders'].remove(item)
        data['revision'] = uuid.uuid4().hex
        atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2).encode())
        return data

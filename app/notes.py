"""Workspace notes, saved independently of attendance records."""
import json
import math
import uuid
from engine import AppError, atomic_write, now


class Notes:
    def __init__(self, root):
        self.path = root / 'data/notes.json'

    def read(self):
        if not self.path.exists():
            return {'revision': '', 'notes': []}
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or not isinstance(data['notes'], list) or not isinstance(data['revision'], str):
                raise ValueError()
            return data
        except (ValueError, KeyError, OSError) as error:
            raise AppError('Notes could not be read. Restore the notes file from a backup.') from error

    def save(self, payload):
        data = self.read()
        if payload.get('revision') != data['revision']:
            raise AppError('Notes changed in another window. Reload notes before saving.')
        action = payload.get('action')
        note = next((n for n in data['notes'] if n['id'] == payload.get('id')), None)
        if action == 'create':
            if len(data['notes']) >= 500:
                raise AppError('You can save up to 500 notes.')
            note = {'id': uuid.uuid4().hex, 'sticky': False, 'x': .7, 'y': .15, 'created': now()}
        elif note is None:
            raise AppError('This note no longer exists. Reload notes.')
        if action in ('create', 'edit'):
            text = payload.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                raise AppError('Write a note of 1–2000 characters.')
            note['text'] = text.strip()
        elif action == 'sticky':
            if type(payload.get('sticky')) is not bool:
                raise AppError('Choose whether to show this sticky note.')
            note['sticky'] = payload['sticky']
        elif action == 'move':
            for key in ('x', 'y'):
                value = payload.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise AppError('Choose a position inside the screen.')
                note[key] = value
        elif action != 'delete':
            raise AppError('Choose a valid note action.')
        if action == 'create':
            data['notes'].insert(0, note)
        if action == 'delete':
            data['notes'].remove(note)
        data['revision'] = uuid.uuid4().hex
        atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2).encode())
        return data

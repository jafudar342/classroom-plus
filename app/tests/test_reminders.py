import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reminders import Reminders
from engine import AppError


class ReminderTests(unittest.TestCase):
    def test_persist_edit_complete_reopen_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Reminders(Path(folder))
            data = store.save(dict(action='create', text='Lecture', due='2026-11-16T10:00:00+05:30', revision=''))
            item = data['reminders'][0]
            self.assertEqual(item['due'], '2026-11-16T04:30:00+00:00')
            for payload in [dict(action='edit',text='Prepare lecture',due='2026-11-17T10:00:00Z'),dict(action='complete',completed=True),dict(action='complete',completed=False)]:
                data = store.save(dict(payload, id=item['id'], revision=data['revision']))
            self.assertEqual(Reminders(Path(folder)).read()['reminders'][0]['text'], 'Prepare lecture')
            self.assertFalse(data['reminders'][0]['completed'])
            self.assertEqual(store.save(dict(action='delete',id=item['id'],revision=data['revision']))['reminders'], [])

    def test_invalid_and_stale_changes_preserve_file(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Reminders(Path(folder))
            data = store.save(dict(action='create', text='Keep', due='2026-11-16T10:00:00Z', revision=''))
            original = store.path.read_bytes()
            for payload in [dict(action='create',text='Stale',due='2026-11-16T10:00:00Z',revision=''),dict(action='edit',text=' ',due='invalid'),dict(action='edit',text='Invalid',due='2026-11-16T10:00:00'),dict(action='complete',completed='true')]:
                request=dict(id=data['reminders'][0]['id'],revision=data['revision']);request.update(payload)
                with self.assertRaises(AppError):store.save(request)
                self.assertEqual(store.path.read_bytes(), original)
            store.path.write_text('{broken')
            with self.assertRaises(AppError):store.read()

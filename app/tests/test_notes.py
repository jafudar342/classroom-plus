import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notes import Notes
from engine import AppError


class NotesTests(unittest.TestCase):
    def test_saved_notes_hide_move_edit_and_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Notes(Path(folder))
            data = store.save(dict(action='create', text='First note', revision=''))
            identifier = data['notes'][0]['id']
            for action in [dict(action='sticky', sticky=True), dict(action='move', x=.2, y=.4), dict(action='edit', text='Changed'), dict(action='sticky', sticky=False)]:
                data = store.save(dict(action, id=identifier, revision=data['revision']))
            saved = Notes(Path(folder)).read()['notes'][0]
            self.assertEqual((saved['text'], saved['sticky'], saved['x'], saved['y']), ('Changed', False, .2, .4))
            self.assertEqual(store.save(dict(action='delete', id=identifier, revision=data['revision']))['notes'], [])

    def test_invalid_and_stale_writes_preserve_notes(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Notes(Path(folder))
            data = store.save(dict(action='create', text='Keep', revision=''))
            original = store.path.read_bytes()
            for payload in [dict(action='create', text='stale', revision=''), dict(action='create', text=' ', revision=data['revision']), dict(action='move', id=data['notes'][0]['id'], x=float('nan'), y=0, revision=data['revision'])]:
                with self.assertRaises(AppError): store.save(payload)
                self.assertEqual(store.path.read_bytes(), original)
            store.path.write_text('{broken')
            with self.assertRaises(AppError): store.read()

"""Run with the project's start-app.sh. Serves only on localhost."""
import asyncio
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tornado.httpserver
import tornado.ioloop
import tornado.web
from PIL import Image, ImageOps
import numpy as np

from engine import AppError, Engine, decode_image, image_bytes
from lectures import LectureStore
from timetable import Timetable
from app_settings import AppSettings
from video_attendance import VideoAttendance
from analytics import Analytics
from evaluation import Evaluation
from file_cache import FileCache
from notes import Notes
from reminders import Reminders

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent / "web"
POOL = ThreadPoolExecutor(max_workers=1)
READ_POOL = ThreadPoolExecutor(max_workers=2)
THUMBNAILS = {160: FileCache(128), 640: FileCache(32)}


def thumbnail(path, size):
    def render():
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((size, size))
            return image_bytes(np.array(image))
    return THUMBNAILS[size].get((path,), render)


class Base(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Referrer-Policy", "same-origin")
        self.set_header("Cache-Control", "no-store")
        self.set_header("Permissions-Policy", "camera=(self), microphone=()")
        self.set_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

    def prepare(self):
        if self.request.host_name not in {"localhost", "127.0.0.1", "::1"}:
            raise tornado.web.HTTPError(403, reason="Open the app using localhost.")
        if self.request.method == "POST" and not self.request.headers.get("Content-Type", "").startswith("application/json"):
            raise tornado.web.HTTPError(415, reason="Expected a JSON request.")

    def write_error(self, status_code, **kwargs):
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps({"error": self._reason if status_code < 500 else "The request could not be completed. Check the app terminal for details."}))

    def json_body(self):
        try:
            value = json.loads(self.request.body)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError as error:
            raise tornado.web.HTTPError(400, reason="Invalid request data.") from error

    def capture_options(self, payload):
        for option in ("eye_search", "extra_detection"):
            if type(payload.get(option, False)) is not bool:
                raise tornado.web.HTTPError(400, reason="Detection options must be true or false.")

    async def job(self, function, *args):
        if self.application.busy:
            self.set_status(409)
            self.finish({"error": "A photo is being processed. Please wait for it to finish."})
            return
        self.application.busy = True
        try:
            result = await asyncio.get_running_loop().run_in_executor(POOL, function, *args)
            self.write(result)
        except AppError as error:
            self.set_status(422)
            self.write({"error": str(error), "code": error.code})
        except Exception:
            logging.exception("App request failed")
            self.set_status(500)
            self.write({"error": "Processing failed. Check the terminal for details, then try another photo."})
        finally:
            self.application.busy = False


class RemindersAction(Base):
    async def get(self):
        await self.job(self.application.reminders.read)

    async def post(self):
        await self.job(self.application.reminders.save, self.json_body())


class NotesAction(Base):
    async def get(self):
        await self.job(self.application.notes.read)

    async def post(self):
        await self.job(self.application.notes.save, self.json_body())


class Index(Base):
    def get(self):
        _ = self.xsrf_token
        self.set_header("Content-Type", "text/html; charset=utf-8")
        html = (WEB / "index.html").read_text()
        for asset in ("style.css", "themes.css", "oled.css", "color-spinner.css", "color-spinner.mjs", "sudoku.css", "sudoku.mjs", "about.css", "timetable.css", "timetable.js", "settings.css", "settings.js", "app.js", "theme.js", "chess-egg.js", "dashboard.js", "clock.js", "evaluation.js", "video-attendance.js", "session-studio.js"):
            html = html.replace(f'/static/{asset}"', f'/static/{asset}?v={(WEB / asset).stat().st_mtime_ns}"')
        self.write(html)


class State(Base):
    async def get(self):
        if self.application.busy:
            self.set_status(409)
            self.write({"error": "Processing is in progress. Please wait."})
            return
        token = self.xsrf_token.decode()
        def read():
            state = self.application.engine.state()
            state['lectures'] = self.application.lectures.list()
            state['xsrf'] = token
            return state
        await self.job(read)


class Session(Base):
    def get(self):
        # Independent of model jobs: a stale browser tab can refresh its token.
        self.write({"xsrf": self.xsrf_token.decode()})


class Recognize(Base):
    async def post(self):
        payload = self.json_body()
        self.capture_options(payload)
        if (type(payload.get("save", True)) is not bool
                or payload.get("source", "upload") not in ("upload", "webcam", "camera")):
            raise tornado.web.HTTPError(400, reason="Choose a valid image source and save option.")
        try:
            rgb = decode_image(payload.get("image"))
        except AppError as error:
            self.set_status(422)
            self.write({"error": str(error)})
            return
        await self.job(self.application.engine.recognize, rgb, payload.get("save", True) is True,
                       "webcam" if payload.get("source") in {"webcam", "camera"} else "upload",
                       payload.get("class_id"), payload.get("subject_id"), None, payload.get("extra_detection") is True, payload.get("eye_search") is True)


class Preview(Base):
    async def post(self):
        try:
            rgb = decode_image(self.json_body().get("image"))
        except AppError as error:
            self.set_status(422)
            self.write({"error": str(error)})
            return
        await self.job(self.application.engine.preview_registration, rgb)


class RosterRegistration(Base):
    async def post(self):
        await self.job(self.application.engine.register_without_photo, self.json_body())


class Register(Base):
    async def post(self):
        await self.job(self.application.engine.register, self.json_body())


class ClassSave(Base):
    async def post(self):
        await self.job(self.application.engine.save_class, self.json_body())


class SubjectSave(Base):
    async def post(self):
        await self.job(self.application.engine.save_subject, self.json_body())


class StudentInfo(Base):
    async def get(self, roll):
        await self.job(self.application.engine.student_detail, roll)


class StudentUpdate(Base):
    async def post(self, roll):
        await self.job(self.application.engine.update_student, roll, self.json_body())


class StudentDelete(Base):
    async def post(self, roll):
        await self.job(self.application.engine.delete_student, roll, self.json_body())


class StudentRestore(Base):
    async def post(self):
        await self.job(self.application.engine.restore_student, self.json_body().get("archive_id"))


class ReferencePhoto(Base):
    async def get(self, roll, filename):
        if (not re.fullmatch(r"[0-9]{1,12}", roll) or Path(filename).name != filename
                or Path(filename).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}):
            raise tornado.web.HTTPError(404)
        path = self.application.engine.root / "data/reference" / roll / filename
        if not path.is_file():
            raise tornado.web.HTTPError(404)
        try:
            raw = await asyncio.get_running_loop().run_in_executor(READ_POOL, thumbnail, path, 640)
        except (OSError, ValueError):
            raise tornado.web.HTTPError(404)
        self.set_header('Content-Type', 'image/jpeg')
        self.write(raw)


class Photo(Base):
    async def get(self, roll):
        if not re.fullmatch(r"[0-9]{1,12}", roll):
            raise tornado.web.HTTPError(404)
        files = sorted((self.application.engine.root / "data/reference" / roll).glob("*"),
                       key=lambda path: (path.name.startswith("app_"), path.stat().st_mtime), reverse=True)
        photo = next((path for path in files if path.suffix.lower() in {".jpg", ".jpeg", ".webp", ".png"}), None)
        if photo is None:
            raise tornado.web.HTTPError(404)
        try:
            raw = await asyncio.get_running_loop().run_in_executor(READ_POOL, thumbnail, photo, 160)
        except (OSError, ValueError):
            raise tornado.web.HTTPError(404)
        self.set_header("Content-Type", "image/jpeg")
        self.write(raw)


class Sample(Base):
    def get(self):
        photo = self.application.engine.root / "data/classroom/synthetic_classroom.png"
        if not photo.exists():
            raise tornado.web.HTTPError(404)
        self.set_header("Content-Type", "image/png")
        self.write(photo.read_bytes())


class Report(Base):
    def get(self, run_id, filename):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id) or filename not in {"annotated.jpg", "attendance.csv", "detections.csv", "result.json"}:
            raise tornado.web.HTTPError(404)
        file = self.application.engine.root / "results/app" / run_id / filename
        if not file.is_file():
            raise tornado.web.HTTPError(404)
        if filename == "result.json":
            self.set_header("Content-Type", "application/json")
        elif filename.endswith(".csv"):
            self.set_header("Content-Type", "text/csv; charset=utf-8")
            self.set_header("Content-Disposition", f'attachment; filename="{run_id[:8]}-{filename}"')
        else:
            self.set_header("Content-Type", "image/jpeg")
        self.write(file.read_bytes())


class LectureCreate(Base):
    async def post(self):
        await self.job(self.application.lectures.create, self.json_body())


class LectureAction(Base):
    async def get(self, identifier, action=None):
        try:
            store = self.application.lectures
            if action in ('attendance.csv', 'audit.csv'):
                content = store.export(identifier, action.split('.')[0])
                self.set_header('Content-Type', 'text/csv; charset=utf-8')
                self.set_header('Content-Disposition', f'attachment; filename="lecture-{identifier[:8]}-{action}"')
                self.write(content)
            elif action is None:
                self.write(store.view(store.load(identifier)))
            else:
                raise tornado.web.HTTPError(405)
        except AppError as error:
            self.set_status(422)
            self.set_header('Content-Type', 'application/json')
            self.write({'error': str(error)})

    async def post(self, identifier, action=None):
        payload = self.json_body()
        store = self.application.lectures
        if action == 'capture':
            self.capture_options(payload)
            try:
                rgb = decode_image(payload.get('image'))
            except AppError as error:
                self.set_status(422)
                self.write({'error': str(error)})
                return
            await self.job(store.capture, identifier, payload, rgb)
        elif action in ('attendance', 'face', 'finalize'):
            await self.job({'attendance': store.correct, 'face': store.resolve, 'finalize': store.finalize}[action], identifier, payload)
        else:
            raise tornado.web.HTTPError(404)


class VideoAction(Base):
    async def post(self, identifier, scan_id=None, action='start'):
        payload = self.json_body()
        video = self.application.video
        if action == 'start':
            await self.job(video.start, identifier, payload)
        elif action == 'frame':
            try: rgb = decode_image(payload.get('image'))
            except AppError as error:
                self.set_status(422)
                self.write({'error': str(error)})
                return
            await self.job(video.frame, identifier, scan_id, payload, rgb)
        else:
            await self.job({'stop': video.stop, 'review': video.review}[action], identifier, scan_id, payload)

class VideoPhoto(Base):
    def get(self, identifier, scan_id, track_id):
        try:
            self.set_header('Content-Type', 'image/jpeg')
            self.write(self.application.video.photo(identifier, scan_id, track_id))
        except AppError:
            raise tornado.web.HTTPError(404)


class LectureMedia(Base):
    async def get(self, identifier, capture_id, face_id=None):
        try:
            self.set_header('Content-Type', 'image/jpeg')
            self.write(self.application.lectures.media(identifier, capture_id, face_id))
        except AppError:
            raise tornado.web.HTTPError(404)


class SettingsStatus(Base):
    def get(self):
        self.write(self.application.app_settings.status)


class SettingsAction(Base):
    def get(self):
        if self.application.busy:
            self.set_status(409)
            self.write({'error':'Wait for the current task to finish, then reload Settings.'})
            return
        try:self.write(self.application.app_settings.view())
        except AppError as error:
            self.set_status(422)
            self.write({'error':str(error)})

    async def post(self):
        await self.job(self.application.app_settings.save,self.json_body())


class TimetableAction(Base):
    def get(self):
        try:
            self.write(self.application.timetable.catalog(self.get_query_argument('date','')))
        except AppError as error:
            self.set_status(422)
            self.write({'error':str(error)})

    async def post(self):
        await self.job(self.application.timetable.save,self.json_body())


class TimetableStart(Base):
    async def post(self):
        await self.job(self.application.timetable.start,self.json_body())


class Dashboard(Base):
    async def get(self, export=None):
        try:
            args = [self.get_query_argument(key, '') for key in ('month','class_id','subject_id')]
            if export:
                content = await asyncio.get_running_loop().run_in_executor(READ_POOL, self.application.analytics.export, *args)
                self.set_header('Content-Type', 'text/csv; charset=utf-8')
                self.set_header('Content-Disposition', 'attachment; filename="classroom-monthly-attendance.csv"')
                self.write(content)
            else:
                self.write(await asyncio.get_running_loop().run_in_executor(READ_POOL, self.application.analytics.report, *args))
        except AppError as error:
            self.set_status(422)
            self.write({'error': str(error)})

    async def post(self, export=None):
        if export:
            raise tornado.web.HTTPError(405)
        await self.job(self.application.analytics.save_target, self.json_body())


class EvaluationCatalog(Base):
    def get(self):
        self.write(self.application.evaluation.catalog())

    async def post(self):
        payload = self.json_body()
        try:
            rgb = decode_image(payload.get('image'))
        except AppError as error:
            self.set_status(422)
            self.write({'error': str(error)})
            return
        await self.job(self.application.evaluation.add, payload, rgb)


class EvaluationPhoto(Base):
    async def get(self, identifier, action=None):
        try:
            store = self.application.evaluation
            record = store.read('photos', identifier)
            if action == 'image':
                self.set_header('Content-Type', 'image/png')
                self.write(store.path('photos',identifier,'image.png').read_bytes())
            elif action is None:
                self.write(record)
            else:
                raise tornado.web.HTTPError(405)
        except (AppError, OSError):
            raise tornado.web.HTTPError(404)

    async def post(self, identifier, action=None):
        if action != 'labels':
            raise tornado.web.HTTPError(405)
        await self.job(self.application.evaluation.relabel, identifier, self.json_body())


class EvaluationRun(Base):
    def get(self, identifier=None):
        try:
            store = self.application.evaluation
            record = store.read('runs',identifier)
            defaults = [record['settings'].get('cosine_distance_threshold', .3), record['settings'].get('minimum_gap', .05), .7]
            values = [float(self.get_query_argument(key,str(value))) for key,value in zip(('distance','gap','eye'), defaults)]
            self.write(store.view(record,*values))
        except (AppError,ValueError) as error:
            self.set_status(422)
            self.write({'error': str(error)})

    async def post(self, identifier=None):
        if identifier:
            raise tornado.web.HTTPError(405)
        await self.job(self.application.evaluation.run, self.json_body())


def make_app(root=ROOT):
    application = tornado.web.Application([
        (r"/api/reminders", RemindersAction),
        (r"/", Index), (r"/api/notes", NotesAction), (r"/api/state", State), (r"/api/session", Session), (r"/api/recognize", Recognize),
        (r"/api/register/preview", Preview), (r"/api/register", Register), (r"/api/register/roster", RosterRegistration),
        (r"/api/dashboard(?:/(monthly.csv))?", Dashboard),
        (r"/api/evaluation", EvaluationCatalog),
        (r"/api/evaluation/photos/([a-f0-9]{32})(?:/(image|labels))?", EvaluationPhoto),
        (r"/api/evaluation/runs(?:/([a-f0-9]{32}))?", EvaluationRun),
        (r"/api/lectures/create", LectureCreate),
        (r"/api/timetable", TimetableAction),
        (r"/api/settings", SettingsAction),
        (r"/api/settings/status", SettingsStatus),
        (r"/api/timetable/start", TimetableStart),
        (r"/api/lectures/([a-f0-9]{32})/video/start", VideoAction),
        (r"/api/lectures/([a-f0-9]{32})/video/([a-f0-9]{32})/(frame|stop|review)", VideoAction),
        (r"/api/lectures/([a-f0-9]{32})/video/([a-f0-9]{32})/tracks/([0-9]+)/photo", VideoPhoto),
        (r"/api/lectures/([a-f0-9]{32})/captures/([a-f0-9]{32})/image", LectureMedia),
        (r"/api/lectures/([a-f0-9]{32})/captures/([a-f0-9]{32})/faces/([0-9]+)", LectureMedia),
        (r"/api/lectures/([a-f0-9]{32})(?:/(capture|attendance|face|finalize|attendance\.csv|audit\.csv))?", LectureAction),
        (r"/api/classes/save", ClassSave), (r"/api/subjects/save", SubjectSave),
        (r"/api/students/restore", StudentRestore),
        (r"/api/students/([^/]+)/update", StudentUpdate),
        (r"/api/students/([^/]+)/delete", StudentDelete),
        (r"/api/students/([^/]+)/photos/([^/]+)", ReferencePhoto),
        (r"/api/students/([^/]+)/photo", Photo), (r"/api/sample", Sample),
        (r"/api/students/([^/]+)", StudentInfo),
        (r"/api/reports/([^/]+)/([^/]+)", Report),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": str(WEB)}),
    ], xsrf_cookies=True, xsrf_cookie_name="classroom_attendance_xsrf",
       xsrf_cookie_kwargs={"samesite": "Strict"}, debug=False,
       cookie_secret=__import__("secrets").token_hex(32))
    application.engine = Engine(root)
    application.notes = Notes(Path(root))
    application.reminders = Reminders(Path(root))
    application.lectures = LectureStore(Path(root), application.engine)
    application.video = VideoAttendance(application.lectures)
    application.timetable = Timetable(Path(root), application.engine, application.lectures)
    application.analytics = Analytics(Path(root), application.lectures)
    application.app_settings = AppSettings(Path(root), application.engine, application.lectures, application.analytics)
    application.evaluation = Evaluation(Path(root), application.engine)
    application.busy = False
    return application


def run(root=ROOT, port=8765, open_browser=False):
    import webbrowser
    from workspace import InstanceLock
    root = Path(root)
    (root / 'work').mkdir(parents=True, exist_ok=True)
    lock = InstanceLock(root / 'work/app.lock')
    try:
        application = make_app(root)
        server = tornado.httpserver.HTTPServer(application, max_buffer_size=24_000_000)
        server.listen(port, address='127.0.0.1')
        print(f'Classroom+ ready: http://localhost:{port}', flush=True)
        print('Keep this window open. Press Ctrl+C to stop.', flush=True)
        loop = tornado.ioloop.IOLoop.current()
        if open_browser:
            loop.call_later(.5, webbrowser.open, f'http://localhost:{port}')
        try:
            loop.start()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
    finally:
        lock.close()
    return 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try:
        run(ROOT, args.port)
    except (RuntimeError, OSError) as error:
        parser.exit(1, str(error) + '\n')

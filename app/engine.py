"""Local attendance pipeline; compatible with the existing notebook templates."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from file_cache import FileCache
from registration_quality import reference_quality


class AppError(Exception):
    def __init__(self, message, code="invalid_request"):
        super().__init__(message)
        self.code = code


def now():
    return datetime.now(timezone.utc).isoformat()


def image_bytes(rgb, format="JPEG"):
    buffer = io.BytesIO()
    Image.fromarray(np.asarray(rgb, dtype=np.uint8)).save(buffer, format=format)
    return buffer.getvalue()


def image_url(rgb):
    return "data:image/jpeg;base64," + base64.b64encode(image_bytes(rgb)).decode()


def decode_image(value):
    if not isinstance(value, str) or len(value) > 22_000_000:
        raise AppError("Choose an image smaller than 15 MB.")
    try:
        raw = base64.b64decode(value.split(",", 1)[-1], validate=True)
        if len(raw) > 15_000_000:
            raise AppError("Choose an image smaller than 15 MB.")
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 24_000_000:
                raise AppError("Choose an image with at most 24 million pixels.")
            return np.array(ImageOps.exif_transpose(image).convert("RGB"))
    except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise AppError("This image could not be opened. Try a JPEG, PNG, or WebP photo.") from error


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def csv_bytes(rows, columns):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # Spreadsheet programs must treat student-supplied names as text.
        writer.writerow({key: ("'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value) for key, value in row.items()})
    return output.getvalue().encode("utf-8-sig")


class Engine:
    def __init__(self, root):
        self.root = Path(root)
        os.environ["DEEPFACE_HOME"] = str(self.root / "models")
        os.environ.setdefault("DEEPFACE_BACKEND_ENGINE", "onnx")
        self.previews = {}
        self.eye_patch_cache = {}
        self._registry_cache = FileCache(1)
        self._history_cache = FileCache(512)
        self.settings = json.loads((self.root / "config/demo_matching_settings.json").read_text())
        self.metadata = json.loads((self.root / "embeddings/metadata.json").read_text())
        if self.metadata["model"] != self.settings["model"] or self.metadata["input_normalization"] != self.settings["normalization"]:
            raise AppError("Saved model settings disagree. Restore matching metadata before starting.")

    def registry(self):
        return self._registry_cache.get((self.root / 'data/roster.csv', self.root / 'embeddings/student_templates.npz'), self._read_registry)

    def _read_registry(self):
        with (self.root / "data/roster.csv").open(newline="", encoding="utf-8-sig") as file:
            roster = list(csv.DictReader(file))
        with np.load(self.root / "embeddings/student_templates.npz", allow_pickle=False) as saved:
            vectors = saved["embeddings"].copy()
            rolls = saved["roll_numbers"].astype(str)
            names = saved["names"].astype(str)
            sums = saved["embedding_sums"].copy() if "embedding_sums" in saved else vectors.copy()
            counts = saved["reference_counts"].copy() if "reference_counts" in saved else np.ones(len(rolls), dtype=int)
        if (rolls.ndim != 1 or names.shape != rolls.shape or counts.shape != rolls.shape
                or vectors.shape != (len(rolls), 512) or sums.shape != vectors.shape
                or len(set(rolls)) != len(rolls) or not np.isfinite(vectors).all()
                or not np.isfinite(sums).all() or not np.issubdtype(counts.dtype, np.integer)
                or (counts < 1).any()):
            raise AppError("The saved embedding database needs repair.")
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
            raise AppError("Saved embeddings must be L2-normalized.")
        lengths = np.linalg.norm(sums, axis=1)
        if (lengths <= 0).any() or not np.allclose(sums / lengths[:, None], vectors, atol=1e-4):
            raise AppError("Saved reference sums disagree with the student templates. Restore a registry backup.")
        roster_rolls = [row.get("roll_number") for row in roster]
        if (len(set(roster_rolls)) != len(roster_rolls)
                or any(not isinstance(roll, str) or not re.fullmatch(r"[0-9]{1,12}", roll) for roll in roster_rolls)
                or any(not isinstance(row.get("name"), str) or not row["name"].strip() for row in roster)
                or not set(rolls).issubset(roster_rolls)):
            raise AppError("The roster contains duplicate, invalid, or missing student entries. Restore a registry backup.")
        roster_names = {row["roll_number"]: row["name"] for row in roster}
        if any(roster_names[roll].casefold() != name.casefold() for roll, name in zip(rolls, names)):
            raise AppError("Template labels disagree with the roster. Restore a registry backup.")
        names = np.asarray([roster_names[roll] for roll in rolls], dtype=str)
        return roster, vectors, rolls, names, sums, counts

    def state(self):
        roster, _, rolls, _, _, counts = self.registry()
        counts_by_roll = dict(zip(rolls.tolist(), counts.tolist()))
        history = self.history(limit=None)
        profiles = self.profiles()
        academics = self.academics()
        return {
            "students": [{**profiles.get(student["roll_number"], {}), **student, "registered": student["roll_number"] in counts_by_roll,
                          "references": counts_by_roll.get(student["roll_number"], 0)} for student in roster],
            "settings": self.settings,
            "model": self.metadata["model"],
            "sample_available": (self.root / "data/classroom/synthetic_classroom.png").exists(),
            "history": history[:100],
            "session_count": len(history),
            "archived_students": self.archived_students(),
            "academics": academics,
        }

    def academics(self):
        path = self.root / "data/academics.json"
        if not path.exists():
            return {"classes": [], "subjects": [], "revision": ""}
        try:
            data = json.loads(path.read_text())
            if (not isinstance(data, dict) or not isinstance(data.get("classes"), list)
                    or not isinstance(data.get("subjects"), list) or not isinstance(data.get("revision"), str)):
                raise ValueError()
            ids = set()
            for group in data["classes"]:
                if (not isinstance(group, dict) or not isinstance(group.get("id"), str)
                        or not re.fullmatch(r"[a-f0-9]{32}", group["id"]) or group["id"] in ids
                        or not isinstance(group.get("name"), str) or not group["name"].strip()
                        or not isinstance(group.get("student_rolls"), list)
                        or any(not isinstance(roll, str) or not re.fullmatch(r"[0-9]{1,12}", roll) for roll in group["student_rolls"])
                        or any(not isinstance(group.get(field, ""), str) for field in ("department", "semester", "section"))
                        or len(set(group["student_rolls"])) != len(group["student_rolls"])):
                    raise ValueError()
                ids.add(group["id"])
            subject_ids = set()
            for subject in data["subjects"]:
                if (not isinstance(subject, dict) or not isinstance(subject.get("id"), str)
                        or not re.fullmatch(r"[a-f0-9]{32}", subject["id"]) or subject["id"] in subject_ids
                        or subject.get("class_id") not in ids or not isinstance(subject.get("name"), str)
                        or any(not isinstance(subject.get(field, ""), str) for field in ("code", "teacher"))
                        or not subject["name"].strip()):
                    raise ValueError()
                subject_ids.add(subject["id"])
            return data
        except (ValueError, OSError, TypeError, KeyError) as error:
            raise AppError("Classes and subjects could not be read. Restore the academics backup before editing.") from error

    @staticmethod
    def _academic_text(payload, field, maximum=100, required=False):
        value = payload.get(field, "")
        if (not isinstance(value, str) or len(value.strip()) > maximum
                or any(ord(char) < 32 for char in value) or (required and not value.strip())):
            raise AppError(f"Enter a valid {field.replace('_', ' ')} (up to {maximum} characters).")
        return value.strip()

    def save_class(self, payload):
        data = self.academics()
        if payload.get("revision", "") != data["revision"]:
            raise AppError("Classes changed in another window. Refresh the workspace before saving.")
        group_id = payload.get("id")
        if group_id is not None and not isinstance(group_id, str):
            raise AppError("Choose a valid class to edit.")
        existing = next((group for group in data["classes"] if group["id"] == group_id), None)
        if group_id and not existing:
            raise AppError("Choose an existing class or create a new one.")
        name = self._academic_text(payload, "name", required=True)
        if any(group["name"].casefold() == name.casefold() and group["id"] != group_id for group in data["classes"]):
            raise AppError("A class with this name already exists. Use a distinct class or section name.")
        rolls = payload.get("student_rolls", [])
        if not isinstance(rolls, list) or any(not isinstance(roll, str) for roll in rolls) or len(set(rolls)) != len(rolls):
            raise AppError("Choose a valid student roster without duplicate entries.")
        roster = self.registry()[0]
        if not set(rolls).issubset({student["roll_number"] for student in roster}):
            raise AppError("Some selected students were removed or renamed. Refresh before enrolling them.")
        group = {"id": group_id or uuid.uuid4().hex, "name": name,
                 "department": self._academic_text(payload, "department"),
                 "semester": self._academic_text(payload, "semester", 30),
                 "section": self._academic_text(payload, "section", 30),
                 "student_rolls": sorted(rolls, key=lambda value: (int(value), value))}
        if existing:
            data["classes"][data["classes"].index(existing)] = group
        else:
            data["classes"].append(group)
        data["revision"] = now()
        self._commit_management({self.root / "data/academics.json": json.dumps(data, ensure_ascii=False, indent=2).encode()}, [],
                                {"action": "save_class", "class_id": group["id"]})
        return {"class": group, "academics": data}

    def save_subject(self, payload):
        data = self.academics()
        if payload.get("revision", "") != data["revision"]:
            raise AppError("Subjects changed in another window. Refresh the workspace before saving.")
        subject_id, class_id = payload.get("id"), payload.get("class_id")
        if (subject_id is not None and not isinstance(subject_id, str)) or not isinstance(class_id, str):
            raise AppError("Choose a valid class and subject.")
        group = next((group for group in data["classes"] if group["id"] == class_id), None)
        if not group:
            raise AppError("Create or choose a class before adding its subject.")
        existing = next((subject for subject in data["subjects"] if subject["id"] == subject_id), None)
        if subject_id and (not existing or existing["class_id"] != class_id):
            raise AppError("Edit this subject in its original class, or create a new subject.")
        name = self._academic_text(payload, "name", required=True)
        code = self._academic_text(payload, "code", 30)
        if any(subject["class_id"] == class_id and subject["id"] != subject_id
               and (subject["name"].casefold() == name.casefold()
                    or (code and subject.get("code", "").casefold() == code.casefold())) for subject in data["subjects"]):
            raise AppError("That subject name or code already exists in this class.")
        subject = {"id": subject_id or uuid.uuid4().hex, "class_id": class_id, "name": name,
                   "code": code, "teacher": self._academic_text(payload, "teacher")}
        if existing:
            data["subjects"][data["subjects"].index(existing)] = subject
        else:
            data["subjects"].append(subject)
        data["revision"] = now()
        self._commit_management({self.root / "data/academics.json": json.dumps(data, ensure_ascii=False, indent=2).encode()}, [],
                                {"action": "save_subject", "subject_id": subject["id"], "class_id": class_id})
        return {"subject": subject, "academics": data}

    def attendance_context(self, class_id=None, subject_id=None):
        if class_id in (None, "", "all-students"):
            if subject_id not in (None, ""):
                raise AppError("Choose the subject's class before checking attendance.")
            return {"class_id": "all-students", "class_name": "All students", "subject_id": "",
                    "subject_name": "General attendance", "subject_code": ""}, None
        data = self.academics()
        group = next((group for group in data["classes"] if group["id"] == class_id), None)
        if not group:
            raise AppError("This class is no longer available. Refresh the workspace.")
        subject = next((subject for subject in data["subjects"] if subject["id"] == subject_id and subject["class_id"] == class_id), None)
        if not subject:
            raise AppError("Choose a subject belonging to the selected class before checking attendance.")
        return {"class_id": group["id"], "class_name": group["name"], "subject_id": subject["id"],
                "subject_name": subject["name"], "subject_code": subject.get("code", "")}, set(group["student_rolls"])

    def profiles(self):
        path = self.root / "data/student_profiles.json"
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or any(not isinstance(item, dict) for item in value.values()):
                raise ValueError()
            return value
        except (ValueError, OSError) as error:
            raise AppError("Student details could not be read. Restore the profiles backup before editing.") from error

    def student_identity(self, roll, name, profiles=None):
        profiles = self.profiles() if profiles is None else profiles
        # Legacy registrations acquire a durable identity before they are edited.
        # A new registration reusing a deleted roll gets a fresh identity instead.
        return profiles.get(roll, {}).get("identity_id") or uuid.uuid5(
            uuid.NAMESPACE_URL, f"classroom-plus/legacy-student/{roll}/{name}").hex

    @staticmethod
    def valid_roll(roll):
        if not isinstance(roll, str) or not re.fullmatch(r"[0-9]{1,12}", roll):
            raise AppError("Use a numeric roll number of up to 12 digits.")
        return roll

    def student_detail(self, roll):
        self.valid_roll(roll)
        state = self.state()
        student = next((item for item in state["students"] if item["roll_number"] == roll), None)
        if not student:
            raise AppError("This student is no longer in the directory. Refresh the workspace.")
        student["photos"] = [{"filename": path.name} for path in sorted((self.root / "data/reference" / roll).glob("*"))
                             if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        student["revision"] = self.profiles().get(roll, {}).get("updated_utc", "")
        return student

    def selections(self):
        path = self.root / "config/reference_face_selections.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def _entries(self):
        roster, vectors, rolls, names, sums, counts = self.registry()
        return roster, {str(r): {"name": str(n), "vector": v, "sum": s, "count": int(c)}
                        for r, n, v, s, c in zip(rolls, names, vectors, sums, counts)}

    def _management_files(self, roster, entries, profiles, selections, academics=None):
        ordered = sorted(entries, key=lambda roll: (int(roll), roll))
        roster.sort(key=lambda row: (int(row["roll_number"]), row["roll_number"]))
        buffer = io.BytesIO()
        np.savez_compressed(buffer,
            embeddings=np.stack([entries[r]["vector"] for r in ordered]) if ordered else np.empty((0, 512), dtype=np.float32),
            roll_numbers=np.asarray(ordered, dtype=str), names=np.asarray([entries[r]["name"] for r in ordered], dtype=str),
            embedding_sums=np.stack([entries[r]["sum"] for r in ordered]) if ordered else np.empty((0, 512), dtype=np.float32),
            reference_counts=np.asarray([entries[r]["count"] for r in ordered], dtype=int))
        metadata = dict(self.metadata, registered_students=len(ordered), updated_utc=now())
        files = {
            self.root / "data/roster.csv": self._roster_bytes(roster),
            self.root / "embeddings/student_templates.npz": buffer.getvalue(),
            self.root / "embeddings/metadata.json": json.dumps(metadata, indent=2).encode(),
            self.root / "data/student_profiles.json": json.dumps(profiles, ensure_ascii=False, indent=2).encode(),
            self.root / "config/reference_face_selections.json": json.dumps(selections, indent=2).encode(),
            self.root / "data/academics.json": json.dumps(academics if academics is not None else self.academics(), ensure_ascii=False, indent=2).encode(),
        }
        return files, metadata

    def _commit_management(self, files, moves, audit):
        operation_id = uuid.uuid4().hex
        backup = self.root / "work/app-backups" / f"manage_{operation_id}"
        backup.mkdir(parents=True)
        originals = {path: path.read_bytes() if path.exists() else None for path in files}
        for path, content in originals.items():
            if content is not None:
                (backup / path.name).write_bytes(content)
        completed_moves = []
        try:
            for source, destination in moves:
                if destination.exists():
                    raise AppError("The destination photo folder already exists. Choose another roll number.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.rename(destination)
                completed_moves.append((source, destination))
            for path, content in files.items():
                atomic_write(path, content)
            atomic_write(self.root / "logs/student-management" / f"{operation_id}.json",
                         json.dumps({**audit, "created_utc": now(), "backup": str(backup.relative_to(self.root))}, indent=2).encode())
        except Exception:
            for path, content in originals.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, content)
            for source, destination in reversed(completed_moves):
                destination.rename(source)
            raise

    def update_student(self, roll, payload):
        self.valid_roll(roll)
        new_roll = self.valid_roll(payload.get("roll_number"))
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100 or any(ord(ch) < 32 for ch in name):
            raise AppError("Enter a student name of 1 to 100 characters.")
        name = name.strip()
        roster, entries = self._entries()
        existing = next((row for row in roster if row["roll_number"] == roll), None)
        if not existing:
            raise AppError("This student was removed. Refresh the directory.")
        if new_roll != roll and (any(row["roll_number"] == new_roll for row in roster)
                                 or (self.root / "data/reference" / new_roll).exists()):
            raise AppError("That roll number or photo folder already exists. Choose a different roll number.")
        profiles = self.profiles()
        if payload.get("revision", "") != profiles.get(roll, {}).get("updated_utc", ""):
            raise AppError("This profile changed in another window. Close it and reopen before editing.")
        details = {}
        for field, maximum in {"department": 100, "course": 100, "semester": 30, "section": 30,
                               "email": 200, "phone": 40, "notes": 2000}.items():
            value = payload.get(field, "")
            if not isinstance(value, str) or len(value.strip()) > maximum or "\x00" in value:
                raise AppError(f"Enter valid {field} details (up to {maximum} characters).")
            details[field] = value.strip()
        if details["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", details["email"]):
            raise AppError("Enter a valid email address or leave it blank.")
        custom = payload.get("custom_fields", [])
        if not isinstance(custom, list) or len(custom) > 20:
            raise AppError("Add at most 20 custom fields.")
        details["custom_fields"] = []
        labels = set()
        for field in custom:
            if not isinstance(field, dict) or not isinstance(field.get("label"), str) or not isinstance(field.get("value"), str):
                raise AppError("Each custom field needs a label and a value.")
            label, value = field["label"].strip(), field["value"].strip()
            if not label or len(label) > 60 or len(value) > 500 or label.casefold() in labels or "\x00" in label + value:
                raise AppError("Use unique custom-field labels of up to 60 characters and values of up to 500 characters.")
            labels.add(label.casefold())
            details["custom_fields"].append({"label": label, "value": value})
        details["updated_utc"] = now()
        details["identity_id"] = self.student_identity(roll, existing["name"], profiles)
        profiles.pop(roll, None)
        profiles[new_roll] = details
        existing.update(roll_number=new_roll, name=name)
        if roll in entries:
            entry = entries.pop(roll)
            entry["name"] = name
            entries[new_roll] = entry
        selections = self.selections()
        if roll in selections and new_roll != roll:
            selection = selections.pop(roll)
            selection["photo"] = selection["photo"].replace(f"data/reference/{roll}/", f"data/reference/{new_roll}/", 1)
            selections[new_roll] = selection
        if new_roll in selections:
            selections[new_roll]["name"] = name
        academics = self.academics()
        if new_roll != roll:
            for group in academics["classes"]:
                if roll in group["student_rolls"]:
                    group["student_rolls"] = [new_roll if member == roll else member for member in group["student_rolls"]]
                    academics["revision"] = now()
        files, metadata = self._management_files(roster, entries, profiles, selections, academics)
        old_folder = self.root / "data/reference" / roll
        moves = [(old_folder, self.root / "data/reference" / new_roll)] if new_roll != roll and old_folder.exists() else []
        self._commit_management(files, moves, {"action": "edit", "old_roll": roll, "roll_number": new_roll})
        self.metadata = metadata
        return self.student_detail(new_roll)

    def archived_students(self):
        records = []
        for path in (self.root / "data/student_archive").glob("*/manifest.json"):
            try:
                item = json.loads(path.read_text())
                if not re.fullmatch(r"[a-f0-9]{32}", path.parent.name) or item.get("restored_utc"):
                    continue
                records.append({"archive_id": path.parent.name, "roll_number": item["student"]["roll_number"],
                                "name": item["student"]["name"], "deleted_utc": item["deleted_utc"]})
            except (ValueError, KeyError, TypeError, OSError):
                continue
        return sorted(records, key=lambda row: row["deleted_utc"], reverse=True)

    def delete_student(self, roll, payload):
        self.valid_roll(roll)
        if payload.get("confirmation") != roll:
            raise AppError("Type the student's roll number to confirm deletion.")
        roster, entries = self._entries()
        student = next((row for row in roster if row["roll_number"] == roll), None)
        if not student:
            raise AppError("This student is already removed. Refresh the directory.")
        profiles = self.profiles()
        if payload.get("revision", "") != profiles.get(roll, {}).get("updated_utc", ""):
            raise AppError("This profile changed. Reopen it before deleting.")
        selections = self.selections()
        entry = entries.pop(roll, None)
        archive_id = uuid.uuid4().hex
        archive = self.root / "data/student_archive" / archive_id
        old_profile = dict(profiles.get(roll, {}), identity_id=self.student_identity(roll, student["name"], profiles))
        profiles.pop(roll, None)
        manifest = {"student": student, "profile": old_profile,
                    "embedding_model": self.settings["model"], "input_normalization": self.settings["normalization"],
                    "reference_detector": self.metadata.get("reference_detector", self.metadata.get("detector", "retinaface")),
                    "selection": selections.pop(roll, None), "deleted_utc": now(),
                    "embedding": None if entry is None else {"name": entry["name"], "count": entry["count"],
                                 "vector": entry["vector"].tolist(), "sum": entry["sum"].tolist()}}
        academics = self.academics()
        manifest["class_ids"] = [group["id"] for group in academics["classes"] if roll in group["student_rolls"]]
        for group in academics["classes"]:
            if roll in group["student_rolls"]:
                group["student_rolls"].remove(roll)
                academics["revision"] = now()
        roster = [row for row in roster if row["roll_number"] != roll]
        files, metadata = self._management_files(roster, entries, profiles, selections, academics)
        files[archive / "manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
        folder = self.root / "data/reference" / roll
        moves = [(folder, archive / "reference")] if folder.exists() else []
        self._commit_management(files, moves, {"action": "archive", "roll_number": roll, "archive_id": archive_id})
        self.metadata = metadata
        return {"archive_id": archive_id, "roll_number": roll, "name": student["name"]}

    def restore_student(self, archive_id):
        if not isinstance(archive_id, str) or not re.fullmatch(r"[a-f0-9]{32}", archive_id):
            raise AppError("Choose a student from Recently deleted.")
        archive = self.root / "data/student_archive" / archive_id
        path = archive / "manifest.json"
        if not path.exists():
            raise AppError("The archived student could not be found.")
        manifest = json.loads(path.read_text())
        if manifest.get("restored_utc"):
            raise AppError("This student has already been restored.")
        student = manifest["student"]
        roll = self.valid_roll(student["roll_number"])
        roster, entries = self._entries()
        folder = self.root / "data/reference" / roll
        if any(row["roll_number"] == roll for row in roster) or folder.exists():
            raise AppError("That roll number is in use. Edit the active student's roll number before restoring this record.")
        roster.append(student)
        if manifest["embedding"] is not None:
            entry = manifest["embedding"]
            vector, total = np.asarray(entry["vector"], dtype=np.float32), np.asarray(entry["sum"], dtype=np.float32)
            if (vector.shape != (512,) or total.shape != (512,) or not np.isfinite(total).all()
                    or not np.isfinite(vector).all() or not np.isclose(np.linalg.norm(vector), 1, atol=1e-4)
                    or np.linalg.norm(total) <= 0 or not np.allclose(total / np.linalg.norm(total), vector, atol=1e-4)
                    or type(entry["count"]) is not int or entry["count"] < 1):
                raise AppError("The archived face template is damaged. Restore a registry backup instead.")
            entries[roll] = {"name": student["name"], "vector": vector, "sum": total, "count": entry["count"]}
            if (manifest.get("embedding_model", "Facenet512") != self.settings["model"]
                    or manifest.get("input_normalization", "base") != self.settings["normalization"]):
                from model_catalog import rebuild_entry, verify_sources
                entries[roll], sources = rebuild_entry(self, roll, student["name"], archive / "reference",
                    self.settings["model"], manifest.get("selection"), manifest.get("reference_detector", "retinaface"))
                verify_sources(self.root, sources)
        profiles = self.profiles()
        profiles[roll] = {**manifest["profile"], "updated_utc": now()}
        selections = self.selections()
        if manifest["selection"] is not None:
            selections[roll] = manifest["selection"]
        academics = self.academics()
        for group in academics["classes"]:
            if group["id"] in manifest.get("class_ids", []) and roll not in group["student_rolls"]:
                group["student_rolls"].append(roll)
                academics["revision"] = now()
        files, metadata = self._management_files(roster, entries, profiles, selections, academics)
        files[path] = json.dumps({**manifest, "restored_utc": now()}, ensure_ascii=False, indent=2).encode()
        moves = [(archive / "reference", folder)] if (archive / "reference").exists() else []
        self._commit_management(files, moves, {"action": "restore", "roll_number": roll, "archive_id": archive_id})
        self.metadata = metadata
        return self.student_detail(roll)

    def detect(self, rgb, detector=None):
        from deepface import DeepFace
        try:
            faces = DeepFace.extract_faces(
                img_path=cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), detector_backend=detector or self.settings.get("detector", "retinaface"),
                enforce_detection=True, align=True, color_face="rgb", normalize_face=False,
            )
        except ValueError as error:
            if "face could not be detected" in str(error).lower():
                raise AppError("No face was found. Try brighter lighting or move closer to the camera.", "face_not_found") from error
            raise
        if not faces:
            raise AppError("No face was found. Please try another photo.", "face_not_found")
        return faces

    def detect_with_light_adjustment(self, rgb):
        """Keep baseline detections and review extra candidates from a contrast-adjusted copy."""
        try:
            original = self.detect(rgb)
        except AppError as error:
            if error.code != "face_not_found":
                raise
            original = []
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
        try:
            extra = self.detect(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB))
        except AppError as error:
            if error.code != "face_not_found" or not original:
                raise
            return original
        found = list(original)
        for face in extra:
            area = face["facial_area"]
            for known in found:
                other = known["facial_area"]
                overlap = 1
                for axis, size in (("x", "w"), ("y", "h")):
                    overlap *= max(0, min(area[axis] + area[size], other[axis] + other[size])
                                   - max(area[axis], other[axis]))
                smaller = min(area["w"] * area["h"], other["w"] * other["h"])
                if overlap >= 0.5 * smaller:
                    break
            else:
                found.append({**face, "extra_detection": True})
        return found

    def encode(self, rgb, model_name=None):
        from deepface import DeepFace
        result = DeepFace.represent(
            img_path=cv2.cvtColor(np.asarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2BGR),
            model_name=model_name or self.settings["model"], normalization=self.settings["normalization"],
            detector_backend="skip", align=False,
        )
        vector = np.asarray(result[0]["embedding"], dtype=np.float32)
        length = np.linalg.norm(vector)
        if vector.shape != (512,) or not np.isfinite(vector).all() or length <= 0:
            raise AppError("Could not create a valid face embedding. Try a clearer photo.")
        return vector / length

    def match(self, rgb, faces, class_id=None, subject_id=None, snapshot=None):
        if snapshot is None:
            roster, vectors, rolls, names, _, _ = self.registry()
            context, members = self.attendance_context(class_id, subject_id)
        else:
            roster, vectors, rolls, names, context = snapshot
            members = None
        if members is not None:
            roster = [student for student in roster if student["roll_number"] in members]
            mask = np.asarray([roll in members for roll in rolls], dtype=bool)
            vectors, rolls, names = vectors[mask], rolls[mask], names[mask]
        if not roster:
            raise AppError("Enroll students in this class before taking attendance.")
        if not len(rolls):
            raise AppError("This roster has no registered face templates. Add reference photos first.")
        records = []
        for index, face in enumerate(faces, 1):
            area = face["facial_area"]
            record = {"face_id": index, **{key: int(area[key]) for key in ("x", "y", "w", "h")},
                      "candidate_roll": "", "candidate_name": "", "second_candidate_roll": "",
                      "cosine_distance": None, "euclidean_distance": None, "gap": None,
                      "decision": "Review", "reason": "", "detection_score": float(face["confidence"])}
            try:
                query = self.encode(face["face"])
                distances = 1 - np.clip(vectors @ query, -1, 1)
                order = np.argsort(distances)
                first, second = order[0], order[1] if len(order) > 1 else None
                distance = float(distances[first])
                gap = float(distances[second] - distances[first]) if second is not None else None
                record.update(candidate_roll=str(rolls[first]), candidate_name=str(names[first]),
                              second_candidate_roll=str(rolls[second]) if second is not None else "", cosine_distance=distance,
                              euclidean_distance=float(np.linalg.norm(vectors[first] - query)), gap=gap)
                if distance > self.settings["cosine_distance_threshold"]:
                    record.update(decision="Unknown", reason="No candidate passed the distance threshold.")
                elif gap is not None and gap < self.settings["minimum_gap"]:
                    record.update(reason="The two closest candidates are too similar.")
                elif min(area["w"], area["h"]) < 32:
                    record.update(reason="Face is too small for an automatic attendance decision.")
                else:
                    record.update(decision="Matched", reason="Passed the provisional matching rules." if gap is not None
                                  else "Passed distance threshold; only one registered student in this roster.")
            except Exception as error:
                record["reason"] = f"Face could not be processed: {error}"
            records.append(record)
        for face, record in zip(faces, records):
            if face.get("extra_detection") and record["decision"] == "Matched":
                record.update(decision="Review", reason="Found on the extra detection pass. Confirm this identity.")
        claims = Counter(record["candidate_roll"] for record in records if record["decision"] == "Matched")
        for record in records:
            if record["decision"] == "Matched" and claims[record["candidate_roll"]] > 1:
                record.update(decision="Review", reason="Multiple faces claim this student. Please review.")
        present = {record["candidate_roll"] for record in records if record["decision"] == "Matched"}
        review = {record["candidate_roll"] for record in records if record["decision"] == "Review"}
        registered = set(rolls)
        attendance = []
        for student in roster:
            roll = student["roll_number"]
            status = "Present" if roll in present else "Review" if roll in review or roll not in registered else "Unconfirmed"
            note = "Accepted face match." if status == "Present" else "Registration or match needs review." if status == "Review" else "Not matched in this photo; teacher confirmation is required."
            attendance.append({**student, **context, "status": status, "note": note})
        return records, attendance

    def annotate(self, rgb, records):
        image = Image.fromarray(rgb)
        draw = ImageDraw.Draw(image)
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        font = ImageFont.truetype(font_path, max(13, min(22, image.width // 75))) if Path(font_path).exists() else ImageFont.load_default()
        for record in records:
            x, y, w, h = (record[key] for key in ("x", "y", "w", "h"))
            color = {"Matched": "#158554", "Unknown": "#d44242", "Review": "#b87814"}[record["decision"]]
            label = f"{record['candidate_roll']} · {record['candidate_name']}" if record["decision"] == "Matched" else f"Face {record['face_id']} · {record['decision']}"
            label = record.get("display_label", label)
            box = draw.textbbox((0, 0), label, font=font)
            tw, th = box[2] - box[0] + 12, box[3] - box[1] + 12
            tx = max(0, min(x, image.width - tw))
            ty = max(0, y - th)
            draw.rectangle((x, y, x + w, y + h), outline=color, width=3)
            draw.rectangle((tx, ty, tx + tw, ty + th), fill=color)
            draw.text((tx + 6, ty + 4 - box[1]), label, fill="white", font=font)
        return np.array(image)

    def eye_review(self, rgb, class_id, subject_id, snapshot):
        from eye_search import reference_patch, search
        active, _, registered, _, _, _ = self.registry()
        profiles = self.profiles()
        context, members = (snapshot[4], None) if snapshot else self.attendance_context(class_id, subject_id)
        roster = snapshot[0] if snapshot else [row for row in active if members is None or row["roll_number"] in members]
        active_ids = {self.student_identity(r["roll_number"], r["name"], profiles): r["roll_number"] for r in active}
        selections = self.selections()
        references = []
        for row in roster:
            roll = row["roll_number"]
            current = active_ids.get(row["identity_id"]) if snapshot else roll
            if current not in registered:
                continue
            for path in sorted((self.root / "data/reference" / current).glob("*")):
                if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                    continue
                approval = selections.get(current)
                if approval and str(path.relative_to(self.root)) != approval["photo"]:
                    approval = None
                patch = reference_patch(self, path, approval)
                if patch is not None:
                    references.append((roll, row["name"], patch))
        if not references:
            raise AppError("No usable two-eye reference photos for this roster.")
        records = []
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        for roll, name, score, (x,y,w,h) in search(gray, references):
            records.append(dict(face_id=len(records)+1, x=x,y=y,w=w,h=h, candidate_roll=roll,
                candidate_name=name, second_candidate_roll="", decision="Review", cosine_distance=None,
                euclidean_distance=None, gap=None, detection_score=None, eye_similarity=score,
                reason=f"Eye-region correlation {score:.3f}. Confirm the suggested identity."))
        if not records:
            raise AppError("No clear eye-region match. Try a closer frontal capture.", "face_not_found")
        attendance = [{**row, **context, "status":"Review", "note":"Experimental eye search requires teacher review."}
                      for row in roster]
        return records, attendance

    def recognize(self, rgb, save=True, source="upload", class_id=None, subject_id=None, snapshot=None, extra_detection=False, eye_search=False):
        started = time.monotonic()
        context = snapshot[4] if snapshot is not None else self.attendance_context(class_id, subject_id)[0]
        if eye_search:
            records, attendance = self.eye_review(rgb, class_id, subject_id, snapshot)
        else:
            faces = self.detect_with_light_adjustment(rgb) if extra_detection else self.detect(rgb)
            records, attendance = self.match(rgb, faces, class_id, subject_id, snapshot)
        annotated = self.annotate(rgb, records)
        counts = Counter(row["status"] for row in attendance)
        summary = {"faces": len(records), "eye_search": eye_search, "present": counts["Present"], "absent": counts["Absent"],
                   "unconfirmed": counts["Unconfirmed"], "review": counts["Review"], "unknown_faces": sum(row["decision"] == "Unknown" for row in records),
                   "review_faces": sum(row["decision"] == "Review" for row in records),
                   "seconds": round(time.monotonic() - started, 2), "source": source,
                   "created_utc": now(), "settings": self.settings, "saved": bool(save), **context}
        response = {"summary": summary, "detections": records, "attendance": attendance,
                    "image": image_url(annotated), "run_id": None}
        if save:
            run_id = uuid.uuid4().hex
            directory = self.root / "results/app" / run_id
            directory.mkdir(parents=True)
            try:
                atomic_write(directory / "annotated.jpg", image_bytes(annotated))
                atomic_write(directory / "attendance.csv", csv_bytes(attendance, ["class_name", "subject_name", "subject_code", "roll_number", "name", "status", "note"]))
                atomic_write(directory / "detections.csv", csv_bytes(records, list(records[0])))
                atomic_write(directory / "summary.json", json.dumps(summary, indent=2).encode())
                # Write last: history lists only complete runs.
                atomic_write(directory / "result.json", json.dumps({"summary": summary, "detections": records, "attendance": attendance, "run_id": run_id}).encode())
                response["run_id"] = run_id
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
        return response

    def history(self, limit=100):
        entries = []
        for file in (self.root / "results/app").glob("*/result.json"):
            try:
                entries.append(self._history_cache.get((file,), lambda: self._history_summary(file)))
            except (ValueError, OSError, KeyError, TypeError):
                continue
        entries.sort(key=lambda row: row["created_utc"], reverse=True)
        return entries if limit is None else entries[:limit]

    @staticmethod
    def _history_summary(file):
        summary = json.loads(file.read_text())["summary"]
        if (not isinstance(summary, dict) or not isinstance(summary.get("created_utc"), str)
                or any(type(summary.get(key)) is not int for key in ("present", "faces"))
                or summary.get("source") not in ("upload", "webcam")
                or not re.fullmatch(r"[a-f0-9]{32}", file.parent.name)):
            raise ValueError('Invalid photo report summary.')
        datetime.fromisoformat(summary["created_utc"])
        return {"run_id": file.parent.name, **summary}

    def preview_registration(self, rgb):
        faces = self.detect(rgb)
        self.previews = {key: value for key, value in self.previews.items() if value["expires"] > time.monotonic()}
        if len(self.previews) >= 8:
            del self.previews[next(iter(self.previews))]
        preview_id = uuid.uuid4().hex
        self.previews[preview_id] = {"rgb": rgb, "faces": faces, "expires": time.monotonic() + 900}
        return {"preview_id": preview_id, "faces": [{"index": index, "image": image_url(face["face"]),
                "quality": reference_quality(face, rgb)} for index, face in enumerate(faces)]}

    def register_without_photo(self, payload):
        roll = self.valid_roll(payload.get("roll_number"))
        name = payload.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or any(ord(ch) < 32 for ch in name):
            raise AppError("Enter a student name of 1 to 100 characters.")
        roster = self.registry()[0]
        if any(row["roll_number"] == roll for row in roster):
            raise AppError("This roll number already belongs to a student.")
        row = {"roll_number": roll, "name": name.strip()}
        roster.append(row)
        roster.sort(key=lambda student: (int(student["roll_number"]), student["roll_number"]))
        profiles = self.profiles()
        profiles[roll] = {"identity_id": uuid.uuid4().hex, "updated_utc": now()}
        files = {
            self.root / "data/roster.csv": self._roster_bytes(roster),
            self.root / "data/student_profiles.json": json.dumps(profiles, ensure_ascii=False).encode(),
        }
        class_id = payload.get("class_id")
        if class_id:
            academics = self.academics()
            group = next((group for group in academics["classes"] if group["id"] == class_id), None)
            if group is None:
                raise AppError("Choose an existing class.")
            group["student_rolls"].append(roll)
            academics["revision"] = now()
            files[self.root / "data/academics.json"] = json.dumps(academics, ensure_ascii=False).encode()
        self._commit_management(files, [], {"action": "register_without_photo", "roll_number": roll})
        return row

    def register(self, payload):
        if (not isinstance(payload.get("roll_number"), str)
                or not isinstance(payload.get("name"), str)
                or not isinstance(payload.get("preview_id"), str)
                or type(payload.get("add_reference", False)) is not bool
                or type(payload.get("quality_acknowledged", False)) is not bool):
            raise AppError("Enter a valid roll number, student name, and selected photo.")
        roll = str(payload.get("roll_number", "")).strip()
        name = str(payload.get("name", "")).strip()
        if not re.fullmatch(r"[0-9]{1,12}", roll) or not name or len(name) > 100 or any(ord(ch) < 32 for ch in name):
            raise AppError("Enter a numeric roll number and a name between 1 and 100 characters.")
        preview = self.previews.get(payload.get("preview_id"))
        if not preview or preview["expires"] < time.monotonic():
            raise AppError("Photo preview expired. Please detect the faces again.")
        index = payload.get("face_index")
        if type(index) is not int or not 0 <= index < len(preview["faces"]):
            raise AppError("Select the student's face before registering.")
        roster, vectors, rolls, names, sums, counts = self.registry()
        existing = next((row for row in roster if row["roll_number"] == roll), None)
        if payload.get("add_reference", False) and not existing:
            raise AppError("This student was removed or their roll number changed. Refresh the directory before adding photos.")
        if existing and not payload.get("add_reference", False):
            raise AppError("This roll number already exists. Enable 'Add a reference to an existing student'.")
        if existing and existing["name"].casefold() != name.casefold():
            raise AppError(f"Roll {roll} belongs to {existing['name']}. Use the existing student's name.")
        class_id = payload.get("class_id")
        if class_id not in (None, "") and not isinstance(class_id, str):
            raise AppError("Choose a valid class for this registration.")
        academics = self.academics()
        group = next((group for group in academics["classes"] if group["id"] == class_id), None) if class_id else None
        if class_id and (not group or existing):
            raise AppError("Choose a valid class for a new student. Edit class rosters to enroll existing students.")
        face = preview["faces"][index]
        photo_quality = reference_quality(face, preview.get("rgb"))
        photo_content = image_bytes(face["face"])
        photo_hash = hashlib.sha256(photo_content).hexdigest()
        if existing:
            for reference in (self.root / "data/reference" / roll).glob("*"):
                if reference.is_file() and hashlib.sha256(reference.read_bytes()).hexdigest() == photo_hash:
                    raise AppError("This exact reference photo is already saved. Choose a different photo or capture a new frame.")
        query = self.encode(face["face"])
        entries = {str(r): {"name": str(n), "vector": v, "sum": s, "count": int(c)} for r, n, v, s, c in zip(rolls, names, vectors, sums, counts)}
        if roll in entries:
            combined = entries[roll]["sum"] + query
            length = np.linalg.norm(combined)
            if length < 1e-6:
                raise AppError("The reference conflicts with the existing template. Choose another photo.")
            entries[roll].update(vector=combined / length, sum=combined, count=entries[roll]["count"] + 1)
        else:
            entries[roll] = {"name": existing["name"] if existing else name, "vector": query, "sum": query, "count": 1}
        if not existing:
            roster.append({"roll_number": roll, "name": name})
        profiles = self.profiles()
        identity_id = self.student_identity(roll, existing["name"], profiles) if existing else uuid.uuid4().hex
        profiles[roll] = {**profiles.get(roll, {}), "identity_id": identity_id}
        ordered = sorted(entries, key=lambda value: (int(value), value))
        roster.sort(key=lambda row: (int(row["roll_number"]), row["roll_number"]))
        buffer = io.BytesIO()
        np.savez_compressed(buffer, embeddings=np.stack([entries[r]["vector"] for r in ordered]),
                            roll_numbers=np.asarray(ordered, dtype=str), names=np.asarray([entries[r]["name"] for r in ordered], dtype=str),
                            embedding_sums=np.stack([entries[r]["sum"] for r in ordered]), reference_counts=np.asarray([entries[r]["count"] for r in ordered]))
        metadata = dict(self.metadata, registered_students=len(ordered), updated_utc=now(),
                        template_method="sum_of_unit_embeddings_then_L2; imported templates count as one effective reference")
        photo_id = "app_" + uuid.uuid4().hex
        photo_path = self.root / "data/reference" / roll / f"{photo_id}.jpg"
        files = {
            self.root / "embeddings/student_templates.npz": buffer.getvalue(),
            self.root / "data/roster.csv": self._roster_bytes(roster),
            self.root / "embeddings/metadata.json": json.dumps(metadata, indent=2).encode(),
            self.root / "data/student_profiles.json": json.dumps(profiles, ensure_ascii=False, indent=2).encode(),
        }
        if group is not None:
            group["student_rolls"].append(roll)
            academics["revision"] = now()
            files[self.root / "data/academics.json"] = json.dumps(academics, ensure_ascii=False, indent=2).encode()
        backup = self.root / "work/app-backups" / photo_id
        backup.mkdir(parents=True)
        for path in files:
            if path.exists():
                shutil.copy2(path, backup / path.name)
        original = {path: path.read_bytes() if path.exists() else None for path in files}
        try:
            # Store only the explicitly selected, aligned face as the new reference.
            atomic_write(photo_path, photo_content)
            for path, content in files.items():
                atomic_write(path, content)
            audit = {"roll_number": roll, "name": name, "face_index": index,
                     "photo_sha256": hashlib.sha256(photo_content).hexdigest(),
                     "created_utc": now(), "photo": str(photo_path.relative_to(self.root)),
                     "action": "add_reference" if existing else "register", "backup": str(backup.relative_to(self.root)),
                     "photo_quality": photo_quality, "quality_acknowledged": payload.get("quality_acknowledged", False)}
            atomic_write(self.root / "logs/app-registration" / f"{photo_id}.json", json.dumps(audit, indent=2).encode())
        except Exception:
            for path, content in original.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, content)
            photo_path.unlink(missing_ok=True)
            raise
        self.metadata = metadata
        del self.previews[payload["preview_id"]]
        return {"roll_number": roll, "name": existing["name"] if existing else name, "registered_students": len(ordered),
                "reference_count": entries[roll]["count"], "quality": photo_quality}

    @staticmethod
    def _roster_bytes(roster):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=["roll_number", "name"])
        writer.writeheader()
        writer.writerows(roster)
        return output.getvalue().encode()

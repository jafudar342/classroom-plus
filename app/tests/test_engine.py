import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import AppError, Engine, decode_image


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ["data", "embeddings", "config"]:
            (self.root / folder).mkdir()
        (self.root / "data/roster.csv").write_text("roll_number,name\n1,Alice\n2,Bob\n3,NoTemplate\n")
        self.vectors = np.eye(512, dtype=np.float32)[:2]
        np.savez_compressed(self.root / "embeddings/student_templates.npz", embeddings=self.vectors,
                            roll_numbers=np.array(["1", "2"]), names=np.array(["Alice", "Bob"]))
        (self.root / "config/demo_matching_settings.json").write_text(json.dumps({
            "model": "Facenet512", "normalization": "base", "cosine_distance_threshold": .3, "minimum_gap": .05, "calibrated": False}))
        (self.root / "embeddings/metadata.json").write_text(json.dumps({"model": "Facenet512", "input_normalization": "base"}))
        self.engine = Engine(self.root)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def face():
        return {"facial_area": {"x": 1, "y": 2, "w": 64, "h": 64}, "confidence": .99,
                "face": np.zeros((64, 64, 3), dtype=np.uint8)}

    def test_matching_and_missing_registration(self):
        self.engine.encode = lambda _: self.vectors[0]
        records, roster = self.engine.match(None, [self.face()])
        self.assertEqual(records[0]["candidate_roll"], "1")
        self.assertEqual(records[0]["decision"], "Matched")
        self.assertEqual([row["status"] for row in roster], ["Present", "Unconfirmed", "Review"])

    def test_extra_detection_preserves_first_pass_and_reviews_new_face(self):
        rgb = np.zeros((100, 180, 3), dtype=np.uint8)
        original = self.face()
        additional = self.face()
        additional["facial_area"]["x"] = 100
        with patch.object(self.engine, "detect", side_effect=[[original], [self.face(), additional]]):
            faces = self.engine.detect_with_light_adjustment(rgb)
        self.assertEqual(len(faces), 2)
        self.assertIs(faces[0], original)
        with patch.object(self.engine, "encode", side_effect=self.vectors):
            records, attendance = self.engine.match(rgb, faces)
        self.assertEqual([row["decision"] for row in records], ["Matched", "Review"])
        self.assertEqual(attendance[1]["status"], "Review")

    def test_unknown_not_accepted(self):
        self.engine.encode = lambda _: np.eye(512, dtype=np.float32)[2]
        records, roster = self.engine.match(None, [self.face()])
        self.assertEqual(records[0]["decision"], "Unknown")
        self.assertFalse(any(row["status"] == "Present" for row in roster))

    def test_ambiguous_match_requires_review(self):
        self.engine.encode = lambda _: (self.vectors[0] + self.vectors[1]) / np.sqrt(2)
        records, _ = self.engine.match(None, [self.face()])
        self.assertEqual(records[0]["decision"], "Review")

    def test_duplicate_identity_never_marks_present(self):
        self.engine.encode = lambda _: self.vectors[0]
        records, roster = self.engine.match(None, [self.face(), self.face()])
        self.assertTrue(all(row["decision"] == "Review" for row in records))
        self.assertEqual(roster[0]["status"], "Review")

    def test_embedding_error_is_visible(self):
        def fail(_):
            raise ValueError("broken embedding")
        self.engine.encode = fail
        records, _ = self.engine.match(None, [self.face()])
        self.assertEqual(records[0]["decision"], "Review")
        self.assertIn("broken embedding", records[0]["reason"])

    def preview(self):
        self.engine.previews["test"] = {"faces": [self.face(), self.face()], "expires": time.monotonic() + 60}
        self.engine.encode = lambda _: self.vectors[0]

    def test_registration_requires_explicit_face_and_duplicate_approval(self):
        self.preview()
        with self.assertRaises(AppError):
            self.engine.register({"roll_number": "4", "name": "Carol", "preview_id": "test"})
        with self.assertRaises(AppError):
            self.engine.register({"roll_number": "1", "name": "Alice", "preview_id": "test", "face_index": 0})
        with self.assertRaises(AppError):
            self.engine.register({"roll_number": "../x", "name": "Alice", "preview_id": "test", "face_index": 0})

    def test_registration_updates_templates_and_roster_with_backups(self):
        self.preview()
        self.engine.register({"roll_number": "4", "name": "Carol", "preview_id": "test", "face_index": 1})
        roster, vectors, rolls, _, _, counts = self.engine.registry()
        self.assertIn("4", rolls)
        self.assertEqual(len(roster), 4)
        self.assertEqual(vectors.shape, (3, 512))
        self.assertEqual(counts.tolist(), [1, 1, 1])
        self.assertEqual(len(list((self.root / "data/reference/4").glob("*.jpg"))), 1)
        self.assertEqual(len(list((self.root / "work/app-backups").glob("*/student_templates.npz"))), 1)

    def test_add_reference_keeps_roster_unique(self):
        self.preview()
        self.engine.register({"roll_number": "1", "name": "Alice", "preview_id": "test", "face_index": 0, "add_reference": True})
        roster, vectors, _, _, _, counts = self.engine.registry()
        self.assertEqual(len(roster), 3)
        self.assertEqual(counts[0], 2)
        self.assertAlmostEqual(float(np.linalg.norm(vectors[0])), 1)

    def test_failed_registration_rolls_back_database(self):
        self.preview()
        files = [self.root / "data/roster.csv", self.root / "embeddings/student_templates.npz", self.root / "embeddings/metadata.json"]
        original = {file: file.read_bytes() for file in files}
        import engine
        real_write = engine.atomic_write
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if Path(path).name == "roster.csv" and not failed:
                failed = True
                raise OSError("disk write failed")
            real_write(path, data)
        with patch("engine.atomic_write", fail_once):
            with self.assertRaises(OSError):
                self.engine.register({"roll_number": "4", "name": "Carol", "preview_id": "test", "face_index": 0})
        for file in files:
            self.assertEqual(file.read_bytes(), original[file])
        self.assertEqual(list((self.root / "data/reference/4").glob("*.jpg")), [])

    def test_invalid_upload_has_clear_error(self):
        for value in [None, "not-an-image", "data:image/png;base64,aGVsbG8="]:
            with self.assertRaises(AppError):
                decode_image(value)

    def test_truncated_reference_counts_cannot_erase_students(self):
        np.savez_compressed(self.root / "embeddings/student_templates.npz", embeddings=self.vectors,
                            roll_numbers=np.array(["1", "2"]), names=np.array(["Alice", "Bob"]),
                            embedding_sums=self.vectors, reference_counts=np.array([1]))
        self.preview()
        before = (self.root / "data/roster.csv").read_bytes()
        with self.assertRaises(AppError):
            self.engine.register({"roll_number": "4", "name": "Carol", "preview_id": "test", "face_index": 0})
        self.assertEqual((self.root / "data/roster.csv").read_bytes(), before)

    def test_duplicate_roster_is_rejected(self):
        with (self.root / "data/roster.csv").open("a") as file:
            file.write("1,Duplicate\n")
        with self.assertRaises(AppError):
            self.engine.registry()

    def test_invalid_registration_types_are_clear_errors(self):
        self.preview()
        for changed in [{"name": None}, {"preview_id": []}, {"add_reference": "false"}]:
            payload = {"roll_number": "4", "name": "Carol", "preview_id": "test", "face_index": 0, **changed}
            with self.assertRaises(AppError):
                self.engine.register(payload)

    def test_corrupt_history_does_not_break_workspace(self):
        for index, value in enumerate([None, {"summary": {}}, {"summary": "bad"}]):
            folder = self.root / "results/app" / f"{index:032x}"
            folder.mkdir(parents=True)
            (folder / "result.json").write_text(json.dumps(value))
        self.assertEqual(self.engine.state()["history"], [])
        self.assertEqual(self.engine.state()["session_count"], 0)

    def profile_payload(self, **changes):
        return {"roll_number": "1", "name": "Alice Updated", "department": "Computer Science",
                "course": "M.Tech", "semester": "3", "section": "A", "email": "alice@example.com",
                "phone": "+91 1234567890", "notes": "Demo student", "custom_fields": [{"label": "Batch", "value": "2026"}],
                "revision": "", **changes}

    def reference_folder(self):
        folder = self.root / "data/reference/1"
        folder.mkdir(parents=True)
        Image.new("RGB", (64, 64), "white").save(folder / "reference.jpg")
        return folder

    def test_edit_student_updates_labels_details_and_photo_folder(self):
        self.reference_folder()
        (self.root / "config/reference_face_selections.json").write_text(json.dumps({"1": {"name": "Alice", "photo": "data/reference/1/reference.jpg"}}))
        original_vector = self.engine.registry()[1][0].copy()
        saved = self.engine.update_student("1", self.profile_payload(roll_number="101"))
        self.assertEqual(saved["name"], "Alice Updated")
        self.assertEqual(saved["department"], "Computer Science")
        self.assertEqual(saved["custom_fields"], [{"label": "Batch", "value": "2026"}])
        self.assertFalse((self.root / "data/reference/1").exists())
        self.assertTrue((self.root / "data/reference/101/reference.jpg").exists())
        _, vectors, rolls, names, _, _ = self.engine.registry()
        index = list(rolls).index("101")
        np.testing.assert_array_equal(vectors[index], original_vector)
        self.assertEqual(names[index], "Alice Updated")
        selection = self.engine.selections()["101"]
        self.assertEqual(selection["photo"], "data/reference/101/reference.jpg")

    def test_edit_rejects_duplicate_roll_and_stale_revision(self):
        with self.assertRaises(AppError):
            self.engine.update_student("1", self.profile_payload(roll_number="2"))
        self.engine.update_student("1", self.profile_payload())
        with self.assertRaises(AppError):
            self.engine.update_student("1", self.profile_payload(name="Stale edit"))

    def test_profile_rejects_invalid_custom_fields(self):
        for fields in [[{"label": "Batch", "value": "1"}, {"label": "batch", "value": "2"}], {"label": "not a list"}, [{"label": "", "value": "x"}]]:
            with self.assertRaises(AppError):
                self.engine.update_student("1", self.profile_payload(custom_fields=fields))

    def test_delete_requires_confirmation(self):
        with self.assertRaises(AppError):
            self.engine.delete_student("1", {"confirmation": "2"})
        self.assertIn("1", self.engine.registry()[2])

    def test_stale_add_reference_cannot_recreate_deleted_student(self):
        self.engine.delete_student("1", {"confirmation": "1"})
        self.preview()
        with self.assertRaises(AppError):
            self.engine.register({"roll_number": "1", "name": "Alice", "preview_id": "test", "face_index": 0, "add_reference": True})
        self.assertNotIn("1", self.engine.registry()[2])

    def test_delete_and_restore_preserve_template_details_and_photos(self):
        self.reference_folder()
        saved = self.engine.update_student("1", self.profile_payload())
        vectors_before = self.engine.registry()[1].copy()
        removed = self.engine.delete_student("1", {"confirmation": "1", "revision": saved["revision"]})
        self.assertNotIn("1", self.engine.registry()[2])
        self.assertFalse((self.root / "data/reference/1").exists())
        self.assertNotIn("1", self.engine.profiles())
        self.assertEqual(len(self.engine.archived_students()), 1)
        restored = self.engine.restore_student(removed["archive_id"])
        self.assertEqual(restored["course"], "M.Tech")
        self.assertEqual(restored["name"], "Alice Updated")
        np.testing.assert_array_equal(self.engine.registry()[1], vectors_before)
        self.assertTrue((self.root / "data/reference/1/reference.jpg").exists())
        self.assertEqual(self.engine.archived_students(), [])
        with self.assertRaises(AppError):
            self.engine.restore_student(removed["archive_id"])

    def test_restore_rejects_reused_roll_number(self):
        removed = self.engine.delete_student("1", {"confirmation": "1"})
        self.preview()
        self.engine.register({"roll_number": "1", "name": "Another student", "preview_id": "test", "face_index": 0})
        with self.assertRaises(AppError):
            self.engine.restore_student(removed["archive_id"])

    def test_management_failure_rolls_back_folder_and_files(self):
        self.reference_folder()
        original = (self.root / "data/roster.csv").read_bytes()
        import engine
        real_write = engine.atomic_write
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if Path(path).name == "student_templates.npz" and not failed:
                failed = True
                raise OSError("Disk error")
            real_write(path, data)
        with patch("engine.atomic_write", fail_once):
            with self.assertRaises(OSError):
                self.engine.update_student("1", self.profile_payload(roll_number="101"))
        self.assertEqual((self.root / "data/roster.csv").read_bytes(), original)
        self.assertTrue((self.root / "data/reference/1/reference.jpg").exists())
        self.assertFalse((self.root / "data/reference/101").exists())
        self.assertFalse((self.root / "data/student_profiles.json").exists())

    def test_all_students_can_be_archived_and_restored(self):
        archived = [self.engine.delete_student(roll, {"confirmation": roll}) for roll in ["1", "2", "3"]]
        self.assertEqual(self.engine.registry()[1].shape, (0, 512))
        self.assertEqual(self.engine.state()["students"], [])
        restored = self.engine.restore_student(archived[0]["archive_id"])
        self.assertTrue(restored["registered"])
        self.assertEqual(self.engine.registry()[1].shape, (1, 512))

    def create_class(self, name="Class A", members=None):
        saved = self.engine.save_class({"name": name, "student_rolls": members if members is not None else ["1", "3"], "revision": self.engine.academics()["revision"]})
        group = saved["class"]
        subject = self.engine.save_subject({"class_id": group["id"], "name": "Deep Learning", "code": "AI501", "revision": self.engine.academics()["revision"]})["subject"]
        return group, subject

    def test_class_scopes_matching_and_attendance_to_enrolled_students(self):
        group, subject = self.create_class()
        self.engine.encode = lambda _: self.vectors[0]
        records, attendance = self.engine.match(None, [self.face()], group["id"], subject["id"])
        self.assertEqual(records[0]["decision"], "Matched")
        self.assertIsNone(records[0]["gap"])
        self.assertEqual({row["roll_number"] for row in attendance}, {"1", "3"})
        self.assertEqual(attendance[0]["class_name"], "Class A")
        self.assertEqual(attendance[1]["status"], "Review")
        self.engine.encode = lambda _: self.vectors[1]
        records, _ = self.engine.match(None, [self.face()], group["id"], subject["id"])
        self.assertEqual(records[0]["decision"], "Unknown")
        self.assertNotEqual(records[0]["candidate_roll"], "2")

    def test_subject_from_another_class_is_rejected_before_detection(self):
        first, _ = self.create_class()
        _, foreign = self.create_class("Class B", ["2"])
        def should_not_detect(_):
            raise AssertionError("Detection should not start with an invalid subject")
        self.engine.detect = should_not_detect
        with self.assertRaises(AppError):
            self.engine.recognize(np.zeros((64, 64, 3), dtype=np.uint8), class_id=first["id"], subject_id=foreign["id"])
        with self.assertRaises(AppError):
            self.engine.attendance_context(first["id"], None)

    def test_classes_validate_roster_duplicates_and_stale_edits(self):
        self.create_class()
        for members in [["1", "1"], ["999"], [[]]]:
            with self.assertRaises(AppError):
                self.engine.save_class({"name": "New class", "student_rolls": members, "revision": self.engine.academics()["revision"]})
        with self.assertRaises(AppError):
            self.engine.save_class({"name": "Stale", "student_rolls": [], "revision": ""})
        with self.assertRaises(AppError):
            self.engine.save_class({"name": "class a", "student_rolls": [], "revision": self.engine.academics()["revision"]})

    def test_subject_codes_are_unique_within_a_class(self):
        group, _ = self.create_class()
        with self.assertRaises(AppError):
            self.engine.save_subject({"class_id": group["id"], "name": "Another subject", "code": "ai501", "revision": self.engine.academics()["revision"]})
        second, subject = self.create_class("Class B", ["2"])
        self.assertEqual(subject["code"], "AI501")
        self.assertEqual(subject["class_id"], second["id"])

    def test_class_membership_follows_rename_delete_and_restore(self):
        group, _ = self.create_class()
        saved = self.engine.update_student("1", self.profile_payload(roll_number="101"))
        self.assertIn("101", self.engine.academics()["classes"][0]["student_rolls"])
        self.assertNotIn("1", self.engine.academics()["classes"][0]["student_rolls"])
        deleted = self.engine.delete_student("101", {"confirmation": "101", "revision": saved["revision"]})
        self.assertNotIn("101", self.engine.academics()["classes"][0]["student_rolls"])
        self.engine.restore_student(deleted["archive_id"])
        self.assertIn("101", self.engine.academics()["classes"][0]["student_rolls"])

    def test_new_student_can_be_enrolled_during_registration(self):
        group, _ = self.create_class()
        self.preview()
        self.engine.register({"roll_number": "4", "name": "Carol", "preview_id": "test", "face_index": 0, "class_id": group["id"]})
        self.assertIn("4", self.engine.academics()["classes"][0]["student_rolls"])

    def test_class_subject_reports_keep_their_original_labels(self):
        group, subject = self.create_class()
        self.engine.encode = lambda _: self.vectors[0]
        self.engine.detect = lambda _: [self.face()]
        report = self.engine.recognize(np.zeros((70, 70, 3), dtype=np.uint8), class_id=group["id"], subject_id=subject["id"])
        self.assertEqual(report["summary"]["class_name"], "Class A")
        self.assertEqual(report["summary"]["subject_code"], "AI501")
        path = self.root / "results/app" / report["run_id"] / "attendance.csv"
        before = path.read_bytes()
        self.assertIn("Deep Learning", before.decode("utf-8-sig"))
        self.engine.save_class({"id": group["id"], "name": "Renamed class", "student_rolls": ["1"], "revision": self.engine.academics()["revision"]})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.engine.history()[0]["class_name"], "Class A")


if __name__ == "__main__":
    unittest.main()

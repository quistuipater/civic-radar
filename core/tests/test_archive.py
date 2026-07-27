"""Tests for the raw archive writer -- the "archive first" half of the
project's core principle. Correctness here (never silently overwriting
raw evidence, stable hashing) matters more than almost anything else in
the codebase.
"""

import hashlib

from app.archive import archive_dir_for, now_utc, sha256_hex, slugify, write_archive_file, write_metadata


class TestSlugify:
    def test_lowercases_and_replaces_non_alnum(self):
        assert slugify("Ventura County Board of Supervisors") == "ventura_county_board_of_supervisors"

    def test_strips_leading_trailing_underscores(self):
        assert slugify("  --Weird Input!!--  ") == "weird_input"

    def test_returns_default_for_none_or_empty(self):
        assert slugify(None) == "misc"
        assert slugify("") == "misc"
        assert slugify("   ") == "misc"

    def test_custom_default(self):
        assert slugify(None, default="unknown") == "unknown"


class TestSha256Hex:
    def test_matches_stdlib_hashlib(self):
        content = b"hello world"
        assert sha256_hex(content) == hashlib.sha256(content).hexdigest()

    def test_different_content_different_hash(self):
        assert sha256_hex(b"a") != sha256_hex(b"b")


class TestArchiveDirFor:
    def test_builds_expected_path_shape(self, archive_root):
        when = now_utc().replace(year=2026, month=6, day=24)
        path = archive_dir_for("City of Ventura", "Planning Commission", when)
        assert path == archive_root / "city_of_ventura" / "planning_commission" / "2026" / "2026-06-24"


class TestWriteArchiveFile:
    def test_writes_content_and_returns_path(self, archive_root):
        directory = archive_root / "test"
        path = write_archive_file(directory, "doc.pdf", b"content-a")
        assert path.read_bytes() == b"content-a"

    def test_reusing_same_filename_with_same_content_is_a_no_op(self, archive_root):
        directory = archive_root / "test"
        path1 = write_archive_file(directory, "doc.pdf", b"same")
        path2 = write_archive_file(directory, "doc.pdf", b"same")
        assert path1 == path2

    def test_reusing_same_filename_with_different_content_disambiguates_instead_of_overwriting(self, archive_root):
        directory = archive_root / "test"
        path1 = write_archive_file(directory, "doc.pdf", b"version-a")
        path2 = write_archive_file(directory, "doc.pdf", b"version-b")
        assert path1 != path2
        assert path1.read_bytes() == b"version-a"
        assert path2.read_bytes() == b"version-b"


class TestWriteMetadata:
    def test_writes_json_serializable_dict(self, archive_root):
        path = write_metadata(archive_root, "meta.json", {"count": 3, "note": "ok"})
        assert '"count": 3' in path.read_text()

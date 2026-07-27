"""Manually ingest already-downloaded document(s) into the standard archive/
parse/classify/embed/match/alert pipeline, for sources whose automated
connector is blocked by anti-bot measures we deliberately don't try to defeat
(NetFile's Cloudflare Turnstile, Elections' AWS WAF challenge -- see README).
A human retrieving files themselves in a real browser and handing them to
this script is a different, legitimate thing from automating around the
challenge -- each file still goes through the exact same archive-first/hash/
parse/classify pipeline as an automated fetch, just entering at the "already
downloaded" step instead of ingest_source()'s HTTP fetch.

Files must be reachable from inside the container -- drop them anywhere
under the ./archive/ bind mount on the host (e.g. ./archive/_manual_incoming/
on the host is /archive/_manual_incoming/ in the container).

Single file:
  docker compose run --rm api python scripts/ingest_manual_document.py \\
    --source "NetFile" \\
    --file /archive/_manual_incoming/some_filing.pdf \\
    --document-type notice \\
    --title "Form 460 -- Jane Doe for City Council" \\
    [--meeting-date 2026-07-15] \\
    [--original-url https://netfile.com/...]

Batch (e.g. after downloading many NetFile filings at once): write a CSV
manifest with columns `file,title,document_type` and optional
`meeting_date,original_url` -- file paths are relative to the manifest's own
directory unless absolute:

  file,title,document_type,meeting_date,original_url
  216946685_foreman.pdf,"Form 470 -- Terry Foreman",notice,2026-07-06,https://netfile.com/...
  216946248_dem_club.pdf,"Form 460 -- Democratic Club of Ventura",notice,2026-07-06,https://netfile.com/...

  docker compose run --rm api python scripts/ingest_manual_document.py \\
    --source "NetFile" --manifest /archive/_manual_incoming/manifest.csv

--source is matched by case-insensitive substring against Source.name; must
match exactly one row (one source per run, single-file or batch).
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from app.archive import archive_dir_for, now_utc, sha256_hex, write_archive_file, write_metadata
from app.db import SessionLocal
from app.models import Document, Source

DOCUMENT_TYPES = {"agenda", "minutes", "packet", "notice", "pdf"}
REQUIRED_MANIFEST_COLUMNS = {"file", "title", "document_type"}


def _resolve_source(db, name_substring: str) -> Source:
    matches = db.query(Source).filter(Source.name.ilike(f"%{name_substring}%")).all()
    if len(matches) != 1:
        names = "\n".join(f"  - {s.name}" for s in matches) or "  (no matches)"
        sys.exit(f"expected exactly one source matching {name_substring!r}, found {len(matches)}:\n{names}")
    return matches[0]


def _ingest_one(
    db,
    source: Source,
    file_path: Path,
    *,
    title: str,
    document_type: str,
    meeting_date: date | None,
    original_url: str | None,
) -> str:
    if not file_path.exists():
        return f"SKIP {file_path}: file not found"

    content = file_path.read_bytes()
    content_hash = sha256_hex(content)

    existing = (
        db.query(Document)
        .filter(Document.source_id == source.id, Document.content_hash == content_hash)
        .one_or_none()
    )
    if existing:
        return f"SKIP {file_path.name}: already archived as document {existing.id}"

    directory = archive_dir_for(source.jurisdiction, source.body, meeting_date or now_utc())
    filename = f"{document_type}_{meeting_date or 'nodate'}_{content_hash[:10]}{file_path.suffix}"
    archive_path = write_archive_file(directory, filename, content)
    write_metadata(
        directory,
        f"{filename}.metadata.json",
        {
            "original_url": original_url,
            "manually_retrieved": True,
            "retrieved_at": now_utc().isoformat(),
            "content_hash": content_hash,
            "source_id": str(source.id),
            "file_size_bytes": len(content),
        },
    )

    document = Document(
        source_id=source.id,
        fetch_id=None,
        title=title,
        document_type=document_type,
        original_url=original_url,
        archive_path=str(archive_path),
        content_hash=content_hash,
        mime_type="application/pdf" if file_path.suffix.lower() == ".pdf" else None,
        file_size_bytes=len(content),
        meeting_date=meeting_date,
        jurisdiction=source.jurisdiction,
        agency=source.agency,
        body=source.body,
        parser_status="pending",
    )
    db.add(document)
    db.commit()
    return f"OK {file_path.name} -> document {document.id}"


def _run_manifest(db, source: Source, manifest_path: Path) -> None:
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")

    with open(manifest_path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"no rows in {manifest_path}")

    missing = REQUIRED_MANIFEST_COLUMNS - set(rows[0].keys())
    if missing:
        sys.exit(f"manifest missing required column(s): {sorted(missing)}")

    manifest_dir = manifest_path.parent
    ok = skipped = 0
    for row in rows:
        document_type = row["document_type"].strip()
        if document_type not in DOCUMENT_TYPES:
            print(f"SKIP {row['file']}: invalid document_type {document_type!r} (must be one of {sorted(DOCUMENT_TYPES)})")
            skipped += 1
            continue

        file_path = Path(row["file"])
        if not file_path.is_absolute():
            file_path = manifest_dir / file_path

        meeting_date_str = (row.get("meeting_date") or "").strip()
        meeting_date = date.fromisoformat(meeting_date_str) if meeting_date_str else None
        original_url = (row.get("original_url") or "").strip() or None

        result = _ingest_one(
            db,
            source,
            file_path,
            title=row["title"].strip(),
            document_type=document_type,
            meeting_date=meeting_date,
            original_url=original_url,
        )
        print(result)
        if result.startswith("OK"):
            ok += 1
        else:
            skipped += 1
    print(f"\n{ok} archived, {skipped} skipped.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Case-insensitive substring match against Source.name")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file", type=Path, help="Single already-downloaded file")
    mode.add_argument("--manifest", type=Path, help="CSV: file,title,document_type[,meeting_date][,original_url]")
    parser.add_argument("--document-type", choices=sorted(DOCUMENT_TYPES), help="Required with --file")
    parser.add_argument("--title", help="Required with --file")
    parser.add_argument("--meeting-date", help="YYYY-MM-DD, optional with --file")
    parser.add_argument("--original-url", help="Optional with --file")
    args = parser.parse_args()

    if args.file and (not args.title or not args.document_type):
        parser.error("--file requires --title and --document-type")

    db = SessionLocal()
    try:
        source = _resolve_source(db, args.source)

        if args.manifest:
            _run_manifest(db, source, args.manifest)
            return

        meeting_date = date.fromisoformat(args.meeting_date) if args.meeting_date else None
        result = _ingest_one(
            db,
            source,
            args.file,
            title=args.title,
            document_type=args.document_type,
            meeting_date=meeting_date,
            original_url=args.original_url,
        )
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()

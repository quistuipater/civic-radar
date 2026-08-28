from app.db import Base


def test_record_provenance_tables_are_registered():
    assert "public_records" in Base.metadata.tables
    assert "record_representations" in Base.metadata.tables
    assert "record_representation_gaps" in Base.metadata.tables


def test_representation_links_record_to_archived_document():
    table = Base.metadata.tables["record_representations"]

    assert table.c.public_record_id.foreign_keys
    assert next(iter(table.c.public_record_id.foreign_keys)).target_fullname == "public_records.id"

    assert table.c.document_id.foreign_keys
    assert next(iter(table.c.document_id.foreign_keys)).target_fullname == "documents.id"
    assert table.c.document_id.unique is True


def test_representation_gap_is_explicit_provenance():
    table = Base.metadata.tables["record_representation_gaps"]

    assert table.c.representation_id.foreign_keys
    assert (
        next(iter(table.c.representation_id.foreign_keys)).target_fullname
        == "record_representations.id"
    )
    assert "gap_type" in table.c
    assert "cause" in table.c
    assert "verification_status" in table.c

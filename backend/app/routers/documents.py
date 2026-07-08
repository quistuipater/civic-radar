import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.classify import classify_document
from app.ai.summarize import summarize_document
from app.db import get_db
from app.issue_matching import match_document_to_issue, suggest_issues_for_document
from app.models import AiOutput, Document
from app.schemas import DocumentOut

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    document_type: str | None = None,
    jurisdiction: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Document)
    if document_type:
        query = query.filter(Document.document_type == document_type)
    if jurisdiction:
        query = query.filter(Document.jurisdiction == jurisdiction)
    return query.order_by(Document.created_at.desc()).limit(min(limit, 500)).all()


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    return document


@router.post("/ai/classify/{document_id}")
def trigger_classification(document_id: uuid.UUID, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    output = classify_document(db, document)
    return {"ai_output_id": output.id, "output_json": output.output_json, "error": output.error_message}


@router.post("/ai/summarize/{document_id}")
def trigger_summarization(document_id: uuid.UUID, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    output = summarize_document(db, document)
    if output is None:
        raise HTTPException(status_code=422, detail="no summary prompt configured or no extracted text")
    return {"ai_output_id": output.id, "output_json": output.output_json, "error": output.error_message}


@router.post("/ai/match-issue/{document_id}")
def trigger_issue_match(document_id: uuid.UUID, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    issue = match_document_to_issue(db, document)
    return {"issue_id": issue.id if issue else None}


@router.get("/documents/{document_id}/suggested-issues")
def get_suggested_issues(document_id: uuid.UUID, limit: int = 5, db: Session = Depends(get_db)):
    """Fuzzy embedding-based candidates for a human to confirm via
    POST /api/issues/{id}/links -- never auto-linked (see app/issue_matching.py).
    """
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    suggestions = suggest_issues_for_document(db, document, limit=limit)
    return [
        {"issue_id": s["issue"].id, "title": s["issue"].title, "slug": s["issue"].slug, "distance": s["distance"]}
        for s in suggestions
    ]


@router.get("/documents/{document_id}/ai-outputs")
def get_document_ai_outputs(document_id: uuid.UUID, db: Session = Depends(get_db)):
    outputs = (
        db.query(AiOutput)
        .filter(AiOutput.input_ref_type == "document", AiOutput.input_ref_id == document_id)
        .order_by(AiOutput.created_at.desc())
        .all()
    )
    return [
        {
            "id": o.id,
            "task_type": o.task_type,
            "model_name": o.model_name,
            "prompt_version": o.prompt_version,
            "output_json": o.output_json,
            "confidence": o.confidence,
            "error_message": o.error_message,
            "created_at": o.created_at,
        }
        for o in outputs
    ]

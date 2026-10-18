#!/usr/bin/env python3
"""Export a traceable handoff packet for qualified Macedonian legal counsel."""

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import (
    LegalDocument,
    LegalReviewAssignment,
    create_all_tables,
    get_engine,
    get_session_factory,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the legal review queue")
    parser.add_argument("--country", default="mk")
    parser.add_argument("--output-dir", default="reports/legal-review")
    args = parser.parse_args()

    generated_at = datetime.datetime.utcnow().replace(microsecond=0)
    stamp = generated_at.strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    with session_factory() as db:
        documents = (
            db.query(LegalDocument)
            .filter(LegalDocument.country_code == args.country)
            .order_by(LegalDocument.title.asc())
            .all()
        )
        assignments = (
            db.query(LegalReviewAssignment)
            .filter(
                LegalReviewAssignment.legal_document_id.in_(
                    [document.id for document in documents]
                )
            )
            .order_by(LegalReviewAssignment.created_at.desc())
            .all()
            if documents else []
        )

    assignment_by_document = {}
    for assignment in assignments:
        assignment_by_document.setdefault(assignment.legal_document_id, assignment)

    rows = []
    for document in documents:
        assignment = assignment_by_document.get(document.id)
        rows.append({
            "id": document.id,
            "title": document.title,
            "status": document.source_status.value,
            "source_url": document.source_url,
            "date_accessed": (
                document.date_accessed.isoformat()
                if document.date_accessed else None
            ),
            "verified_at": (
                document.verified_at.isoformat()
                if document.verified_at else None
            ),
            "content_hash": document.content_hash,
            "local_path": document.local_path,
            "assignment": {
                "reviewer_name": assignment.reviewer_name,
                "reviewer_organization": assignment.reviewer_organization,
                "reviewer_jurisdiction": assignment.reviewer_jurisdiction,
                "qualification_reference": assignment.qualification_reference,
                "status": assignment.status,
                "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
            } if assignment else None,
        })

    engine.dispose()

    payload = {
        "generated_at": generated_at.isoformat() + "Z",
        "country": args.country,
        "legal_disclaimer": (
            "This packet organizes source material. It is not legal advice and "
            "does not mark any reference as lawyer verified."
        ),
        "documents": rows,
    }
    json_path = output_dir / f"legal-review-{args.country}-{stamp}.json"
    md_path = output_dir / f"legal-review-{args.country}-{stamp}.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"# Legal review packet: {args.country.upper()}",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"> {payload['legal_disclaimer']}",
        "",
        "## Counsel checklist",
        "",
        "- Confirm the official source and exact title.",
        "- Confirm the consolidated text and all applicable amendments.",
        "- Record effective and repeal dates.",
        "- Verify quoted article numbers and legal limits.",
        "- Record corrections and safe client-facing wording.",
        "- Sign off only through the audited assignment and review workflow.",
        "",
        "## References",
        "",
    ]
    for row in rows:
        lines.extend([
            f"### {row['id']}. {row['title']}",
            "",
            f"- Status: `{row['status']}`",
            f"- Official source: {row['source_url']}",
            f"- Accessed: {row['date_accessed'] or 'Unknown'}",
            f"- Verified at: {row['verified_at'] or 'Needs counsel review'}",
            f"- Content hash: `{row['content_hash'] or 'Not imported'}`",
            f"- Local source: `{row['local_path'] or 'Not imported'}`",
            f"- Assignment: {format_assignment(row['assignment'])}",
            "",
            "Counsel notes:",
            "",
            "- [ ] Official text confirmed",
            "- [ ] Amendments checked",
            "- [ ] Effective date confirmed",
            "- [ ] Client-facing limitations recorded",
            "",
        ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Exported {len(rows)} references")
    print(md_path)
    print(json_path)
    return 0


def format_assignment(assignment: dict | None) -> str:
    if not assignment:
        return "Unassigned"
    qualification = assignment["qualification_reference"] or "qualification pending"
    return (
        f"{assignment['reviewer_name']} ({assignment['status']}; "
        f"{qualification})"
    )


if __name__ == "__main__":
    raise SystemExit(main())

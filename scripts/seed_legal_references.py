#!/usr/bin/env python3
"""Seed starter legal research leads for Macedonian political communications."""

import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.models.database import (
    LegalDocument,
    LegalSourceStatus,
    create_all_tables,
    get_engine,
    get_session_factory,
)


STARTER_REFERENCES = [
    {
        "title": "Constitution of the Republic of North Macedonia",
        "country_code": "mk",
        "legal_area": "constitutional law; freedom of expression; public institutions",
        "source_url": "https://www.sobranie.mk/the-constitution-ofthe-republic-of-macedonia-ns_article-constitution-of-the-republic-of-north-macedonia.nspx",
        "source_name": "Assembly of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "en",
        "tags": ["constitution", "rights", "institutions", "official"],
        "summary": (
            "Official Assembly page for the Constitution. Use as the first legal research lead "
            "for constitutional rights, institutional powers, and lawful public communication."
        ),
        "reference_text": (
            "Research lead only. Cite exact constitutional articles only after human review of "
            "the official text and any applicable amendments."
        ),
        "article_refs": "Constitution and amendments; verify exact article numbers before use.",
        "confidence_score": 0.75,
        "notes": "Official source. Still requires lawyer/legal review before client-facing legal claims.",
    },
    {
        "title": "Official Gazette Constitution PDF",
        "country_code": "mk",
        "legal_area": "constitutional law; official gazette reference",
        "source_url": "https://www.slvesnik.com.mk/content/pdf/USTAV-eng.pdf",
        "source_name": "Official Gazette of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "en",
        "tags": ["constitution", "official gazette", "pdf"],
        "summary": (
            "Official Gazette PDF copy of the Constitution in English. Useful for offline "
            "reference, but exact article use should be checked against the latest official text."
        ),
        "reference_text": "Research lead only; verify amendments and current consolidated status.",
        "article_refs": "Constitution PDF; verify amendments before relying on exact text.",
        "confidence_score": 0.7,
        "notes": "Use as a citation lead, not automated legal advice.",
    },
    {
        "title": "Ministry of Justice legal database",
        "country_code": "mk",
        "legal_area": "legal research; laws and regulations",
        "source_url": "https://www.pravda.gov.mk/mk-MK/registri/ldbis-pravna-baza-na-zakoni-i-propisi",
        "source_name": "Ministry of Justice of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["laws", "regulations", "legal database", "official"],
        "summary": (
            "Official Ministry of Justice entry point for the legal database of laws and regulations. "
            "Use this to locate the latest legal texts before drafting legal references."
        ),
        "reference_text": (
            "Research lead only. Search the database for the specific law, then store the exact "
            "official document and review status separately."
        ),
        "article_refs": "LDBIS legal database; specific laws must be added as separate reviewed references.",
        "confidence_score": 0.65,
        "notes": "Best starter source for finding current Macedonian legal texts.",
    },
    {
        "title": "Ministry of Justice laws and regulation page",
        "country_code": "mk",
        "legal_area": "legal research; laws and regulations",
        "source_url": "https://www.pravda.gov.mk/en-GB/regulativa/zakoni",
        "source_name": "Ministry of Justice of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "en",
        "tags": ["laws", "regulations", "official"],
        "summary": (
            "Official Ministry of Justice regulation/laws page. Use as an English-language "
            "entry point for legal research leads."
        ),
        "reference_text": "Research lead only; locate and verify the specific law text before citation.",
        "article_refs": "Ministry regulation/laws page; not a substitute for the exact law text.",
        "confidence_score": 0.55,
        "notes": "Can help operators find relevant law pages; final legal review still required.",
    },
    {
        "title": "Free legal aid official service page",
        "country_code": "mk",
        "legal_area": "access to justice; legal support",
        "source_url": "https://www.pravda.gov.mk/en-GB/uslugi/besplatna-pravna-pomos",
        "source_name": "Ministry of Justice of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "en",
        "tags": ["free legal aid", "access to justice", "official"],
        "summary": (
            "Official Ministry page for free legal aid. Useful as a research lead when a response "
            "pack should recommend legal assistance or rights-support resources."
        ),
        "reference_text": "Research lead only; verify current eligibility and procedure before advising anyone.",
        "article_refs": "Free legal assistance service information.",
        "confidence_score": 0.55,
        "notes": "Operational reference, not a legal opinion.",
    },
    {
        "title": "Law on Civil Liability for Insult and Defamation - research lead",
        "country_code": "mk",
        "legal_area": "defamation; insult; civil liability; media response",
        "source_url": "https://slvesnik.com.mk/Issues/f42e17c5726e4545859991e55606982e.pdf",
        "source_name": "Official Gazette of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["defamation", "insult", "civil liability", "media"],
        "summary": (
            "Research lead for political response packs involving insult, defamation, and reputational attacks. "
            "Operators must locate the exact current law text and article numbers before citing it."
        ),
        "reference_text": "Needs exact law text extraction and Macedonian lawyer review before use as legal support.",
        "article_refs": "Find exact law and article references in the official legal database.",
        "confidence_score": 0.45,
        "notes": "Official Gazette 251/2022 source located. Import exact text and obtain lawyer review before client use.",
    },
    {
        "title": "Electoral Code - research lead",
        "country_code": "mk",
        "legal_area": "elections; campaign conduct; electoral rules",
        "source_url": "https://www.sobranie.mk/izborni-zakoni.nspx",
        "source_name": "Assembly of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["elections", "campaign", "electoral code"],
        "summary": (
            "Research lead for campaign-period claims, election conduct, public communication, and party briefings. "
            "Verify current amendments and exact provisions before advice."
        ),
        "reference_text": "Needs exact Electoral Code text and amendment review before citation.",
        "article_refs": "Find exact Electoral Code article references in the official legal database.",
        "confidence_score": 0.45,
        "notes": "Official Assembly election-law collection. Current amendments and exact provisions still require lawyer review.",
    },
    {
        "title": "Criminal Code and Criminal Procedure - research lead",
        "country_code": "mk",
        "legal_area": "criminal law; criminal procedure; presumption of innocence",
        "source_url": "https://ldbis.pravda.gov.mk/PregledNaZakon.aspx?id=72834",
        "source_name": "Ministry of Justice LDBIS",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["criminal", "procedure", "presumption", "allegations"],
        "summary": (
            "Research lead for allegations of crime, corruption, investigations, charges, and court proceedings. "
            "Response drafts should separate allegation, investigation, charge, and final judgment."
        ),
        "reference_text": "Needs exact Criminal Code and Criminal Procedure provisions before any legal claim.",
        "article_refs": "Find exact law/article references in the official legal database.",
        "confidence_score": 0.45,
        "notes": "Official LDBIS law chain includes 2026 amendments. Counsel must identify the applicable consolidated provision.",
    },
    {
        "title": "Anti-corruption and conflict of interest law - research lead",
        "country_code": "mk",
        "legal_area": "anti-corruption; conflict of interest; public office",
        "source_url": "https://www.dksk.mk/fileadmin/user_upload/Zakon_za_sprecuvanje_na_korupcija_i_sudirot_na_interesi.pdf",
        "source_name": "State Commission for Prevention of Corruption",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["corruption", "conflict of interest", "public office"],
        "summary": (
            "Research lead for corruption/conflict-of-interest claims in political monitoring and due diligence. "
            "Use official findings or proceedings before making direct allegations."
        ),
        "reference_text": "Needs exact current law text and official body references before use.",
        "article_refs": "Find exact anti-corruption/conflict-of-interest law references in the official database.",
        "confidence_score": 0.45,
        "notes": "Official regulator-hosted law text. Check later amendments and obtain lawyer review before conclusions.",
    },
    {
        "title": "Free Access to Public Information law - research lead",
        "country_code": "mk",
        "legal_area": "free access to public information; transparency; public information",
        "source_url": "https://slvesnik.com.mk/content/zspijk.pdf",
        "source_name": "Official Gazette of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["public information", "transparency", "access to information"],
        "summary": (
            "Research lead for press-conference recommendations that ask institutions to publish documents, "
            "answer information requests, or clarify public records."
        ),
        "reference_text": "Needs exact current law text and procedure verification before advising a request.",
        "article_refs": "Find exact free-access-to-public-information references in the official database.",
        "confidence_score": 0.45,
        "notes": "Official Gazette editorial consolidated text. Verify current amendments and procedure with counsel.",
    },
    {
        "title": "Media and audiovisual services regulation - research lead",
        "country_code": "mk",
        "legal_area": "media regulation; audiovisual services; public communication",
        "source_url": "https://avmu.mk/закон-за-аудио-и-аудиовизуелни-медиум/",
        "source_name": "Agency for Audio and Audiovisual Media Services",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["media", "audiovisual", "public communication"],
        "summary": (
            "Research lead for media-response, broadcast, and public-communication questions. "
            "Verify the current media-law text and regulator guidance before relying on it."
        ),
        "reference_text": "Needs exact media/audiovisual law text and regulator context before citation.",
        "article_refs": "Find exact media regulation references in the official database.",
        "confidence_score": 0.45,
        "notes": "Official regulator amendment collection through 2025. Counsel must determine which provisions apply.",
    },
    {
        "title": "General Administrative Procedure Act - research lead",
        "country_code": "mk",
        "legal_area": "administrative procedure; public institutions; administrative decisions",
        "source_url": "https://ldbis.pravda.gov.mk/PregledNaZakon.aspx?id=37954",
        "source_name": "Ministry of Justice LDBIS",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["administrative procedure", "public institutions", "official decisions"],
        "summary": (
            "Official LDBIS law record for general administrative procedure. Useful when a "
            "briefing concerns an institution's procedure, notice, decision, appeal, or deadline."
        ),
        "reference_text": (
            "Research lead only. Counsel must identify the current consolidated provision and "
            "confirm that the administrative procedure applies to the specific institution."
        ),
        "article_refs": "Act and linked amendments; verify current article and effective date.",
        "confidence_score": 0.55,
        "notes": "Official law record. Exact application and later amendments require lawyer review.",
    },
    {
        "title": "Whistleblower Protection Act - research lead",
        "country_code": "mk",
        "legal_area": "whistleblower protection; protected reporting; public interest",
        "source_url": "https://dksk.mk/mk/заштита-на-укажувачите/",
        "source_name": "State Commission for Prevention of Corruption",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["whistleblower", "protected reporting", "public interest", "corruption"],
        "summary": (
            "Official regulator page explaining protected reporting and linking the whistleblower "
            "protection law and procedures."
        ),
        "reference_text": (
            "Research lead only. Do not identify or advise a whistleblower from automated output; "
            "obtain specialist legal review before any public response."
        ),
        "article_refs": "Whistleblower protection law and regulator procedures.",
        "confidence_score": 0.55,
        "notes": "High-sensitivity area. Human legal and privacy review is mandatory.",
    },
    {
        "title": "Lobbying Act - research lead",
        "country_code": "mk",
        "legal_area": "lobbying; public policy influence; public officials",
        "source_url": "https://www.slvesnik.com.mk/Issues/893cad07af514b83aac5d9a4ac6d5341.pdf",
        "source_name": "Official Gazette of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["lobbying", "public officials", "public policy", "transparency"],
        "summary": (
            "Official Gazette issue containing the 2021 Lobbying Act. Useful for claims about "
            "registered lobbying, influence on public policy, and communications with officials."
        ),
        "reference_text": (
            "Research lead only. Counsel must confirm the exact provision, exclusions, registration "
            "status, and any later amendments before a client makes a legal assertion."
        ),
        "article_refs": "Official Gazette 122/2021; verify amendments and applicable provisions.",
        "confidence_score": 0.55,
        "notes": "Official Gazette source. Requires consolidated-law and lawyer review.",
    },
    {
        "title": "Rules of Procedure of the Assembly - research lead",
        "country_code": "mk",
        "legal_area": "parliamentary procedure; public sessions; legislative process",
        "source_url": "https://www.sobranie.mk/delovnik-na-sobranieto-na-republika-makedonija-precisten-tekst.nspx",
        "source_name": "Assembly of the Republic of North Macedonia",
        "source_status": LegalSourceStatus.OFFICIAL,
        "language": "mk",
        "tags": ["assembly", "parliamentary procedure", "legislative process", "public sessions"],
        "summary": (
            "Official Assembly consolidated rules page covering organization, sessions, public "
            "proceedings, legislative procedure, resolutions, and parliamentary acts."
        ),
        "reference_text": (
            "Research lead only. Confirm later amendments and the exact procedural article before "
            "using it in a press conference or political response."
        ),
        "article_refs": "Assembly rules and amendments; verify current consolidated status.",
        "confidence_score": 0.55,
        "notes": "Official Assembly source. Current procedural applicability requires counsel review.",
    },
]


def main():
    parser = argparse.ArgumentParser(description="Seed starter Macedonian legal references")
    parser.add_argument("--apply", action="store_true", help="Write references to the database")
    parser.add_argument(
        "--refresh-official",
        action="store_true",
        help="Refresh source/status metadata for matching existing references",
    )
    args = parser.parse_args()

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    session_factory = get_session_factory(engine)
    db = session_factory()
    try:
        created = 0
        skipped = 0
        for reference in STARTER_REFERENCES:
            existing = (
                db.query(LegalDocument)
                .filter(
                    LegalDocument.title == reference["title"],
                    LegalDocument.country_code == reference["country_code"],
                )
                .first()
            )
            if existing:
                if args.apply and args.refresh_official:
                    for field in (
                        "source_url", "source_name", "source_status", "summary",
                        "reference_text", "article_refs", "confidence_score", "notes",
                    ):
                        setattr(existing, field, reference[field])
                    existing.date_accessed = datetime.datetime.utcnow()
                skipped += 1
                continue
            if args.apply:
                db.add(LegalDocument(
                    **reference,
                    date_accessed=datetime.datetime.utcnow(),
                ))
            created += 1
        if args.apply:
            db.commit()
        action = "Inserted" if args.apply else "Would insert"
        print(f"{action}: {created}; skipped existing: {skipped}")
        if not args.apply:
            print("Dry run only. Re-run with --apply to write these research leads.")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()

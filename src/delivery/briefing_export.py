"""PDF exports for party briefings and response packs."""

import datetime
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.models.database import Client


BRAND_PRIMARY = HexColor("#102a43")
BRAND_ACCENT = HexColor("#d94f45")
BRAND_GREEN = HexColor("#147c80")
BRAND_LIGHT = HexColor("#f4f7f9")
BRAND_TEXT = HexColor("#243b53")
BRAND_MUTED = HexColor("#6b7c8f")
BRAND_WHITE = HexColor("#ffffff")
BRAND_BORDER = HexColor("#d9e2ec")
BRAND_WARNING_BG = HexColor("#fff4e6")
BRAND_WARNING_TEXT = HexColor("#8a4b0f")


class BriefingExportGenerator:
    """Generate client-ready PDF exports from structured briefing data."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.styles = getSampleStyleSheet()
        self._init_styles()

    def _init_styles(self) -> None:
        self.styles.add(ParagraphStyle(
            "ExportTitle",
            parent=self.styles["Title"],
            fontSize=23,
            leading=29,
            textColor=BRAND_PRIMARY,
            alignment=TA_CENTER,
            spaceAfter=10,
        ))
        self.styles.add(ParagraphStyle(
            "ExportSubtitle",
            parent=self.styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=BRAND_MUTED,
            alignment=TA_CENTER,
            spaceAfter=12,
        ))
        self.styles.add(ParagraphStyle(
            "SectionTitle",
            parent=self.styles["Heading2"],
            fontSize=14,
            leading=18,
            textColor=BRAND_PRIMARY,
            spaceBefore=14,
            spaceAfter=8,
        ))
        self.styles.add(ParagraphStyle(
            "BodyNI",
            parent=self.styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=BRAND_TEXT,
            alignment=TA_LEFT,
            spaceAfter=6,
        ))
        self.styles.add(ParagraphStyle(
            "SmallNI",
            parent=self.styles["Normal"],
            fontSize=8,
            leading=11,
            textColor=BRAND_MUTED,
            spaceAfter=4,
        ))
        self.styles.add(ParagraphStyle(
            "TableCellNI",
            parent=self.styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=BRAND_TEXT,
        ))
        self.styles.add(ParagraphStyle(
            "TableHeaderNI",
            parent=self.styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=BRAND_WHITE,
            fontName="Helvetica-Bold",
        ))
        self.styles.add(ParagraphStyle(
            "GuardrailNI",
            parent=self.styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=BRAND_WARNING_TEXT,
        ))

    def generate_party_briefing(self, client: Client, payload: dict) -> Path:
        topic = payload.get("topic") or "party_briefing"
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filepath = self.output_dir / f"party_briefing_{client.id}_{self._slug(topic)}_{timestamp}.pdf"
        doc = self._document(filepath, f"Party Briefing - {topic}")

        story = self._header("Party Press Briefing", client, payload.get("date_range"))
        story.extend(self._snapshot_section("Briefing Snapshot", [
            ("Topic", topic),
            ("Objective", payload.get("objective") or "Not specified"),
            ("Audience", payload.get("audience") or "Not specified"),
            ("Tone", payload.get("tone") or "Not specified"),
            ("Source articles", str(len(payload.get("source_articles") or []))),
        ]))
        story.extend(self._guardrail_section("party briefing"))
        story.extend(self._confidence(payload.get("confidence") or {}))
        story.extend(self._grounding_contract_section(payload.get("grounding_contract") or {}))
        story.extend(self._paragraph_section("Coverage Summary", payload.get("coverage_summary")))
        story.extend(self._evidence_section(payload.get("evidence_brief") or []))
        story.extend(self._citation_pack_section(payload.get("citation_pack") or []))
        story.extend(self._claim_support_section(payload.get("claim_support_matrix") or []))
        story.extend(self._list_section("Claims To Verify Before Speaking", payload.get("claims_to_verify") or []))
        story.extend(self._list_section("Suggested Talking Points", payload.get("suggested_talking_points") or []))
        story.extend(self._list_section("Press Conference Flow", payload.get("press_conference_outline") or []))
        story.extend(self._list_section("Do Not Say Unless Verified", payload.get("do_not_say_unless_verified") or []))
        story.extend(self._list_section("Risk Warnings", payload.get("risk_warnings") or []))
        story.extend(self._legal_section(payload.get("legal_context") or []))
        story.extend(self._source_section(payload.get("source_articles") or []))
        story.extend(self._disclaimer(payload.get("disclaimer")))
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return filepath

    def generate_response_pack(self, client: Client, payload: dict) -> Path:
        item = payload.get("watchlist_item") or {}
        title = item.get("label") or "response_pack"
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filepath = self.output_dir / f"response_pack_{client.id}_{self._slug(title)}_{timestamp}.pdf"
        doc = self._document(filepath, f"Response Pack - {title}")

        story = self._header("Response Pack", client, f"Severity: {payload.get('severity', 'unknown')}")
        story.extend(self._snapshot_section("Response Snapshot", [
            ("Tracked item", title),
            ("Severity", payload.get("severity") or "unknown"),
            ("Recommended posture", payload.get("recommended_posture") or "Not available"),
            ("Evidence items", str(len(payload.get("evidence_brief") or []))),
            ("Legal flags", str(len(payload.get("legal_review_flags") or []))),
        ]))
        story.extend(self._guardrail_section("response pack"))
        story.extend(self._confidence(payload.get("confidence") or {}))
        story.extend(self._grounding_contract_section(payload.get("grounding_contract") or {}))
        story.extend(self._paragraph_section("Situation Summary", payload.get("situation_summary")))
        story.extend(self._paragraph_section("Recommended Posture", payload.get("recommended_posture")))
        story.extend(self._evidence_section(payload.get("evidence_brief") or []))
        story.extend(self._citation_pack_section(payload.get("citation_pack") or []))
        story.extend(self._claim_support_section(payload.get("claim_support_matrix") or []))
        story.extend(self._list_section("Claims To Verify Before Responding", payload.get("claims_to_verify") or []))
        story.extend(self._list_section("Legal Review Flags", payload.get("legal_review_flags") or []))
        story.extend(self._legal_section(payload.get("legal_context") or []))
        story.extend(self._list_section("Evidence Steps", payload.get("evidence_steps") or []))
        story.extend(self._drafts_section(payload.get("draft_responses") or []))
        story.extend(self._source_section(payload.get("source_articles") or []))
        story.extend(self._disclaimer(payload.get("disclaimer")))
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return filepath

    def generate_client_daily_brief(self, client: Client, payload: dict) -> Path:
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filepath = self.output_dir / f"client_daily_brief_{client.id}_{self._slug(client.name)}_{timestamp}.pdf"
        doc = self._document(filepath, f"Client Daily Brief - {client.name}")

        story = self._header("Client Daily Brief", client, f"{payload.get('period_days', 1)} day window")
        story.extend(self._snapshot_section("Daily Snapshot", [
            ("Period", f"{payload.get('period_days', 1)} day window"),
            ("Headline", payload.get("headline") or "No headline"),
            ("Matched articles", str(len(payload.get("matched_articles") or []))),
            ("Evidence items", str(len(payload.get("evidence_brief") or []))),
            ("Risk items", str(len(payload.get("risk_items") or []))),
        ]))
        story.extend(self._guardrail_section("daily brief"))
        story.extend(self._paragraph_section("Headline", payload.get("headline")))
        story.extend(self._paragraph_section("Summary", payload.get("summary")))
        story.extend(self._evidence_section(payload.get("evidence_brief") or []))
        story.extend(self._list_section("Recommended Actions", payload.get("recommended_actions") or []))
        story.extend(self._risk_section(payload.get("risk_items") or []))
        story.extend(self._source_section(payload.get("matched_articles") or []))
        story.extend(self._disclaimer(
            "This client brief is communications intelligence from stored sources, not legal advice."
        ))
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return filepath

    def generate_entity_briefing(self, payload: dict) -> Path:
        entity = self._as_dict(payload.get("entity") or {})
        entity_name = entity.get("name") or "entity"
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filepath = self.output_dir / f"entity_briefing_{self._slug(entity_name)}_{timestamp}.pdf"
        doc = self._document(filepath, f"Entity Dossier - {entity_name}")

        story = self._entity_header(entity_name, entity, f"{payload.get('period_days', 90)} day dossier")
        story.extend(self._snapshot_section("Entity Snapshot", [
            ("Entity", entity_name),
            ("Type", entity.get("entity_type") or "unknown"),
            ("Mentions", str(entity.get("total_mentions", 0))),
            ("Period", f"{payload.get('period_days', 90)} days"),
            ("Evidence items", str(len(payload.get("evidence_brief") or []))),
        ]))
        story.extend(self._guardrail_section("entity dossier"))
        story.extend(self._paragraph_section("Headline", payload.get("headline")))
        story.extend(self._paragraph_section("Dossier Summary", payload.get("summary")))
        story.extend(self._entity_signal_section(payload))
        story.extend(self._evidence_section(payload.get("evidence_brief") or []))
        story.extend(self._connected_entities_section(payload.get("connected_entities") or []))
        story.extend(self._list_section("Verification Notes", payload.get("recommended_actions") or []))
        story.extend(self._source_section(payload.get("source_articles") or []))
        story.extend(self._disclaimer(
            "This entity dossier is source-backed communications intelligence. Verify original sources before external use."
        ))
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return filepath

    def _document(self, filepath: Path, title: str) -> SimpleDocTemplate:
        return SimpleDocTemplate(
            str(filepath),
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title=title,
        )

    def _header(self, title: str, client: Client, subtitle: str | None) -> list:
        generated_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        plan = client.plan.value if hasattr(client.plan, "value") else str(client.plan)
        table = Table([
            ["Client", self._safe(client.name)],
            ["Plan", self._safe(plan)],
            ["Generated", generated_at],
        ], colWidths=[3.5 * cm, 11 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BRAND_PRIMARY),
            ("TEXTCOLOR", (0, 0), (0, -1), BRAND_WHITE),
            ("BACKGROUND", (1, 0), (1, -1), BRAND_LIGHT),
            ("TEXTCOLOR", (1, 0), (1, -1), BRAND_TEXT),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, BRAND_MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return [
            Paragraph(title, self.styles["ExportTitle"]),
            Paragraph(self._safe(subtitle or "Client-ready intelligence export"), self.styles["ExportSubtitle"]),
            HRFlowable(width="55%", thickness=2, color=BRAND_ACCENT),
            Spacer(1, 0.5 * cm),
            table,
            Spacer(1, 0.35 * cm),
        ]

    def _entity_header(self, title: str, entity: dict, subtitle: str | None) -> list:
        generated_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        table = Table([
            ["Entity", self._safe(title)],
            ["Type", self._safe(entity.get("entity_type") or "unknown")],
            ["Mentions", str(entity.get("total_mentions", 0))],
            ["Generated", generated_at],
        ], colWidths=[3.5 * cm, 11 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BRAND_PRIMARY),
            ("TEXTCOLOR", (0, 0), (0, -1), BRAND_WHITE),
            ("BACKGROUND", (1, 0), (1, -1), BRAND_LIGHT),
            ("TEXTCOLOR", (1, 0), (1, -1), BRAND_TEXT),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, BRAND_MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return [
            Paragraph(f"Entity Dossier: {self._safe(title)}", self.styles["ExportTitle"]),
            Paragraph(self._safe(subtitle or "Source-backed entity profile"), self.styles["ExportSubtitle"]),
            HRFlowable(width="55%", thickness=2, color=BRAND_ACCENT),
            Spacer(1, 0.5 * cm),
            table,
            Spacer(1, 0.35 * cm),
        ]

    def _confidence(self, confidence: dict) -> list:
        if not confidence:
            return []
        rows = [
            ["Confidence", f"{confidence.get('level', 'unknown')} ({confidence.get('score', '-')}/100)"],
            ["Articles", str(confidence.get("article_count", 0))],
            ["Sources", str(confidence.get("source_count", 0))],
            ["Official legal refs", str(confidence.get("official_legal_refs", 0))],
        ]
        table = Table(rows, colWidths=[4 * cm, 10.5 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BRAND_GREEN),
            ("TEXTCOLOR", (0, 0), (0, -1), BRAND_WHITE),
            ("BACKGROUND", (1, 0), (1, -1), BRAND_LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.2, BRAND_MUTED),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements = [Paragraph("Confidence", self.styles["SectionTitle"]), table]
        if confidence.get("reason"):
            elements.append(Paragraph(self._safe(confidence["reason"]), self.styles["SmallNI"]))
        return elements

    def _snapshot_section(self, title: str, rows: list[tuple[str, str]]) -> list:
        table_rows = []
        for label, value in rows:
            table_rows.append([
                Paragraph(self._safe(label), self.styles["TableHeaderNI"]),
                Paragraph(self._safe(value), self.styles["TableCellNI"]),
            ])
        table = Table(table_rows, colWidths=[4 * cm, 10.5 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BRAND_PRIMARY),
            ("BACKGROUND", (1, 0), (1, -1), BRAND_LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.25, BRAND_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return [Paragraph(title, self.styles["SectionTitle"]), table]

    def _guardrail_section(self, report_type: str) -> list:
        text = (
            f"This {report_type} must stay evidence-first. Use the citation labels, dates, "
            "source names, and URLs when speaking externally. Do not present single-source "
            "or unsupported claims as fact. Legal interpretations require official text "
            "and review by qualified Macedonian counsel before public use."
        )
        table = Table([[Paragraph(self._safe(text), self.styles["GuardrailNI"])]], colWidths=[14.5 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_WARNING_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, BRAND_WARNING_TEXT),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        return [Spacer(1, 0.2 * cm), table, Spacer(1, 0.15 * cm)]

    def _grounding_contract_section(self, contract: dict) -> list:
        if not contract:
            return []
        rows = [
            ["Decision", contract.get("decision", "unknown")],
            ["Public use", contract.get("public_use", "Verify before public use.")],
            ["Evidence", f"{contract.get('article_count', 0)} articles / {contract.get('source_count', 0)} sources"],
            ["Citations", str(contract.get("citation_count", 0))],
            ["Unsupported claims", str(contract.get("unsupported_claim_count", 0))],
            ["Single-source claims", str(contract.get("single_source_claim_count", 0))],
            ["Legal review items", str(contract.get("legal_review_count", 0))],
        ]
        table = Table(
            [[self._cell(label), self._cell(str(value))] for label, value in rows],
            colWidths=[4 * cm, 10.5 * cm],
        )
        table.setStyle(self._data_table_style())
        elements = [Paragraph("Grounding Contract", self.styles["SectionTitle"]), table]
        blocked = contract.get("blocked_public_claims") or []
        if blocked:
            elements.extend(self._list_section("Blocked Public Claims", blocked))
        return elements

    def _paragraph_section(self, title: str, text: str | None) -> list:
        return [
            Paragraph(title, self.styles["SectionTitle"]),
            Paragraph(self._safe(text or "No content available."), self.styles["BodyNI"]),
        ]

    def _list_section(self, title: str, items: list[str]) -> list:
        return [
            Paragraph(title, self.styles["SectionTitle"]),
            self._bullet_list(items or ["No items available."]),
        ]

    def _evidence_section(self, items: list[dict]) -> list:
        elements = [Paragraph("Source-Backed Evidence", self.styles["SectionTitle"])]
        if not items:
            elements.append(Paragraph("No evidence bullets available.", self.styles["BodyNI"]))
            return elements
        for item in items:
            meta = self._citation(item)
            elements.append(Paragraph(self._safe(item.get("claim") or "Untitled source item"), self.styles["BodyNI"]))
            elements.append(Paragraph(self._safe(meta), self.styles["SmallNI"]))
            elements.append(Paragraph(self._safe(item.get("use_in_briefing") or ""), self.styles["SmallNI"]))
            elements.append(Spacer(1, 0.15 * cm))
        return elements

    def _citation_pack_section(self, items: list[dict]) -> list:
        elements = [Paragraph("Citation Pack", self.styles["SectionTitle"])]
        if not items:
            elements.append(Paragraph("No citations available.", self.styles["BodyNI"]))
            return elements
        rows = [[
            Paragraph("Label", self.styles["TableHeaderNI"]),
            Paragraph("Claim / Use", self.styles["TableHeaderNI"]),
            Paragraph("Source", self.styles["TableHeaderNI"]),
            Paragraph("Date", self.styles["TableHeaderNI"]),
            Paragraph("URL", self.styles["TableHeaderNI"]),
        ]]
        for item in items[:24]:
            label = f"[{item.get('label') or 'S?'}]"
            claim = item.get("claim") or item.get("inline") or "Source item"
            safe_use = item.get("safe_use") or "Verify against the original source before use."
            rows.append([
                self._cell(label),
                self._cell(f"{claim}\n{safe_use}"),
                self._cell(item.get("source_name") or "Unknown"),
                self._cell(self._date(item.get("published_at"))),
                self._cell(self._compact_url(item.get("url"))),
            ])
        table = Table(rows, colWidths=[1.5 * cm, 5.1 * cm, 2.6 * cm, 2.2 * cm, 3.1 * cm], repeatRows=1)
        table.setStyle(self._data_table_style())
        elements.append(table)
        return elements

    def _claim_support_section(self, items: list[dict]) -> list:
        elements = [Paragraph("Claim Support Matrix", self.styles["SectionTitle"])]
        if not items:
            elements.append(Paragraph("No requested claims were classified.", self.styles["BodyNI"]))
            return elements
        rows = [[
            Paragraph("Claim", self.styles["TableHeaderNI"]),
            Paragraph("Status", self.styles["TableHeaderNI"]),
            Paragraph("Evidence", self.styles["TableHeaderNI"]),
            Paragraph("Safe Use", self.styles["TableHeaderNI"]),
        ]]
        for item in items[:12]:
            evidence = (
                f"{item.get('supporting_article_count', 0)} articles / "
                f"{item.get('supporting_source_count', 0)} sources"
            )
            if item.get("legal_review_required"):
                evidence += "\nLegal review required"
            rows.append([
                self._cell(item.get("claim") or "Claim"),
                self._cell(item.get("status") or "unknown"),
                self._cell(evidence),
                self._cell(item.get("safe_use") or "Verify before public use."),
            ])
        table = Table(rows, colWidths=[4.7 * cm, 2.8 * cm, 2.8 * cm, 4.2 * cm], repeatRows=1)
        table.setStyle(self._data_table_style())
        elements.append(table)
        return elements

    def _legal_section(self, items: list[dict]) -> list:
        elements = [Paragraph("Legal Context", self.styles["SectionTitle"])]
        if not items:
            elements.append(Paragraph("No legal references available.", self.styles["BodyNI"]))
            return elements
        rows = [[
            Paragraph("Area", self.styles["TableHeaderNI"]),
            Paragraph("Status", self.styles["TableHeaderNI"]),
            Paragraph("Safe Use", self.styles["TableHeaderNI"]),
            Paragraph("Source", self.styles["TableHeaderNI"]),
        ]]
        for item in items:
            status = item.get("legal_basis_status") or item.get("status") or "unknown"
            if item.get("requires_lawyer_review"):
                status = f"{status}\nLawyer review required"
            rows.append([
                self._cell(f"{item.get('area') or 'Legal reference'}\n{item.get('guidance') or ''}"),
                self._cell(status),
                self._cell(item.get("safe_use") or item.get("warning") or "Verify before public use."),
                self._cell(item.get("source_url") or item.get("article_refs") or "No source URL"),
            ])
        table = Table(rows, colWidths=[4.3 * cm, 3.1 * cm, 4.4 * cm, 2.7 * cm], repeatRows=1)
        table.setStyle(self._data_table_style())
        elements.append(table)
        return elements

    def _drafts_section(self, drafts: list[dict]) -> list:
        elements = [Paragraph("Draft Responses", self.styles["SectionTitle"])]
        if not drafts:
            elements.append(Paragraph("No draft responses available.", self.styles["BodyNI"]))
            return elements
        for draft in drafts:
            tone = str(draft.get("tone", "draft")).title()
            status = str(draft.get("status") or "internal_review").replace("_", " ")
            readiness = str(draft.get("public_readiness") or "caution").replace("_", " ")
            risk = str(draft.get("risk_level") or "medium")
            use_case = str(draft.get("use_case") or "Use only with the attached citation and verification trail.")
            elements.append(Paragraph(self._safe(f"{tone} - {status}"), self.styles["BodyNI"]))
            elements.append(Paragraph(self._safe(f"Readiness: {readiness}; risk: {risk}; use: {use_case}"), self.styles["SmallNI"]))
            elements.append(Paragraph(self._safe("English draft"), self.styles["SmallNI"]))
            elements.append(Paragraph(self._safe(str(draft.get("text", ""))), self.styles["SmallNI"]))
            if draft.get("mk_text"):
                elements.append(Paragraph(self._safe("Macedonian working draft"), self.styles["SmallNI"]))
                elements.append(Paragraph(self._safe(str(draft.get("mk_text", ""))), self.styles["SmallNI"]))
        return elements

    def _risk_section(self, risks: list[dict]) -> list:
        elements = [Paragraph("Risk Signals", self.styles["SectionTitle"])]
        if not risks:
            elements.append(Paragraph("No risk signals in this brief window.", self.styles["BodyNI"]))
            return elements
        for risk in risks[:8]:
            meta = (
                f"Severity: {risk.get('severity', 'unknown')}; "
                f"articles: {risk.get('article_count', 0)}; "
                f"sources: {risk.get('source_count', 0)}"
            )
            elements.append(Paragraph(self._safe(risk.get("label") or "Risk signal"), self.styles["BodyNI"]))
            elements.append(Paragraph(self._safe(meta), self.styles["SmallNI"]))
            elements.append(Paragraph(self._safe(risk.get("recommended_action") or ""), self.styles["SmallNI"]))
        return elements

    def _entity_signal_section(self, payload: dict) -> list:
        sentiment = payload.get("sentiment") or {}
        sources = payload.get("source_coverage") or []
        timeline = payload.get("mention_timeline") or []
        peak = max(timeline, key=lambda item: item.get("mentions", 0), default={})
        rows = [
            ["Sentiment", f"{sentiment.get('label', 'neutral')} ({sentiment.get('score', 0)})"],
            ["Scored mentions", str(sentiment.get("scored_mentions", 0))],
            ["Sources", str(len(sources))],
            ["Peak day", f"{peak.get('date', 'n/a')} ({peak.get('mentions', 0)} mentions)"],
        ]
        table = Table(rows, colWidths=[4 * cm, 10.5 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BRAND_GREEN),
            ("TEXTCOLOR", (0, 0), (0, -1), BRAND_WHITE),
            ("BACKGROUND", (1, 0), (1, -1), BRAND_LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.2, BRAND_MUTED),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements = [Paragraph("Entity Signals", self.styles["SectionTitle"]), table]
        if sources:
            lines = [
                f"{source.get('source_name', 'Unknown')}: {source.get('article_count', 0)} articles, {source.get('mention_count', 0)} mentions"
                for source in sources[:8]
            ]
            elements.append(Paragraph(self._safe("Top sources: " + "; ".join(lines)), self.styles["SmallNI"]))
        return elements

    def _connected_entities_section(self, entities: list[dict]) -> list:
        elements = [Paragraph("Connected Entities", self.styles["SectionTitle"])]
        if not entities:
            elements.append(Paragraph("No connected entities found.", self.styles["BodyNI"]))
            return elements
        rows = [["Entity", "Type", "Shared articles", "Mentions"]]
        for entity in entities[:10]:
            rows.append([
                self._safe(entity.get("name") or "Unknown"),
                self._safe(entity.get("entity_type") or "unknown"),
                str(entity.get("shared_articles", 0)),
                str(entity.get("mention_count", 0)),
            ])
        table = Table(rows, colWidths=[6.5 * cm, 3 * cm, 2.5 * cm, 2.5 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_WHITE),
            ("BACKGROUND", (0, 1), (-1, -1), BRAND_LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.2, BRAND_MUTED),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)
        return elements

    def _source_section(self, articles: list[dict]) -> list:
        elements = [Paragraph("Source Trail", self.styles["SectionTitle"])]
        if not articles:
            elements.append(Paragraph("No source articles available.", self.styles["BodyNI"]))
            return elements
        rows = [[
            Paragraph("Source", self.styles["TableHeaderNI"]),
            Paragraph("Published / Fetched", self.styles["TableHeaderNI"]),
            Paragraph("Article", self.styles["TableHeaderNI"]),
            Paragraph("URL", self.styles["TableHeaderNI"]),
        ]]
        for article in articles[:24]:
            article = self._as_dict(article)
            rows.append([
                self._cell(article.get("source_name") or "Unknown"),
                self._cell(
                    f"Published: {self._date(article.get('published_at'))}\n"
                    f"Fetched: {self._date(article.get('fetched_at'))}"
                ),
                self._cell(article.get("title") or "Untitled"),
                self._cell(self._compact_url(article.get("url"))),
            ])
        table = Table(rows, colWidths=[2.8 * cm, 3.1 * cm, 5.3 * cm, 3.3 * cm], repeatRows=1)
        table.setStyle(self._data_table_style())
        elements.append(table)
        return elements

    def _disclaimer(self, text: str | None) -> list:
        return [
            Spacer(1, 0.35 * cm),
            HRFlowable(width="100%", thickness=1, color=BRAND_GREEN),
            Spacer(1, 0.2 * cm),
            Paragraph(
                self._safe(text or "This export is communications intelligence, not legal advice."),
                self.styles["SmallNI"],
            ),
        ]

    def _bullet_list(self, items: list[str]) -> ListFlowable:
        return ListFlowable(
            [ListItem(Paragraph(self._safe(str(item)), self.styles["BodyNI"])) for item in items],
            bulletType="bullet",
            leftIndent=16,
        )

    def _cell(self, value) -> Paragraph:
        text = "<br/>".join(escape(part) for part in str(value or "").splitlines())
        return Paragraph(text, self.styles["TableCellNI"])

    @staticmethod
    def _data_table_style() -> TableStyle:
        return TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
            ("BACKGROUND", (0, 1), (-1, -1), BRAND_LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.2, BRAND_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ])

    @staticmethod
    def _as_dict(value) -> dict:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "dict"):
            return value.dict()
        return dict(value or {})

    @staticmethod
    def _citation(item: dict) -> str:
        return (
            f"Source: {item.get('source_name', 'Unknown')}; "
            f"type: {item.get('source_type', 'unknown')}; "
            f"published: {BriefingExportGenerator._date(item.get('published_at'))}; "
            f"reliability: {item.get('reliability_score', 'n/a')}; "
            f"URL: {item.get('url', '')}"
        )

    @staticmethod
    def _article_citation(article: dict) -> str:
        return (
            f"Source: {article.get('source_name', 'Unknown')}; "
            f"published: {BriefingExportGenerator._date(article.get('published_at'))}; "
            f"fetched: {BriefingExportGenerator._date(article.get('fetched_at'))}; "
            f"URL: {article.get('url', '')}"
        )

    @staticmethod
    def _compact_url(value) -> str:
        text = str(value or "")
        if len(text) <= 95:
            return text
        return text[:92] + "..."

    @staticmethod
    def _date(value) -> str:
        if not value:
            return "No date"
        if isinstance(value, datetime.datetime):
            return value.strftime("%Y-%m-%d %H:%M")
        return str(value).replace("T", " ")[:16]

    @staticmethod
    def _safe(value: str) -> str:
        return escape(str(value or ""))

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
        return slug[:40] or "export"

    @staticmethod
    def _footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(BRAND_MUTED)
        canvas.drawCentredString(A4[0] / 2, 1 * cm, f"NewsIntel | Source-backed intelligence | Page {doc.page}")
        canvas.restoreState()

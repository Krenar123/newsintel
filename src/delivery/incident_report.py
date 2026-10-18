"""Incident PDF reports for client case files."""

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
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.models.database import Client, ClientIncident, ClientIncidentEvidence


BRAND_PRIMARY = HexColor("#102a43")
BRAND_ACCENT = HexColor("#d94f45")
BRAND_GREEN = HexColor("#147c80")
BRAND_LIGHT = HexColor("#f4f7f9")
BRAND_TEXT = HexColor("#243b53")
BRAND_MUTED = HexColor("#6b7c8f")
BRAND_WHITE = HexColor("#ffffff")


class IncidentReportGenerator:
    """Generate a polished PDF dossier for a client incident."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.styles = getSampleStyleSheet()
        self._init_styles()

    def _init_styles(self) -> None:
        self.styles.add(ParagraphStyle(
            "IncidentTitle",
            parent=self.styles["Title"],
            fontSize=24,
            leading=30,
            textColor=BRAND_PRIMARY,
            alignment=TA_CENTER,
            spaceAfter=10,
        ))
        self.styles.add(ParagraphStyle(
            "IncidentSubtitle",
            parent=self.styles["Normal"],
            fontSize=11,
            leading=15,
            textColor=BRAND_MUTED,
            alignment=TA_CENTER,
            spaceAfter=18,
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
            "BodyTextNI",
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
        ))

    def generate(
        self,
        client: Client,
        incident: ClientIncident,
        evidence_items: list[ClientIncidentEvidence],
    ) -> Path:
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"incident_{incident.id}_{self._slug(incident.title)}_{timestamp}.pdf"
        filepath = self.output_dir / filename

        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title=f"Incident Report - {incident.title}",
        )

        story = []
        story.extend(self._cover(client, incident, evidence_items))
        story.append(PageBreak())
        story.extend(self._case_summary(incident))
        story.extend(self._evidence_section(evidence_items))
        story.extend(self._drafts_section(incident.draft_responses or []))
        story.extend(self._disclaimer())

        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return filepath

    def _cover(
        self,
        client: Client,
        incident: ClientIncident,
        evidence_items: list[ClientIncidentEvidence],
    ) -> list:
        generated_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        first_seen = self._date(incident.first_seen_at)
        last_seen = self._date(incident.last_seen_at)
        plan = client.plan.value if hasattr(client.plan, "value") else str(client.plan)

        elements = [
            Spacer(1, 3 * cm),
            Paragraph("Incident Intelligence Report", self.styles["IncidentTitle"]),
            Paragraph(self._safe(incident.title), self.styles["IncidentSubtitle"]),
            HRFlowable(width="55%", thickness=2, color=BRAND_ACCENT),
            Spacer(1, 1 * cm),
        ]

        table_data = [
            ["Client", self._safe(client.name)],
            ["Plan", self._safe(plan)],
            ["Severity", self._safe(incident.severity.upper())],
            ["Status", self._safe(incident.status.value.replace("_", " ").title())],
            ["First Seen", first_seen],
            ["Last Updated", last_seen],
            ["Evidence Items", str(len(evidence_items))],
            ["Generated", generated_at],
        ]
        table = Table(table_data, colWidths=[4 * cm, 10 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BRAND_PRIMARY),
            ("TEXTCOLOR", (0, 0), (0, -1), BRAND_WHITE),
            ("BACKGROUND", (1, 0), (1, -1), BRAND_LIGHT),
            ("TEXTCOLOR", (1, 0), (1, -1), BRAND_TEXT),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, BRAND_MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 3 * cm))
        elements.append(Paragraph("Generated by NewsIntel", self.styles["SmallNI"]))
        return elements

    def _case_summary(self, incident: ClientIncident) -> list:
        return [
            Paragraph("Situation Summary", self.styles["SectionTitle"]),
            Paragraph(self._safe(incident.summary or "No summary saved."), self.styles["BodyTextNI"]),
            Paragraph("Recommended Posture", self.styles["SectionTitle"]),
            Paragraph(
                self._safe(incident.recommended_posture or "No recommendation saved."),
                self.styles["BodyTextNI"],
            ),
            Paragraph("Legal Review Flags", self.styles["SectionTitle"]),
            self._bullet_list(incident.legal_review_flags or ["No flags saved."]),
            Paragraph("Evidence Steps", self.styles["SectionTitle"]),
            self._bullet_list(incident.evidence_steps or ["No evidence steps saved."]),
        ]

    def _evidence_section(self, evidence_items: list[ClientIncidentEvidence]) -> list:
        elements = [Paragraph("Evidence Trail", self.styles["SectionTitle"])]
        if not evidence_items:
            elements.append(Paragraph("No evidence attached yet.", self.styles["BodyTextNI"]))
            return elements

        for item in evidence_items:
            title = item.title or item.url
            source = item.source_name or "Unknown source"
            date = self._date(item.published_at or item.captured_at)
            elements.append(Paragraph(self._safe(title), self.styles["BodyTextNI"]))
            elements.append(Paragraph(
                self._safe(f"{source} | {item.evidence_type} | {date}"),
                self.styles["SmallNI"],
            ))
            elements.append(Paragraph(self._safe(item.url), self.styles["SmallNI"]))
            if item.notes:
                elements.append(Paragraph(self._safe(f"Notes: {item.notes}"), self.styles["SmallNI"]))
            elements.append(Spacer(1, 0.25 * cm))
        return elements

    def _drafts_section(self, drafts: list[dict]) -> list:
        elements = [Paragraph("Saved Draft Responses", self.styles["SectionTitle"])]
        if not drafts:
            elements.append(Paragraph("No draft responses saved.", self.styles["BodyTextNI"]))
            return elements

        for draft in drafts:
            tone = str(draft.get("tone", "draft")).title()
            text = str(draft.get("text", ""))
            status = str(draft.get("status") or "internal_review").replace("_", " ")
            readiness = str(draft.get("public_readiness") or "caution").replace("_", " ")
            risk = str(draft.get("risk_level") or "medium")
            use_case = str(draft.get("use_case") or "Use only with attached evidence.")
            elements.append(Paragraph(self._safe(f"{tone} - {status}"), self.styles["BodyTextNI"]))
            elements.append(Paragraph(self._safe(f"Readiness: {readiness}; risk: {risk}; use: {use_case}"), self.styles["SmallNI"]))
            elements.append(Paragraph(self._safe("English draft"), self.styles["SmallNI"]))
            elements.append(Paragraph(self._safe(text), self.styles["SmallNI"]))
            if draft.get("mk_text"):
                elements.append(Paragraph(self._safe("Macedonian working draft"), self.styles["SmallNI"]))
                elements.append(Paragraph(self._safe(str(draft.get("mk_text", ""))), self.styles["SmallNI"]))
            elements.append(Spacer(1, 0.2 * cm))
        return elements

    def _disclaimer(self) -> list:
        return [
            Spacer(1, 0.5 * cm),
            HRFlowable(width="100%", thickness=1, color=BRAND_GREEN),
            Spacer(1, 0.25 * cm),
            Paragraph(
                "This report is communications support and legal-risk triage, not legal advice. "
                "A qualified Macedonian lawyer should review final legal positions and public statements.",
                self.styles["SmallNI"],
            ),
        ]

    def _bullet_list(self, items: list[str]) -> ListFlowable:
        return ListFlowable(
            [
                ListItem(Paragraph(self._safe(str(item)), self.styles["BodyTextNI"]))
                for item in items
            ],
            bulletType="bullet",
            leftIndent=16,
        )

    @staticmethod
    def _safe(value: str) -> str:
        return escape(value or "")

    @staticmethod
    def _date(value: datetime.datetime | None) -> str:
        if not value:
            return "No date"
        return value.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
        return slug[:40] or "case"

    @staticmethod
    def _footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(BRAND_MUTED)
        canvas.drawCentredString(
            A4[0] / 2,
            1.25 * cm,
            f"NewsIntel Case Report | Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()

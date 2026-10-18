"""
PDF Report Generator — Creates polished news briefing PDFs.

Generates professional reports with:
  - Cover page with country, date range, and stats
  - Table of contents by category
  - Article summaries grouped by category
  - Key figures section (most mentioned entities)
  - Trend indicators
"""

import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, cm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    HRFlowable,
)

from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from src.models.database import (
    Article, Summary, Entity, EntityMention, ArticleCategory, SummaryType,
)

import structlog

logger = structlog.get_logger()


# ── Brand colors ──────────────────────────────────────────────────────────
BRAND_PRIMARY = HexColor("#1a1a2e")    # Dark navy
BRAND_ACCENT = HexColor("#e94560")     # Red accent
BRAND_LIGHT = HexColor("#f5f5f5")      # Light gray
BRAND_TEXT = HexColor("#333333")        # Body text
BRAND_MUTED = HexColor("#888888")      # Muted text
BRAND_WHITE = HexColor("#ffffff")


@dataclass
class ReportConfig:
    """Configuration for report generation."""
    country_name: str = "North Macedonia"
    country_code: str = "mk"
    date_from: Optional[datetime.datetime] = None
    date_to: Optional[datetime.datetime] = None
    categories: Optional[list[str]] = None   # None = all
    max_articles_per_category: int = 10
    include_entities: bool = True
    include_trends: bool = True
    title: Optional[str] = None
    subtitle: Optional[str] = None


class PDFReportGenerator:
    """Generates professional news briefing PDFs."""

    def __init__(self, session: Session, output_dir: Path):
        self.session = session
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._init_styles()

    def _init_styles(self):
        """Set up custom paragraph styles."""
        self.styles = getSampleStyleSheet()

        self.styles.add(ParagraphStyle(
            "CoverTitle",
            parent=self.styles["Title"],
            fontSize=28,
            textColor=BRAND_PRIMARY,
            spaceAfter=10,
            alignment=TA_CENTER,
        ))
        self.styles.add(ParagraphStyle(
            "CoverSubtitle",
            parent=self.styles["Normal"],
            fontSize=14,
            textColor=BRAND_MUTED,
            alignment=TA_CENTER,
            spaceAfter=30,
        ))
        self.styles.add(ParagraphStyle(
            "CategoryHeader",
            parent=self.styles["Heading1"],
            fontSize=18,
            textColor=BRAND_PRIMARY,
            spaceBefore=20,
            spaceAfter=10,
            borderWidth=0,
            borderPadding=0,
        ))
        self.styles.add(ParagraphStyle(
            "ArticleTitle",
            parent=self.styles["Heading2"],
            fontSize=12,
            textColor=BRAND_ACCENT,
            spaceBefore=12,
            spaceAfter=4,
        ))
        self.styles.add(ParagraphStyle(
            "ArticleMeta",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=BRAND_MUTED,
            spaceAfter=4,
        ))
        self.styles.add(ParagraphStyle(
            "SummaryText",
            parent=self.styles["Normal"],
            fontSize=10,
            textColor=BRAND_TEXT,
            leading=14,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
        ))
        self.styles.add(ParagraphStyle(
            "EntityName",
            parent=self.styles["Normal"],
            fontSize=10,
            textColor=BRAND_PRIMARY,
            fontName="Helvetica-Bold",
        ))
        self.styles.add(ParagraphStyle(
            "FooterStyle",
            parent=self.styles["Normal"],
            fontSize=8,
            textColor=BRAND_MUTED,
            alignment=TA_CENTER,
        ))

    def generate(self, config: ReportConfig) -> Path:
        """
        Generate a complete news briefing PDF.

        Returns the path to the generated file.
        """
        # Default date range: last 7 days
        if not config.date_to:
            config.date_to = datetime.datetime.utcnow()
        if not config.date_from:
            config.date_from = config.date_to - datetime.timedelta(days=7)

        # Build filename
        date_str = config.date_to.strftime("%Y-%m-%d")
        filename = f"briefing_{config.country_code}_{date_str}.pdf"
        filepath = self.output_dir / filename

        # Create document
        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2.5 * cm,
            bottomMargin=2 * cm,
        )

        story = []

        # ── Cover page ────────────────────────────────────────────
        story.extend(self._build_cover(config))
        story.append(PageBreak())

        # ── Fetch data ────────────────────────────────────────────
        articles_by_cat = self._fetch_articles(config)

        # ── Key figures section ───────────────────────────────────
        if config.include_entities:
            entities_section = self._build_entities_section(config)
            if entities_section:
                story.extend(entities_section)
                story.append(PageBreak())

        # ── Articles by category ──────────────────────────────────
        for category, articles in articles_by_cat.items():
            story.extend(self._build_category_section(category, articles))

        # ── Build PDF ─────────────────────────────────────────────
        doc.build(
            story,
            onFirstPage=self._add_footer,
            onLaterPages=self._add_footer,
        )

        logger.info(
            "report_generated",
            path=str(filepath),
            categories=len(articles_by_cat),
            total_articles=sum(len(a) for a in articles_by_cat.values()),
        )

        return filepath

    def _build_cover(self, config: ReportConfig) -> list:
        """Build the cover page elements."""
        elements = []
        elements.append(Spacer(1, 3 * cm))

        title = config.title or f"News Intelligence Briefing"
        elements.append(Paragraph(title, self.styles["CoverTitle"]))

        subtitle = config.subtitle or config.country_name
        elements.append(Paragraph(subtitle, self.styles["CoverSubtitle"]))

        date_range = (
            f"{config.date_from.strftime('%B %d, %Y')} — "
            f"{config.date_to.strftime('%B %d, %Y')}"
        )
        elements.append(Paragraph(date_range, self.styles["CoverSubtitle"]))

        elements.append(Spacer(1, 2 * cm))
        elements.append(HRFlowable(
            width="60%", thickness=2, color=BRAND_ACCENT,
        ))
        elements.append(Spacer(1, 1 * cm))

        # Quick stats
        total = (
            self.session.query(func.count(Article.id))
            .filter(
                Article.published_at >= config.date_from,
                Article.published_at <= config.date_to,
            )
            .scalar() or 0
        )
        source_count = (
            self.session.query(func.count(func.distinct(Article.source_id)))
            .filter(
                Article.published_at >= config.date_from,
                Article.published_at <= config.date_to,
            )
            .scalar() or 0
        )

        stats_text = (
            f"{total} articles analyzed from {source_count} sources"
        )
        elements.append(Paragraph(stats_text, self.styles["CoverSubtitle"]))

        elements.append(Spacer(1, 4 * cm))
        elements.append(Paragraph(
            "Generated by NewsIntel",
            self.styles["FooterStyle"],
        ))
        elements.append(Paragraph(
            f"Report date: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            self.styles["FooterStyle"],
        ))

        return elements

    def _build_entities_section(self, config: ReportConfig) -> list:
        """Build the 'Key Figures' section showing top entities."""
        elements = []

        top_entities = (
            self.session.query(Entity)
            .join(EntityMention)
            .join(Article)
            .filter(
                Article.published_at >= config.date_from,
                Article.published_at <= config.date_to,
            )
            .group_by(Entity.id)
            .order_by(desc(func.sum(EntityMention.mention_count)))
            .limit(15)
            .all()
        )

        if not top_entities:
            return []

        elements.append(Paragraph(
            "Key Figures &amp; Entities", self.styles["CategoryHeader"]
        ))
        elements.append(HRFlowable(
            width="100%", thickness=1, color=BRAND_ACCENT,
        ))
        elements.append(Spacer(1, 0.3 * cm))

        # Build table
        table_data = [["Name", "Type", "Mentions"]]
        for entity in top_entities:
            table_data.append([
                entity.name,
                entity.entity_type.value.capitalize(),
                str(entity.total_mentions),
            ])

        table = Table(table_data, colWidths=[8 * cm, 4 * cm, 3 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), BRAND_WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("TEXTCOLOR", (0, 1), (-1, -1), BRAND_TEXT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BRAND_WHITE, BRAND_LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.5, BRAND_MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)

        return elements

    def _build_category_section(
        self, category: str, articles: list
    ) -> list:
        """Build a section for one category with article summaries."""
        elements = []

        elements.append(Paragraph(
            category.upper(), self.styles["CategoryHeader"]
        ))
        elements.append(HRFlowable(
            width="100%", thickness=1, color=BRAND_ACCENT,
        ))

        for article, summary in articles:
            # Title
            elements.append(Paragraph(
                article.title, self.styles["ArticleTitle"]
            ))

            # Meta line
            source_name = article.source.name if article.source else "Unknown"
            pub_date = (
                article.published_at.strftime("%b %d, %Y")
                if article.published_at else "Unknown date"
            )
            meta = f"{source_name} | {pub_date}"
            if article.author:
                meta += f" | {article.author}"
            elements.append(Paragraph(meta, self.styles["ArticleMeta"]))

            # Summary
            summary_text = summary.text if summary else "No summary available."
            elements.append(Paragraph(
                summary_text, self.styles["SummaryText"]
            ))

        elements.append(Spacer(1, 0.5 * cm))
        return elements

    def _fetch_articles(self, config: ReportConfig) -> dict:
        """Fetch articles grouped by category for the report."""
        query = (
            self.session.query(Article, Summary, ArticleCategory)
            .outerjoin(Summary, (
                (Summary.article_id == Article.id) &
                (Summary.summary_type == SummaryType.EXTRACTIVE)
            ))
            .join(ArticleCategory)
            .filter(
                Article.published_at >= config.date_from,
                Article.published_at <= config.date_to,
                Article.is_processed == True,
                ArticleCategory.is_primary == True,
            )
        )

        if config.categories:
            query = query.filter(
                ArticleCategory.category.in_(config.categories)
            )

        query = query.order_by(
            ArticleCategory.category,
            desc(Article.published_at),
        )

        results = query.all()

        # Group by category, limit per category
        grouped: dict[str, list] = {}
        for article, summary, cat in results:
            if cat.category not in grouped:
                grouped[cat.category] = []
            if len(grouped[cat.category]) < config.max_articles_per_category:
                grouped[cat.category].append((article, summary))

        return grouped

    @staticmethod
    def _add_footer(canvas, doc):
        """Add page number footer."""
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(BRAND_MUTED)
        page_num = canvas.getPageNumber()
        canvas.drawCentredString(
            A4[0] / 2, 1.5 * cm,
            f"NewsIntel Briefing — Page {page_num}"
        )
        canvas.restoreState()

"""
Alert System — Real-time notifications when news matches user criteria.

Supports multiple channels:
  - Email (instant or digest)
  - Webhook (POST JSON to any URL — Slack, Zapier, custom apps)
  - Telegram bot
  - In-app (stored in DB for API polling)

Alert types:
  - Entity alert: "Notify me when [Person X] appears in news"
  - Keyword alert: "Notify me when articles contain [corruption + minister]"
  - Category alert: "Notify me on all [politics] articles"
  - Sentiment alert: "Notify me when sentiment about [Person X] drops below -0.3"
  - Volume alert: "Notify me when [Topic X] has 5+ articles in 24 hours"

Design: Alerts are evaluated after each processing batch, not per-article.
This avoids spam and allows batching (e.g., "3 new articles about Person X").
"""

import datetime
import json
import re
from typing import Optional
from enum import Enum
from dataclasses import dataclass, field

import httpx
import structlog
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime,
    ForeignKey, JSON, Enum as SQLEnum, func, or_,
)
from sqlalchemy.orm import Session, Mapped, mapped_column, relationship

from src.models.database import (
    Base, Article, Entity, EntityMention, ArticleCategory, Source,
    StoryCluster,
)
from src.search.normalization import search_blob, search_variants

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Database models for alerts
# ---------------------------------------------------------------------------

class AlertChannel(str, Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"
    TELEGRAM = "telegram"
    IN_APP = "in_app"


class AlertType(str, Enum):
    ENTITY = "entity"           # Specific person/org/place
    KEYWORD = "keyword"         # Text search
    CATEGORY = "category"       # Article category
    SENTIMENT = "sentiment"     # Sentiment threshold
    VOLUME = "volume"           # Spike detection
    RISK_SCORE = "risk_score"   # Political risk threshold
    STORY_SPREAD = "story_spread"  # Same story reported by multiple sources
    ATTACK_THEME = "attack_theme"  # Attack-language theme volume


class Alert(Base):
    """User-defined alert rule."""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    user_email: Mapped[str] = mapped_column(String(255), index=True)
    alert_type: Mapped[AlertType] = mapped_column(SQLEnum(AlertType))
    channel: Mapped[AlertChannel] = mapped_column(SQLEnum(AlertChannel))

    # Alert criteria (flexible JSON)
    criteria: Mapped[dict] = mapped_column(
        JSON,
        comment=(
            'Examples: '
            '{"entity_id": 42} for entity alerts, '
            '{"keywords": ["corruption", "minister"]} for keyword alerts, '
            '{"category": "politics", "country_code": "mk"} for category, '
            '{"entity_id": 42, "threshold": -0.3} for sentiment, '
            '{"keyword": "protest", "min_articles": 5, "hours": 24} for volume'
        ),
    )

    # Channel-specific config
    channel_config: Mapped[Optional[dict]] = mapped_column(
        JSON, default=dict,
        comment=(
            '{"webhook_url": "..."} or {"telegram_chat_id": "..."} '
            'or {"email": "..."}'
        ),
    )

    # Settings
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    country_code: Mapped[Optional[str]] = mapped_column(String(10))
    cooldown_minutes: Mapped[int] = mapped_column(
        Integer, default=60,
        comment="Minimum time between notifications for this alert",
    )
    last_triggered_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    total_triggers: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )


class AlertNotification(Base):
    """Record of a sent notification."""
    __tablename__ = "alert_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    articles_matched: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    channel: Mapped[AlertChannel] = mapped_column(SQLEnum(AlertChannel))
    sent_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=func.now()
    )
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[Optional[str]] = mapped_column(Text)

    # For in-app: track if user has read it
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# Alert evaluation engine
# ---------------------------------------------------------------------------

@dataclass
class MatchedArticle:
    """An article that matched an alert criteria."""
    article_id: int
    title: str
    url: str
    source_name: str
    published_at: Optional[datetime.datetime]
    match_reason: str           # Why this article matched
    sentiment_score: Optional[float] = None


@dataclass
class AlertEvaluation:
    """Result of evaluating a single alert against new articles."""
    alert_id: int
    alert_name: str
    triggered: bool
    matched_articles: list[MatchedArticle] = field(default_factory=list)
    message: str = ""


class AlertEngine:
    """
    Evaluates alert rules against newly processed articles.

    Call evaluate_all() after each processing batch to check which
    alerts should fire and send notifications.
    """

    def __init__(self, session: Session):
        self.session = session

    def evaluate_all(
        self,
        since: Optional[datetime.datetime] = None,
    ) -> list[AlertEvaluation]:
        """
        Evaluate all active alerts against recent articles.

        Args:
            since: Only check articles ingested after this time.
                   Defaults to 1 hour ago.

        Returns:
            List of AlertEvaluation results (triggered and not).
        """
        if since is None:
            since = datetime.datetime.utcnow() - datetime.timedelta(hours=1)

        # Get all active alerts
        alerts = (
            self.session.query(Alert)
            .filter(Alert.is_active == True)
            .all()
        )

        results = []
        for alert in alerts:
            # Check cooldown
            if alert.last_triggered_at:
                cooldown_until = (
                    alert.last_triggered_at
                    + datetime.timedelta(minutes=alert.cooldown_minutes)
                )
                if datetime.datetime.utcnow() < cooldown_until:
                    continue

            evaluation = self._evaluate_alert(alert, since)
            results.append(evaluation)

            if evaluation.triggered:
                self._record_trigger(alert, evaluation)

        triggered_count = sum(1 for r in results if r.triggered)
        logger.info(
            "alerts_evaluated",
            total=len(alerts),
            triggered=triggered_count,
        )

        return results

    def _evaluate_alert(
        self, alert: Alert, since: datetime.datetime
    ) -> AlertEvaluation:
        """Evaluate a single alert rule."""
        evaluators = {
            AlertType.ENTITY: self._eval_entity,
            AlertType.KEYWORD: self._eval_keyword,
            AlertType.CATEGORY: self._eval_category,
            AlertType.SENTIMENT: self._eval_sentiment,
            AlertType.VOLUME: self._eval_volume,
            AlertType.RISK_SCORE: self._eval_risk_score,
            AlertType.STORY_SPREAD: self._eval_story_spread,
            AlertType.ATTACK_THEME: self._eval_attack_theme,
        }

        evaluator = evaluators.get(alert.alert_type)
        if not evaluator:
            return AlertEvaluation(
                alert_id=alert.id,
                alert_name=alert.name,
                triggered=False,
                message=f"Unknown alert type: {alert.alert_type}",
            )

        return evaluator(alert, since)

    def _eval_entity(
        self, alert: Alert, since: datetime.datetime
    ) -> AlertEvaluation:
        """Check if a specific entity appeared in recent articles."""
        entity_id = alert.criteria.get("entity_id")
        if not entity_id:
            return AlertEvaluation(
                alert_id=alert.id, alert_name=alert.name,
                triggered=False, message="Missing entity_id",
            )

        # Find recent articles mentioning this entity
        results = (
            self.session.query(Article, EntityMention)
            .join(EntityMention)
            .filter(
                EntityMention.entity_id == entity_id,
                Article.ingested_at >= since,
                or_(Article.quality_status == None, Article.quality_status != "excluded"),
            )
            .order_by(Article.published_at.desc())
            .limit(10)
            .all()
        )

        if not results:
            return AlertEvaluation(
                alert_id=alert.id, alert_name=alert.name,
                triggered=False,
            )

        entity = self.session.query(Entity).get(entity_id)
        entity_name = entity.name if entity else f"Entity #{entity_id}"

        matched = [
            MatchedArticle(
                article_id=article.id,
                title=article.title,
                url=article.url,
                source_name=article.source.name if article.source else "",
                published_at=article.published_at,
                match_reason=f"Mentions {entity_name}",
                sentiment_score=mention.sentiment_score,
            )
            for article, mention in results
        ]

        return AlertEvaluation(
            alert_id=alert.id,
            alert_name=alert.name,
            triggered=True,
            matched_articles=matched,
            message=f"{len(matched)} new articles mention {entity_name}",
        )

    def _eval_keyword(
        self, alert: Alert, since: datetime.datetime
    ) -> AlertEvaluation:
        """Check if recent articles contain specific keywords."""
        keywords = alert.criteria.get("keywords", [])
        match_all = alert.criteria.get("match_all", False)

        if not keywords:
            return AlertEvaluation(
                alert_id=alert.id, alert_name=alert.name,
                triggered=False, message="No keywords specified",
            )

        # Query articles
        query = self.session.query(Article).filter(
            Article.ingested_at >= since,
            Article.is_processed == True,
            or_(Article.quality_status == None, Article.quality_status != "excluded"),
        )

        if alert.country_code:
            query = query.join(Source).filter(
                Source.country_code == alert.country_code
            )

        articles = query.all()
        matched = []

        for article in articles:
            text = article.search_text or search_blob(article.title, article.content)

            if match_all:
                if all(any(variant in text for variant in search_variants(kw)) for kw in keywords):
                    matched.append(MatchedArticle(
                        article_id=article.id,
                        title=article.title,
                        url=article.url,
                        source_name=article.source.name if article.source else "",
                        published_at=article.published_at,
                        match_reason=f"Contains all: {', '.join(keywords)}",
                    ))
            else:
                found = [
                    kw for kw in keywords
                    if any(variant in text for variant in search_variants(kw))
                ]
                if found:
                    matched.append(MatchedArticle(
                        article_id=article.id,
                        title=article.title,
                        url=article.url,
                        source_name=article.source.name if article.source else "",
                        published_at=article.published_at,
                        match_reason=f"Contains: {', '.join(found)}",
                    ))

        return AlertEvaluation(
            alert_id=alert.id,
            alert_name=alert.name,
            triggered=len(matched) > 0,
            matched_articles=matched[:10],
            message=f"{len(matched)} articles match keywords",
        )

    def _eval_category(
        self, alert: Alert, since: datetime.datetime
    ) -> AlertEvaluation:
        """Check for new articles in a specific category."""
        category = alert.criteria.get("category")
        if not category:
            return AlertEvaluation(
                alert_id=alert.id, alert_name=alert.name,
                triggered=False, message="No category specified",
            )

        query = (
            self.session.query(Article)
            .join(ArticleCategory)
            .filter(
                ArticleCategory.category == category,
                ArticleCategory.is_primary == True,
                Article.ingested_at >= since,
                or_(Article.quality_status == None, Article.quality_status != "excluded"),
            )
        )

        if alert.country_code:
            query = query.join(Source).filter(
                Source.country_code == alert.country_code
            )

        articles = query.limit(10).all()

        matched = [
            MatchedArticle(
                article_id=a.id,
                title=a.title,
                url=a.url,
                source_name=a.source.name if a.source else "",
                published_at=a.published_at,
                match_reason=f"Category: {category}",
            )
            for a in articles
        ]

        return AlertEvaluation(
            alert_id=alert.id,
            alert_name=alert.name,
            triggered=len(matched) > 0,
            matched_articles=matched,
            message=f"{len(matched)} new {category} articles",
        )

    def _eval_sentiment(
        self, alert: Alert, since: datetime.datetime
    ) -> AlertEvaluation:
        """Check if entity sentiment drops below/above threshold."""
        entity_id = alert.criteria.get("entity_id")
        threshold = alert.criteria.get("threshold", -0.3)
        direction = alert.criteria.get("direction", "below")  # "below" or "above"

        if not entity_id:
            return AlertEvaluation(
                alert_id=alert.id, alert_name=alert.name,
                triggered=False, message="Missing entity_id",
            )

        # Get recent mentions with sentiment
        results = (
            self.session.query(Article, EntityMention)
            .join(EntityMention)
            .filter(
                EntityMention.entity_id == entity_id,
                EntityMention.sentiment_score.isnot(None),
                Article.ingested_at >= since,
                or_(Article.quality_status == None, Article.quality_status != "excluded"),
            )
            .all()
        )

        if not results:
            return AlertEvaluation(
                alert_id=alert.id, alert_name=alert.name,
                triggered=False,
            )

        # Check if any mention crosses the threshold
        crossed = []
        for article, mention in results:
            if direction == "below" and mention.sentiment_score < threshold:
                crossed.append((article, mention))
            elif direction == "above" and mention.sentiment_score > threshold:
                crossed.append((article, mention))

        if not crossed:
            return AlertEvaluation(
                alert_id=alert.id, alert_name=alert.name,
                triggered=False,
            )

        entity = self.session.query(Entity).get(entity_id)
        entity_name = entity.name if entity else f"Entity #{entity_id}"

        matched = [
            MatchedArticle(
                article_id=article.id,
                title=article.title,
                url=article.url,
                source_name=article.source.name if article.source else "",
                published_at=article.published_at,
                match_reason=(
                    f"Sentiment {direction} {threshold}: "
                    f"{mention.sentiment_score:.2f}"
                ),
                sentiment_score=mention.sentiment_score,
            )
            for article, mention in crossed
        ]

        avg_sentiment = sum(m.sentiment_score for m in matched if m.sentiment_score) / max(len(matched), 1)

        return AlertEvaluation(
            alert_id=alert.id,
            alert_name=alert.name,
            triggered=True,
            matched_articles=matched,
            message=(
                f"{entity_name} sentiment alert: {len(matched)} mentions "
                f"{direction} {threshold} (avg: {avg_sentiment:.2f})"
            ),
        )

    def _eval_volume(
        self, alert: Alert, since: datetime.datetime
    ) -> AlertEvaluation:
        """Check if a topic has unusual volume (spike detection)."""
        keyword = alert.criteria.get("keyword", "")
        min_articles = alert.criteria.get("min_articles", 5)
        hours = alert.criteria.get("hours", 24)

        window_start = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)

        conditions = []
        for variant in search_variants(keyword):
            term = f"%{variant}%"
            conditions.extend([
                Article.search_text.ilike(term),
                Article.title.ilike(term),
                Article.content.ilike(term),
            ])
        query = self.session.query(Article).filter(
            Article.ingested_at >= window_start,
            or_(Article.quality_status == None, Article.quality_status != "excluded"),
        )
        if conditions:
            query = query.filter(or_(*conditions))

        if alert.country_code:
            query = query.join(Source).filter(
                Source.country_code == alert.country_code
            )

        count = query.count()

        if count < min_articles:
            return AlertEvaluation(
                alert_id=alert.id, alert_name=alert.name,
                triggered=False,
                message=f"Only {count} articles (threshold: {min_articles})",
            )

        articles = query.limit(10).all()
        matched = [
            MatchedArticle(
                article_id=a.id,
                title=a.title,
                url=a.url,
                source_name=a.source.name if a.source else "",
                published_at=a.published_at,
                match_reason=f"Volume spike: {count} articles in {hours}h",
            )
            for a in articles
        ]

        return AlertEvaluation(
            alert_id=alert.id,
            alert_name=alert.name,
            triggered=True,
            matched_articles=matched,
            message=f"Volume spike: {count} articles about '{keyword}' in {hours}h",
        )

    def _eval_risk_score(
        self, alert: Alert, since: datetime.datetime
    ) -> AlertEvaluation:
        """Check whether the country political risk score is above a threshold."""
        from src.processing.risk_scoring import PoliticalRiskScorer

        threshold = int(alert.criteria.get("risk_score_gte", 70))
        hours = int(alert.criteria.get("window_hours", 24))
        country_code = alert.country_code or alert.criteria.get("country_code") or "mk"
        days = max(1, round(hours / 24))
        result = PoliticalRiskScorer(self.session).country_risk(country_code=country_code, days=days)

        if result.score < threshold:
            return AlertEvaluation(
                alert_id=alert.id,
                alert_name=alert.name,
                triggered=False,
                message=f"Risk score {result.score} is below threshold {threshold}",
            )

        matched = [
            MatchedArticle(
                article_id=item["article_id"],
                title=item["title"],
                url=item["url"],
                source_name=item["source_name"],
                published_at=item.get("published_at"),
                match_reason=f"Risk driver: {result.level}",
            )
            for item in result.items[:10]
        ]
        return AlertEvaluation(
            alert_id=alert.id,
            alert_name=alert.name,
            triggered=True,
            matched_articles=matched,
            message=f"Political risk score is {result.score}/100 ({result.level})",
        )

    def _eval_story_spread(
        self, alert: Alert, since: datetime.datetime
    ) -> AlertEvaluation:
        """Check for validated story clusters spreading across multiple sources."""
        min_sources = int(alert.criteria.get("source_count_gte", 3))
        hours = int(alert.criteria.get("window_hours", 24))
        status = alert.criteria.get("status")
        country_code = alert.country_code or alert.criteria.get("country_code") or "mk"
        window_start = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)

        query = self.session.query(StoryCluster).filter(
            StoryCluster.country_code == country_code,
            StoryCluster.source_count >= min_sources,
            StoryCluster.last_published_at >= window_start,
        )
        if status:
            query = query.filter(StoryCluster.status == status)

        clusters = query.order_by(StoryCluster.source_count.desc()).limit(10).all()
        matched = []
        for cluster in clusters:
            link = cluster.articles[0] if cluster.articles else None
            article = link.article if link else None
            matched.append(MatchedArticle(
                article_id=article.id if article else 0,
                title=article.title if article else cluster.title,
                url=article.url if article else "",
                source_name=article.source.name if article and article.source else "Multiple sources",
                published_at=cluster.last_published_at,
                match_reason=f"Reported by {cluster.source_count} sources",
            ))

        return AlertEvaluation(
            alert_id=alert.id,
            alert_name=alert.name,
            triggered=bool(matched),
            matched_articles=matched,
            message=f"{len(matched)} stories spread to {min_sources}+ sources",
        )

    def _eval_attack_theme(
        self, alert: Alert, since: datetime.datetime
    ) -> AlertEvaluation:
        """Check if attack-language around a theme has crossed a count threshold."""
        from src.processing.risk_scoring import ATTACK_TERMS

        category = alert.criteria.get("attack_category")
        min_count = int(alert.criteria.get("count_gte", 3))
        hours = int(alert.criteria.get("window_hours", 24))
        if not category or category not in ATTACK_TERMS:
            return AlertEvaluation(
                alert_id=alert.id,
                alert_name=alert.name,
                triggered=False,
                message="Missing or unsupported attack_category",
            )

        window_start = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        query = self.session.query(Article).filter(
            Article.ingested_at >= window_start,
            Article.is_processed == True,
            or_(Article.quality_status == None, Article.quality_status != "excluded"),
        )
        if alert.country_code:
            query = query.join(Source).filter(Source.country_code == alert.country_code)

        matched = []
        terms = ATTACK_TERMS[category]
        for article in query.all():
            text = f"{article.title} {article.content or ''}".lower()
            found = [term for term in terms if term in text]
            if found:
                matched.append(MatchedArticle(
                    article_id=article.id,
                    title=article.title,
                    url=article.url,
                    source_name=article.source.name if article.source else "",
                    published_at=article.published_at,
                    match_reason=f"{category.replace('_', ' ')}: {', '.join(found[:3])}",
                ))

        return AlertEvaluation(
            alert_id=alert.id,
            alert_name=alert.name,
            triggered=len(matched) >= min_count,
            matched_articles=matched[:10],
            message=f"{len(matched)} articles match {category.replace('_', ' ')} attack language",
        )

    def _record_trigger(self, alert: Alert, evaluation: AlertEvaluation):
        """Update alert trigger timestamp and create notification record."""
        alert.last_triggered_at = datetime.datetime.utcnow()
        alert.total_triggers += 1

        notification = AlertNotification(
            alert_id=alert.id,
            articles_matched=len(evaluation.matched_articles),
            payload={
                "message": evaluation.message,
                "articles": [
                    {
                        "id": m.article_id,
                        "title": m.title,
                        "url": m.url,
                        "source": m.source_name,
                        "reason": m.match_reason,
                        "sentiment": m.sentiment_score,
                    }
                    for m in evaluation.matched_articles
                ],
            },
            channel=alert.channel,
        )
        self.session.add(notification)
        self.session.commit()


# ---------------------------------------------------------------------------
# Notification dispatcher
# ---------------------------------------------------------------------------

class NotificationDispatcher:
    """
    Sends alert notifications through configured channels.

    Supports email, webhook (Slack/Zapier/custom), and Telegram.
    """

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        sender_email: str = "",
        telegram_bot_token: str = "",
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.sender_email = sender_email
        self.telegram_token = telegram_bot_token

    def dispatch(
        self, alert: Alert, evaluation: AlertEvaluation
    ) -> bool:
        """Send notification through the alert's configured channel."""
        dispatchers = {
            AlertChannel.EMAIL: self._send_email,
            AlertChannel.WEBHOOK: self._send_webhook,
            AlertChannel.TELEGRAM: self._send_telegram,
            AlertChannel.IN_APP: self._store_in_app,
        }

        dispatcher = dispatchers.get(alert.channel)
        if not dispatcher:
            logger.error("unknown_channel", channel=alert.channel)
            return False

        try:
            return dispatcher(alert, evaluation)
        except Exception as e:
            logger.error(
                "notification_failed",
                alert_id=alert.id,
                channel=alert.channel.value,
                error=str(e),
            )
            return False

    def _send_webhook(
        self, alert: Alert, evaluation: AlertEvaluation
    ) -> bool:
        """POST JSON payload to webhook URL (Slack, Zapier, custom)."""
        webhook_url = alert.channel_config.get("webhook_url")
        if not webhook_url:
            logger.error("webhook_url_missing", alert_id=alert.id)
            return False

        # Build payload (Slack-compatible by default)
        articles_text = "\n".join(
            f"• <{m.url}|{m.title}> ({m.match_reason})"
            for m in evaluation.matched_articles[:5]
        )

        payload = {
            "text": f"🔔 *{alert.name}*\n{evaluation.message}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"🔔 *{alert.name}*\n"
                            f"{evaluation.message}\n\n"
                            f"{articles_text}"
                        ),
                    },
                }
            ],
            # Also include raw data for non-Slack consumers
            "newsintel": {
                "alert_id": alert.id,
                "alert_name": alert.name,
                "alert_type": alert.alert_type.value,
                "message": evaluation.message,
                "articles": [
                    {
                        "id": m.article_id,
                        "title": m.title,
                        "url": m.url,
                        "source": m.source_name,
                        "reason": m.match_reason,
                        "sentiment": m.sentiment_score,
                    }
                    for m in evaluation.matched_articles
                ],
            },
        }

        with httpx.Client(timeout=10.0) as client:
            response = client.post(webhook_url, json=payload)
            response.raise_for_status()

        logger.info(
            "webhook_sent",
            alert_id=alert.id,
            url=webhook_url[:50],
        )
        return True

    def _send_telegram(
        self, alert: Alert, evaluation: AlertEvaluation
    ) -> bool:
        """Send notification via Telegram Bot API."""
        chat_id = alert.channel_config.get("telegram_chat_id")
        if not chat_id or not self.telegram_token:
            logger.error("telegram_config_missing", alert_id=alert.id)
            return False

        # Build message
        articles_text = "\n".join(
            f"▸ [{m.title}]({m.url})"
            for m in evaluation.matched_articles[:5]
        )

        message = (
            f"🔔 *{alert.name}*\n\n"
            f"{evaluation.message}\n\n"
            f"{articles_text}"
        )

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"

        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })
            response.raise_for_status()

        logger.info("telegram_sent", alert_id=alert.id, chat_id=chat_id)
        return True

    def _send_email(
        self, alert: Alert, evaluation: AlertEvaluation
    ) -> bool:
        """Send alert email."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        recipient = alert.channel_config.get("email", alert.user_email)

        # Build HTML email
        articles_html = "".join(
            f'<div style="margin:10px 0;padding:10px;background:#f9f9f9;'
            f'border-left:3px solid #e94560;border-radius:4px;">'
            f'<a href="{m.url}" style="color:#1a1a2e;font-weight:bold;'
            f'text-decoration:none;">{m.title}</a>'
            f'<br><span style="font-size:12px;color:#888;">'
            f'{m.source_name} | {m.match_reason}</span></div>'
            for m in evaluation.matched_articles[:5]
        )

        html_body = f"""
        <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
            <div style="background:#1a1a2e;color:white;padding:20px;text-align:center;">
                <h2 style="margin:0;">🔔 NewsIntel Alert</h2>
            </div>
            <div style="padding:20px;">
                <h3 style="color:#1a1a2e;">{alert.name}</h3>
                <p>{evaluation.message}</p>
                {articles_html}
            </div>
            <div style="padding:15px;text-align:center;font-size:12px;color:#888;">
                NewsIntel Alert System
            </div>
        </div>
        """

        msg = MIMEMultipart("alternative")
        msg["From"] = f"NewsIntel Alerts <{self.sender_email}>"
        msg["To"] = recipient
        msg["Subject"] = f"🔔 {alert.name}: {evaluation.message[:80]}"
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)

        logger.info("alert_email_sent", alert_id=alert.id, to=recipient)
        return True

    def _store_in_app(
        self, alert: Alert, evaluation: AlertEvaluation
    ) -> bool:
        """Store notification for in-app retrieval (already done in engine)."""
        logger.info("in_app_notification_stored", alert_id=alert.id)
        return True

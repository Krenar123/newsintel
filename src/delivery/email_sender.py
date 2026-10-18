"""
Email Delivery — Sends reports to subscribers via SMTP.

Supports:
  - PDF attachments
  - HTML email body with summary
  - Batch sending to subscriber lists
  - Template-based emails using Jinja2
"""

import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path
from typing import Optional

from jinja2 import Template
import structlog

logger = structlog.get_logger()


# ── HTML Email Template ────────────────────────────────────────────────

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 0; background: #f5f5f5; }
    .container { max-width: 600px; margin: 0 auto; background: white; }
    .header { background: #1a1a2e; color: white; padding: 30px; text-align: center; }
    .header h1 { margin: 0; font-size: 24px; }
    .header p { margin: 8px 0 0; opacity: 0.8; font-size: 14px; }
    .content { padding: 30px; }
    .stat-row { display: flex; justify-content: space-around; padding: 20px; background: #f8f8f8; margin: 20px 0; border-radius: 8px; }
    .stat { text-align: center; }
    .stat-num { font-size: 28px; font-weight: bold; color: #e94560; }
    .stat-label { font-size: 12px; color: #888; text-transform: uppercase; }
    .category { margin: 20px 0; }
    .category h2 { font-size: 16px; color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 5px; }
    .article { margin: 12px 0; padding: 12px; background: #fafafa; border-radius: 6px; border-left: 3px solid #e94560; }
    .article h3 { margin: 0 0 5px; font-size: 14px; }
    .article h3 a { color: #1a1a2e; text-decoration: none; }
    .article p { margin: 5px 0 0; font-size: 13px; color: #555; line-height: 1.5; }
    .article .meta { font-size: 11px; color: #999; }
    .footer { padding: 20px; text-align: center; font-size: 12px; color: #999; background: #f5f5f5; }
    .cta-button { display: inline-block; background: #e94560; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; margin: 20px 0; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>{{ title }}</h1>
      <p>{{ subtitle }}</p>
    </div>
    <div class="content">
      <p>Your {{ frequency }} news briefing for <strong>{{ country }}</strong> is ready.</p>
      <p style="font-size: 13px; color: #666;">{{ date_range }}</p>

      <table width="100%" cellpadding="0" cellspacing="0" style="margin: 20px 0;">
        <tr>
          <td align="center" style="padding: 15px; background: #f8f8f8; border-radius: 8px;">
            <div style="font-size: 28px; font-weight: bold; color: #e94560;">{{ total_articles }}</div>
            <div style="font-size: 12px; color: #888; text-transform: uppercase;">Articles</div>
          </td>
          <td width="10"></td>
          <td align="center" style="padding: 15px; background: #f8f8f8; border-radius: 8px;">
            <div style="font-size: 28px; font-weight: bold; color: #e94560;">{{ total_sources }}</div>
            <div style="font-size: 12px; color: #888; text-transform: uppercase;">Sources</div>
          </td>
          <td width="10"></td>
          <td align="center" style="padding: 15px; background: #f8f8f8; border-radius: 8px;">
            <div style="font-size: 28px; font-weight: bold; color: #e94560;">{{ total_entities }}</div>
            <div style="font-size: 12px; color: #888; text-transform: uppercase;">Key Figures</div>
          </td>
        </tr>
      </table>

      {% for cat_name, articles in categories.items() %}
      <div class="category">
        <h2>{{ cat_name | upper }}</h2>
        {% for article in articles[:5] %}
        <div class="article">
          <h3><a href="{{ article.url }}">{{ article.title }}</a></h3>
          <div class="meta">{{ article.source }} | {{ article.date }}</div>
          <p>{{ article.summary }}</p>
        </div>
        {% endfor %}
      </div>
      {% endfor %}

      {% if pdf_attached %}
      <p style="text-align: center; margin-top: 30px;">
        <strong>Full report attached as PDF.</strong>
      </p>
      {% endif %}
    </div>
    <div class="footer">
      <p>You're receiving this because you subscribed to NewsIntel briefings.</p>
      <p><a href="{{ unsubscribe_url }}" style="color: #999;">Unsubscribe</a></p>
    </div>
  </div>
</body>
</html>
"""


class EmailSender:
    """Sends report emails to subscribers."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        sender_email: str,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.sender_email = sender_email
        self._template = Template(EMAIL_TEMPLATE)

    def send_report(
        self,
        recipient_email: str,
        recipient_name: str,
        subject: str,
        template_data: dict,
        pdf_path: Optional[Path] = None,
    ) -> bool:
        """
        Send a report email with optional PDF attachment.

        Args:
            recipient_email:  To address
            recipient_name:   Recipient display name
            subject:          Email subject line
            template_data:    Dict for rendering the HTML template
            pdf_path:         Optional path to PDF attachment

        Returns:
            True if sent successfully
        """
        try:
            msg = MIMEMultipart("mixed")
            msg["From"] = f"NewsIntel <{self.sender_email}>"
            msg["To"] = f"{recipient_name} <{recipient_email}>"
            msg["Subject"] = subject

            # Render HTML body
            html_body = self._template.render(**template_data)
            html_part = MIMEText(html_body, "html", "utf-8")
            msg.attach(html_part)

            # Attach PDF if provided
            if pdf_path and Path(pdf_path).exists():
                with open(pdf_path, "rb") as f:
                    pdf_attachment = MIMEApplication(f.read(), _subtype="pdf")
                    pdf_attachment.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=Path(pdf_path).name,
                    )
                    msg.attach(pdf_attachment)

            # Send
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info(
                "email_sent",
                to=recipient_email,
                subject=subject,
                has_pdf=pdf_path is not None,
            )
            return True

        except Exception as e:
            logger.error(
                "email_send_failed",
                to=recipient_email,
                error=str(e),
            )
            return False

    def send_batch(
        self,
        recipients: list[dict],
        subject: str,
        template_data: dict,
        pdf_path: Optional[Path] = None,
    ) -> dict:
        """
        Send the same report to multiple recipients.

        Args:
            recipients:  List of {"email": ..., "name": ...}
            subject:     Email subject
            template_data: Template context
            pdf_path:    Optional PDF attachment

        Returns:
            Stats dict with sent/failed counts
        """
        stats = {"sent": 0, "failed": 0}

        for recipient in recipients:
            success = self.send_report(
                recipient_email=recipient["email"],
                recipient_name=recipient.get("name", ""),
                subject=subject,
                template_data=template_data,
                pdf_path=pdf_path,
            )
            if success:
                stats["sent"] += 1
            else:
                stats["failed"] += 1

        logger.info("batch_send_complete", **stats)
        return stats

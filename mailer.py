# -*- coding: utf-8 -*-
"""Send engine — GỬI QUA OUTLOOK M365 CỦA TỔ CHỨC (sender @midomax.vn).
send() tự chọn kênh: nếu có đủ creds Graph (cfg.USE_GRAPH) -> Microsoft Graph (Mail.Send, client-credentials);
ngược lại -> SMTP Outlook 587 STARTTLS (dự phòng, chỉ chạy nếu org còn cho Basic Auth).
Đổi/điều chỉnh kênh chỉ sửa file này; phần còn lại không phụ thuộc cách gửi."""
import smtplib, ssl, sys, os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alert_config as cfg

GRAPH_AUTHORITY = "https://login.microsoftonline.com/{tenant}"
GRAPH_SCOPE     = ["https://graph.microsoft.com/.default"]


def has_channel():
    """True nếu đã cấu hình được 1 kênh gửi (Graph creds hoặc SMTP password)."""
    return cfg.USE_GRAPH or bool(cfg.SMTP_PASSWORD)


def send(subject, html, to=None):
    """Gửi 1 email HTML (@midomax.vn). Tự chọn Graph nếu có creds, else SMTP. Trả về số người nhận."""
    to = to or cfg.RECIPIENTS
    if cfg.USE_GRAPH:
        return _send_via_graph(subject, html, to)
    return _send_via_smtp(subject, html, to)


def _send_via_graph(subject, html, to):
    """Microsoft Graph (Mail.Send application): msal lấy token -> POST /users/{sender}/sendMail."""
    import msal, requests  # pip install msal requests
    app = msal.ConfidentialClientApplication(
        cfg.GRAPH_CLIENT_ID,
        authority=GRAPH_AUTHORITY.format(tenant=cfg.GRAPH_TENANT_ID),
        client_credential=cfg.GRAPH_SECRET)
    tok = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in tok:
        raise RuntimeError(f"Graph lấy token lỗi: {tok.get('error')} - {tok.get('error_description')}")
    payload = {"message": {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
    }, "saveToSentItems": True}
    r = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{cfg.SENDER}/sendMail",
        headers={"Authorization": "Bearer " + tok["access_token"], "Content-Type": "application/json"},
        json=payload, timeout=60)
    if r.status_code not in (202, 200):
        raise RuntimeError(f"Graph sendMail lỗi {r.status_code}: {r.text}")
    return len(to)


def _send_via_smtp(subject, html, to):
    """SMTP Outlook M365 587 STARTTLS (dự phòng)."""
    if not cfg.SMTP_PASSWORD:
        raise RuntimeError("Chưa có kênh gửi: thiếu creds Graph (config.py) và chưa set ALERT_SMTP_PASSWORD.")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject; msg["From"] = cfg.SENDER; msg["To"] = ", ".join(to)
    msg.attach(MIMEText(html, "html", "utf-8"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT) as s:
        s.ehlo(); s.starttls(context=ctx); s.ehlo()
        s.login(cfg.SENDER, cfg.SMTP_PASSWORD); s.sendmail(cfg.SENDER, to, msg.as_string())
    return len(to)

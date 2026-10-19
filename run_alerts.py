# -*- coding: utf-8 -*-
"""Orchestrator: chạy rule -> nếu có SKU MỚI -> render HTML -> gửi mail. Dedup để không gửi lại SKU đã báo.
  python run_alerts.py            # gửi thật (cần ALERT_SMTP_PASSWORD)
  python run_alerts.py --dry-run  # chỉ in + xuất preview.html, KHÔNG gửi
Lịch: thêm dòng gọi file này vào run_daily.bat."""
import sys, os, io, csv, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import alert_config as cfg
import received_not_sold as rule
import mailer

HERE = os.path.dirname(os.path.abspath(__file__))
SENT_LOG = os.path.join(HERE, "sent_log.csv")   # key = "SKU|ngày nhập" -> chỉ báo 1 lần / SKU-lần-nhập


def load_sent():
    s = set()
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG, encoding="utf-8") as f:
            for row in csv.reader(f):
                if row:
                    s.add(row[0])
    return s


def append_sent(keys):
    with open(SENT_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f); today = datetime.date.today().isoformat()
        for k in keys:
            w.writerow([k, today])


def main(dry):
    cn, cur = rule.connect()
    rows = rule.detect(cur); cn.close()
    sent = load_sent()
    new = [r for r in rows if f"{r[0]}|{r[2]}" not in sent]   # r[0]=SKU, r[2]=first_receipt
    print(f"{len(rows)} SKU hit rule; {len(new)} MỚI (chưa báo).")
    if not new:
        print("Không có SKU mới -> không gửi."); return
    html = rule.render_html(new)
    subj = f"Hàng nhập kho hơn {cfg.NO_SALE_DAYS} ngày chưa phát sinh doanh số"
    if not dry and not mailer.has_channel():
        print("⚠ Chưa cấu hình kênh gửi (Graph creds ở config.py / ALERT_SMTP_PASSWORD) -> chạy DRY (không gửi).")
        dry = True
    if dry:
        out = os.path.join(HERE, "preview.html"); open(out, "w", encoding="utf-8").write(html)
        print("[DRY-RUN] KHÔNG gửi. Subject:", subj); print("Preview HTML ->", out)
    else:
        n = mailer.send(subj, html)
        append_sent([f"{r[0]}|{r[2]}" for r in new])
        print(f"Đã gửi tới {n} người; ghi {len(new)} SKU vào sent_log.csv.")


if __name__ == "__main__":
    main("--dry-run" in sys.argv or "--dry" in sys.argv)

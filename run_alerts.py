# -*- coding: utf-8 -*-
"""Orchestrator: chạy rule -> lọc SKU đủ điều kiện (cooldown) -> render HTML -> gửi mail.
Dedup = cooldown theo SKU: SKU đã gửi bị chặn cfg.COOLDOWN_DAYS ngày; sau đó nếu vẫn fail thì nhắc lại.
  python run_alerts.py            # gửi thật (cần kênh Graph/SMTP)
  python run_alerts.py --dry-run  # chỉ in + xuất preview.html, KHÔNG gửi
Lịch: thêm dòng gọi file này vào run_daily.bat."""
import sys, os, io, csv, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import alert_config as cfg
import received_not_sold as rule
import mailer

HERE = os.path.dirname(os.path.abspath(__file__))
SENT_LOG = os.path.join(HERE, "alert_sent_log.csv")  # mỗi dòng = "Mã hàng(Code), ngày-gửi" (append, giữ history).
#   Grain alert = Code (mặt hàng+màu). File sent_log.csv cũ (grain SKU) giữ lại làm lịch sử, KHÔNG dùng nữa.


def load_sent():
    """Đọc sent_log.csv -> dict {sku: ngày gửi GẦN NHẤT (date)}.
    Tương thích format cũ (key 'SKU|ngày-lô'): lấy phần trước '|' làm SKU."""
    m = {}
    if os.path.exists(SENT_LOG):
        # utf-8-sig: nuốt BOM nếu có (tránh BOM ở đầu file làm hỏng khóa dòng đầu -> dedup sai)
        with open(SENT_LOG, encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if not row or len(row) < 2:
                    continue
                sku = row[0].split("|")[0].strip()
                try:
                    d = datetime.date.fromisoformat(row[1].strip())
                except ValueError:
                    continue   # bỏ dòng ngày hỏng
                if sku and (sku not in m or d > m[sku]):
                    m[sku] = d
    return m


def append_sent(skus):
    """Ghi mỗi SKU vừa gửi 1 dòng [sku, hôm nay]."""
    with open(SENT_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f); today = datetime.date.today().isoformat()
        for sku in skus:
            w.writerow([sku, today])


def main(dry):
    cn, cur = rule.connect()
    rows = rule.detect(cur); cn.close()
    sent = load_sent()
    today = datetime.date.today()
    cd = getattr(cfg, "COOLDOWN_DAYS", 2)

    def eligible(sku):
        # Gửi nếu chưa từng gửi, hoặc đã qua cooldown (today - lần gửi cuối > COOLDOWN_DAYS)
        last = sent.get(sku)
        return last is None or (today - last).days > cd

    new = [r for r in rows if eligible(r[0])]   # r[0] = Products_Key (khóa dedup, ổn định)
    print(f"{len(rows)} mặt hàng hit rule; {len(new)} đủ điều kiện gửi (cooldown {cd} ngày/mặt hàng).")
    if not new:
        print("Không có mặt hàng đủ điều kiện -> không gửi."); return
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
        append_sent([r[0] for r in new])
        print(f"Đã gửi tới {n} người; ghi {len(new)} mặt hàng vào alert_sent_log.csv.")


if __name__ == "__main__":
    main("--dry-run" in sys.argv or "--dry" in sys.argv)

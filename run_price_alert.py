# -*- coding: utf-8 -*-
"""Orchestrator alert THAY ĐỔI GIÁ BÁN LẺ: detect (LAG, window N ngày) -> dedup -> gửi mail.
Dedup "đã gửi là thôi": key = "SKU|ngày đổi|giá mới" trong price_change_sent_log.csv (append, giữ history).
  python run_price_alert.py            # gửi thật (cần kênh Graph/SMTP)
  python run_price_alert.py --dry-run  # chỉ in + xuất preview_price.html, KHÔNG gửi
  python run_price_alert.py --lookback=30  # mở rộng cửa sổ (test với data cũ)
Lịch: 14h10 VN = '10 7 * * *' UTC (ngay sau alert tồn kho 14h00)."""
import sys, os, io, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import alert_config as cfg
import retail_price_change as rule
import mailer

HERE = os.path.dirname(os.path.abspath(__file__))
SENT_LOG = os.path.join(HERE, "price_change_sent_log.csv")  # mỗi dòng = "SKU|ngày|giá mới"


def _key(sku, change_date, new_num, new_p):
    """Danh tính 1 thay đổi giá: SKU | ngày đổi | chứng từ mới (Mã) | giá mới (tròn).
    Chứng từ = ID sự kiện; ngày chống số chứng từ lặp qua năm."""
    return f"{sku}|{change_date}|{new_num}|{int(round(float(new_p)))}"


def load_sent():
    s = set()
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG, encoding="utf-8-sig") as f:   # utf-8-sig: nuốt BOM nếu có
            for row in csv.reader(f):
                if row and row[0].strip():
                    s.add(row[0].strip())
    return s


def append_sent(keys):
    with open(SENT_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for k in keys:
            w.writerow([k])


def main(dry, lookback=None):
    # Lần chạy ĐẦU TIÊN (chưa có log) & không chỉ định --lookback -> quét rộng bắt đợt đổi gần nhất (ra mắt).
    first_run = lookback is None and not os.path.exists(SENT_LOG)
    if first_run:
        lookback = getattr(cfg, "PRICE_FIRST_RUN_LOOKBACK", 30)
        print(f"[first-run] log trống -> quét {lookback} ngày (bắt đợt đổi gần nhất)")
    cn, cur = rule.connect()
    rows = rule.detect(cur, lookback_days=lookback)   # None -> cfg.PRICE_LOOKBACK_DAYS
    cn.close()
    sent = load_sent()
    # r = (sku, sport, pname, sku_detail, change_date, old_price, old_doc, new_price, new_doc, new_num)
    new = [r for r in rows if _key(r[0], r[4], r[9], r[7]) not in sent]
    win = lookback if lookback is not None else cfg.PRICE_LOOKBACK_DAYS
    print(f"{len(rows)} SKU đổi giá bán lẻ (window {win} ngày); {len(new)} chưa gửi.")
    if not new:
        print("Không có thay đổi mới -> không gửi."); return
    html = rule.render_html(new)
    subj = "Thay đổi thông tin sản phẩm"
    if not dry and not mailer.has_channel():
        print("⚠ Chưa cấu hình kênh gửi (Graph/SMTP) -> chạy DRY (không gửi)."); dry = True
    if dry:
        out = os.path.join(HERE, "preview_price.html"); open(out, "w", encoding="utf-8").write(html)
        print("[DRY-RUN] KHÔNG gửi. Subject:", subj); print("Preview ->", out)
    else:
        # Người nhận: env ALERT_RECIPIENTS (test) -> else PRICE_RECIPIENTS (prod, khác list tồn kho)
        rcpt = [x.strip() for x in os.environ.get("ALERT_RECIPIENTS", "").split(",") if x.strip()] or cfg.PRICE_RECIPIENTS
        n = mailer.send(subj, html, to=rcpt)
        append_sent([_key(r[0], r[4], r[9], r[7]) for r in new])
        print(f"Đã gửi tới {n} người; ghi {len(new)} thay đổi vào price_change_sent_log.csv.")


if __name__ == "__main__":
    _dry = "--dry-run" in sys.argv or "--dry" in sys.argv
    _lb = None
    for a in sys.argv[1:]:
        if a.startswith("--lookback="):
            _lb = int(a.split("=")[1])
    main(_dry, _lb)

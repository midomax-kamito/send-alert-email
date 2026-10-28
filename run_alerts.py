# -*- coding: utf-8 -*-
"""Orchestrator: chạy rule -> quyết định gửi theo SO SÁNH NGÀY-QUA-NGÀY -> render HTML -> gửi mail.

Luật gửi (thay cooldown cũ):
  - Lập danh sách hôm nay = mặt hàng (Products_Key) "nhập >NO_SALE_DAYS ngày chưa bán".
  - Có mặt hàng MỚI so với lần xử lý trước -> gửi FULL danh sách hiện tại; reset bộ đếm ngày lặng.
  - Không có mặt hàng mới -> không gửi, tăng bộ đếm; chạm REMINDER_QUIET_DAYS -> gửi nhắc full, reset.
  - Lần đầu (chưa có state) -> mọi mặt hàng là "mới" -> gửi full 1 lần (bootstrap).
Trạng thái ở alert_state.json: {prev_keys, quiet_days, last_date}. Guard last_date=hôm nay -> không gửi 2 lần/ngày.

  python run_alerts.py            # gửi thật (cần kênh Graph/SMTP)
  python run_alerts.py --dry-run  # chỉ in quyết định + xuất preview.html, KHÔNG gửi, KHÔNG đổi state
Lịch: cron trên server gọi file này 1 lần/ngày.
"""
import sys, os, io, csv, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import alert_config as cfg
import received_not_sold as rule
import mailer

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "alert_state.json")   # trạng thái day-over-day (prev_keys, quiet_days, last_date)
SENT_LOG = os.path.join(HERE, "alert_sent_log.csv")   # audit: mỗi dòng "Products_Key, ngày-gửi" (append, giữ history)


def load_state():
    """Đọc alert_state.json -> {prev_keys:set, quiet_days:int, last_date:str}. File chưa có/hỏng -> state rỗng."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return {"prev_keys": set(d.get("prev_keys", [])),
                "quiet_days": int(d.get("quiet_days", 0)),
                "last_date": str(d.get("last_date", ""))}
    except (FileNotFoundError, ValueError, OSError, TypeError):
        return {"prev_keys": set(), "quiet_days": 0, "last_date": ""}


def save_state(prev_keys, quiet_days, last_date):
    """Ghi atomic (tmp + replace) để không hỏng state nếu dừng giữa chừng."""
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"prev_keys": sorted(prev_keys), "quiet_days": int(quiet_days), "last_date": last_date},
                  f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def append_sent(keys):
    """Audit: ghi mỗi key vừa gửi 1 dòng [key, hôm nay] vào alert_sent_log.csv."""
    with open(SENT_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f); today = datetime.date.today().isoformat()
        for k in keys:
            w.writerow([k, today])


def decide(today_keys, prev_keys, quiet_days, reminder_days):
    """HÀM THUẦN (không đụng DB/file) -> (do_send, new_quiet, reason). Test được bằng mô phỏng.
    - Có mặt hàng mới (today - prev) -> gửi, quiet=0.
    - Hết mặt hàng mới & quiet_days+1 >= reminder_days -> gửi nhắc, quiet=0.
    - Còn lại -> không gửi, quiet+1."""
    new_members = set(today_keys) - set(prev_keys)
    if new_members:
        return True, 0, f"{len(new_members)} mặt hàng mới"
    if quiet_days + 1 >= reminder_days:
        return True, 0, f"nhắc định kỳ (đã {quiet_days + 1} ngày không có mặt hàng mới)"
    return False, quiet_days + 1, f"không có mặt hàng mới (ngày lặng {quiet_days + 1}/{reminder_days})"


def main(dry):
    cn, cur = rule.connect()
    rows = rule.detect(cur); cn.close()
    today_keys = {r[0] for r in rows}                 # r[0] = Products_Key (khóa so sánh, ổn định)
    state = load_state()
    today = datetime.date.today().isoformat()
    reminder = getattr(cfg, "REMINDER_QUIET_DAYS", 3)

    # Guard chống gửi 2 lần/ngày (chỉ ở chế độ gửi thật; dry-run luôn cho xem).
    if not dry and state["last_date"] == today:
        print(f"Đã xử lý hôm nay ({today}) -> bỏ qua (chống gửi trùng).")
        return

    do_send, new_quiet, reason = decide(today_keys, state["prev_keys"], state["quiet_days"], reminder)
    print(f"{len(rows)} mặt hàng trong tình trạng này | quyết định: "
          f"{'GỬI' if do_send else 'KHÔNG GỬI'} ({reason}).")

    subj = f"Hàng nhập kho hơn {cfg.NO_SALE_DAYS} ngày chưa phát sinh doanh số"

    if dry:
        if do_send and rows:
            out = os.path.join(HERE, "preview.html")
            open(out, "w", encoding="utf-8").write(rule.render_html(rows))
            print("[DRY-RUN] Sẽ gửi. Subject:", subj, "| Preview ->", out)
        else:
            print("[DRY-RUN] Sẽ KHÔNG gửi mail.")
        print("[DRY-RUN] Không thay đổi state.")
        return

    # Gửi full danh sách hiện tại nếu quyết định gửi VÀ có mặt hàng.
    if do_send and rows:
        if not mailer.has_channel():
            print("⚠ Chưa cấu hình kênh gửi (Graph/SMTP) -> KHÔNG gửi, KHÔNG đổi state (sẽ thử lại lần sau).")
            open(os.path.join(HERE, "preview.html"), "w", encoding="utf-8").write(rule.render_html(rows))
            return
        n = mailer.send(subj, rule.render_html(rows))
        append_sent([r[0] for r in rows])
        print(f"Đã gửi {len(rows)} mặt hàng tới {n} người.")
    elif do_send and not rows:
        print("Quyết định gửi nhưng danh sách rỗng -> không gửi mail (không có gì để báo).")
    # Cập nhật state cho ngày mai (prev = danh sách hôm nay, quiet đã tính trong decide).
    save_state(today_keys, new_quiet, today)
    print(f"State: quiet_days={new_quiet}, prev={len(today_keys)} mặt hàng, last_date={today}.")


if __name__ == "__main__":
    main("--dry-run" in sys.argv or "--dry" in sys.argv)

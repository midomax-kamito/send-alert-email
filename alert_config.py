# -*- coding: utf-8 -*-
"""Cấu hình alert: người gửi/nhận + tham số rule + bộ lọc nhiễu. (DB + Graph creds dùng config.py gốc của repo.)"""
import os, sys
# Dùng chung config.py (DB + Graph creds, gitignored) của repo 1c-data-sync — 1 nguồn secret duy nhất.
# Path config: env C1_CONFIG_DIR (Linux/server), fallback path Windows (máy dev).
sys.path.insert(0, os.environ.get("C1_CONFIG_DIR", r"D:\midomax\midomax\3. project\1c-data-sync-repo\1c-data-sync"))
import config

# ================== EMAIL — GỬI QUA OUTLOOK M365 CỦA TỔ CHỨC (@midomax.vn) ==================
# Kênh CHÍNH = Microsoft Graph (app "midomax-rules-alert-mailer", quyền Mail.Send, client-credentials).
# Creds đọc từ config.py (application_client_id / directory_tenant_id / value) — fallback env nếu muốn.
# SMTP Outlook 587 chỉ là dự phòng khi org còn cho Basic Auth (hiện M365 thường TẮT).
SENDER        = os.environ.get("ALERT_SENDER", "no-reply@midomax.vn")   # hộp thư Outlook tổ chức gửi đi
RECIPIENTS    = [   # người nhận
    "chucamlinh@midomax.vn",
    "minhnb@midomax.vn",
    "chatnv@midomax.vn",
    "anhttq@midomax.vn",
    "phuongnb@midomax.vn",
    "tuyenbvt@midomax.vn",
    "thuongvt@midomax.vn",
    "ngoclb@midomax.vn",
    "hangntk@midomax.vn",
    "hanhvtb@midomax.vn",
    "dinhndt@midomax.vn",
    "phuongnt@midomax.vn",
    "trinhltt@midomax.vn",
    "bi01@midomax.vn",
    "thaont@midomax.vn",
    "trangnth@midomax.vn",
]
# Override tạm (test/debug): ALERT_RECIPIENTS="a@midomax.vn,b@midomax.vn" -> chỉ gửi danh sách này.
# VD chạy thử gửi mỗi bi01: ALERT_RECIPIENTS=bi01@midomax.vn python3 run_alerts.py
_env_rcpt = os.environ.get("ALERT_RECIPIENTS", "").strip()
if _env_rcpt:
    RECIPIENTS = [x.strip() for x in _env_rcpt.split(",") if x.strip()]

# ---- Kênh A: Microsoft Graph (ưu tiên) ----
GRAPH_TENANT_ID = os.environ.get("ALERT_GRAPH_TENANT")   or getattr(config, "directory_tenant_id", "")
GRAPH_CLIENT_ID = os.environ.get("ALERT_GRAPH_CLIENT_ID") or getattr(config, "application_client_id", "")
GRAPH_SECRET    = os.environ.get("ALERT_GRAPH_CLIENT_SECRET") or getattr(config, "value", "")
USE_GRAPH       = bool(GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_SECRET)

# ---- Kênh B (dự phòng): SMTP Outlook M365 ----
SMTP_PASSWORD = os.environ.get("ALERT_SMTP_PASSWORD", "")               # mật khẩu/App Password của @midomax.vn
SMTP_HOST     = "smtp.office365.com"
SMTP_PORT     = 587                                                     # Outlook M365 = STARTTLS 587

# ---- Tham số rule "nhập nhưng chưa bán" ----
# Rule B (tốc độ mở bán): xét lô nhập 'đã chín' (ngày nhập + NO_SALE_DAYS <= hôm nay);
# fail nếu trong [ngày nhập, ngày nhập+NO_SALE_DAYS] không có đơn bán nào.
NO_SALE_DAYS = 5    # lô nhập đã >= N ngày mà chưa phát sinh đơn bán nào -> alert (business chốt 5 ngày)
WINDOW_DAYS  = 90   # trần quét lô nhập: chỉ xét lô nhập cách đây N..WINDOW_DAYS ngày (PHẢI > NO_SALE_DAYS).
                    #   =90 -> coi như "nhập >=5 ngày chưa bán", cắt trần 90 ngày để query nhẹ + không lôi tồn quá cũ.
MIN_RECV_QTY = 20   # chỉ alert lô có SL nhập > ngưỡng này (loại nhập mẫu/lẻ 1-2 chiếc). 0 = không lọc SL.

# ---- Gửi theo so sánh ngày-qua-ngày (THAY cooldown cũ) ----
# Logic trong run_alerts.py: mỗi ngày lập danh sách mặt hàng "nhập >NO_SALE_DAYS ngày chưa bán".
#   - Có mặt hàng MỚI so với lần xử lý trước -> gửi FULL danh sách hiện tại, reset bộ đếm ngày lặng.
#   - Không có mặt hàng mới -> không gửi, tăng bộ đếm; chạm REMINDER_QUIET_DAYS -> gửi nhắc full, reset.
# Trạng thái lưu ở alert_state.json (prev_keys + quiet_days + last_date). Lần đầu (chưa có state) = gửi full 1 lần.
REMINDER_QUIET_DAYS = 3   # ngày lặng thứ 3 (không có mặt hàng mới) thì gửi nhắc lại full danh sách
# COOLDOWN_DAYS: KHÔNG CÒN DÙNG (đã thay bằng logic day-over-day ở trên). Giữ biến để không vỡ import cũ.
COOLDOWN_DAYS = 2

# ---- Rule 2: thay đổi GIÁ BÁN LẺ ----
# PriceKind 'Giá bán lẻ' trong TypesOfPrices (1C). Giá đổi khi có PriceSetup mới với giá khác lần trước.
RETAIL_PRICE_KIND   = "a1d6ecca-0372-11ef-84a3-3cfdfe9ee884"
# Báo thay đổi giá có Date trong N ngày gần nhất (hấp thụ sync trễ / cron lỡ ngày / cuối tuần).
# Window > 1 ngày nên BẮT BUỘC dedup (price_change_sent_log.csv, key = SKU|ngày|chứng từ mới|giá mới).
PRICE_LOOKBACK_DAYS = 4
# Lần chạy ĐẦU TIÊN (chưa có log) quét rộng hơn để bắt đợt đổi giá gần nhất (ra mắt). Sau đó về PRICE_LOOKBACK_DAYS.
PRICE_FIRST_RUN_LOOKBACK = 30
# Người nhận alert giá (KHÁC list tồn kho). run_price_alert.py dùng list này; env ALERT_RECIPIENTS override (test).
PRICE_RECIPIENTS = [
    "minhnb@midomax.vn", "thuongvt@midomax.vn", "phuongnb@midomax.vn", "huepv@midomax.vn",
    "thaont@midomax.vn", "chatnv@midomax.vn", "tuyenbvt@midomax.vn", "anhnd@midomax.vn",
    "nganhtt@midomax.vn", "ngoclb@midomax.vn", "hanhvtb@midomax.vn", "hangntk@midomax.vn",
    "yendtk@midomax.vn", "thangnv@midomax.vn", "anhnt@midomax.vn", "duynt@midomax.vn",
    "trangnth@midomax.vn", "phuongnt@midomax.vn", "dinhndt@midomax.vn", "trinhltt@midomax.vn",
    "lyntp@midomax.vn", "tungnd@midomax.vn", "bi01@midomax.vn",
]

# ---- Bộ lọc nhiễu (REGEXP, utf8mb4_general_ci = không phân biệt hoa thường) ----
# Chỉ tính loại mặt hàng này (ItemKinds.Description). Loại Dịch vụ/phí... tự bị loại.
ITEM_KIND               = "Hàng hóa"
# Kho KHÔNG tính (bảo hành / hàng mẫu / chụp hình / công cụ-dụng cụ / gửi NCC / trung gian)
EXCLUDE_WAREHOUSE_REGEX = r"bảo hành|hàng mẫu|chụp hình|CCDC|gửi nhà cung cấp|trung gian"
# TẮT (để rỗng). Lọc theo TỪ KHÓA trong tên không đáng tin: 'hộp' còn nằm trong tên hàng BÁN được
# (bóng 'hộp 3 quả', grip '21 cuộn/hộp', combo quà) -> loại nhầm hàng bán. Loại bao bì giao cho EXCLUDE_GROUP_EXACT.
EXCLUDE_NAME_REGEX      = r""
# TẮT (để rỗng). 5 tên trước đây đều đã được EXCLUDE_GROUP_EXACT (theo nhóm) phủ -> thừa.
EXCLUDE_NAME_EXACT      = []
# SKU prefix: TẮT (để rỗng). Trước dùng '^VT' với giả định VT = vật tư, nhưng nhiều SKU ^VT nằm
# trong nhóm BÁN (Phụ kiện/Vợt) nơi 'VT' KHÔNG mang nghĩa 'vật tư' -> lọc theo prefix không đáng tin.
# Việc loại vật tư/bao bì/không-bán giao cho EXCLUDE_GROUP_EXACT (theo nhóm) đảm nhiệm.
EXCLUDE_SKU_REGEX       = r""
# Loại theo NHÓM: đã chuyển sang BẢNG DWH `tb_excluded_group_products_sport_brand` (nguồn chuẩn, dùng chung
# với vw_sku.is_excluded_group_products_sport_brand). received_not_sold.py anti-join trực tiếp bảng đó.
# Sửa danh sách = INSERT/UPDATE is_active/DELETE trong DB (không cần sửa code). Nhóm "Dự án" không đưa vào bảng.

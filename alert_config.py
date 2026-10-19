# -*- coding: utf-8 -*-
"""Cấu hình alert: người gửi/nhận + tham số rule + bộ lọc nhiễu. (DB + Graph creds dùng config.py gốc của repo.)"""
import os, sys
# Dùng chung config.py (DB + Graph creds, gitignored) của repo 1c-data-sync — 1 nguồn secret duy nhất.
sys.path.insert(0, r"D:\midomax\midomax\3. project\1c-data-sync-repo\1c-data-sync")
import config

# ================== EMAIL — GỬI QUA OUTLOOK M365 CỦA TỔ CHỨC (@midomax.vn) ==================
# Kênh CHÍNH = Microsoft Graph (app "midomax-rules-alert-mailer", quyền Mail.Send, client-credentials).
# Creds đọc từ config.py (application_client_id / directory_tenant_id / value) — fallback env nếu muốn.
# SMTP Outlook 587 chỉ là dự phòng khi org còn cho Basic Auth (hiện M365 thường TẮT).
SENDER        = os.environ.get("ALERT_SENDER", "no-reply@midomax.vn")   # hộp thư Outlook tổ chức gửi đi
RECIPIENTS    = [   # người nhận
    # "chucamlinh@midomax.vn",
    # "minhnb@midomax.vn",
    # "chatnv@midomax.vn",
    # "anhttq@midomax.vn",
    # "phuongnb@midomax.vn",
    # "tuyenbvt@midomax.vn",
    # "thuongvt@midomax.vn",
    # "hangntk@midomax.vn",
    # "hanhvtb@midomax.vn",
    # "dinhndt@midomax.vn",
    # "phuongnt@midomax.vn",
    # "trinhltt@midomax.vn",
    "bi01@midomax.vn",
]

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
NO_SALE_DAYS = 5    # cửa sổ "5 ngày đầu" sau nhập phải phát sinh đơn bán
WINDOW_DAYS  = 10   # quét lô nhập trong N ngày gần nhất (PHẢI >= NO_SALE_DAYS). Nới rộng = chịu được run sót;
                    #   dedup (sent_log) đảm bảo mỗi lô fail chỉ gửi 1 lần dù chạy nhiều lần/ngày.
MIN_RECV_QTY = 20   # chỉ alert lô có SL nhập > ngưỡng này (loại nhập mẫu/lẻ 1-2 chiếc). 0 = không lọc SL.

# ---- Bộ lọc nhiễu (REGEXP, utf8mb4_general_ci = không phân biệt hoa thường) ----
# Chỉ tính loại mặt hàng này (ItemKinds.Description). Loại Dịch vụ/phí... tự bị loại.
ITEM_KIND               = "Hàng hóa"
# Kho KHÔNG tính (bảo hành / hàng mẫu / chụp hình / công cụ-dụng cụ / gửi NCC / trung gian)
EXCLUDE_WAREHOUSE_REGEX = r"bảo hành|hàng mẫu|chụp hình|CCDC|gửi nhà cung cấp|trung gian"
# Hàng KHÔNG tính theo tên (bao bì). Để "" nếu không muốn lọc.
EXCLUDE_NAME_REGEX      = r"hộp|carton|thùng"
# SKU KHÔNG tính theo prefix: 'VT' = vật tư (bao bì/công cụ dụng cụ/tem/decan...). Để "" nếu không lọc.
EXCLUDE_SKU_REGEX       = r"^VT"

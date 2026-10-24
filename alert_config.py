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
NO_SALE_DAYS = 10   # lô nhập đã >= N ngày mà chưa phát sinh đơn bán nào -> alert (business chốt 10 ngày)
WINDOW_DAYS  = 90   # trần quét lô nhập: chỉ xét lô nhập cách đây N..WINDOW_DAYS ngày (PHẢI > NO_SALE_DAYS).
                    #   =90 -> coi như "nhập >=10 ngày chưa bán", cắt trần 90 ngày để query nhẹ + không lôi tồn quá cũ.
MIN_RECV_QTY = 20   # chỉ alert lô có SL nhập > ngưỡng này (loại nhập mẫu/lẻ 1-2 chiếc). 0 = không lọc SL.

# ---- Dedup: cooldown theo SKU (chống spam, vẫn nhắc định kỳ) ----
# Đã gửi 1 SKU -> chặn COOLDOWN_DAYS ngày tiếp; ngày thứ (COOLDOWN_DAYS+1) nếu vẫn fail thì gửi lại.
# VD =2: gửi ngày D -> chặn D+1, D+2 -> D+3 mở lại. Cooldown thuần theo SKU (lô nhập mới trong cooldown vẫn bị chặn).
COOLDOWN_DAYS = 2

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
# Loại theo NHÓM DANH SÁCH (Products.Parent_Key -> Description = nhóm cha trực tiếp của mặt hàng).
# Khớp TRIM + general_ci (không phân biệt hoa thường, bỏ khoảng trắng thừa). Gồm: vật tư/chi phí/phí/
# công cụ-thiết bị/in ấn/bao bì/dịch vụ + toàn bộ nhóm HÀNG MẪU (không bán). Giữ nhóm "Dự án".
EXCLUDE_GROUP_EXACT     = [
    # --- Không phải hàng bán (vật tư / chi phí / công cụ / in ấn / bao bì / dịch vụ) ---
    "Vật tư khác", "Vật tư băng dính", "Vật tư (kho, showroom, BP in ép)",
    "CPQLBH khác", "CP Lương", "Chi phí QLBH",
    "Phí khác", "Phí ship", "Phí làm khuôn, mẫu", "Phí test mẫu",
    "Công cụ dụng cụ, thiết bị khác", "Công cụ dụng cụ, thiết bị",
    "Máy tính", "Vách, giá, kệ, tủ", "Bàn ghế", "Điều hòa", "Khung chữ A",
    "Decal", "Mực in", "Bột pet",
    "Túi, hộp đựng sản phẩm", "Túi, thùng bán hàng",
    "Dịch vụ", "Hóa đơn", "Khác",
    # --- Hàng MẪU (nhập kho nhưng không bán) ---
    "Giày Mẫu", "Giày Mẫu Kamito, Mizuno", "Giày Mẫu Khác",
    "Vợt Mẫu", "Vợt Mẫu Kamito, Mizuno", "Vợt Mẫu Khác",
    "Quần áo Mẫu", "Quần áo Mẫu Kamito, Mizuno", "Quần áo Mẫu Khác",
    "Phụ kiện Mẫu", "Phụ kiện Mẫu Kamito, Mizuno", "Phụ kiện Mẫu Khác",
    "Quả bóng Mẫu", "Quả bóng Mẫu Kamito, Mizuno", "Quả bóng Mẫu Khác",
    "Túi balo Mẫu", "Túi balo Mẫu Kamito, Mizuno", "Túi balo Mẫu Khác",
    "Tất Mẫu", "Tất Mẫu Kamito, Mizuno",
    "Mũ Mẫu", "Mũ mẫu Kamito",
]

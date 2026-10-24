# -*- coding: utf-8 -*-
"""Rule: MẶT HÀNG (sản phẩm = Products_Key, gộp mọi màu/size) đã NHẬP (GoodsReceiptNote) mà CHƯA BÁN kể từ ngày nhập.
Mô hình 1 bảng (grain = PHIẾU nhập × SẢN PHẨM): mỗi lô nhập + 'ngày bán đầu tiên SAU ngày nhập'
(NULL = chưa bán). HIT RULE = (chưa bán) & (ngày nhập >= today-NO_SALE_DAYS) & (SL phiếu > MIN_RECV_QTY).
Mỗi sản phẩm báo lô XA NHẤT (ngày nhập cũ nhất chưa bán) -> số ngày = TUỔI TỒN ĐỌNG.
Lọc: kho bán được / loại Hàng hóa / tên bao bì / SKU ^VT / Nhóm danh sách (EXCLUDE_GROUP_EXACT: vật tư·chi phí·hàng mẫu...).
Nguồn: DWH kazgevim_1C (Posted=1, DeletionMark=0).
"""
import sys, os
# Dùng chung config.py (DB creds, gitignored) của repo 1c-data-sync — 1 nguồn secret duy nhất.
# Path config: env C1_CONFIG_DIR (Linux/server), fallback path Windows (máy dev).
sys.path.insert(0, os.environ.get("C1_CONFIG_DIR", r"D:\midomax\midomax\3. project\1c-data-sync-repo\1c-data-sync"))
import config, pymysql
import alert_config as cfg


def connect():
    cn = pymysql.connect(host=config.db_host, user=config.db_user, password=config.db_raw_password,
                         database=config.db_name, port=config.db_port, charset="utf8mb4", read_timeout=600)
    cur = cn.cursor(); cur.execute("SET collation_connection='utf8mb4_general_ci'")
    return cn, cur


def detect(cur):
    """-> list[(products_key, code, name, fail_day, days_since, recv_qty, warehouses, phieu)].
    Grain = PHIẾU nhập × PRODUCTS (mặt hàng, gộp mọi màu+size). code = GROUP_CONCAT mã (ic.Code) của SP.
    Mô hình 1 bảng: lô nhập + 'ngày bán đầu tiên SAU ngày nhập' (NULL = chưa bán). HIT RULE = chưa bán &
    ngày nhập >= today-N & SL phiếu > Q. Mỗi SP báo lô XA NHẤT (ngày nhập cũ nhất chưa bán) -> tuổi tồn đọng.
    Bán BẤT KỲ màu/size nào của SP kể từ nhập -> cả SP coi như chạy. Dedup theo Products_Key (ổn định)."""
    W, N, Q = cfg.WINDOW_DAYS, cfg.NO_SALE_DAYS, cfg.MIN_RECV_QTY
    # Loại CỨNG theo tên chính xác (inline literal nên ký tự *+() an toàn; COLLATE general_ci tránh lệch collation với Products unicode_ci)
    _exact = getattr(cfg, "EXCLUDE_NAME_EXACT", []) or []
    exact_clause = ""
    if _exact:
        _vals = ",".join("'" + x.replace("'", "''") + "'" for x in _exact)
        exact_clause = f"AND (p.Description IS NULL OR p.Description COLLATE utf8mb4_general_ci NOT IN ({_vals}))"
    # Loại theo NHÓM: anti-join bảng tb_excluded_group_products_sport_brand (nguồn chuẩn trong DWH, sửa bằng SQL).
    # par = nhóm cha trực tiếp của SP (= group_products_sport_brand). Cả 2 unicode_ci -> không cần COLLATE.
    # Nhóm mới KHÔNG có trong bảng -> không loại (chỉ loại khi được thêm vào bảng).
    # 1) BẢNG LÔ NHẬP: mỗi dòng = (phiếu × Products_Key), SL = tổng mọi màu/size của SP trong phiếu.
    #    Lọc CẤU TRÚC: kho bán được, loại Hàng hóa, tên ≠ bao bì, Code ≠ ^VT, tên ∉ loại cứng. (≥N ngày & SL>Q ở bước 4)
    cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_recv")
    cur.execute(f"""CREATE TEMPORARY TABLE tmp_recv AS
        SELECT h.Ref_Key AS pn_key, g.Products_Key AS pk, MAX(h.Number) AS phieu, MAX(LEFT(h.Date,10)) AS rday,
               MAX(w.Description) AS kho, MAX(p.Description) AS name,
               GROUP_CONCAT(DISTINCT TRIM(ic.Code) ORDER BY TRIM(ic.Code) SEPARATOR ', ') AS code,
               SUM(g.Count) AS sl
        FROM GoodsReceiptNote h
        JOIN GoodsReceiptNote_Goods g ON g.Ref_Key = h.Ref_Key
        JOIN ItemsCharacteristics ic ON ic.Ref_Key = g.Characteristic_Key
        JOIN ItemKinds ik ON CAST(ic.ProductKind_Key AS char(50) charset utf8mb4) COLLATE utf8mb4_general_ci
                           = CAST(ik.Ref_Key          AS char(50) charset utf8mb4) COLLATE utf8mb4_general_ci
        LEFT JOIN Products p ON p.Ref_Key = g.Products_Key
        LEFT JOIN Products par ON par.Ref_Key = p.Parent_Key
        LEFT JOIN tb_excluded_group_products_sport_brand exg
               ON TRIM(par.Description) = exg.group_products_sport_brand AND exg.is_active = 1
        LEFT JOIN Warehouses w ON w.Ref_Key = h.Warehouse_Key
        WHERE h.Posted=1 AND h.DeletionMark=0
          AND ic.SKU <> ''
          AND h.Date >= DATE_FORMAT(CURDATE() - INTERVAL {W} DAY, '%%Y-%%m-%%d')
          AND h.Date <  DATE_FORMAT(CURDATE() + INTERVAL 1 DAY, '%%Y-%%m-%%d')
          AND (%s = '' OR w.Description IS NULL OR w.Description NOT REGEXP %s)
          AND CAST(ik.Description AS char(50) charset utf8mb4) COLLATE utf8mb4_general_ci = %s
          AND (%s = '' OR p.Description IS NULL OR p.Description NOT REGEXP %s)
          {exact_clause}
          AND exg.group_products_sport_brand IS NULL
          AND (%s = '' OR TRIM(ic.Code) NOT REGEXP %s)
        GROUP BY h.Ref_Key, g.Products_Key""",
        (cfg.EXCLUDE_WAREHOUSE_REGEX, cfg.EXCLUDE_WAREHOUSE_REGEX, cfg.ITEM_KIND,
         cfg.EXCLUDE_NAME_REGEX, cfg.EXCLUDE_NAME_REGEX, cfg.EXCLUDE_SKU_REGEX, cfg.EXCLUDE_SKU_REGEX))
    # 2) NGÀY bán (distinct Products_Key, ngày) trong cửa sổ -> để tìm 'ngày bán đầu tiên sau nhập'
    cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_sold")
    cur.execute(f"""CREATE TEMPORARY TABLE tmp_sold AS
        SELECT DISTINCT cg.Products_Key AS pk, LEFT(ci.Date,10) AS sday
        FROM CustomerInvoice ci
        JOIN CustomerInvoice_Goods cg ON cg.Ref_Key = ci.Ref_Key
        WHERE ci.Posted=1 AND ci.DeletionMark=0
          AND ci.Date >= DATE_FORMAT(CURDATE() - INTERVAL {W} DAY, '%Y-%m-%d')""")
    # 3) GẮN 'ngày bán đầu tiên SAU ngày nhập' = MIN(sday >= rday); NULL = chưa bán kể từ nhập
    cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_enriched")
    cur.execute("""CREATE TEMPORARY TABLE tmp_enriched AS
        SELECT r.pk, r.phieu, r.rday, r.kho, r.name, r.code, r.sl, MIN(s.sday) AS next_sale
        FROM tmp_recv r
        LEFT JOIN tmp_sold s ON s.pk = r.pk AND s.sday >= r.rday
        GROUP BY r.pn_key, r.pk, r.phieu, r.rday, r.kho, r.name, r.code, r.sl""")
    # 4a) HIT RULE -> mỗi Products lấy lô XA NHẤT (MIN rday). (temp table tách riêng: MariaDB
    #     không cho tham chiếu 1 temp table 2 lần trong cùng 1 query)
    cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_oldest")
    cur.execute(f"""CREATE TEMPORARY TABLE tmp_oldest AS
        SELECT pk, MIN(rday) AS fail_day
        FROM tmp_enriched
        WHERE next_sale IS NULL
          AND rday <= DATE_FORMAT(CURDATE() - INTERVAL {N} DAY, '%Y-%m-%d')
          AND sl > {Q}
        GROUP BY pk""")
    # 4b) ráp thông tin lô xa nhất (1 dòng/Products; tie cùng ngày -> lấy đại diện bằng MAX)
    cur.execute(f"""
        SELECT e.pk, MAX(e.code) AS code, MAX(e.name) AS name, o.fail_day,
               DATEDIFF(CURDATE(), o.fail_day) AS days_since,
               MAX(e.sl) AS recv_qty, MAX(e.kho) AS warehouses, MAX(e.phieu) AS phieu
        FROM tmp_enriched e
        JOIN tmp_oldest o ON o.pk = e.pk AND e.rday = o.fail_day
        WHERE e.next_sale IS NULL AND e.sl > {Q}
        GROUP BY e.pk, o.fail_day
        ORDER BY days_since DESC, name""")
    return cur.fetchall()


def render_html(rows):
    intro = ("<p>Gửi các anh/chị,</p>"
             f"<p>Team ITD gửi danh sách <b>{len(rows)} mặt hàng</b> đã nhập kho mà "
             f"<b>quá {cfg.NO_SALE_DAYS} ngày</b> vẫn chưa phát sinh doanh số (tính từ lô nhập cũ nhất chưa bán).</p>")
    cols = ["Tên mặt hàng", "Số phiếu", "Ngày nhập", "SL", "Kho nhập", "Số ngày tồn đọng"]
    th = "".join(f"<th style='padding:4px 8px;border:1px solid #ccc;background:#f2f2f2'>{h}</th>" for h in cols)
    trs = []
    for pk, code, name, recv, days, qty, wh, phieu in rows:
        tds = [name or "", phieu or "", recv, f"{float(qty):,.0f}", wh or "", days]
        trs.append("<tr>" + "".join(
            f"<td style='padding:4px 8px;border:1px solid #ccc'>{v}</td>" for v in tds) + "</tr>")
    table = f"<table style='border-collapse:collapse;font-family:Arial;font-size:13px'><tr>{th}</tr>{''.join(trs)}</table>"
    sign = "<p>Trân trọng,<br>Team ITD</p>"
    return intro + table + sign


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    cn, cur = connect()
    rows = detect(cur)
    print(f"[DRY-RUN] {len(rows)} mặt hàng hit rule (W={cfg.WINDOW_DAYS}, N={cfg.NO_SALE_DAYS}, SL>{cfg.MIN_RECV_QTY}, loại={cfg.ITEM_KIND})\n")
    print(f"{'ngày nhập':11} {'số ngày':>7} {'SL':>7}  {'kho':20} {'mã hàng':24} tên")
    for pk, code, name, recv, days, qty, wh, phieu in rows[:20]:
        print(f"{str(recv):11} {days:>7} {float(qty):>7.0f}  {str(wh)[:20]:20} {str(code)[:24]:24} {str(name)[:36]}")
    cn.close()

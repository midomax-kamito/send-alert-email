# -*- coding: utf-8 -*-
"""Rule: THAY ĐỔI GIÁ BÁN LẺ (PriceKind 'Giá bán lẻ').

Giá bán lẻ 1 SKU = giá ở chứng từ PriceSetup mới nhất cho SKU đó. "Đổi" = chứng từ mới có Price khác
chứng từ liền trước -> LAG(Price) theo Date. HIT = Price != prev & DATE(Date) trong [hôm nay - lookback].

LỌC (giống email tồn kho): ItemKind='Hàng hóa' + loại nhóm trong tb_excluded_group_products_sport_brand.
Stateless về nguồn (đọc lịch sử PriceSetup). Dedup "đã gửi là thôi" ở run_price_alert.py
(key = SKU|ngày|chứng từ mới|giá mới). Nguồn: DWH kazgevim_1C (PriceSetup Posted=1).
"""
import sys, os
sys.path.insert(0, os.environ.get("C1_CONFIG_DIR", r"D:\midomax\midomax\3. project\1c-data-sync-repo\1c-data-sync"))
import config, pymysql
import alert_config as cfg


def connect():
    cn = pymysql.connect(host=config.db_host, user=config.db_user, password=config.db_raw_password,
                         database=config.db_name, port=config.db_port, charset="utf8mb4", read_timeout=600)
    return cn, cn.cursor()


def detect(cur, lookback_days=None):
    """-> list[(sku, sport, product, sku_detail, change_date, old_price, old_doc, new_price, new_doc, new_num)].

    old_doc/new_doc = 'Mã + thời gian' (TM-... yyyy-mm-dd hh:mm:ss). new_num = chỉ Mã (cho khóa dedup).
    Lọc Hàng hóa + nhóm bị loại áp TRONG CTE (cùng SP nên LAG lịch sử vẫn đúng)."""
    n = cfg.PRICE_LOOKBACK_DAYS if lookback_days is None else int(lookback_days)
    cur.execute(f"""
        WITH h AS (
            SELECT ic.SKU AS sku, psd.sport_desc AS sport, pr.Description AS pname,
                   ic.Description AS sku_detail, ps.Number AS num, ps.Date AS dt, g.Price AS price,
                   LAG(g.Price)   OVER w AS prev_price,
                   LAG(ps.Number) OVER w AS prev_num,
                   LAG(ps.Date)   OVER w AS prev_dt
            FROM PriceSetup ps
            JOIN PriceSetup_Goods2_5 g ON ps.Ref_Key = g.Ref_Key
            JOIN ItemsCharacteristics ic ON g.PricingVariant_Key = ic.ItemsCharacteristicForPricing_Key
            LEFT JOIN Products pr  ON ic.Owner = pr.Ref_Key
            LEFT JOIN Products par ON pr.Parent_Key = par.Ref_Key
            LEFT JOIN product_sport_desc psd ON pr.Ref_Key = psd.Ref_Key
            JOIN ItemKinds ik ON CAST(ic.ProductKind_Key AS char(50) charset utf8mb4) COLLATE utf8mb4_general_ci
                               = CAST(ik.Ref_Key          AS char(50) charset utf8mb4) COLLATE utf8mb4_general_ci
            LEFT JOIN tb_excluded_group_products_sport_brand exg
                   ON TRIM(par.Description) = exg.group_products_sport_brand AND exg.is_active = 1
            WHERE ps.Posted = 1 AND g.PriceKind_Key = '{cfg.RETAIL_PRICE_KIND}'
              AND CAST(ik.Description AS char(50) charset utf8mb4) COLLATE utf8mb4_general_ci = 'Hàng hóa'
              AND exg.group_products_sport_brand IS NULL
            WINDOW w AS (PARTITION BY g.PricingVariant_Key ORDER BY ps.Date, ps.Ref_Key)
        )
        SELECT sku, sport, pname, sku_detail,
               DATE_FORMAT(dt, '%Y-%m-%d') AS change_date,
               prev_price,
               CONCAT(prev_num, ' ', DATE_FORMAT(prev_dt, '%Y-%m-%d %H:%i:%s')) AS old_doc,
               price,
               CONCAT(num, ' ', DATE_FORMAT(dt, '%Y-%m-%d %H:%i:%s')) AS new_doc,
               num
        FROM h
        WHERE prev_price IS NOT NULL AND price <> prev_price
          AND dt >= DATE_SUB(CURDATE(), INTERVAL {n} DAY)
        ORDER BY dt DESC, sku""")
    return cur.fetchall()


def render_html(rows):
    intro = ("<p>Gửi các anh/chị,</p>"
             f"<p>Team ITD gửi danh sách <b>{len(rows)} SKU</b> có <b>thay đổi giá bán lẻ</b> gần đây.</p>")
    cols = ["Bộ môn", "Sản phẩm", "Chi tiết SKU", "Ngày thay đổi",
            "Giá cũ", "Chứng từ giá cũ", "Giá mới", "Chứng từ giá mới", "% thay đổi"]
    th = "".join(f"<th style='padding:4px 8px;border:1px solid #ccc;background:#f2f2f2'>{h}</th>" for h in cols)
    trs = []
    for sku, sport, pname, sku_detail, change_date, old_p, old_doc, new_p, new_doc, _num in rows:
        op, np_ = float(old_p), float(new_p)
        color = "#16a34a" if np_ > op else "#c0392b"          # tăng=xanh lá (bán đắt), giảm=đỏ
        arrow = "▲" if np_ > op else "▼"
        pct = (np_ - op) / op * 100 if op else 0
        pct_cell = f"<b style='color:{color}'>{arrow} {pct:+.0f}%</b>"
        tds = [sport or "", pname or "", sku_detail or "", change_date,
               f"{op:,.0f}", old_doc or "",
               f"{np_:,.0f}", new_doc or "", pct_cell]
        trs.append("<tr>" + "".join(
            f"<td style='padding:4px 8px;border:1px solid #ccc'>{v}</td>" for v in tds) + "</tr>")
    table = f"<table style='border-collapse:collapse;font-family:Arial;font-size:13px'><tr>{th}</tr>{''.join(trs)}</table>"
    return intro + table + "<p>Trân trọng,<br>Team ITD</p>"


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    lb = 30
    for a in sys.argv[1:]:
        if a.startswith("--lookback="):
            lb = int(a.split("=")[1])
    cn, cur = connect()
    rows = detect(cur, lookback_days=lb)
    cn.close()
    print(f"[DRY] {len(rows)} SKU đổi giá bán lẻ trong {lb} ngày (đã lọc Hàng hóa + nhóm)\n")
    for sku, sport, pname, det, d, op, od, np_, nd, num in rows[:15]:
        print(f"{d} | {sport[:10]:10} | {str(pname)[:22]:22} | {float(op):>9,.0f} -> {float(np_):>9,.0f} | {num}")

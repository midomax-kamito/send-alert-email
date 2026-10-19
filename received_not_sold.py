# -*- coding: utf-8 -*-
"""Rule: SKU đã NHẬP (GoodsReceiptNote) nhưng sau NO_SALE_DAYS ngày vẫn CHƯA BÁN (no CustomerInvoice).
Grain: SKU = (Products_Key, Characteristic_Key). Nguồn: DWH kazgevim_1C (mirror Posted=1, DeletionMark=0).
Nhanh: 2 bảng tạm (nhập gần đây / bán gần đây) anti-join bằng Ref_Key (bảng *_Goods chỉ index Ref_Key).
Vì nhập <= WINDOW_DAYS ngày nên mọi 'bán sau nhập' cũng trong WINDOW_DAYS ngày -> quét bán gần đây là ĐỦ.
"""
import sys, os
# Dùng chung config.py (DB creds, gitignored) của repo 1c-data-sync — 1 nguồn secret duy nhất.
sys.path.insert(0, r"D:\midomax\midomax\3. project\1c-data-sync-repo\1c-data-sync")
import config, pymysql
import alert_config as cfg


def connect():
    cn = pymysql.connect(host=config.db_host, user=config.db_user, password=config.db_raw_password,
                         database=config.db_name, port=config.db_port, charset="utf8mb4", read_timeout=600)
    cur = cn.cursor(); cur.execute("SET collation_connection='utf8mb4_general_ci'")
    return cn, cur


def detect(cur):
    """-> list[(sku, name, fail_day, days_since, recv_qty)] đã lọc kho/bao bì/loại mặt hàng/SL.
    Rule: với MỖI ngày nhập 'đã chín' (ngày nhập + N <= hôm nay), nếu TỪ ngày nhập ĐẾN HÔM NAY SKU
    vẫn KHÔNG có đơn bán nào -> lô đó fail. Gộp per-SKU: báo lô fail GẦN NHẤT.
    recv_qty = SL của lô fail đó; days_since = hôm nay - ngày lô fail. Chỉ loại = cfg.ITEM_KIND, SL > cfg.MIN_RECV_QTY.
    Lưu ý: cần W (WINDOW_DAYS) >= N (NO_SALE_DAYS) thì mới có lô chín trong cửa sổ quét."""
    W, N, Q = cfg.WINDOW_DAYS, cfg.NO_SALE_DAYS, cfg.MIN_RECV_QTY
    # 1) NHẬP theo (SKU, NGÀY nhập), chỉ xét lô 'đã chín': today-W <= ngày nhập <= today-N; chỉ kho bán được;
    #    CHỈ giữ lô có SL nhập > MIN_RECV_QTY (loại nhập mẫu/lẻ)
    cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_recv_day")
    cur.execute(f"""CREATE TEMPORARY TABLE tmp_recv_day AS
        SELECT g.Products_Key, g.Characteristic_Key, LEFT(h.Date,10) AS rday, SUM(g.Count) AS day_qty,
               GROUP_CONCAT(DISTINCT w.Description ORDER BY w.Description SEPARATOR ', ') AS warehouses
        FROM GoodsReceiptNote h
        JOIN GoodsReceiptNote_Goods g ON g.Ref_Key = h.Ref_Key
        LEFT JOIN Warehouses w ON w.Ref_Key = h.Warehouse_Key
        WHERE h.Posted=1 AND h.DeletionMark=0
          AND LEFT(h.Date,10) >= DATE_FORMAT(CURDATE() - INTERVAL {W} DAY, '%%Y-%%m-%%d')
          AND LEFT(h.Date,10) <= DATE_FORMAT(CURDATE() - INTERVAL {N} DAY, '%%Y-%%m-%%d')
          AND (%s = '' OR w.Description IS NULL OR w.Description NOT REGEXP %s)
        GROUP BY g.Products_Key, g.Characteristic_Key, LEFT(h.Date,10)
        HAVING SUM(g.Count) > {Q}""",
        (cfg.EXCLUDE_WAREHOUSE_REGEX, cfg.EXCLUDE_WAREHOUSE_REGEX))
    # 2) NGÀY bán của SKU trong cửa sổ liên quan [today-W, today] (đủ bao mọi [rday, rday+N])
    cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_sold_day")
    cur.execute(f"""CREATE TEMPORARY TABLE tmp_sold_day AS
        SELECT DISTINCT cg.Products_Key, cg.Characteristic_Key, LEFT(ci.Date,10) AS sday
        FROM CustomerInvoice ci JOIN CustomerInvoice_Goods cg ON cg.Ref_Key = ci.Ref_Key
        WHERE ci.Posted=1 AND ci.DeletionMark=0
          AND LEFT(ci.Date,10) >= DATE_FORMAT(CURDATE() - INTERVAL {W} DAY, '%Y-%m-%d')""")
    # 3) LÔ FAIL = từ ngày nhập (rday) đến HÔM NAY vẫn KHÔNG có đơn bán nào của SKU
    cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_fail")
    cur.execute("""CREATE TEMPORARY TABLE tmp_fail AS
        SELECT r.Products_Key, r.Characteristic_Key, r.rday, r.day_qty, r.warehouses
        FROM tmp_recv_day r
        LEFT JOIN tmp_sold_day s ON s.Products_Key = r.Products_Key
             AND s.Characteristic_Key <=> r.Characteristic_Key
             AND s.sday >= r.rday
        GROUP BY r.Products_Key, r.Characteristic_Key, r.rday, r.day_qty, r.warehouses
        HAVING COUNT(s.sday) = 0""")
    # 4) gộp per-SKU -> lô fail GẦN NHẤT
    cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_fail_max")
    cur.execute("""CREATE TEMPORARY TABLE tmp_fail_max AS
        SELECT Products_Key, Characteristic_Key, MAX(rday) AS fail_day
        FROM tmp_fail GROUP BY Products_Key, Characteristic_Key""")
    # 5) ráp tên/SKU + lọc loại = Hàng hóa + bao bì theo tên
    cur.execute(f"""
        SELECT ic.SKU, p.Description AS name, m.fail_day,
               DATEDIFF(CURDATE(), m.fail_day) AS days_since, f.day_qty AS recv_qty, f.warehouses
        FROM tmp_fail_max m
        JOIN tmp_fail f ON f.Products_Key = m.Products_Key
             AND f.Characteristic_Key <=> m.Characteristic_Key AND f.rday = m.fail_day
        JOIN ItemsCharacteristics ic ON ic.Ref_Key = m.Characteristic_Key
        JOIN ItemKinds ik ON CAST(ic.ProductKind_Key AS char(50) charset utf8mb4) COLLATE utf8mb4_general_ci
                           = CAST(ik.Ref_Key          AS char(50) charset utf8mb4) COLLATE utf8mb4_general_ci
        LEFT JOIN Products p ON p.Ref_Key = m.Products_Key
        WHERE CAST(ik.Description AS char(50) charset utf8mb4) COLLATE utf8mb4_general_ci = %s
          AND (%s = '' OR p.Description IS NULL OR p.Description NOT REGEXP %s)
          AND (%s = '' OR ic.SKU NOT REGEXP %s)
        ORDER BY name, ic.SKU""",
        (cfg.ITEM_KIND, cfg.EXCLUDE_NAME_REGEX, cfg.EXCLUDE_NAME_REGEX,
         cfg.EXCLUDE_SKU_REGEX, cfg.EXCLUDE_SKU_REGEX))
    return cur.fetchall()


def render_html(rows):
    intro = ("<p>Gửi các anh/chị,</p>"
             f"<p>Team ITD gửi danh sách <b>{len(rows)} SKU</b> đã nhập kho đến nay "
             f"<b>quá {cfg.NO_SALE_DAYS} ngày</b> vẫn chưa phát sinh doanh số.</p>")
    cols = ["Tên mặt hàng", "SKU", "Ngày nhập (lô)", "SL", "Kho nhập", "Số ngày kể từ nhập"]
    th = "".join(f"<th style='padding:4px 8px;border:1px solid #ccc;background:#f2f2f2'>{h}</th>" for h in cols)
    trs = []
    for sku, name, recv, days, qty, wh in rows:
        tds = [name or "", sku or "", recv, f"{float(qty):,.0f}", wh or "", days]
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
    print(f"{'ngày nhập':11} {'số ngày':>7} {'SL':>7}  {'kho':22} {'SKU':15} tên")
    for sku, name, recv, days, qty, wh in rows[:20]:
        print(f"{str(recv):11} {days:>7} {float(qty):>7.0f}  {str(wh)[:22]:22} {str(sku):15} {str(name)[:38]}")
    cn.close()

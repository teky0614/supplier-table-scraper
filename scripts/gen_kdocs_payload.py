# -*- coding: utf-8 -*-
"""由字段 JSON 生成 kdocs sheet.range_data_batch_update 的两份 payload。

列位置不写死：默认 0=主图 1=标题 2=袋规 3=袋价 4=尺寸 5=编码，
若共享表改版，用 cols=1,2,3,4,5 覆盖，或在阶段0 用 MCP 读表头核对后再传。

用法：
  python gen_kdocs_payload.py fields=<fields.json> file_id=<id> start_row=4 prefix=<前缀> \
         [cols=1,2,3,4,5] [pic_col=0] [worksheet_id=1] [markup=1.13] [step=5]

fields.json 每项：title, color, dia, jan, oid, cost
start_row 是 0-based（4 = 表格第 5 行）。
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, cfg_float, cfg_int, norm_color


def price(cost, markup, step):
    return int(math.ceil(float(cost) * markup / step) * step)


def main():
    a = dict(x.split("=", 1) for x in sys.argv[1:] if "=" in x)
    cfg = load_config()
    fields = json.load(open(a["fields"], encoding="utf-8"))
    fid = a.get("file_id") or cfg.get("kdocs_file_id", "")
    start = int(a.get("start_row", cfg_int(cfg, "kdocs_data_start_row", 4)))
    prefix = a.get("prefix", "kdocs_payload")
    cols = [int(x) for x in a.get("cols", "1,2,3,4,5").split(",")]
    pic_col = int(a.get("pic_col", 0))
    wsid = int(a.get("worksheet_id", cfg_int(cfg, "kdocs_worksheet_id", 1)))
    markup = float(a.get("markup", cfg_float(cfg, "kdocs_price_markup", 1.13)))
    step = float(a.get("step", cfg_float(cfg, "kdocs_price_step", 5)))

    text_ops, pic_ops, table = [], [], []
    for i, f in enumerate(fields):
        r = start + i
        p = price(f["cost"], markup, step)
        pairs = [(cols[0], f["title"]), (cols[1], norm_color(f["color"])), (cols[2], str(p))]
        if str(f["dia"]).strip() != "":
            pairs.append((cols[3], str(f["dia"]).strip()))
        else:
            table.append({"row": r, "title": f["title"], "skip_dia": True})
        pairs.append((cols[4], "'" + str(f["jan"]).strip()))   # 前置单引号强制文本
        for col, val in pairs:
            text_ops.append({"op_type": "cell_operation_type_formula",
                             "row_from": r, "row_to": r,
                             "col_from": col, "col_to": col, "formula": val})
        pic_ops.append({"op_type": "cell_operation_type_picture",
                        "row_from": r, "row_to": r,
                        "col_from": pic_col, "col_to": pic_col,
                        "cell_pic_info": {"tag": "sheet_pic_type_attachment",
                                          "pic_content": f["oid"],
                                          "width": -1, "height": -1}})
        table.append({"row": r, "title": f["title"], "color": norm_color(f["color"]),
                      "cost": f["cost"], "price": p, "dia": f["dia"], "jan": f["jan"]})

    tp, pp = prefix + "_text.json", prefix + "_pic.json"
    json.dump({"file_id": fid, "worksheet_id": wsid, "range_data": text_ops},
              open(tp, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"file_id": fid, "worksheet_id": wsid, "range_data": pic_ops},
              open(pp, "w", encoding="utf-8"), ensure_ascii=False)

    for t in table:
        if "price" in t:
            print("%d | %s | %s | %s->%d | %s | %s%s"
                  % (t["row"], t["title"][:22], t["color"], t["cost"], t["price"],
                     t["dia"], t["jan"], "  << 尺寸空，跳过E列" if t.get("skip_dia") else ""))
    print("\n生成：%s (%d条文本)  %s (%d条图片)" % (tp, len(text_ops), pp, len(pic_ops)))


if __name__ == "__main__":
    main()

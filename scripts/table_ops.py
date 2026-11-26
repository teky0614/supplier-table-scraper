# -*- coding: utf-8 -*-
"""总表 / 临时表 的确定性操作。所有列一律按【表头名】定位，禁止硬编码列号。

子命令（参数都是 key=value）：
  headers    file=<xlsx>                       打印表头名 -> 列字母映射（阶段0 用）
  backup     file=<xlsx> dir=<备份目录>         复制备份，带时间戳，绝不覆盖
  sync_plan  tmp=<临时表> master=<总表> out=<diff.json> [min_ratio=0.9]
                                               只算不写：出 插入/删除/剔除/护栏 清单
  sync_apply master=<总表> diff=<diff.json> out=<测试副本> [force=1]
                                               落地到测试副本（真表只读）
  mark       file=<测试副本> titles=<json> [out=]   指定标题置顶并标红，其余清标
  fill       file=<测试副本> fields=<json>          回填 颜色/直径/广告图/编码
  verify     real=<真表> test=<测试副本> n=<N>      落地前验收
  diff_kdocs master=<总表> kdocs=<json> out=<json>  总表 vs 共享表 标题 diff
  clean      titles=<json> out=<json>          批量清洗标题（核对用）

统一用 default venv（路径见 config.yaml 的 python_exe，禁止硬编码/裸 Python）。
所有路径与业务参数从 config.yaml 读取；错误统一 emit 错误码供 watchdog 定位。
"""
import sys, os, json, shutil, math, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openpyxl
from openpyxl.styles import PatternFill, Font
from collections import Counter
from common import load_config, cfg_float, cfg_int, emit, out as emit_out, norm_color

# 表头别名：从左到右优先。同一个 key 命中多个不同列 -> 直接报错，要求人工确认。
ALIASES = {
    "title": ["标题未清洗", "商品标题", "标题"],
    "clean": ["清洗后标题", "清洗后标题(B列)", "清洗后标题（B列）", "清洗标题"],
    "link":  ["链接", "商品链接", "商品地址"],
    "cost":  ["原袋价格", "价格（元）", "价格(元)", "价格"],
    "color": ["颜色分类"],
    "dia":   ["蛋壳直径"],
    "img":   ["广告图"],
    "jan":   ["编码"],
}
REQUIRED = {
    "sync_plan":  ("title", "cost"),
    "sync_apply": ("title", "cost"),
}

PINK = PatternFill("solid", fgColor="FFFFC7CE")
NOFILL = PatternFill(fill_type=None)
RED_FONT = "FF9C0006"
BLACK_FONT = "FF000000"

PROTECT_PREFIX = ("联系", "备注", "说明", "合计", "总计")


# ---------------- 基础 ----------------
def kv_args(argv):
    return dict(a.split("=", 1) for a in argv if "=" in a)


def load(path):
    wb = openpyxl.load_workbook(path, data_only=False)
    return wb, wb.active


def header_map(ws):
    h = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(1, c).value
        if v is None:
            continue
        name = str(v).strip()
        if name and name not in h:
            h[name] = c
    return h


def resolve(ws, need=()):
    h = header_map(ws)
    m, notes = {}, []
    for key, aliases in ALIASES.items():
        hits = [(a, h[a]) for a in aliases if a in h]
        cols = {c for _, c in hits}
        if len(cols) > 1:
            emit("E020", "表头歧义：%s 同时命中 %s，请人工确认后再跑" % (key, hits))
            raise SystemExit(2)
        if hits:
            m[key] = hits[0][1]
            if hits[0][0] != aliases[0]:
                notes.append("%s -> 「%s」" % (key, hits[0][0]))
    missing = [k for k in need if k not in m]
    if missing:
        emit("E020", "缺必需列 %s；实际表头=%s" % (missing, list(h)))
        raise SystemExit(2)
    return m, h, notes


def col_letter(idx):
    s = ""
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def s(v):
    return "" if v is None else str(v).strip()


_RULES = None
def rules():
    """业务规则从 config.yaml 读（惰性加载，默认值保持与原版一致）。"""
    global _RULES
    if _RULES is None:
        cfg = load_config()
        _RULES = {
            "prefix": cfg.get("clean_strip_prefix", "日本正版"),
            "must": cfg.get("title_must_contain", "扭蛋"),
            "price_purge": cfg_float(cfg, "price_purge_above", 700),
            "price_purge_below": cfg_float(cfg, "price_purge_below", 200),
        }
    return _RULES


def clean_title(t):
    """去开头配置前缀（默认「日本正版」）-> 删最后一个配置关键词（默认「扭蛋」）及其后全部文字。"""
    r = rules()
    x = s(t)
    if r["prefix"] and x.startswith(r["prefix"]):
        x = x[len(r["prefix"]):].strip()
    if r["must"]:
        i = x.rfind(r["must"])
        if i >= 0:
            x = x[:i].strip()
    return x


def is_protected(t):
    x = s(t)
    return (not x) or x.startswith(PROTECT_PREFIX) or "VX" in x.upper()


def num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace("¥", "").replace("￥", "").replace(",", "").strip())
    except ValueError:
        return None


def records(ws, m):
    out = []
    for r in range(2, ws.max_row + 1):
        rec = {"row": r}
        for k, c in m.items():
            rec[k] = ws.cell(r, c).value
        out.append(rec)
    return out


# ---------------- headers ----------------
def cmd_headers(a):
    _, ws = load(a["file"])
    m, h, notes = resolve(ws)
    print(json.dumps({
        "file": a["file"],
        "sheet": ws.title,
        "dims": [ws.max_row, ws.max_column],
        "header_row": {str(k): col_letter(v) for k, v in sorted(h.items(), key=lambda x: x[1])},
        "canonical": {k: col_letter(v) for k, v in sorted(m.items(), key=lambda x: x[1])},
        "alias_notes": notes,
    }, ensure_ascii=False, indent=2))


# ---------------- backup ----------------
def cmd_backup(a):
    src, d = a["file"], a["dir"]
    os.makedirs(d, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(src))
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(d, "%s_备份_%s%s" % (base, stamp, ext))
    i = 1
    while os.path.exists(dst):
        dst = os.path.join(d, "%s_备份_%s_%d%s" % (base, stamp, i, ext))
        i += 1
    shutil.copy2(src, dst)
    print(json.dumps({"ok": True, "backup": dst, "size": os.path.getsize(dst)}, ensure_ascii=False))


# ---------------- sync_plan ----------------
def cmd_sync_plan(a):
    cfg = load_config()
    min_ratio = float(a.get("min_ratio", cfg_float(cfg, "min_coverage_ratio", 0.9)))
    _, wt = load(a["tmp"])
    mt, _, _ = resolve(wt, ("title", "cost"))
    _, wm = load(a["master"])
    mm, _, _ = resolve(wm, ("title", "cost"))

    tmp = [r for r in records(wt, mt) if not is_protected(r["title"])]
    mas = records(wm, mm)
    mas_goods = [r for r in mas if not is_protected(r["title"])]
    protected = [{"row": r["row"], "title": s(r["title"])} for r in mas if is_protected(r["title"])]

    tmp_titles = [s(r["title"]) for r in tmp]
    mas_titles = [s(r["title"]) for r in mas_goods]
    dup_t = [t for t, c in Counter(tmp_titles).items() if c > 1]
    dup_m = [t for t, c in Counter(mas_titles).items() if c > 1]

    tset, mset = set(tmp_titles), set(mas_titles)
    link_of = {s(r["title"]): s(r.get("link")) for r in tmp}
    link_of_m = {s(r["title"]): s(r.get("link")) for r in mas_goods}

    rc = rules()
    def purge(title, cost):
        """返回剔除原因（空串=保留）。上下限都从 config 读。"""
        c = num(cost)
        if c is not None and c > rc["price_purge"]:
            return "价格>%g" % rc["price_purge"]
        if c is not None and c < rc["price_purge_below"]:
            return "价格<%g" % rc["price_purge_below"]
        if bool(rc["must"]) and rc["must"] not in s(title):
            return "不含%s" % rc["must"]
        return ""

    insert, tmp_dropped, valid_titles = [], [], []
    for r in tmp:
        t = s(r["title"])
        if t in mset:
            valid_titles.append(t)
            continue
        reason = purge(t, r.get("cost"))
        if reason:
            tmp_dropped.append({"title": t, "cost": num(r.get("cost")),
                                "reason": reason})
            continue
        valid_titles.append(t)
        insert.append({"title": t, "clean": clean_title(t), "cost": num(r.get("cost")),
                       "link": s(r.get("link")), "src_row": r["row"]})

    delete, purged_out = [], []
    for r in mas_goods:
        t = s(r["title"])
        if t not in tset:
            delete.append({"row": r["row"], "title": t, "cost": num(r.get("cost")),
                           "reason": "采集缺失"})
        elif purge(t, r.get("cost")):
            delete.append({"row": r["row"], "title": t, "cost": num(r.get("cost")),
                           "reason": "价格>700 或 不含扭蛋"})
    purged_out = [d for d in delete if d["reason"] != "采集缺失"]

    link_warn = [{"title": t, "tmp": link_of.get(t), "master": link_of_m.get(t)}
                 for t in (tset & mset) if link_of.get(t) and link_of_m.get(t)
                 and link_of[t] != link_of_m[t]]

    covered = len(set(valid_titles))
    base = len(mas_titles) or 1
    ratio = covered / base
    guard = {"covered": covered, "master": len(mas_titles), "ratio": round(ratio, 3),
             "min_ratio": min_ratio, "ok": ratio >= min_ratio}
    if len(delete) > base * 0.3:
        guard["ok"] = False
        guard["reason_delete_ratio"] = round(len(delete) / base, 3)

    plan = {
        "tmp": a["tmp"], "master": a["master"],
        "counts": {"tmp": len(tmp), "master_goods": len(mas_titles),
                   "insert": len(insert), "delete": len(delete),
                   "purge": len(purged_out), "tmp_dropped": len(tmp_dropped),
                   "protected": len(protected)},
        "guard": guard,
        "insert": insert, "delete": delete, "tmp_dropped": tmp_dropped,
        "protected": protected,
        "warn": {"dup_title_tmp": dup_t, "dup_title_master": dup_m, "link_mismatch": link_warn},
    }
    json.dump(plan, open(a["out"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "out": a["out"], "counts": plan["counts"],
                      "guard": guard,
                      "dup_tmp": len(dup_t), "dup_master": len(dup_m),
                      "link_mismatch": len(link_warn)}, ensure_ascii=False, indent=2))
    if not guard["ok"]:
        print("!! 护栏未通过：采集覆盖率 %.1f%% < %.0f%% 或删除比例过高。"
              "疑似采集视图不是全店（选了分类/新品筛选），禁止继续。"
              % (ratio * 100, min_ratio * 100), file=sys.stderr)


# ---------------- sync_apply ----------------
def cmd_sync_apply(a):
    plan = json.load(open(a["diff"], encoding="utf-8"))
    if not plan["guard"]["ok"] and a.get("force") != "1":
        emit("E021", "护栏未通过（覆盖率/删除比例），拒绝落地。确认全店采集后加 force=1 重跑。")
        raise SystemExit(2)
    shutil.copy2(a["master"], a["out"])
    wb, ws = load(a["out"])
    m, _, _ = resolve(ws, ("title", "cost"))

    # 1) 先删（自下而上，行号不漂移）
    dels = sorted(plan["delete"], key=lambda x: -x["row"])
    for d in dels:
        cur = s(ws.cell(d["row"], m["title"]).value)
        if cur != d["title"]:
            emit("E022", "删行前核对失败：第%d行 期望「%s」实际「%s」" % (d["row"], d["title"], cur))
            raise SystemExit(2)
        ws.delete_rows(d["row"], 1)

    # 2) 再插（一次性插 n 行在表头下）
    ins = plan["insert"]
    if ins:
        ws.insert_rows(2, len(ins))
        for i, rec in enumerate(ins):
            r = 2 + i
            ws.cell(r, m["title"]).value = rec["title"]
            if "link" in m and rec.get("link"):
                ws.cell(r, m["link"]).value = rec["link"]
            if rec.get("cost") is not None:
                ws.cell(r, m["cost"]).value = rec["cost"]
            if "clean" in m:
                ws.cell(r, m["clean"]).value = rec["clean"]

    # 3) 底色：新行浅粉，其余全部清标（表头不动）
    n = len(ins)
    for r in range(2, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(r, c)
            if r < 2 + n:
                cell.fill = PINK
            else:
                cell.fill = NOFILL
    wb.save(a["out"])
    if a.get("base"):
        shutil.copy2(a["out"], a["base"])   # 同步后基准快照：留给 verify 当对照物

    # 4) 自检：标题多重集与预期一致（原始总表 - 已删 + 新插入）
    wb2, ws2 = load(a["out"])
    m2, _, _ = resolve(ws2, ("title",))
    got = [s(r["title"]) for r in records(ws2, m2) if not is_protected(r["title"])]
    _, ws_m = load(a["master"])
    mm, _, _ = resolve(ws_m, ("title",))
    del_rows = {d["row"] for d in plan["delete"]}
    exp = [x["title"] for x in ins] + [
        s(r["title"]) for r in records(ws_m, mm)
        if not is_protected(r["title"]) and r["row"] not in del_rows]
    if Counter(got) != Counter(exp):
        diff_a = set(got) - set(exp)
        diff_b = set(exp) - set(got)
        emit("E022", "落地自检失败：多出 %s 缺少 %s" % (list(diff_a)[:5], list(diff_b)[:5]))
        raise SystemExit(2)
    print(json.dumps({"ok": True, "out": a["out"], "inserted": n, "deleted": len(dels),
                      "rows_now": ws2.max_row, "pink_rows": "2~%d" % (n + 1)}, ensure_ascii=False))


# ---------------- mark ----------------
def norm_titles(raw):
    """把标题清单归一化为字符串数组。

    兼容三种输入（2026-11-24 v1.0.1）：
      1) ["标题A", "标题B"]                      纯字符串数组（原约定）
      2) {"titles": ["标题A", ...]}              带 titles 键的对象
      3) [{"row":2,"title":"标题A","clean":"..."}] 对象数组（stage2 diff 直接生成）
    对象项按 title / clean / clean_title / name 顺序取第一个非空值。
    """
    if isinstance(raw, dict):
        raw = raw.get("titles", raw.get("clean_titles", []))
    out = []
    for t in raw:
        if isinstance(t, dict):
            pick = next((t.get(k) for k in ("title", "clean", "clean_title", "name")
                         if t.get(k) not in (None, "")), None)
            if pick is None:
                emit("E024", "titles 对象项缺 title/clean/name 字段：%r" % t)
                raise SystemExit(2)
            out.append(s(pick))
        else:
            out.append(s(t))
    return out


def cmd_mark(a):
    path = a["file"]
    titles = norm_titles(json.load(open(a["titles"], encoding="utf-8")))
    if not titles:
        emit("E024", "标题清单为空")
        raise SystemExit(2)
    if len(titles) != len(set(titles)):
        emit("E024", "标题清单有重复，先去掉重复项")
        raise SystemExit(2)
    wb, ws = load(path)
    m, _, _ = resolve(ws, ("clean",))
    col = m["clean"]
    maxc = ws.max_column
    rows = [[ws.cell(r, c).value for c in range(1, maxc + 1)] for r in range(2, ws.max_row + 1)]
    tgt = [r for r in rows if s(r[col - 1]) in set(titles)]
    rest = [r for r in rows if s(r[col - 1]) not in set(titles)]
    if len(tgt) != len(set(titles)):
        hit = {s(r[col - 1]) for r in tgt}
        emit("E023", "命中 %d 条 / 清单 %d 条；未命中：%s"
             % (len(tgt), len(set(titles)), [t for t in titles if t not in hit]))
        raise SystemExit(2)
    n = len(tgt)
    for idx, vals in enumerate(tgt + rest):
        rr = 2 + idx
        for c in range(1, maxc + 1):
            cell = ws.cell(rr, c)
            cell.value = vals[c - 1]
            old = cell.font
            if idx < n:
                cell.fill = PINK
                cell.font = Font(color=RED_FONT, bold=old.bold, size=old.size, name=old.name)
            else:
                cell.fill = NOFILL
                cell.font = Font(color=BLACK_FONT, bold=old.bold, size=old.size, name=old.name)
    wb.save(a.get("out", path))
    print(json.dumps({"ok": True, "file": a.get("out", path), "marked": n,
                      "rows": "2~%d" % (n + 1)}, ensure_ascii=False))


# ---------------- fill ----------------
def cmd_fill(a):
    fields = json.load(open(a["fields"], encoding="utf-8"))
    wb, ws = load(a["file"])
    m, _, _ = resolve(ws, ("clean", "color", "dia", "img", "jan"))
    before = {r: tuple(ws.cell(r, c).value for c in range(1, ws.max_column + 1))
              for r in range(2, ws.max_row + 1)}
    for f in fields:
        r = int(f["row"])
        cur = s(ws.cell(r, m["clean"]).value)
        if cur != s(f["title"]):
            emit("E023", "第%d行标题不符：%r != %r" % (r, cur, f["title"]))
            raise SystemExit(2)
        ws.cell(r, m["color"]).value = norm_color(f["color"])
        ws.cell(r, m["dia"]).value = s(f["dia"])
        ws.cell(r, m["img"]).value = s(f["img"])
        c = ws.cell(r, m["jan"])
        c.value = s(f["jan"])
        c.number_format = "@"
    wb.save(a["file"])
    after = {r: tuple(ws.cell(r, c).value for c in range(1, ws.max_column + 1)) for r in before}
    skip = {m[k] for k in ("color", "dia", "img", "jan")}
    for r in before:
        b = tuple(v for i, v in enumerate(before[r], 1) if i not in skip)
        af = tuple(v for i, v in enumerate(after[r], 1) if i not in skip)
        if b != af:
            raise SystemExit("第%d行非目标列被意外改动" % r)
    print(json.dumps({"ok": True, "filled": len(fields), "dims": [ws.max_row, ws.max_column]},
                     ensure_ascii=False))


# ---------------- verify ----------------
def cmd_verify(a):
    n = int(a["n"])
    wb_r, ws_r = load(a["real"])
    wb_t, ws_t = load(a["test"])
    if (ws_r.max_row, ws_r.max_column) != (ws_t.max_row, ws_t.max_column):
        emit("E022", "维度不一致：真表 %dx%d 副本 %dx%d"
             % (ws_r.max_row, ws_r.max_column, ws_t.max_row, ws_t.max_column))
        raise SystemExit(2)
    m, _, _ = resolve(ws_t, ("clean", "color", "img", "jan"))
    skip = {m[k] for k in ("color", "dia", "img", "jan")}
    cols = [c for c in range(1, ws_t.max_column + 1) if c not in skip]
    A = Counter(tuple(ws_r.cell(r, c).value for c in cols) for r in range(2, ws_r.max_row + 1))
    B = Counter(tuple(ws_t.cell(r, c).value for c in cols) for r in range(2, ws_t.max_row + 1))
    if A != B:
        only_a = list((A - B).elements())[:3]
        only_b = list((B - A).elements())[:3]
        raise SystemExit("非抓取列数据集合不一致：仅真表%s 仅副本%s" % (only_a, only_b))
    lack = [r for r in range(2, n + 2)
            if not (ws_t.cell(r, m["color"]).value and ws_t.cell(r, m["img"]).value
                    and ws_t.cell(r, m["jan"]).value)]
    if lack:
        raise SystemExit("前%d行 颜色/广告图/编码 有空：行%s" % (n, lack))
    red = [r for r in range(2, ws_t.max_row + 1)
           if str(ws_t.cell(r, 1).fill.fgColor.rgb or "").upper().endswith("C7CE")]
    if red != list(range(2, n + 2)):
        raise SystemExit("标红区间不对：应 2~%d，实际 %s" % (n + 1, red[:20]))
    print(json.dumps({"ok": True, "dims": [ws_t.max_row, ws_t.max_column], "n": n,
                      "pink": "2~%d" % (n + 1)}, ensure_ascii=False))


# ---------------- diff_kdocs ----------------
def cmd_diff_kdocs(a):
    master, kdocs = a["master"], a["kdocs"]
    raw = json.load(open(kdocs, encoding="utf-8"))
    if isinstance(raw, dict):
        start = int(raw.get("start_row", 5))
        titles = raw.get("titles", [])
    else:
        start, titles = 5, raw
    kd = [(start + i, s(t)) for i, t in enumerate(titles) if not is_protected(t)]
    wb, ws = load(master)
    m, _, _ = resolve(ws, ("clean",))
    loc = [(r["row"], s(r["clean"])) for r in records(ws, m) if not is_protected(r.get("clean"))]
    kset, lset = set(t for _, t in kd), set(t for _, t in loc)
    # 行号基准（v1.0.1 修正）：kdocs MCP 的 row_from/row_to/originRow 都是 0-based。
    # 这里 row 保留 1-based（给人看 / 与本地表行号一致），另出 origin_row=row-1 供直接删行。
    out = {
        "row_basis": "row=1-based(Excel行号); origin_row=0-based(直接填 kdocs row_from/row_to)",
        "kdocs_rows": len(kd), "local_rows": len(loc),
        "local_only": [{"row": r, "title": t} for r, t in loc if t not in kset],
        "kdocs_only": [{"row": r, "origin_row": r - 1, "title": t}
                       for r, t in kd if t not in lset],
        "dup_kdocs": [t for t, c in Counter(t for _, t in kd).items() if c > 1],
        "dup_local": [t for t, c in Counter(t for _, t in loc).items() if c > 1],
    }
    json.dump(out, open(a["out"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "out": a["out"], "local_only": len(out["local_only"]),
                      "kdocs_only": len(out["kdocs_only"]),
                      "kdocs_only_origin_rows": [x["origin_row"] for x in out["kdocs_only"]],
                      "dup_kdocs": len(out["dup_kdocs"]),
                      "dup_local": len(out["dup_local"]),
                      "hint": "删共享表行用 kdocs_only[].origin_row (0-based)，删前仍须逐行重读核对"},
                     ensure_ascii=False))


# ---------------- clean ----------------
def cmd_clean(a):
    titles = json.load(open(a["titles"], encoding="utf-8"))
    if isinstance(titles, dict):
        titles = titles["titles"]
    res = [{"raw": t, "clean": clean_title(t)} for t in titles]
    json.dump(res, open(a["out"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "out": a["out"], "n": len(res)}, ensure_ascii=False))


CMDS = {
    "headers": cmd_headers, "backup": cmd_backup,
    "sync_plan": cmd_sync_plan, "sync_apply": cmd_sync_apply,
    "mark": cmd_mark, "fill": cmd_fill, "verify": cmd_verify,
    "diff_kdocs": cmd_diff_kdocs, "clean": cmd_clean,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        raise SystemExit("用法：table_ops.py {%s} k=v ..." % "|".join(CMDS))
    CMDS[sys.argv[1]](kv_args(sys.argv[2:]))

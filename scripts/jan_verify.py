# -*- coding: utf-8 -*-
"""JAN 条码校验：机器解码 + 裁剪放大出图 + GS1 校验位核对。

只做「判断」不做「拍板」——最终仍要 AI 肉眼看放大图。冲突时以放大原图为准（铁律）。

用法：
  python jan_verify.py img=<图片> [out=<输出目录>] [zoom=8] [crop=x,y,w,h ...] [crops=<json>]

crops JSON 可为 [[x,y,w,h], ...]；不传 crop 时对整图解码。
输出：<out>/crop_1.png ... 供肉眼看；stdout 打印 JSON 结论。
"""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image
try:
    import zxingcpp
except ImportError:
    from common import die
    die("E002", "缺 zxingcpp，请用 default venv 运行")

FMT = ""


def gs1(d):
    """13 位 JAN：前12位 奇位×1 偶位×3 求和，校验位=(10-和%10)%10。"""
    if len(d) != 13 or not d.isdigit():
        return None, None
    sm = sum(int(d[i]) * (1 if i % 2 == 0 else 3) for i in range(12))
    exp = (10 - sm % 10) % 10
    return exp, exp == int(d[12])


def decode(im):
    out = []
    try:
        for r in zxingcpp.read_barcodes(im):
            out.append({"text": (r.text or "").strip(), "fmt": str(r.format)})
    except Exception as e:
        out.append({"text": "", "fmt": "ERROR:" + str(e)})
    return out


def upscale(im, z):
    rs = getattr(Image, "Resampling", Image).LANCZOS
    return im.resize((im.width * z, im.height * z), rs)


def main():
    a = dict(x.split("=", 1) for x in sys.argv[1:] if "=" in x)
    path = a["img"]
    out = a.get("out") or os.path.join(os.path.dirname(os.path.abspath(path)), "jan_check")
    os.makedirs(out, exist_ok=True)
    zoom = int(a.get("zoom", 8))

    crops = []
    if a.get("crops"):
        crops = json.load(open(a["crops"], encoding="utf-8"))
    for k, v in a.items():
        if k == "crop":
            crops.append([int(x) for x in v.split(",")])
    # 允许 crop= 出现多次
    vals = [x.split("=", 1)[1] for x in sys.argv[1:] if x.startswith("crop=")]
    crops = [[int(x) for x in v.split(",")] for v in vals] or crops

    im = Image.open(path).convert("RGB")
    hits, enlarged = [], []

    for h in decode(im):
        h["source"] = "full"
        hits.append(h)

    box = im.getbbox()
    for i, (x, y, w, h) in enumerate(crops, 1):
        x, y = max(0, x), max(0, y)
        w, h = min(w, box[2] - x), min(h, box[3] - y)
        sub = im.crop((x, y, x + w, y + h))
        big = upscale(sub, zoom)
        p = os.path.join(out, "crop_%d.png" % i)
        big.save(p)
        enlarged.append({"path": p, "box": [x, y, w, h], "size": [big.width, big.height]})
        for r in decode(big):
            r["source"] = "crop_%d" % i
            hits.append(r)

    # 归并候选
    cand = {}
    for h in hits:
        t = h["text"]
        if not t:
            continue
        exp, ok = gs1(t)
        c = cand.setdefault(t, {"text": t, "count": 0, "sources": [], "len": len(t),
                                "gs1_expected": exp, "gs1_ok": ok})
        c["count"] += 1
        if h["source"] not in c["sources"]:
            c["sources"].append(h["source"])

    jans = {t: c for t, c in cand.items() if c["len"] == 13 and t.isdigit()}
    others = [c for t, c in cand.items() if t not in jans]

    if len(jans) == 1:
        only = list(jans.values())[0]
        verdict = "PASS_ZXING" if only["gs1_ok"] else "GS1_FAIL"
    elif len(jans) > 1:
        verdict = "CONFLICT"
    else:
        verdict = "NO_DECODE"

    res = {
        "img": path, "verdict": verdict,
        "candidates": sorted(jans.values(), key=lambda c: -c["count"]),
        "non_jan": others, "enlarged": enlarged,
        "note": "GS1 通过不等于读对；zxing 与放大图冲突时以放大原图为准，必须肉眼逐位复核。"
    }
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if verdict == "CONFLICT":
        print("ERR E030 多个候选，按铁律：多张裁剪交叉确认 + 肉眼读放大图，不要挑 GS1 通过的凑数。",
              file=sys.stderr)
    if verdict == "GS1_FAIL":
        print("ERR E031 GS1 不通过：换更高倍数重裁/换区域，以原图读数为准并标注请用户复核。",
              file=sys.stderr)
    if verdict == "NO_DECODE":
        print("ERR E032 无解码结果：扩大裁剪区/提高倍数重试，或人工直接读图。", file=sys.stderr)


if __name__ == "__main__":
    main()

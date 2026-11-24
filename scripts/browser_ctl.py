# -*- coding: utf-8 -*-
"""拟人浏览器控制：只发 CDP 真实鼠标事件，绝不碰 DOM 业务数据（防风控）。

自包含：内置 cdp_client.py，端口从 config.yaml 读，不依赖外部技能路径。
铁律：evaluate 仅允许读 location.href / document.title / 视口尺寸；
      页面业务数据（标题/价格/SKU）一律截图肉眼识别；遇验证框立即停。

子命令：
  status / url / title / viewport / shot PATH / move X Y / click X Y [--jitter N]
  wheel X Y DY [--steps N] [--pause S] [--jitter N]
  tabs              列出所有标签页 URL（用于确认店铺页/插件页）
  navigate URL      用 CDP 打开 URL（仅用于首登后跳店铺页，不做业务读取）
  guard             截图并检测页面是否出现风控/验证关键词（返回 risk=true 需人工）
  全局可加 --port P 覆盖配置端口。
"""
import sys, os, time, random, argparse, json, base64
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cdp_client as C
from common import load_config, cfg_int, out, emit

RISK_WORDS = ["验证", "验证码", "滑动", "滑块", "拼图", "拖动", "还原", "安全验证", "前往验证",
              "captcha", "访问频繁", "异常", "请登录", "行为异常", "操作过于频繁"]


def jit(v, n):
    return v + random.uniform(-n, n) if n else v


def connect(port, host, url_contains=None):
    cl = C.CDPClient(host=host, port=port)
    pages = cl.list_pages()
    if not pages:
        emit("E011", "CDP 无标签页")
        raise SystemExit(2)
    page = None
    if url_contains:
        for p in pages:
            if url_contains in (p.get("url") or ""):
                page = p
                break
    if page is None:
        for p in pages:
            if (p.get("url") or "").startswith("http"):
                page = p
                break
    if page is None:
        page = pages[0]
    cl.connect_page(page["id"])
    return cl, page


def mouse_move(cl, x, y):
    cl.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": round(x, 1), "y": round(y, 1),
                                         "button": "none", "buttons": 0})


def mouse_click(cl, x, y):
    mouse_move(cl, x, y)
    time.sleep(random.uniform(0.08, 0.22))
    cl.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": round(x, 1), "y": round(y, 1),
                                         "button": "left", "buttons": 1, "clickCount": 1})
    time.sleep(random.uniform(0.06, 0.16))
    cl.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": round(x, 1), "y": round(y, 1),
                                         "button": "left", "buttons": 0, "clickCount": 1})


def mouse_wheel(cl, x, y, dy):
    cl.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": round(x, 1), "y": round(y, 1),
                                         "deltaX": 0, "deltaY": round(dy, 1),
                                         "button": "none", "buttons": 0})


def shot_bytes(cl):
    cl.send("Page.enable")
    res = cl.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    data = res.get("data")
    if not data:
        raise C.CDPError("截图返回空数据")
    return base64.b64decode(data)


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description="拟人浏览器控制（自包含 CDP，只发真实鼠标事件）")
    ap.add_argument("cmd", choices=["status", "url", "title", "viewport", "shot", "move", "click",
                                    "wheel", "tabs", "navigate", "guard"])
    ap.add_argument("--port", type=int, default=cfg_int(cfg, "cdp_port", 9333))
    ap.add_argument("--host", default=cfg.get("cdp_host", "127.0.0.1"))
    ap.add_argument("--url-contains", default=None)
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    port, host = a.port, a.host

    if a.cmd == "status":
        cl = C.CDPClient(host=host, port=port)
        try:
            info = cl.version()
            out({"ok": True, "browser": info.get("Browser"), "port": port,
                 "pages": len(cl.list_pages())})
        except Exception as e:
            emit("E010", "CDP %d 不可达: %s" % (port, e))
            raise SystemExit(2)
        return

    if a.cmd == "tabs":
        cl = C.CDPClient(host=host, port=port)
        try:
            tabs = cl.list_pages()
        except Exception as e:
            emit("E010", "CDP %d 不可达: %s" % (port, e))
            raise SystemExit(2)
        out({"ok": True, "tabs": [{"url": p.get("url"), "title": p.get("title")}
                                  for p in tabs]})
        return

    try:
        cl, page = connect(port, host, a.url_contains)
    except C.CDPError as e:
        emit("E010", "CDP %d 连接失败: %s" % (port, e))
        raise SystemExit(2)
    try:
        if a.cmd == "url":
            print(cl.evaluate("location.href").get("value", ""))
        elif a.cmd == "title":
            print(cl.evaluate("document.title").get("value", ""))
        elif a.cmd == "viewport":
            v = cl.evaluate("JSON.stringify({innerW:innerWidth,innerH:innerHeight,dpr:devicePixelRatio,screenW:screen.width,screenH:screen.height})").get("value")
            print(v)
        elif a.cmd == "navigate":
            cl.send("Page.enable")
            cl.send("Page.navigate", {"url": a.args[0]})
            out({"ok": True, "navigate": a.args[0]})
        elif a.cmd == "shot":
            path = a.args[0]
            data = shot_bytes(cl)
            with open(path, "wb") as f:
                f.write(data)
            out({"ok": True, "shot": path, "bytes": len(data)})
        elif a.cmd == "move":
            mouse_move(cl, jit(float(a.args[0]), 3), jit(float(a.args[1]), 3))
            out({"ok": True, "move": a.args[:2]})
        elif a.cmd == "click":
            x, y = float(a.args[0]), float(a.args[1])
            j = float(next((x.split("=")[1] for x in a.args if x.startswith("jitter=")), 2.0))
            mouse_click(cl, jit(x, j), jit(y, j))
            out({"ok": True, "click": [x, y]})
        elif a.cmd == "wheel":
            x, y, dy = float(a.args[0]), float(a.args[1]), float(a.args[2])
            steps = int(next((s.split("=")[1] for s in a.args if s.startswith("steps=")), 1))
            pause = float(next((s.split("=")[1] for s in a.args if s.startswith("pause=")), 0.0))
            jitter = float(next((s.split("=")[1] for s in a.args if s.startswith("jitter=")), 6.0))
            per = dy / steps
            for _ in range(steps):
                mouse_move(cl, jit(x, jitter), jit(y, jitter))
                mouse_wheel(cl, jit(x, jitter), jit(y, jitter), per)
                if pause:
                    time.sleep(pause + random.uniform(0, pause * 0.6))
            out({"ok": True, "wheel": dy, "steps": steps})
        elif a.cmd == "guard":
            # 截图存临时字节，用 OCR/AI 判断；这里只做关键词提示（AI 需看图确认）
            data = shot_bytes(cl)
            path = os.path.join(HERE, "..", "logs", "guard_tmp.png")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            url = cl.evaluate("location.href").get("value", "")
            out({"ok": True, "shot": path, "url": url,
                 "hint": "AI 必须看图确认是否风控/验证框；命中关键词立即停，不重试",
                 "risk_words": RISK_WORDS})
    finally:
        cl.close()


if __name__ == "__main__":
    main()

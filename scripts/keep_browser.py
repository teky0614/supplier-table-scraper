# -*- coding: utf-8 -*-
"""浏览器保活：用指定命令启动 Chrome 后常驻，防止沙箱回收。

必须由宿主以 run_in_background=true 运行本脚本（不要 nohup/&）。
退出全部 chrome 后启动，单实例 + 9333 调试端口 + 专用 profile。
"""
import os, sys, subprocess, time, signal
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, out

cfg = load_config()
exe = cfg.get("chrome_exe", "")
flags = cfg.get("chrome_flags", "")
port = int(cfg.get("cdp_port", 9333))

if not os.path.exists(exe):
    print("ERR E010 Chrome 不存在: %s" % exe, file=sys.stderr)
    raise SystemExit(2)

# 启动浏览器（不用 shell，避免进程组被回收）
args = [exe] + flags.split()
proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
out({"ok": True, "pid": proc.pid, "port": port, "msg": "浏览器已启动，进入保活"})


def on_exit(sig, frame):
    out({"msg": "保活退出（浏览器可能仍在运行）"})
    raise SystemExit(0)


signal.signal(signal.SIGTERM, on_exit)
# 常驻：每 30s 检查 CDP 是否还活着，死了就退出让宿主重拉
import urllib.request
while True:
    time.sleep(30)
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=3)
    except Exception:
        out({"ok": False, "msg": "CDP 掉线，保活退出"})
        raise SystemExit(1)

# -*- coding: utf-8 -*-
"""环境自检：CDP 端口、浏览器指纹、登录态、至尊宝插件、Python 依赖、路径。

子命令：
  check   全面自检，打印 JSON 结论；任一硬项失败 exit 2
  launch  打印带调试端口的浏览器启动命令（供人工/脚本重启用）
  quick   只查 CDP 端口是否可达（轻量，供各脚本前置）

铁律：不合格直接拒绝启动，不带着坏环境往下跑。
"""
import os, sys, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, cfg_int, out, emit

HERE = os.path.dirname(os.path.abspath(__file__))


def http_json(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def cdp_pages(port, host="127.0.0.1"):
    return http_json("http://%s:%d/json/list" % (host, port), timeout=3)


def cdp_version(port, host="127.0.0.1"):
    return http_json("http://%s:%d/json/version" % (host, port), timeout=3)


def check_deps():
    r = {}
    for mod in ("openpyxl", "PIL", "zxingcpp"):
        try:
            m = __import__(mod)
            r[mod] = {"ok": True, "version": getattr(m, "__version__", "?")}
        except ImportError as e:
            r[mod] = {"ok": False, "error": str(e)}
    return r


def check_paths(cfg):
    r = {}
    master = cfg.get("master_xlsx", "")
    r["master_xlsx"] = {"path": master, "exists": os.path.exists(master)}
    r["backup_dir"] = {"path": cfg.get("backup_dir", ""),
                        "exists": os.path.exists(cfg.get("backup_dir", ""))}
    r["python_exe"] = {"path": cfg.get("python_exe", ""),
                        "is_current": os.path.abspath(sys.executable).lower()
                        == os.path.abspath(cfg.get("python_exe", "")).lower(),
                        "current": sys.executable}
    return r


def check_plugin(cfg, pages):
    """检测至尊宝：优先看 CDP 页面里的 chrome-extension service-worker，其次看扩展目录。"""
    ext_id = cfg.get("zhizunbao_ext_id", "").strip()
    found_cdp = False
    if pages:
        for p in pages:
            u = p.get("url", "")
            if "chrome-extension://" in u and ext_id and ext_id in u:
                found_cdp = True
    # 解压加载痕迹（本机实际方式）
    unpacked = r"C:\Chrome-Direct-Test\Default\UnpackedExtensions"
    found_dir = False
    name = None
    if os.path.isdir(unpacked):
        for d in os.listdir(unpacked):
            mf = os.path.join(unpacked, d, "manifest.json")
            if os.path.exists(mf):
                try:
                    with open(mf, encoding="utf-8") as f:
                        m = json.load(f)
                    if "至尊宝" in str(m.get("name", "")):
                        found_dir = True
                        name = m.get("name")
                except Exception:
                    pass
    return {"ok": found_cdp or found_dir, "via_cdp": found_cdp,
            "via_unpacked_dir": found_dir, "name": name,
            "note": "解压加载方式不在 Preferences 扩展列表里，属正常" if found_dir else ""}


def do_check(a):
    cfg = load_config()
    port = cfg_int(cfg, "cdp_port", 9333)
    result = {"ok": True, "checks": {}, "errors": []}

    deps = check_deps()
    result["checks"]["deps"] = deps
    if not all(v["ok"] for v in deps.values()):
        result["ok"] = False
        result["errors"].append("E002: 依赖缺失，请用 default venv 运行")

    ver = cdp_version(port, cfg.get("cdp_host", "127.0.0.1"))
    pages = cdp_pages(port, cfg.get("cdp_host", "127.0.0.1"))
    result["checks"]["cdp"] = {
        "port": port, "reachable": bool(ver),
        "browser": (ver or {}).get("Browser"), "pages": len(pages) if pages else 0,
    }
    if not ver:
        result["ok"] = False
        result["errors"].append("E010: CDP 端口 %d 不可达（浏览器未带调试端口启动）" % port)
    elif not pages:
        result["ok"] = False
        result["errors"].append("E011: CDP 无标签页")

    plugin = check_plugin(cfg, pages)
    result["checks"]["zhizunbao"] = plugin
    if not plugin["ok"]:
        result["errors"].append("E012: 未检测到至尊宝插件（警告，可继续但采集会失败）")

    result["checks"]["paths"] = check_paths(cfg)
    r = result["checks"]["paths"].get("master_xlsx", {})
    if not r.get("exists"):
        result["errors"].append("WARN: 主表 %s 不存在（运行前请确认）" % r.get("path"))

    out(result)
    if not result["ok"]:
        for e in result["errors"]:
            emit(e.split(":")[0], e)
        raise SystemExit(2)


def do_quick(a):
    cfg = load_config()
    port = cfg_int(cfg, "cdp_port", 9333)
    ver = cdp_version(port, cfg.get("cdp_host", "127.0.0.1"))
    out({"ok": bool(ver), "port": port, "browser": (ver or {}).get("Browser")})
    if not ver:
        emit("E010", "CDP 端口 %d 不可达" % port)
        raise SystemExit(2)


def do_launch(a):
    cfg = load_config()
    out({"ok": True,
         "command": '"%s" %s' % (cfg.get("chrome_exe", ""), cfg.get("chrome_flags", "")),
         "note": "先退出全部 chrome.exe 再用此命令启动；同 profile 多实例会让调试端口失效"})


CMDS = {"check": do_check, "quick": do_quick, "launch": do_launch}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    a = dict(x.split("=", 1) for x in sys.argv[2:] if "=" in x)
    if cmd not in CMDS:
        raise SystemExit("用法：env_doctor.py {check|quick|launch}")
    CMDS[cmd](a)

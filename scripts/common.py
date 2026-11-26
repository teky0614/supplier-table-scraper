# -*- coding: utf-8 -*-
"""公共基础：配置读取、路径解析、JSON I/O、统一输出、错误码。

设计目标：所有脚本共享同一套配置源和错误语义，禁止各自硬编码。
配置读取零第三方依赖（不引 pyyaml），解析 config.yaml 的简单 key: value 行。
"""
import os, sys, json, io, re

# 让 Windows 控制台正确打印中文
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.yaml")

# 错误码表：脚本失败时 print ERR <code>，监控据此定位阶段/动作
ERR = {
    "E001": "配置读取失败",
    "E002": "依赖缺失（openpyxl/zxingcpp/Pillow）",
    "E010": "CDP 端口不可达（浏览器未用调试端口启动）",
    "E011": "CDP 无标签页",
    "E012": "至尊宝插件未检测到",
    "E020": "表头歧义或必需列缺失",
    "E021": "护栏未通过（覆盖率不足/删除比例过高）",
    "E022": "落地自检失败（标题集合不一致）",
    "E023": "标题未命中（完全一致匹配失败）",
    "E024": "标题清单有重复",
    "E030": "JAN 多候选冲突（需人工看放大图）",
    "E031": "JAN GS1 校验不通过（需重裁/复核）",
    "E032": "JAN 无解码结果",
    "E040": "风控/验证框出现（立即停，不重试）",
    "E050": "共享表写入回读验收失败",
    "E099": "其他未分类错误",
}


def load_config(path=None):
    """解析简单 YAML（key: value，# 注释，忽略空行）。值统一为字符串。"""
    p = path or CONFIG_PATH
    cfg = {}
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if ":" not in s:
                    continue
                k, v = s.split(":", 1)
                k = k.strip()
                v = v.split(" #", 1)[0].strip()  # 行尾注释
                v = v.strip('"').strip("'")
                cfg[k] = v
    except Exception as e:
        die("E001", "读配置 %s 失败: %s" % (p, e))
    return cfg


def cfg_int(cfg, key, default=None):
    return int(cfg.get(key, default)) if cfg.get(key, default) is not None else default


def cfg_float(cfg, key, default=None):
    return float(cfg.get(key, default)) if cfg.get(key, default) is not None else default


def out(obj):
    """统一 stdout JSON 输出，脚本间可解析。"""
    print(json.dumps(obj, ensure_ascii=False))


def emit(code, msg=""):
    """打印结构化错误行：ERR <code> <msg>，供 watchdog 捕获定位。"""
    print("ERR %s %s" % (code, msg), file=sys.stderr)


def die(code, msg=""):
    emit(code, msg)
    raise SystemExit(2)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj, indent=1):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)


def kv_args(argv):
    return dict(a.split("=", 1) for a in argv if "=" in a)


def norm_color(v):
    """SKU 袋规只保留纯数字（2026-11-26 用户规则）。

    "原袋20个" -> "20"；"30" -> "30"；"原袋120个/整箱" -> "120"。
    取字符串中第一段连续数字；无数字时返回原值并交给上层校验（不应静默吞掉）。
    """
    s = str(v).strip()
    m = re.search(r"\d+", s)
    return m.group(0) if m else s


def check_deps():
    """检查关键第三方依赖，缺失则 E002。"""
    missing = []
    for mod in ("openpyxl", "PIL", "zxingcpp"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        die("E002", "缺依赖 %s；请用 default venv 运行：%s"
            % (missing, load_config().get("python_exe", "")))


if __name__ == "__main__":
    c = load_config()
    out({"config_path": CONFIG_PATH, "python_exe": c.get("python_exe"),
         "cdp_port": c.get("cdp_port"), "keys": len(c)})

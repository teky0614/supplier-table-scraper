# -*- coding: utf-8 -*-
"""全流程监控：run_id、状态机、日志、超时、失败定位、重试与自修复建议。

子命令（key=value）：
  init      run=<run_dir> stage=<阶段名>            创建 run 目录与 state.json
  step      run=<run_dir> step=<步骤> status=<start|ok|fail> \
            detail=<json可选> timeout=<秒可选>       记录步骤状态（原子写）
  stage     run=<run_dir> stage=<阶段> status=<...>  记录阶段级状态
  gate      run=<run_dir> gate=<A|B|C> status=<pending|approved|rejected>
  retry     run=<run_dir> step=<步骤> [max=3]        读重试计数，返回是否可重试
  status    run=<run_dir>                            打印当前状态总览
  failpoint run=<run_dir>                            打印失败定位报告（最后成功点+缺产物+建议）
  report    run=<run_dir> out=<md路径>               生成作业报告 markdown

设计：
- state.json 每步原子写（先写 .tmp 再 os.replace），崩溃后从最后成功点恢复。
- events.jsonl 追加写结构化事件，含耗时。
- 重试策略：脚本类可重试（retry 子命令计数）；风控/门禁 不重试（由调用方遵守）。
- 失败定位：给出最后成功步骤、失败步骤、耗时异常、缺失产物、自修复建议。
"""
import os, sys, json, time, datetime, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import kv_args, out, write_json, read_json, ERR

STAGES = ["env", "collect", "sync_local", "diff_kdocs", "scrape", "write_kdocs", "land", "finish"]


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def paths(run):
    return {
        "dir": run,
        "state": os.path.join(run, "state.json"),
        "events": os.path.join(run, "events.jsonl"),
        "gates": os.path.join(run, "gates.json"),
    }


def atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_state(run):
    p = paths(run)["state"]
    if not os.path.exists(p):
        raise SystemExit("state.json 不存在，先 init: " + p)
    return read_json(p)


def append_event(run, ev):
    ev.setdefault("ts", now())
    with open(paths(run)["events"], "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def cmd_init(a):
    run = a["run"]
    os.makedirs(run, exist_ok=True)
    for sub in ("shots", "payload", "logs"):
        os.makedirs(os.path.join(run, sub), exist_ok=True)
    st = {
        "run_id": os.path.basename(run.rstrip("/\\")),
        "created": now(), "updated": now(),
        "stage": a.get("stage", "env"), "status": "running",
        "current_step": None, "last_ok_step": None,
        "steps": {}, "gates": {"A": "pending", "B": "pending", "C": "pending"},
        "artifacts": {}, "retries": {}, "failure": None,
    }
    atomic_json(paths(run)["state"], st)
    append_event(run, {"event": "init", "stage": st["stage"], "run": run})
    out({"ok": True, "run": run, "run_id": st["run_id"]})


def _set_step(a, status):
    run, step = a["run"], a["step"]
    st = load_state(run)
    t0 = st["steps"].get(step, {}).get("start_ts")
    if status == "start":
        st["current_step"] = step
        st["steps"][step] = {"status": "running", "start_ts": now(),
                             "detail": a.get("detail", ""),
                             "timeout": a.get("timeout")}
        st["status"] = "running"
    else:
        rec = st["steps"].setdefault(step, {})
        rec["status"] = status
        rec["end_ts"] = now()
        if a.get("detail"):
            rec["detail"] = a["detail"]
        if t0:
            try:
                fmt = "%Y-%m-%dT%H:%M:%S"
                rec["elapsed_s"] = round((datetime.datetime.fromisoformat(rec["end_ts"])
                                          - datetime.datetime.fromisoformat(t0)).total_seconds(), 1)
            except Exception:
                pass
        if status == "ok":
            st["last_ok_step"] = step
            st["current_step"] = None
            if a.get("artifact"):
                st["artifacts"].setdefault(step, []).append(a["artifact"])
        else:
            st["status"] = "failed"
            st["failure"] = {"step": step, "detail": a.get("detail", ""), "ts": now()}
            st["current_step"] = step
    st["updated"] = now()
    atomic_json(paths(run)["state"], st)
    append_event(run, {"event": "step", "step": step, "status": status,
                       "detail": a.get("detail", ""), "elapsed_s": st["steps"][step].get("elapsed_s")})
    # 超时告警
    if status == "ok" and st["steps"][step].get("elapsed_s") and a.get("timeout"):
        if st["steps"][step]["elapsed_s"] > float(a["timeout"]):
            append_event(run, {"event": "timeout_warn", "step": step,
                               "elapsed_s": st["steps"][step]["elapsed_s"], "timeout": a["timeout"]})
    out({"ok": True, "step": step, "status": status})


def cmd_step(a):
    _set_step(a, a.get("status", "start"))


def cmd_stage(a):
    run = a["run"]
    st = load_state(run)
    st["stage"] = a["stage"]
    if a.get("status"):
        st["status"] = a["status"]
    st["updated"] = now()
    atomic_json(paths(run)["state"], st)
    append_event(run, {"event": "stage", "stage": a["stage"], "status": a.get("status", "")})
    out({"ok": True, "stage": a["stage"]})


def cmd_gate(a):
    run, g = a["run"], a["gate"]
    st = load_state(run)
    st["gates"][g] = a["status"]
    st["updated"] = now()
    atomic_json(paths(run)["state"], st)
    append_event(run, {"event": "gate", "gate": g, "status": a["status"]})
    out({"ok": True, "gate": g, "status": a["status"]})


def cmd_retry(a):
    run, step = a["run"], a["step"]
    mx = int(a.get("max", 3))
    st = load_state(run)
    n = st["retries"].get(step, 0) + 1
    st["retries"][step] = n
    atomic_json(paths(run)["state"], st)
    can = n <= mx
    append_event(run, {"event": "retry", "step": step, "n": n, "allowed": can})
    out({"ok": True, "step": step, "attempt": n, "max": mx, "can_retry": can,
         "hint": "" if can else "已达重试上限，转人工/自修复流程"})


def cmd_status(a):
    st = load_state(a["run"])
    summary = {
        "run_id": st["run_id"], "stage": st["stage"], "status": st["status"],
        "last_ok_step": st["last_ok_step"], "current_step": st["current_step"],
        "steps": {k: v["status"] for k, v in st["steps"].items()},
        "gates": st["gates"], "failure": st["failure"],
        "retries": st["retries"], "updated": st["updated"],
    }
    out(summary)


def cmd_failpoint(a):
    st = load_state(a["run"])
    fail = st.get("failure") or {}
    bad_step = fail.get("step")
    # 耗时异常步骤
    slow = [(k, v.get("elapsed_s")) for k, v in st["steps"].items()
            if v.get("elapsed_s") and v["elapsed_s"] > 120]
    # 缺失产物（按已知阶段期望）
    expect = {"sync_local": ["diff.json"], "diff_kdocs": ["kd_diff.json"],
              "scrape": ["fields.json"], "write_kdocs": ["pay_text.json", "pay_pic.json"]}
    missing = []
    for stg, files in expect.items():
        if stg in st["steps"] and st["steps"][stg]["status"] == "ok":
            for fn in files:
                fp = os.path.join(a["run"], fn)
                if not os.path.exists(fp):
                    missing.append(fn)
    # 自修复建议
    advice = []
    if bad_step:
        advice.append("从最后成功点 %s 重跑步骤 %s（脚本幂等，可安全重跑）"
                      % (st.get("last_ok_step"), bad_step))
    if "E010" in str(fail.get("detail", "")):
        advice.append("浏览器未带调试端口：退出全部 chrome 后用 chrome_flags 重启，再 env_doctor check")
    if "E021" in str(fail.get("detail", "")):
        advice.append("护栏未过：确认是否全店采集（误选分类/新品筛选），核实后 sync_apply force=1")
    if "E030" in str(fail.get("detail", "")) or "E031" in str(fail.get("detail", "")):
        advice.append("JAN 存疑：按铁律看放大原图逐位复核，不挑 GS1 通过值凑数；门禁C 报用户")
    if "E040" in str(fail.get("detail", "")):
        advice.append("风控/验证框：立即停止，不重试，通知用户人工处理")
    if not advice:
        advice.append("查 events.jsonl 最后几条事件定位；确认备份存在后再决定回滚或重跑")
    out({"run_id": st["run_id"], "stage": st["stage"], "status": st["status"],
         "last_ok_step": st.get("last_ok_step"), "failed_step": bad_step,
         "failure_detail": fail.get("detail"), "slow_steps": slow,
         "missing_artifacts": missing, "retries": st["retries"],
         "self_heal_advice": advice})


def cmd_report(a):
    st = load_state(a["run"])
    lines = ["# 供应商表格抓取 · 作业报告", ""]
    lines.append("- run_id: %s" % st["run_id"])
    lines.append("- 阶段: %s" % st["stage"])
    lines.append("- 状态: %s" % st["status"])
    lines.append("- 开始: %s / 更新: %s" % (st["created"], st["updated"]))
    lines.append("")
    lines.append("## 步骤状态")
    lines.append("| 步骤 | 状态 | 耗时(s) | 备注 |")
    lines.append("|---|---|---|---|")
    for k, v in st["steps"].items():
        lines.append("| %s | %s | %s | %s |" % (k, v["status"], v.get("elapsed_s", ""), str(v.get("detail", ""))[:60]))
    lines.append("")
    lines.append("## 门禁")
    for g, s in st["gates"].items():
        lines.append("- 门禁 %s: %s" % (g, s))
    if st.get("failure"):
        lines.append("")
        lines.append("## 失败信息")
        lines.append("- 步骤: %s" % st["failure"].get("step"))
        lines.append("- 详情: %s" % st["failure"].get("detail"))
    txt = "\n".join(lines)
    with open(a["out"], "w", encoding="utf-8") as f:
        f.write(txt)
    out({"ok": True, "report": a["out"]})


CMDS = {"init": cmd_init, "step": cmd_step, "stage": cmd_stage, "gate": cmd_gate,
        "retry": cmd_retry, "status": cmd_status, "failpoint": cmd_failpoint, "report": cmd_report}

if __name__ == "__main__":
    a = kv_args(sys.argv[2:])
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        raise SystemExit("用法：watchdog.py {%s} k=v ..." % "|".join(CMDS))
    CMDS[sys.argv[1]](a)

# -*- coding: utf-8 -*-
"""统一编排入口：把九阶段的脚本调用串起来，每步自动打 watchdog 点。

这不是"全自动无人值守"脚本——AI 视觉判断和门禁仍需 AI/人来做，本入口负责：
  1) 提供每个阶段的确定性脚本调用（带监控埋点）
  2) 阶段间前置校验（上一步没成功就拒绝往下）
  3) 失败时自动打印 failpoint 定位报告

子命令：
  init-run       run=<目录>              初始化一次作业
  stage0-env     run=<目录>              环境自检
  stage2-backup  run=<目录> [kdocs=0]    双备份（本地+共享表需 AI 用 MCP 调 save_as_file）
  stage2-sync    run=<目录> tmp=<临时表>  同步计划+落地测试副本（护栏门禁前）
  stage3-diff    run=<目录> kdocs=<json>  共享表 diff
  stage4-mark    run=<目录> titles=<json> 标红置顶
  stage5-fill    run=<目录> fields=<json> 回填字段
  stage5-payload run=<目录> oid=<json>    生成写入 payload
  stage6-verify  run=<目录> real=<真表> n=<N>
  failpoint / status / report             监控

注意：共享表的 MCP 写入（删行/插行/写单元格/图片上传/行高）必须由 AI 直接调 kdocs 工具，
      脚本只负责生成 payload 和回读验收数据；这是"AI 执行 + 脚本计算"的混合点。
"""
import os, sys, subprocess, shlex
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import load_config, out, emit, read_json, write_json

PY = load_config().get("python_exe", sys.executable)


def call(script, args, run=None, step=None, timeout=None, artifact=None):
    """调用子脚本并自动打 watchdog 埋点。"""
    if run and step:
        subprocess.run([PY, os.path.join(HERE, "watchdog.py"), "step",
                        "run=" + run, "step=" + step, "status=start",
                        "timeout=" + str(timeout or 120)], check=False)
    cmd = [PY, os.path.join(HERE, script)] + args
    r = subprocess.run(cmd)
    ok = r.returncode == 0
    if run and step:
        kv = ["run=" + run, "step=" + step, "status=" + ("ok" if ok else "fail")]
        if artifact:
            kv.append("artifact=" + artifact)
        subprocess.run([PY, os.path.join(HERE, "watchdog.py"), "step"] + kv, check=False)
    if not ok:
        # 失败即打印定位报告
        subprocess.run([PY, os.path.join(HERE, "watchdog.py"), "failpoint", "run=" + run], check=False)
        raise SystemExit(r.returncode)
    return ok


def cmd_init_run(a):
    run = a["run"]
    call("watchdog.py", ["init", "run=" + run, "stage=env"], timeout=30)
    out({"ok": True, "run": run, "hint": "阶段0起，每步已自动埋点"})


def cmd_stage0_env(a):
    call("env_doctor.py", ["check"], run=a["run"], step="env_check", timeout=60)


def cmd_stage2_backup(a):
    cfg = load_config()
    call("table_ops.py", ["backup", "file=" + cfg.get("master_xlsx", ""),
                          "dir=" + cfg.get("backup_dir", "")],
         run=a["run"], step="backup_local", timeout=60)
    out({"ok": True, "note": "共享表备份需 AI 调 kdocs save_as_file（dst_drive_id="
          + cfg.get("kdocs_backup_drive_id", "") + "）"})


def cmd_stage2_sync(a):
    cfg = load_config()
    tmp = a["tmp"]
    diff = os.path.join(a["run"], "diff.json")
    base = os.path.join(a["run"], "总表_基准.xlsx")
    test = os.path.join(a["run"], "总表_测试.xlsx")
    call("table_ops.py", ["sync_plan", "tmp=" + tmp, "master=" + cfg.get("master_xlsx", ""),
                          "out=" + diff], run=a["run"], step="sync_plan", timeout=60, artifact=diff)
    plan = read_json(diff)
    out({"ok": True, "guard": plan["guard"], "counts": plan["counts"],
         "GATE": "A", "hint": "必须 AI 向用户汇报新增/删除/剔除/护栏并获确认后再落地"})
    if a.get("approved") == "1":
        call("watchdog.py", ["gate", "run=" + a["run"], "gate=A", "status=approved"])
        extra = ["force=1"] if a.get("force") == "1" else []
        # sync_apply 的 out/base 默认写到 run 目录
        call("table_ops.py", ["sync_apply", "master=" + cfg.get("master_xlsx", ""),
                              "diff=" + diff, "out=" + test, "base=" + base] + extra,
             run=a["run"], step="sync_apply", timeout=120, artifact=test)
        out({"ok": True, "test": test, "base": base})
    else:
        call("watchdog.py", ["gate", "run=" + a["run"], "gate=A", "status=pending"])


def cmd_stage3_diff(a):
    cfg = load_config()
    kd = a["kdocs"]  # AI 用 MCP 读共享表 B 列后落成的 json
    outf = os.path.join(a["run"], "kd_diff.json")
    call("table_ops.py", ["diff_kdocs", "master=" + os.path.join(a["run"], "总表_测试.xlsx"),
                          "kdocs=" + kd, "out=" + outf],
         run=a["run"], step="diff_kdocs", timeout=60, artifact=outf)
    d = read_json(outf)
    out({"ok": True, "local_only": len(d["local_only"]), "kdocs_only": len(d["kdocs_only"]),
         "GATE": "B", "hint": "kdocs_only 必须列清单给用户确认后删；local_only 即待抓 N 款"})


def cmd_stage4_mark(a):
    call("table_ops.py", ["mark", "file=" + os.path.join(a["run"], "总表_测试.xlsx"),
                          "titles=" + a["titles"]],
         run=a["run"], step="mark", timeout=60)


def cmd_stage5_fill(a):
    call("table_ops.py", ["fill", "file=" + os.path.join(a["run"], "总表_测试.xlsx"),
                          "fields=" + a["fields"]],
         run=a["run"], step="fill", timeout=60)


def cmd_stage5_payload(a):
    cfg = load_config()
    fields_oid = a["oid"]  # fields.json 每项加 oid 后的文件
    prefix = os.path.join(a["run"], "payload", "pay")
    call("gen_kdocs_payload.py",
         ["fields=" + fields_oid, "file_id=" + cfg.get("kdocs_file_id", ""),
          "prefix=" + prefix],
         run=a["run"], step="payload", timeout=60)
    out({"ok": True, "text": prefix + "_text.json", "pic": prefix + "_pic.json",
         "hint": "AI 调 sheet.range_data_batch_update 提交两份 payload 的 range_data"})


def cmd_stage6_verify(a):
    real = a.get("real") or load_config().get("master_xlsx", "")
    call("table_ops.py", ["verify", "real=" + real,
                          "test=" + os.path.join(a["run"], "总表_测试.xlsx"),
                          "n=" + a["n"]],
         run=a["run"], step="verify", timeout=60)


def cmd_monitor(a, which):
    call("watchdog.py", [which, "run=" + a["run"]], timeout=30)


CMDS = {
    "init-run": cmd_init_run, "stage0-env": cmd_stage0_env,
    "stage2-backup": cmd_stage2_backup, "stage2-sync": cmd_stage2_sync,
    "stage3-diff": cmd_stage3_diff, "stage4-mark": cmd_stage4_mark,
    "stage5-fill": cmd_stage5_fill, "stage5-payload": cmd_stage5_payload,
    "stage6-verify": cmd_stage6_verify,
    "failpoint": lambda a: cmd_monitor(a, "failpoint"),
    "status": lambda a: cmd_monitor(a, "status"),
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        raise SystemExit("用法：run.py {%s} k=v ..." % "|".join(CMDS))
    a = dict(x.split("=", 1) for x in sys.argv[2:] if "=" in x)
    CMDS[sys.argv[1]](a)

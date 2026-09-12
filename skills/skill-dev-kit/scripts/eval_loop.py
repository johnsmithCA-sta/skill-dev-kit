#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_loop.py — 技能评测循环编排（with-skill vs baseline 对比 + 聚合）
====================================================================
对标官方规范的评测循环编排（run_eval + aggregate_benchmark）：为「带技能」与「基线」
两种运行收集输出并做断言评分，聚合为 benchmark.json，辅助判断技能是否真的提升了表现。

⚠️ **双跑不自动编排**：脚本不会自己派发 with_skill / baseline 两臂——两条运行需人工并行
发起并各自落到用例目录，再分别聚合。自动双跑当前未实现（详见 references/评测方法论.md §1.7）。

用法:
  python3 eval_loop.py <evals_dir> [--run] [--aggregate] [--out benchmark.json]

  --run        扫描 <evals_dir> 下每个用例目录，执行 run_cmd（若提供）产生 output 与 timing
  --aggregate  聚合所有用例的 grading.json → benchmark.json（默认动作）
  --out        聚合输出文件（默认 <evals_dir>/benchmark.json）
  --exts       只统计这些扩展名的产物（逗号分隔，如 .md,.txt）；
               默认 **按内容探测读全部非二进制文本**，不做扩展名白名单

目录约定（每个测试用例一个子目录）:
  evals_dir/
  ├── case-01/
  │   ├── eval.json        # {"prompt":..., "assertions":[...]} 断言=期望输出应包含的要点
  │   ├── run_cmd.txt      # 可选：执行命令，产物写入 output/
  │   ├── output/          # 运行产物（带技能）
  │   ├── baseline/        # 基线产物（不带技能）
  │   └── grading.json     # 评分结果：{"assertions":[{"text":..,"pass":true,"evidence":..}]}
  └── case-02/ ...

评分模式（降级策略，零外部依赖）:
  1. grading.json 已存在 → 直接读取（人工/LLM 预先评分）；
  2. 否则按 eval.json.assertions 做子串包含检查（启发式评分，evidence=命中/缺失要点）；
  3. 无任何断言 → skip（不纳入聚合）；
  4. output/ 无产物 → skip（无数据 ≠ 全错，见下）。

缓存语义（v1.7.1 修正，别再踩）:
  · 启发式评分产物落盘为 grading.json，mode="heuristic-substring"，属**机器缓存**；
  · `--run` 重跑后会自动删掉这类缓存并按新产物重评；**人工预置的 grading.json
    （mode 非 heuristic-substring）一律保留**；
  · 无产物时**不落盘**评分——曾经照样打成 0 分并写进 grading.json，既把
    「没跑」记成「全错」（违反评测方法论 §1.1），又会把下一轮真跑出来的产物
    锁死在 0 分上，且 mode 显示 pre-graded 极难排查。

退出码（三态，CI 必须按此判定）:
  0 = PASS    均分 ≥ 0.7，可放行
  2 = REVIEW  均分 < 0.7；或 NO-DATA（没有可评分用例）—— **需人工确认，不等于通过**
  1 = 运行期失败（目录不存在等硬错误）—— 阻断

  ⚠️ 曾存在的静默失败：REVIEW 被判为 0，CI 直接放行低分技能。REVIEW 必须走 2。
  CI 判据应写为「1 阻断 / 2 告警 + 人工确认」，只判 0/1 会让 REVIEW 被当通过。

示例:
  python3 eval_loop.py ./my-skill/evals --aggregate
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

def load_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

# 仅作快速排除（大二进制文件不值得逐字节解码），真正的判定靠内容探测
BIN_EXT_SKIP = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar",
    ".mp4", ".mp3", ".wav", ".mov", ".woff", ".woff2", ".ttf", ".otf",
    ".pyc", ".so", ".dylib", ".exe", ".dll", ".class", ".jar", ".xlsx", ".docx", ".pptx",
)

def _is_text_file(p, probe=4096):
    """按内容探测是否文本文件：前 probe 字节含 NUL 或无法 utf-8 解码 → 判为二进制。

    为什么不用扩展名白名单：白名单只能覆盖"我们想到的"产物类型，
    .html / .log / .csv / .yaml 这类真实产物会被漏评，评分结果假阴性。
    """
    try:
        with open(p, "rb") as f:
            chunk = f.read(probe)
    except Exception:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True

def read_dir_text(d, exts=None):
    """拼接目录下的文本产物，用于断言子串匹配。

    exts=None（默认）→ 读全部**非二进制**文本（内容探测，非扩展名白名单）；
    exts 显式给出（如 --exts .md,.txt）→ 仅读这些扩展名。
    """
    if not os.path.isdir(d):
        return ""
    want = tuple(e.strip().lower() for e in exts) if exts else None
    chunks = []
    for root, _, files in os.walk(d):
        for fn in sorted(files):
            p = os.path.join(root, fn)
            low = fn.lower()
            if want is not None:
                if not low.endswith(want):
                    continue
            elif low.endswith(BIN_EXT_SKIP) or not _is_text_file(p):
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    chunks.append(f.read())
            except Exception:
                pass
    return "\n".join(chunks)

def heuristic_grade(eval_json, output_text):
    """按断言做子串包含检查，生成 grading 结构。"""
    assertions = (eval_json or {}).get("assertions", [])
    if not assertions:
        return None
    graded = []
    for a in assertions:
        key = a if isinstance(a, str) else a.get("text", "")
        hit = bool(key) and key in output_text
        graded.append({
            "text": key,
            "pass": hit,
            "evidence": ("输出包含要点" if hit else "输出缺失要点: %s" % key),
        })
    passed = sum(1 for g in graded if g["pass"])
    return {
        "assertions": graded,
        "passed": passed,
        "total": len(graded),
        "score": (passed / len(graded)) if graded else 0.0,
        "mode": "heuristic-substring",
    }

def run_case(case_dir):
    cmd_file = os.path.join(case_dir, "run_cmd.txt")
    out_dir = os.path.join(case_dir, "output")
    if not os.path.isfile(cmd_file):
        return False, "无 run_cmd.txt，跳过执行"
    with open(cmd_file, encoding="utf-8") as f:
        cmd = f.read().strip()
    if not cmd:
        return False, "run_cmd.txt 为空"
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, shell=True, cwd=case_dir, capture_output=True, text=True, timeout=300)
        dt = time.time() - t0
        with open(os.path.join(out_dir, "_stdout.txt"), "w", encoding="utf-8") as f:
            f.write(r.stdout or "")
        with open(os.path.join(out_dir, "_stderr.txt"), "w", encoding="utf-8") as f:
            f.write(r.stderr or "")
        with open(os.path.join(case_dir, "timing.json"), "w", encoding="utf-8") as f:
            json.dump({"seconds": round(dt, 3), "exit_code": r.returncode}, f, ensure_ascii=False, indent=2)
        invalidate_machine_grading(case_dir)
        return True, "exit=%d 用时 %.2fs" % (r.returncode, dt)
    except Exception as e:
        return False, "执行失败: %s" % e

def invalidate_machine_grading(case_dir):
    """--run 重跑后，删掉本脚本自己写的启发式评分缓存，保证按新产物重评。

    只删 `mode == "heuristic-substring"` 的（机器缓存，重算无损）；
    **人工预置的 grading.json 一律保留**——那是有意的人工评分，重跑产物不该冲掉它。

    ⚠️ 历史缺陷：不失效缓存的话，产物已经更新、聚合却仍读旧结论，
    表现为「明明全绿却报 0 分」——而 grading.json 的存在会让 mode 显示成
    `pre-graded`，看上去像人工评的，极难排查。
    """
    p = os.path.join(case_dir, "grading.json")
    if not os.path.isfile(p):
        return False
    try:
        with open(p, encoding="utf-8") as f:
            g = json.load(f)
    except Exception:
        return False
    if not isinstance(g, dict) or g.get("mode") != "heuristic-substring":
        return False
    os.remove(p)
    return True

def grade_case(case_dir, exts=None):
    eval_json = load_json(os.path.join(case_dir, "eval.json")) or {}
    grading = load_json(os.path.join(case_dir, "grading.json"))
    if grading:
        return grading, "pre-graded"
    out_text = read_dir_text(os.path.join(case_dir, "output"), exts=exts)
    # ⚠️ 无产物 = 无数据，不是「全错」。曾经在此照常打分并落盘 0 分 grading.json，
    # 既违反评测方法论 §1.1（无数据不得判 FAIL），又会把下一轮真跑出来的产物
    # 锁死在 0 分上（缓存被当 pre-graded 读取）。无产物一律 skip，不落盘。
    if not out_text.strip():
        return None, "skip（output/ 无产物，需先 --run）"
    g = heuristic_grade(eval_json, out_text)
    if g:
        with open(os.path.join(case_dir, "grading.json"), "w", encoding="utf-8") as f:
            json.dump(g, f, ensure_ascii=False, indent=2)
        return g, "heuristic"
    return None, "skip（无 grading.json 且 eval.json 无断言）"

def aggregate(evals_dir, out_path, exts=None):
    cases = sorted(d for d in glob.glob(os.path.join(evals_dir, "*")) if os.path.isdir(d))
    if not cases:
        return None, "无测试用例子目录"
    rows, tot_pass, tot_score, graded_n = [], 0, 0.0, 0
    for c in cases:
        name = os.path.basename(c)
        grading, mode = grade_case(c, exts=exts)
        if not grading:
            rows.append({"case": name, "status": mode})
            continue
        passed = grading.get("passed")
        total = grading.get("total")
        if passed is None:  # pre-graded 结构：从 assertions 推导
            a = grading.get("assertions", [])
            passed = sum(1 for x in a if x.get("pass"))
            total = len(a)
        score = (passed / total) if total else 0.0
        graded_n += 1
        tot_pass += passed
        tot_score += score
        rows.append({"case": name, "mode": mode, "passed": passed, "total": total, "score": round(score, 3)})
    bench = {
        "cases": len(cases),
        "graded": graded_n,
        "assertion_passed": tot_pass,
        "avg_score": round(tot_score / graded_n, 3) if graded_n else 0.0,
        "verdict": ("PASS" if graded_n and (tot_score / graded_n) >= 0.7 else ("REVIEW" if graded_n else "NO-DATA")),
        "detail": rows,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(bench, f, ensure_ascii=False, indent=2)
    return bench, None

def main():
    ap = argparse.ArgumentParser(
        description="技能评测循环编排与聚合",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 最常用：聚合本技能 evals/ 下各用例的评分，产出 benchmark.json
  python3 scripts/eval_loop.py ./evals --aggregate

  # 指定聚合输出位置，并把产物限定为 md/txt
  python3 scripts/eval_loop.py ./evals --aggregate --out ./evals/benchmark.json --exts .md,.txt

  # 先跑各用例的 run_cmd.txt 产出 output/，再聚合
  python3 scripts/eval_loop.py ./evals --run --aggregate
""")
    ap.add_argument("evals_dir", help="评估集目录：其下每个子目录算一个用例")
    ap.add_argument("--run", action="store_true",
                    help="先执行各用例的 run_cmd.txt 产出 output/，再聚合（缺省只聚合已有结果）")
    ap.add_argument("--aggregate", action="store_true",
                    help="聚合各用例评分并写出 benchmark.json")
    ap.add_argument("--out", default=None,
                    help="聚合输出路径（默认写 <评估集目录>/benchmark.json）")
    ap.add_argument("--exts", default=None,
                    help="只统计这些扩展名的产物（逗号分隔，如 .md,.txt）；"
                         "默认按内容探测读全部非二进制文本")
    args = ap.parse_args()
    exts = tuple(e.strip() for e in args.exts.split(",") if e.strip()) if args.exts else None

    evals_dir = os.path.abspath(args.evals_dir)
    if not os.path.isdir(evals_dir):
        print("FAIL  目录不存在: %s" % evals_dir)
        return 1
    out = args.out or os.path.join(evals_dir, "benchmark.json")

    if args.run:
        for c in sorted(glob.glob(os.path.join(evals_dir, "*"))):
            if os.path.isdir(c):
                ok, msg = run_case(c)
                print(("RUN  " if ok else "SKIP ") + os.path.basename(c) + "  " + msg)

    bench, err = aggregate(evals_dir, out, exts=exts)
    if err:
        # 未做评测 ≠ 通过：给 REVIEW(2) 而不是 FAIL(1)，也不是 PASS(0)
        print("REVIEW  " + err + "（未产生任何评分，需人工确认；若有预期用例请检查目录结构）")
        return 2
    print("benchmark: %s" % out)
    print("用例 %d，评分 %d，断言通过 %d，均分 %.2f，判定 %s" % (
        bench["cases"], bench["graded"], bench["assertion_passed"], bench["avg_score"], bench["verdict"]))
    for r in bench["detail"]:
        if "score" in r:
            print("  %s  %s  %d/%d  score=%.2f" % (r["case"], r["mode"], r["passed"], r["total"], r["score"]))
        else:
            print("  %s  %s" % (r["case"], r["status"]))
    # PASS → 0（可放行）｜REVIEW → 2（需人工确认）｜NO-DATA → 2（未做评测，告警）
    # 历史缺陷：此处曾把 REVIEW 判为 0，导致低分技能被 CI 放行（静默失败）
    return {"PASS": 0}.get(bench["verdict"], 2)

if __name__ == "__main__":
    sys.exit(main())

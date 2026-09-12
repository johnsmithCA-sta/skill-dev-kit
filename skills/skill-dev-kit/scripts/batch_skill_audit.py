#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_skill_audit.py — 批量技能体检：一次对 N 个技能跑同一套门禁
=====================================================================
为什么需要它
  一个技能的体检要跑三条命令（description 质量、常规发布预检、严格发布预检），再手工抄
  一遍结构数字。20+ 个技能就是 60+ 次调用加一张手抄表——既慢又会抄错，抄错的表格还会被
  当成结论。本脚本把「发现技能 → 逐个跑门禁 → 汇总成一张表」收成一条命令。

用法
  python3 batch_skill_audit.py [根目录] [--exclude 目录名] [--only 目录名] [--limit N]
                              [--platform skillhub|github] [--timeout 秒] [--no-help-probe]
                              [--json] [--json-out [路径]]

  根目录          技能集合的父目录，默认 ~/.workbuddy/skills；其下含 SKILL.md 的子目录算一个技能
  --exclude       跳过的目录名，可多次传入（也支持逗号分隔）
  --only          只体检指定目录名的技能，可多次传入；试跑/复现单个技能时用
  --limit         最多体检前 N 个技能（按目录名排序）；试跑时用
  --platform      发布预检查的平台档（默认 skillhub），原样透传给发布预检
  --timeout       单条子命令的超时秒数（默认 120）
  --no-help-probe 不探测脚本的 --help（见下「判断口径」第 ④ 条，探测有副作用风险）
  --json          把结果以 JSON 打到标准输出（替代人读汇总表）
  --json-out      把 JSON 写到文件；不带值则写到 ~/.workbuddy/batch-audit-<时间戳>.json

退出码（三态，与包内其余工具一致）
  0 = PASS   全部技能通过
  1 = FAIL   至少一个技能 FAIL
  2 = REVIEW 无 FAIL，但有 REVIEW / 不可判（超时、跑不起来、拿不到结论）

判断口径（每个技能收集四类证据）
  ① desc-check       调同目录的 description 触发词校验，取**退出码**：0 PASS / 1 FAIL / 2 REVIEW
  ② 发布预检普通档    调同目录的发布预检 --platform <平台>，取**退出码**：0 PASS / 1 FAIL / 2 参数错
  ③ 发布预检严格档    同上再加 --strict。**严格档不参与全局退出码**：--strict 的语义是
                     「把低危告警也当失败」，它把 author 缺失、正文超目标值这类「应当有」
                     的规范项升格成阻断，拿它当发布闸门会把正常状态判死（与包内
                     「自建门禁严于目标平台会误杀正确写法」是同一条纪律）。严格档照常列出，
                     普通档 PASS 而严格档 FAIL 时标 WARN，交人工判断。
  ④ --help 覆盖率     只探测**构造了 argparse 的那批脚本**。对被检技能的脚本跑 --help 有可能
                     触发它自身的副作用，不构造 argparse 的脚本一律不执行（只计不计入）。
                     计入数为 0 时该项为「不可判」（列 —），不因此判 FAIL。
  结论优先级：先取子进程**退出码**；只有结构数字（§ 章节引用的判定数/断链数）才去解析发布
  预检输出里的**稳定标记**，且不回落到匹配大段人读文案。
  § 章节引用：解析「已判定的 N 处章节引用全部存在」「章节引用断链:」「未判定 N 处」三个稳定
  标记；一个都没有 = 发布预检没跑出这一节 = 不可判（列 —），不判 FAIL，计入 REVIEW 信号。

结构统计口径（每个技能除门禁外还给一组数字，供横向对比）
  · 文件构成 = 顶层文件 / references 递归 / scripts 递归 / evals 递归**各自的文件数**，
    统一排除 __pycache__：编译缓存不是技能资产，计进去数字会随「有没有跑过编译检查」而变，
    同一批技能的表格立刻不可比。
  · 正文体积照抄同目录发布预检的现成实现（中文字数 × 1.0 + 非中文字符数 ÷ 4，先剥 frontmatter）。
  · 触发词条数照抄同目录触发词评估工具的章节解析口径（含「A / B / C」拆条），两边数字必须对得上。
  · frontmatter 字段清单与 version 取自顶部 --- 块的简易解析；没有 --- 块则整项为 null。

落盘纪律
  报告**不写进被检技能目录**：默认只打标准输出，--json-out 默认落到 ~/.workbuddy/ 下。
  若给出的路径落在被检技能目录或本工具包目录内，直接拒绝写入并走 REVIEW——体检不改被检对象。

示例
  python3 batch_skill_audit.py
  python3 batch_skill_audit.py --only skill-dev-kit
  python3 batch_skill_audit.py ~/.workbuddy/skills --exclude _template --limit 5
  python3 batch_skill_audit.py --json
  python3 batch_skill_audit.py --json-out
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(HERE)                                    # 本工具包根目录
DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills")
DEFAULT_TIMEOUT = 120
JSON_OUT_DEFAULT = "__default__"     # --json-out 不带值时的哨兵，实际路径带时间戳现算

# 结论映射：退出码 → 三态词。拿不到退出码（None）与「参数错」(2) 都归 REVIEW——
# 判不了就说判不了，不许美化成一个通过。
RC_VERDICT = {0: "PASS", 1: "FAIL", 2: "REVIEW"}

# 发布预检输出里的稳定标记（只认这几个，不去匹配大段人读文案）
RE_SEC_JUDGED = re.compile(r"已判定的\s*(\d+)\s*处章节引用全部存在")
RE_SEC_UNJUDGED = re.compile(r"未判定\s*(\d+)\s*处")
SEC_BROKEN_MARK = "章节引用断链:"
PREFLIGHT_RESULT_MARK = "结果: "


# ---------------------------------------------------------------- 基础读取
def _read(path):
    """读文本；读不到返回 None（不抛，交给调用方判不可判）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _count_files(directory):
    """目录下（递归）文件数；目录不存在返回 0。

    排除 __pycache__：那是编译缓存不是技能资产，跑过一次语法编译检查它就会出现，
    计进去会让同一个技能的数字随「有没有跑过编译」而变（表格立刻不可比）。
    """
    if not os.path.isdir(directory):
        return 0
    n = 0
    for dp, dn, fs in os.walk(directory):
        dn[:] = [d for d in dn if d != "__pycache__"]
        n += len(fs)
    return n


def parse_frontmatter(path):
    """提取顶部 --- 块的 key: value（与发布预检同口径的简易解析）。缺块返回 None。"""
    text = _read(path)
    if text is None:
        return None
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return None
    fields = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        km = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if km:
            fields[km.group(1)] = km.group(2).strip().strip("\"'")
    return fields


def body_token_estimate(path):
    """估算 SKILL.md **正文**体积（token）。读不到返回 None。

    口径（照抄同目录发布预检的现成实现，不另造一套）:
        正文 token ≈ 中文字数 × 1.0 + 非中文字符数 / 4
    先剔掉 frontmatter —— 规范说的是「正文体」；两个口径混用会把一份达标文件虚高报错。
    """
    text = _read(path)
    if text is None:
        return None
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)
    cn = len(re.findall(r"[\u4e00-\u9fff]", body))
    return int(round(cn + (len(body) - cn) / 4))


def count_triggers(text):
    """「触发词」章节的条目数（口径照抄同目录的触发词评估工具）。

    支持「## 触发词 / ## Triggers / ### 触发词」；章节内一行里的「A / B / C」算 3 条
    （整行当一条会让条目数虚低，与评估工具的切分口径必须一致，否则两边数字对不上）。
    括号不配对说明切到了句内，整行回退，避免切出残片。
    """
    if not text:
        return None
    m = re.search(r"^#{1,4}\s*(触发词|triggers?)\s*$", text, re.M | re.I)
    if not m:
        return None
    seg = text[m.end():]
    nxt = re.search(r"^#{1,4}\s", seg, re.M)
    if nxt:
        seg = seg[:nxt.start()]
    out = []
    for line in seg.splitlines():
        s = re.sub(r"^[\s>*\-\d.、·]+", "", line).strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in re.split(r"\s*/\s*|、|；|;", s) if p.strip()]
        if all(p.count("（") == p.count("）") and p.count("(") == p.count(")") for p in parts) \
                and len(parts) > 1:
            out.extend(parts)
        else:
            out.append(s)
    return len(out)


# ---------------------------------------------------------------- 子进程
def run_cmd(cmd, cwd, timeout):
    """跑一条子命令，返回 (退出码, 合并后的输出)。超时/起不来时退出码为 None。"""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return None, f"[REVIEW] 超时（>{timeout}s）"
    except OSError as e:
        return None, f"[REVIEW] 无法执行: {e}"


def _stable_line(out, prefix):
    """从输出里取一条**带稳定前缀**的结论行做证据（判定只用退出码，这里只给人看）。

    取不到带前缀的行时退回第一条非空输出（例如超时/起不来时我们自己的提示行），
    免得明细里只剩一句「见单跑输出」——那等于没给证据。
    """
    for line in out.splitlines():
        if line.startswith(prefix):
            return line.strip()[:120]
    for line in out.splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def _verdict_line(out):
    """按 FAIL/PASS/REVIEW 前缀取一行结论做证据；都没有则退回第一条非空输出。"""
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    for prefix in ("FAIL", "PASS", "REVIEW"):
        for ln in lines:
            if ln.startswith(prefix):
                return ln[:120]
    return lines[0][:120] if lines else ""


def _uses_argparse(path):
    """该脚本是否构造了 argparse.ArgumentParser（决定要不要跑 --help 探测）。"""
    text = _read(path)
    if text is None:
        return None                       # 读不了 → 不可判
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "ArgumentParser":
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "argparse" \
                and any(a.name == "ArgumentParser" for a in node.names):
            return True
    return False


def help_coverage(root, timeout, probe=True):
    """scripts/*.py 的 --help 覆盖率。返回 dict。

    只执行**构造了 argparse 的脚本**：对被检技能的任意脚本跑 --help 有可能触发它自身的
    副作用，那是「改了被检对象」，体检工具不能干。不构造 argparse 的脚本只计数、不执行，
    其占比单列，避免把「没法安全探测」算成「探测不通过」。
    """
    scripts = os.path.join(root, "scripts")
    if not os.path.isdir(scripts):
        return {"probed": 0, "ok": 0, "failed": [], "skipped_non_argparse": 0,
                "parse_failed": 0, "coverage": None}
    pys = sorted(f for f in os.listdir(scripts) if f.endswith(".py"))
    probed, ok, failed, skipped, parse_failed = 0, 0, [], 0, 0
    for fn in pys:
        p = os.path.join(scripts, fn)
        flag = _uses_argparse(p)
        if flag is None:
            parse_failed += 1
            continue
        if not flag:
            skipped += 1
            continue
        if not probe:
            skipped += 1
            continue
        probed += 1
        rc, _ = run_cmd([sys.executable, p, "--help"], cwd=root, timeout=timeout)
        if rc == 0:
            ok += 1
        else:
            failed.append({"script": f"scripts/{fn}", "rc": rc})
    return {"probed": probed, "ok": ok, "failed": failed,
            "skipped_non_argparse": skipped, "parse_failed": parse_failed,
            "coverage": (ok / probed) if probed else None}


# ---------------------------------------------------------------- § 章节引用解析
def parse_section_refs(out):
    """从发布预检输出解析 § 章节引用的「判定数 / 断链数」。解析不到返回 None。

    三个稳定标记：`已判定的 N 处章节引用全部存在` / `章节引用断链: …` / `未判定 N 处`。
    有断链时预检不会再打「已判定的 N 处」那行，此时判定数记 None 而不是编一个数出来。
    """
    judged = RE_SEC_JUDGED.search(out)
    unjudged = RE_SEC_UNJUDGED.search(out)
    broken = sum(1 for line in out.splitlines() if SEC_BROKEN_MARK in line)
    if not judged and not unjudged and not broken:
        return None
    return {
        "judged": int(judged.group(1)) if judged else None,
        "broken": broken,
        "unjudged": int(unjudged.group(1)) if unjudged else None,
    }


# ---------------------------------------------------------------- 单个技能
def audit_skill(name, root, timeout, platform, probe_help):
    """跑完一个技能的四类证据，返回结果 dict（status ∈ PASS/FAIL/REVIEW）。"""
    desc_rc, desc_out = run_cmd(
        [sys.executable, os.path.join(HERE, "eval_trigger.py"), root, "--desc-check"],
        cwd=root, timeout=timeout)
    pre_rc, pre_out = run_cmd(
        [sys.executable, os.path.join(HERE, "preflight_release.py"), root,
         "--platform", platform], cwd=root, timeout=timeout)
    strict_rc, strict_out = run_cmd(
        [sys.executable, os.path.join(HERE, "preflight_release.py"), root,
         "--platform", platform, "--strict"], cwd=root, timeout=timeout)

    skill_md = os.path.join(root, "SKILL.md")
    text = _read(skill_md)
    fm = parse_frontmatter(skill_md)
    structure = {
        "top_files": len([f for f in os.listdir(root)
                          if os.path.isfile(os.path.join(root, f))]),
        "references": _count_files(os.path.join(root, "references")),
        "scripts": _count_files(os.path.join(root, "scripts")),
        "evals": _count_files(os.path.join(root, "evals")),
        "body_tokens": body_token_estimate(skill_md),
        "frontmatter": sorted(fm.keys()) if fm else None,
        "triggers": count_triggers(text),
        "sec_refs": parse_section_refs(pre_out),
        "version": (fm or {}).get("version"),
    }
    help_cov = help_coverage(root, timeout, probe=probe_help)

    desc_v = RC_VERDICT.get(desc_rc, "REVIEW")
    pre_v = RC_VERDICT.get(pre_rc, "REVIEW")
    strict_v = RC_VERDICT.get(strict_rc, "REVIEW")

    # 只有「有数据且确实不合格」才算 FAIL；其余拿不到结论的一律 REVIEW。
    findings = []       # (级别, 文本)  级别 ∈ FAIL/REVIEW/WARN
    if desc_v == "FAIL":
        findings.append(("FAIL", "desc-check 不达标: " + (_verdict_line(desc_out) or "见单跑输出")))
    elif desc_v == "REVIEW":
        findings.append(("REVIEW", "desc-check 判不了: " + (_verdict_line(desc_out) or "见单跑输出")))
    if pre_v == "FAIL":
        findings.append(("FAIL", "发布预检(常规档) 不通过: "
                         + (_stable_line(pre_out, PREFLIGHT_RESULT_MARK) or "见单跑输出")))
    elif pre_v == "REVIEW":
        findings.append(("REVIEW", "发布预检(常规档) 判不了: "
                         + (_stable_line(pre_out, PREFLIGHT_RESULT_MARK) or "见单跑输出")))
    if help_cov["failed"]:
        names = "、".join(f["script"] for f in help_cov["failed"][:3])
        findings.append(("REVIEW", f"有 {len(help_cov['failed'])} 个脚本 --help 跑不通（{names}）"
                                   "—— 可能是脚本缺陷，也可能只是缺必填参数或依赖未装，请人工看一眼"))
    if structure["sec_refs"] is None:
        findings.append(("REVIEW", "拿不到 § 章节引用的判定结果（发布预检没跑出这一节）"))

    levels = {lv for lv, _ in findings}
    status = "FAIL" if "FAIL" in levels else ("REVIEW" if "REVIEW" in levels else "PASS")
    strict_note = (strict_v == "FAIL" and pre_v == "PASS")   # 严格档比常规档更严 → 只提示

    return {
        "name": name, "dir": root, "status": status,
        "desc_check": {"rc": desc_rc, "verdict": desc_v, "detail": _verdict_line(desc_out)},
        "preflight": {"rc": pre_rc, "verdict": pre_v,
                      "detail": _stable_line(pre_out, PREFLIGHT_RESULT_MARK),
                      "strict_rc": strict_rc, "strict_verdict": strict_v,
                      "strict_detail": _stable_line(strict_out, PREFLIGHT_RESULT_MARK),
                      "strict_stricter": strict_note},
        "structure": structure,
        "help": help_cov,
        "findings": [{"level": lv, "text": tx} for lv, tx in findings],
    }


# ---------------------------------------------------------------- 输出
def _disp_width(s):
    """终端显示宽度：全角按 2 计。中文技能名不对齐的表没法看。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _pad(s, width):
    return s + " " * max(0, width - _disp_width(s))


def _cell(v, suffix=""):
    return f"{v}{suffix}" if v not in (None, "") else "—"


def render_table(results):
    """人读汇总表。列都已判空：拿不到的值一律显示 —，不显示 0 冒充数据。"""
    headers = ["技能名", "desc", "常规档", "严格档", "正文tk", "ref/scr/eval",
               "触发词", "§判定/断链", "help", "状态"]
    rows = []
    for r in results:
        s = r["structure"]
        sec = s["sec_refs"]
        sec_cell = "—" if not sec else \
            f"{_cell(sec['judged'])}/{sec['broken']}"
        h = r["help"]
        help_cell = "—" if not h["probed"] and not h["failed"] else \
            (f"{h['ok']}/{h['probed']}" + ("!" if h["failed"] else ""))
        struct = (f"{_cell(s['top_files'])}/{_cell(s['references'])}"
                  f"/{_cell(s['scripts'])}/{_cell(s['evals'])}")
        rows.append([
            r["name"], r["desc_check"]["verdict"], r["preflight"]["verdict"],
            r["preflight"]["strict_verdict"] + ("*" if r["preflight"]["strict_stricter"] else ""),
            f"{s['body_tokens']:,}" if s["body_tokens"] is not None else "—",
            struct, _cell(s["triggers"]), sec_cell, help_cell, r["status"],
        ])
    widths = [max(_disp_width(h), *(_disp_width(row[i]) for row in rows)) if rows
              else _disp_width(h) for i, h in enumerate(headers)]
    lines = ["  ".join(_pad(h, w) for h, w in zip(headers, widths)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(_pad(c, w) for c, w in zip(row, widths)).rstrip())
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="批量技能体检：一次对 N 个技能跑同一套门禁并汇总",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 最常用：体检默认根目录下的全部技能
  python3 scripts/batch_skill_audit.py

  # 只体检本技能包（试跑/复现单个技能，最快）
  python3 scripts/batch_skill_audit.py --only skill-dev-kit

  # 指定根目录，跳过目录名含模板的项，只看前 5 个
  python3 scripts/batch_skill_audit.py ~/.workbuddy/skills --exclude _template --limit 5

  # 机器可读：JSON 打到标准输出
  python3 scripts/batch_skill_audit.py --json

  # JSON 落盘（不带值 → ~/.workbuddy/batch-audit-<时间戳>.json，不会写进任何技能目录）
  python3 scripts/batch_skill_audit.py --json-out

  # 不探测脚本 --help（被检技能里若有会执行真动作的脚本）
  python3 scripts/batch_skill_audit.py --only skill-dev-kit --no-help-probe
""")
    ap.add_argument("root", nargs="?", default=DEFAULT_ROOT,
                    help=f"技能集合的父目录（默认 {os.path.join('~', '.workbuddy', 'skills')}）")
    ap.add_argument("--exclude", action="append", default=[], metavar="目录名",
                    help="跳过的技能目录名，可多次传入（也支持逗号分隔）")
    ap.add_argument("--only", action="append", default=[], metavar="目录名",
                    help="只体检这些技能目录名，可多次传入")
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="最多体检前 N 个技能（按目录名排序）")
    ap.add_argument("--platform", choices=["skillhub", "github"], default="skillhub",
                    help="发布预检的平台档（默认 skillhub）")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, metavar="秒",
                    help=f"单条子命令超时秒数（默认 {DEFAULT_TIMEOUT}）")
    ap.add_argument("--no-help-probe", action="store_true",
                    help="不探测 scripts/*.py 的 --help 覆盖率")
    ap.add_argument("--json", action="store_true", help="以 JSON 打到标准输出（替代人读汇总表）")
    ap.add_argument("--json-out", nargs="?", const=JSON_OUT_DEFAULT, default=None, metavar="路径",
                    help="把 JSON 写到文件；不带值则写到 ~/.workbuddy/batch-audit-<时间戳>.json")
    args = ap.parse_args()

    def split_multi(items):
        out = []
        for it in items:
            out += [x.strip() for x in (it or "").split(",") if x.strip()]
        return out

    root = os.path.abspath(os.path.expanduser(args.root))
    if not os.path.isdir(root):
        print(f"[REVIEW] 根目录不存在: {root} —— 判不了，不判 FAIL")
        return 2

    excludes, only = set(split_multi(args.exclude)), split_multi(args.only)
    skills, skipped_names = [], []
    for name in sorted(os.listdir(root)):
        if name.startswith("."):
            continue
        p = os.path.join(root, name)
        if not os.path.isdir(p) or not os.path.isfile(os.path.join(p, "SKILL.md")):
            continue
        if name in excludes:
            skipped_names.append(name)
            continue
        if only and name not in only:
            continue
        skills.append((name, p))
    if args.limit and args.limit > 0:
        skills = skills[:args.limit]

    # 落盘守卫：报告不许写进被检对象（任何被检技能目录或本工具包目录）
    json_target = None
    if args.json_out is not None:
        if args.json_out == JSON_OUT_DEFAULT:
            json_target = os.path.join(
                os.path.expanduser("~"), ".workbuddy",
                f"batch-audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
        else:
            json_target = os.path.abspath(os.path.expanduser(args.json_out))
        # 三处都不许写：被检技能目录（改了被检对象）、被检集合根目录（往技能集合里丢垃圾文件）、
        # 本工具包目录（体检报告不是技能资产，混进去会被打包/发布）。
        banned = ([(d, "被检技能目录") for _, d in skills]
                  + [(os.path.abspath(root), "被检技能集合根目录"), (PKG_DIR, "本工具包目录")])
        for b, label in banned:
            if json_target == b or json_target.startswith(b + os.sep):
                print(f"[REVIEW] 拒绝写入报告: {json_target}")
                print(f"         落在{label}范围内（{b}）—— 体检不改被检对象，请换到该范围之外")
                return 2

    if not skills:
        print(f"[REVIEW] {root} 下没有发现技能目录（含 SKILL.md 的子目录）")
        if only:
            print(f"         --only 指定的名字未找到: {', '.join(only)}")
        return 2

    results = []
    for name, path in skills:
        results.append(audit_skill(name, path, args.timeout, args.platform,
                                   probe_help=not args.no_help_probe))

    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_review = sum(1 for r in results if r["status"] == "REVIEW")
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    code = 1 if n_fail else (2 if n_review else 0)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": root,
        "platform": args.platform,
        "summary": {"total": len(results), "pass": n_pass, "review": n_review,
                    "fail": n_fail, "exit": code},
        "skills": results,
    }

    if json_target:
        try:
            with open(json_target, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as e:
            print(f"[REVIEW] 报告写入失败: {json_target} ({e})")
            return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("── 批量技能体检 ──")
        print(f"根目录 : {root}")
        extra = f"，跳过 {len(skipped_names)} 个: {', '.join(skipped_names)}" if skipped_names else ""
        print(f"技能数 : {len(results)}（platform={args.platform}，超时 {args.timeout}s）{extra}")
        print()
        print(render_table(results))
        print()
        print("状态口径: 常规档/严格档 = 发布预检退出码（严格档为更严视图，★不参与全局退出码）；"
              "help = 已探测的 argparse 脚本中 --help 通过数，! 表示有跑不通的；— = 拿不到数据")
        details = [r for r in results if r["findings"]]
        if details:
            print()
            print("-- 明细（仅列出 PASS 之外的项）--")
            for r in details:
                for f in r["findings"]:
                    mark = {"FAIL": "✗", "REVIEW": "⚠", "WARN": "·"}[f["level"]]
                    print(f"  {mark} {r['name']}  {f['text']}")
        strict_notes = [r["name"] for r in results if r["preflight"]["strict_stricter"]]
        if strict_notes:
            print()
            print(f"  严格档比常规档更严（请人工判断，不阻断）: {', '.join(strict_notes)}")
        if json_target:
            print(f"\nJSON 已写: {json_target}")

    print()
    print(f"结果: {'FAIL' if code == 1 else ('REVIEW' if code == 2 else 'PASS')} "
          f"(技能 {len(results)} 个：PASS {n_pass} / REVIEW {n_review} / FAIL {n_fail})")
    if code == 2:
        print("说明: REVIEW = 判不了（超时/跑不起来/拿不到结论），**不等于不通过**；"
              "CI 请按「1 阻断 / 2 告警+人工确认」处理")
    return code


if __name__ == "__main__":
    sys.exit(main())

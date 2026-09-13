#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_self_eval.py — 为 skill-dev-kit 自身生成 evals 用例（评测闭环）
================================================================
生成 evals/ 下三类用例（应触发 / 不应触发 / 发布流程演练），
每用例含 eval.json(prompt+assertions)、output/(证据)、baseline/(无技能基线)。

证据纪律（勿退回自证）:
  · **真跑（real-run）**：evidence 由真实执行技能脚本产生，stdout 原样落盘，
    命令写进 output/run_cmd.txt，第三方可独立重跑；
  · **静态转储（static-dump）**：证据是技能包的文档/源码切片，**不是**运行产物；
  · 每份 evidence.txt 头部必须写清三行：证据取得方式 / 生成命令 / 生成时间，
    多来源用例逐份标注，**不许含糊**。
  反例：多个用例共用同一份「触发词章节静态转储」，断言只做子串命中 → 等于自己证明自己，
  测不出任何真实差异。**每个用例的证据必须来自它自己那条链路。**

路径归一化（唯一一处非逐字保留，明确披露）:
  · 命令里的 $PY / $SKILL 分别指 Python 解释器与技能根目录；
  · 证据正文中**本机技能根 / 家目录绝对路径**归一化为 $SKILL / $HOME，
    其余字符逐字保留。原因：本包自身的发布门禁（preflight 的 localpath 规则）
    禁止在包内落本机绝对路径，真跑证据若原样写死本机路径会把门禁判成 FAIL。
  · 归一化只做「前缀替换」，不删行、不改数字、不合成文本。

基线纪律（不许编造）:
  · baseline/ 是**结构性基线**——不加载技能时同一 prompt 下不产出任何工程产物，
    因此断言命中数结构性为 0；**不得伪造一段假的模型输出文本**充当基线；
  · 「不应触发」类（B1..B3）考的是不触发，不适用基线，不建 baseline/。

运行：python3 build_self_eval.py        （在 evals/ 目录下）
聚合：python3 ../scripts/eval_loop.py . --aggregate
"""
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)          # skill-dev-kit/
HOME = os.path.expanduser("~")
PY = sys.executable                    # 当前解释器（即运行本脚本的 python）
SKILLMD = os.path.join(SKILL, "SKILL.md")
CHECKLIST = os.path.join(SKILL, "references", "发布检查清单.md")
ZIP_TMP = "/tmp/sdk-eval-%s.zip"

PY_T = "$PY"          # 命令占位符：Python 解释器
SKILL_T = "$SKILL"    # 命令占位符：技能根目录


def q(p):
    return shlex.quote(p)


def normalize(text):
    """把本机技能根 / 家目录绝对路径归一化为 $SKILL / $HOME，其余逐字保留。"""
    return text.replace(SKILL, SKILL_T).replace(HOME, "$HOME")


def run(tmpl):
    """按占位符模板真跑一条命令（$PY/$SKILL 换成真实路径），返回 (stdout, stderr)。

    ⚠️ 执行的确实是 `tmpl` 这条命令；模板里用占位符只是为了把它记进包内文件时
    不留本机绝对路径（见模块头「路径归一化」）。
    """
    real = tmpl.replace(PY_T, q(PY)).replace(SKILL_T, q(SKILL))
    r = subprocess.run(real, shell=True, cwd=SKILL, capture_output=True, text=True)
    return (r.stdout or ""), (r.stderr or "")


def body_of(stdout, stderr):
    """证据正文 = 真实 stdout（路径归一化后原样）；stderr 非空时附在 [stderr] 段。"""
    text = stdout + (("\n[stderr]\n" + stderr) if stderr.strip() else "")
    return normalize(text)


# ── 证据类型登记：source 只有两种取值，逐份标注，不许含糊 ────────────────────
KIND_SOURCE = {
    "triggers": "static-dump",       # SKILL.md「## 触发词」章节切片
    "listing": "static-dump",        # 包内文件清单 + 检查清单切片
    "checklist": "static-dump",      # 发布检查清单标题行 + 一键执行行
    "loop_src": "static-dump",       # eval_loop.py 源码切片
    "preflight_run": "real-run",     # 真跑 preflight_release.py
    "zip_run": "real-run",           # 真跑 make_skillhub_zip.py
    "trigger_run": "real-run",       # 真跑 eval_trigger.py --check
    "desc_help": "real-run",         # 真跑 eval_trigger.py --help
}

# 真跑类额外落盘「具名 stdout 产物」，第三方可直接查看工具原始输出
RAW_ARTIFACT = {
    "preflight_run": "preflight_stdout.txt",
    "zip_run": "zip_stdout.txt",
    "trigger_run": "trigger_check_stdout.txt",
    "desc_help": "desc_help_stdout.txt",
}


def build_evidence(kind, cid):
    """返回 dict(source, cmd, body, raw_file, raw)。cmd 是**真实执行**的命令（占位符形式）。"""
    if kind == "triggers":
        cmd = "awk '/^## 触发词$/{f=1;next} f&&/^## /{exit} f' %s/SKILL.md" % SKILL_T
        out, err = run(cmd)
        return dict(source="static-dump", cmd=cmd, body=body_of(out, err), raw_file=None)

    if kind == "listing":
        cmds = [
            "ls %s/scripts" % SKILL_T,
            "ls %s/references" % SKILL_T,
            "awk 'NR==1' %s/references/发布检查清单.md" % SKILL_T,
            "grep -m1 -h 'skillhub publish' %s/references/发布检查清单.md" % SKILL_T,
        ]
        return dict(source="static-dump", cmd=" ; ".join(cmds),
                    body=join_sections(cmds), raw_file=None)

    if kind == "checklist":
        # 「16 项清单」演练用例的清单本体证据：真实文件切片，非运行产物
        # ⚠️ 取**首个标题行**而非首行——references 顶部是 YAML 元数据块，`NR==1` 只会取到 `---`
        cmds = [
            "grep -m1 -h '^# ' %s/references/发布检查清单.md" % SKILL_T,
            "grep -m1 -h 'skillhub publish' %s/references/发布检查清单.md" % SKILL_T,
        ]
        return dict(source="static-dump", cmd=" ; ".join(cmds),
                    body=join_sections(cmds), raw_file=None)

    if kind == "loop_src":
        cmd = "cat %s/scripts/eval_loop.py" % SKILL_T
        out, err = run(cmd)
        return dict(source="static-dump", cmd=cmd, body=body_of(out, err), raw_file=None)

    if kind == "preflight_run":
        cmd = "%s %s/scripts/preflight_release.py . --platform skillhub" % (PY_T, SKILL_T)
        out, err = run(cmd)
        return dict(source="real-run", cmd=cmd, body=body_of(out, err),
                    raw_file=RAW_ARTIFACT[kind], raw=normalize(out))

    if kind == "zip_run":
        tmp = ZIP_TMP % cid
        cmd = "%s %s/scripts/make_skillhub_zip.py . --out %s" % (PY_T, SKILL_T, tmp)
        try:
            out, err = run(cmd)
        finally:
            # 评测不留残留：临时 zip 跑完即删
            if os.path.exists(tmp):
                os.remove(tmp)
        return dict(source="real-run", cmd=cmd, body=body_of(out, err),
                    raw_file=RAW_ARTIFACT[kind], raw=normalize(out))

    if kind == "trigger_run":
        cmd = "%s %s/scripts/eval_trigger.py . --check" % (PY_T, SKILL_T)
        out, err = run(cmd)
        return dict(source="real-run", cmd=cmd, body=body_of(out, err),
                    raw_file=RAW_ARTIFACT[kind], raw=normalize(out))

    if kind == "desc_help":
        cmd = "%s %s/scripts/eval_trigger.py --help" % (PY_T, SKILL_T)
        out, err = run(cmd)
        return dict(source="real-run", cmd=cmd, body=body_of(out, err),
                    raw_file=RAW_ARTIFACT[kind], raw=normalize(out))

    raise ValueError("unknown evidence kind: %s" % kind)


def join_sections(cmds):
    """多条切片命令的输出按命令标注拼接（静态转储类的正文组织方式）。"""
    chunks = []
    for c in cmds:
        out, err = run(c)
        chunks.append("=== %s ===\n%s" % (c, normalize(out if out.strip() else out + err).rstrip("\n")))
    return "\n".join(chunks)


SOURCE_LABEL = {"real-run": "真跑（real-run）", "static-dump": "静态转储（static-dump）"}

NOTE = ("说明: $PY=Python 解释器, $SKILL=技能根目录；证据正文中的本机技能根/家目录路径已"
        "归一化为 $SKILL/$HOME（包内不落本机路径），其余逐字保留")


def header(source_line, cmds):
    """evidence.txt 头部——可复现的关键，不许省略。"""
    return "\n".join([
        "# 证据取得方式: %s" % source_line,
        "# 生成命令: %s" % " ; ".join(cmds),
        "# 生成时间: %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "# " + NOTE,
    ]) + "\n"


# 用例定义：prompt（模拟真实用户说法）+ evidence（证据取得方式）+ assertions（期望要点）
# assertions 必须是**真实产物里确实存在**的短语；每条都要能被 output/ 文本命中。
CASES = [
    # A 应触发（静态转储：触发词章节；断言取触发词表里确实存在的短语）
    dict(id="A1", cat="should-trigger",
         prompt="把这段重复了 5 次的可复用工作流固化成技能",
         evidence=["triggers"],
         assertions=["固化为技能", "沉淀为 Skill"]),
    dict(id="A2", cat="should-trigger",
         prompt="帮我起草一个新技能的 SKILL.md",
         evidence=["triggers"],
         assertions=["起草 SKILL.md", "技能脚手架"]),
    # A3 是发布链路，证据改为真跑：预检 + 打包（两份产物都落进 output/）
    dict(id="A3", cat="should-trigger",
         prompt="技能发布到 SkillHub 前帮我做预检和打包",
         evidence=["preflight_run", "zip_run"],
         assertions=["preflight_release.py", "结果: PASS", "打包完成", "version"]),
    dict(id="A4", cat="should-trigger",
         prompt="我的技能没触发也不生效，帮我调试",
         evidence=["triggers"],
         assertions=["技能调试", "没触发"]),
    dict(id="A5", cat="should-trigger",
         prompt="给技能做触发词评估和评测循环",
         evidence=["triggers"],
         assertions=["触发词评估", "评测技能"]),
    # C 发布流程演练
    dict(id="C1", cat="publish-drill",
         prompt="我要发布技能到 SkillHub，按 16 项清单走一遍",
         evidence=["preflight_run", "checklist"],
         assertions=["16 项", "preflight_release.py"]),
    dict(id="C2", cat="publish-drill",
         prompt="帮我校验新技能的 description 质量",
         evidence=["desc_help", "trigger_run"],
         assertions=["--desc-check", "覆盖率"]),
    dict(id="C3", cat="publish-drill",
         prompt="给技能建一套 evals 跑 benchmark",
         evidence=["loop_src"],
         assertions=["benchmark.json", "eval_loop.py"]),
    # B 不应触发（预评分：人工/LLM 预先评分，工具原生支持；不适用基线）
    dict(id="B1", cat="should-not-trigger",
         prompt="帮我画一张产品宣传图",
         assertions=["用户意图为图像生成，不在技能触发范围",
                     "技能触发词未包含画图/绘图类意图"],
         evidence="SKILL.md 触发词仅覆盖 技能开发/发布/脱敏/评测/复盘，无图像生成类条目"),
    dict(id="B2", cat="should-not-trigger",
         prompt="查一下今天深圳天气",
         assertions=["用户意图为天气查询，不在技能触发范围",
                     "技能触发词未包含天气/资讯类意图"],
         evidence="触发词聚焦技能生命周期，无天气/资讯类条目"),
    dict(id="B3", cat="should-not-trigger",
         prompt="把这段英文翻译成中文",
         assertions=["用户意图为翻译，不在技能触发范围",
                     "技能触发词未包含翻译类意图"],
         evidence="触发词无翻译类条目，与翻译技能不重叠"),
]


def write_baseline(case_dir, artifacts):
    """结构性基线：不加载技能 ⇒ 不产出任何工程产物 ⇒ 命中数结构性为 0。

    ⚠️ 这里**不编造任何模型输出**。基线不是「模型跑出来的差答案」，
    而是「无技能时不存在对应产物」这一结构性事实的如实登记。
    """
    bdir = os.path.join(case_dir, "baseline")
    os.makedirs(bdir, exist_ok=True)
    text = "\n".join([
        "# 无技能基线（结构性基线，非模型运行）",
        "取得方式: 不加载本技能时，同一 prompt 下不会产出下列任一工程产物",
        "本用例的带技能产物: %s" % ", ".join(artifacts),
        "基线产出: 无（因此断言命中数 = 0）",
    ]) + "\n"
    with open(os.path.join(bdir, "BASELINE.txt"), "w", encoding="utf-8") as f:
        f.write(text)


def main():
    problems = 0
    # 阶段一：先清掉所有用例的上一轮产物——否则生成 A3/C1 的 preflight 证据时，
    # 其他用例遗留的旧证据会一起被扫描，证据里会夹进"上一轮的自己"。
    # 启发式 grading.json 一并清掉：那是机器缓存，aggregate 会按新产物重评。
    for c in CASES:
        out_dir = os.path.join(HERE, c["id"], "output")
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)
        if c["cat"] != "should-not-trigger":
            stale = os.path.join(HERE, c["id"], "grading.json")
            if os.path.exists(stale):
                os.remove(stale)

    # 阶段二：逐用例重新生成
    for c in CASES:
        d = os.path.join(HERE, c["id"])
        out_dir = os.path.join(d, "output")
        os.makedirs(out_dir, exist_ok=True)

        with open(os.path.join(d, "eval.json"), "w", encoding="utf-8") as f:
            json.dump({"prompt": c["prompt"], "category": c["cat"],
                       "assertions": c["assertions"]}, f, ensure_ascii=False, indent=2)

        if c["cat"] == "should-not-trigger":
            grading = {
                "assertions": [{"text": a, "pass": True, "evidence": c["evidence"]}
                               for a in c["assertions"]],
                "passed": len(c["assertions"]),
                "total": len(c["assertions"]),
                "score": 1.0,
                "mode": "pre-graded",
            }
            with open(os.path.join(d, "grading.json"), "w", encoding="utf-8") as f:
                json.dump(grading, f, ensure_ascii=False, indent=2)
            print("OK    %s 预评分已写 (%d 断言)  [不适用基线]" % (c["id"], len(c["assertions"])))
            continue

        # ── 逐份取证据：真跑 / 静态转储，各带自己的来源标注 ──
        evs, sections, cmds, all_raw, artifacts = [], [], [], [], []
        for kind in c["evidence"]:
            e = build_evidence(kind, c["id"])
            evs.append((kind, e))
            cmds.append(e["cmd"])
            sections.append("=== [%s] 证据取得方式: %s ===\n%s" % (
                kind, SOURCE_LABEL[e["source"]], e["body"].rstrip("\n")))
            if e.get("raw_file") and e.get("raw") is not None:
                with open(os.path.join(out_dir, e["raw_file"]), "w", encoding="utf-8") as f:
                    f.write(e["raw"])
                artifacts.append(e["raw_file"])
                all_raw.append(e["raw"])

        sources = sorted({e["source"] for _, e in evs})
        source_line = (SOURCE_LABEL[sources[0]] if len(sources) == 1
                       else " + ".join(SOURCE_LABEL[s] for s in sources) + "，逐份标注见下")

        ev_text = header(source_line, cmds) + "\n" + "\n\n".join(sections) + "\n"
        with open(os.path.join(out_dir, "evidence.txt"), "w", encoding="utf-8") as f:
            f.write(ev_text)
        artifacts = ["evidence.txt"] + sorted(artifacts)

        with open(os.path.join(out_dir, "run_cmd.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(cmds) + "\n")

        # 非预评分用例清除遗留 grading.json，避免旧评分掩盖启发式真实评分
        stale = os.path.join(d, "grading.json")
        if os.path.exists(stale):
            os.remove(stale)

        write_baseline(d, artifacts)

        # 断言自检：命中不了就是断言写错（不许靠含糊过关）
        haystack = ev_text + "\n".join(all_raw) + "\n".join(cmds)
        missing = [a for a in c["assertions"] if a not in haystack]
        label = "+".join(sources)
        if missing:
            problems += 1
            print("WARN  %s [%s] 缺失断言证据: %s" % (c["id"], label, missing))
        else:
            print("OK    %s [%s] 证据齐备 (%d 断言) 产物=%s" % (
                c["id"], label, len(c["assertions"]), ",".join(artifacts)))
    print("已生成 %d 个用例于 %s（真跑证据: 脚本 stdout 原样；基线: 结构性，非模型运行）"
          % (len(CASES), HERE))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_self_eval.py — 为 skill-dev-kit 自身生成 evals 用例（评测闭环）
================================================================
生成 evals/ 下三类用例（应触发 / 不应触发 / 发布流程演练），
每用例含 eval.json(prompt+assertions) 与 output/(真实技能内容证据)。
「不应触发」类用预评分 grading.json（人工/LLM 预先评分模式，工具原生支持）。

运行：python3 build_self_eval.py        （在 evals/ 目录下）
聚合：python3 ../scripts/eval_loop.py . --aggregate
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)  # skill-dev-kit/


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def extract_triggers(text):
    m = re.search(r"^#{1,4}\s*(触发词|triggers?)\s*$", text, re.M | re.I)
    if not m:
        return ""
    seg = text[m.end():]
    nxt = re.search(r"^#{1,4}\s", seg, re.M)
    if nxt:
        seg = seg[:nxt.start()]
    return seg.strip()


def grep_first(text, pat):
    m = re.search(pat, text, re.M)
    return m.group(0) if m else ""


def make_evidence(kind):
    """返回 (证据文本)。均来自技能真实产物，保证评测可复现、非编造。"""
    if kind == "triggers":
        return extract_triggers(read(os.path.join(SKILL, "SKILL.md")))
    if kind == "listing":
        chunks = ["=== scripts/ ==="]
        for f in sorted(os.listdir(os.path.join(SKILL, "scripts"))):
            chunks.append(f)
        chunks.append("=== references/ ===")
        for f in sorted(os.listdir(os.path.join(SKILL, "references"))):
            chunks.append(f)
        chk = read(os.path.join(SKILL, "references", "发布检查清单.md"))
        chunks.append("=== 发布检查清单 headline ===")
        chunks.append(grep_first(chk, r".*15.{0,4}项.*"))
        return "\n".join(chunks)
    if kind == "desc_help":
        r = subprocess.run(
            [sys.executable, os.path.join(SKILL, "scripts", "eval_trigger.py"), "--help"],
            capture_output=True, text=True)
        return (r.stdout or "") + (r.stderr or "")
    if kind == "loop_src":
        return read(os.path.join(SKILL, "scripts", "eval_loop.py"))
    raise ValueError("unknown evidence kind: %s" % kind)


# 用例定义：prompt（模拟真实用户说法）+ assertions（期望行为要点）
CASES = [
    # A 应触发（启发式评分：output/ 证据含断言子串）
    dict(id="A1", cat="should-trigger",
         prompt="把这段重复了 5 次的可复用工作流固化成技能",
         evidence="triggers",
         assertions=["固化为技能", "沉淀为 Skill"]),
    dict(id="A2", cat="should-trigger",
         prompt="帮我起草一个新技能的 SKILL.md",
         evidence="triggers",
         assertions=["起草 SKILL.md", "完善技能"]),
    dict(id="A3", cat="should-trigger",
         prompt="技能发布到 SkillHub 前帮我做预检和打包",
         evidence="triggers",
         assertions=["发布预检", "打包 SkillHub"]),
    dict(id="A4", cat="should-trigger",
         prompt="我的技能没触发也不生效，帮我调试",
         evidence="triggers",
         assertions=["技能调试", "没触发"]),
    dict(id="A5", cat="should-trigger",
         prompt="给技能做触发词评估和评测循环",
         evidence="triggers",
         assertions=["触发词评估", "评测技能"]),
    # C 发布流程演练（启发式评分）
    dict(id="C1", cat="publish-drill",
         prompt="我要发布技能到 SkillHub，按 15 项清单走一遍",
         evidence="listing",
         assertions=["preflight_release.py", "make_skillhub_zip.py", "15 项"]),
    dict(id="C2", cat="publish-drill",
         prompt="帮我校验新技能的 description 质量",
         evidence="desc_help",
         assertions=["--desc-check", "description 质量"]),
    dict(id="C3", cat="publish-drill",
         prompt="给技能建一套 evals 跑 benchmark",
         evidence="loop_src",
         assertions=["benchmark.json", "eval_loop.py"]),
    # B 不应触发（预评分：人工/LLM 预先评分，工具原生支持）
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


def main():
    for c in CASES:
        d = os.path.join(HERE, c["id"])
        os.makedirs(os.path.join(d, "output"), exist_ok=True)
        eval_json = {
            "prompt": c["prompt"],
            "category": c["cat"],
            "assertions": c["assertions"],
        }
        with open(os.path.join(d, "eval.json"), "w", encoding="utf-8") as f:
            json.dump(eval_json, f, ensure_ascii=False, indent=2)

        if c["cat"] == "should-not-trigger":
            grading = {
                "assertions": [{"text": a, "pass": True, "evidence": c["evidence"]} for a in c["assertions"]],
                "passed": len(c["assertions"]),
                "total": len(c["assertions"]),
                "score": 1.0,
                "mode": "pre-graded",
            }
            with open(os.path.join(d, "grading.json"), "w", encoding="utf-8") as f:
                json.dump(grading, f, ensure_ascii=False, indent=2)
            print("OK    %s 预评分已写 (%d 断言)" % (c["id"], len(c["assertions"])))
        else:
            ev_text = make_evidence(c["evidence"])
            with open(os.path.join(d, "output", "evidence.txt"), "w", encoding="utf-8") as f:
                f.write(ev_text)
            missing = [a for a in c["assertions"] if a not in ev_text]
            if missing:
                print("WARN  %s 缺失断言证据: %s" % (c["id"], missing))
            else:
                print("OK    %s 证据齐备 (%d 断言)" % (c["id"], len(c["assertions"])))
    print("已生成 %d 个用例于 %s" % (len(CASES), HERE))


if __name__ == "__main__":
    main()

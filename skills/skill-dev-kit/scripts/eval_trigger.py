#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_trigger.py — SKILL.md description 触发词评估工具
======================================================
对标 Anthropic skill-creator 的「触发词优化」：生成 should-trigger / should-not-trigger
评估集，并静态检查 SKILL.md 的触发词覆盖是否命中预期意图。

用法:
  python3 eval_trigger.py <技能目录> [--gen] [--check] [--desc-check] [--desc "文本"] [--count N] [--out evals.json]

  --gen        生成评估集模板（should/should-not 触发词清单，人工/LLM 填充后回读）
  --check      静态检查 SKILL.md 触发词覆盖率（默认动作，二者都省略时执行）
  --desc-check 静态校验 frontmatter description 本体质量（第三人称/动作动词/场景/无 how/排他边界）
  --desc TEXT  直接校验给定描述文本（配合 --desc-check，跳过读技能目录，用于快速试错）
  --count      生成评估集时每类条数（默认 10，--gen 时生效）
  --out        评估集输出文件（默认 <技能目录>/evals.json）

退出码: 0 = 达标(PASS)  1 = 不达标(FAIL)  2 = 需人工确认(REVIEW)

工作原理（check 模式）:
  1. 解析 SKILL.md 的「触发词」章节（## 触发词 或 ## Triggers）；
  2. 用字符串归一化（小写/去空白）比对预期意图清单是否被触发词覆盖；
  3. 未覆盖 → FAIL，提示补写触发词；覆盖率不足阈值 → REVIEW。

工作原理（desc-check 模式）:
  对 description 做 5 项静态校验（规则来源：方法论 §2.2，详见 references/description 编写方法论.md）：
  第三人称（无 我/本助手/I） / 含动作动词 / 含场景或文件类型 / 无 how 描述 / 含排他边界词。
  任一项不合格 → FAIL（退出码 1）。「Helps with documents」这类泛泛描述必 FAIL。

示例:
  python3 eval_trigger.py ./my-skill --gen --count 20      # 生成 20+20 评估集
  python3 eval_trigger.py ./my-skill --check               # 检查触发词覆盖
  python3 eval_trigger.py ./my-skill --desc-check          # 校验 description 质量
  python3 eval_trigger.py . --desc-check --desc "Helps with documents"  # FAIL 演示
"""
import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------- 触发词章节解析
def load_skill_text(skill_dir):
    for name in ("SKILL.md", "skill.md"):
        p = os.path.join(skill_dir, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return f.read(), p
    return None, None

def extract_triggers(text):
    """从 SKILL.md 提取「触发词」章节的条目列表。支持「## 触发词 / ## Triggers / ### 触发词」。"""
    m = re.search(r"^#{1,4}\s*(触发词|triggers?)\s*$", text, re.M | re.I)
    if not m:
        return []
    seg = text[m.end():]
    nxt = re.search(r"^#{1,4}\s", seg, re.M)
    if nxt:
        seg = seg[:nxt.start()]
    out = []
    for line in seg.splitlines():
        s = re.sub(r"^[\s>*\-\d.、·]+", "", line).strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out

def extract_frontmatter_description(text):
    m = re.search(r"^---\s*\n(.*?)\n---\s*$", text, re.S | re.M)
    if not m:
        return ""
    fm = m.group(1)
    d = re.search(r"^description:\s*(.*)$", fm, re.M)
    return d.group(1).strip().strip('"\'' ) if d else ""

# ---------------------------------------------------------------- 归一化比对
def norm(s):
    return re.sub(r"\s+", "", s).lower()

def coverage(triggers, intents):
    """返回 (覆盖的意图, 未覆盖的意图)。意图命中 = 任一触发词包含/被包含该意图关键词。"""
    tnorm = [norm(t) for t in triggers]
    hit, miss = [], []
    for it in intents:
        itn = norm(it)
        ok = any(itn and (itn in t or t in itn) for t in tnorm if t)
        (hit if ok else miss).append(it)
    return hit, miss

# ---------------------------------------------------------------- 评估集生成（--gen）
DEFAULT_INTENTS = [
    "固化为技能", "沉淀为 Skill", "起草 SKILL.md", "完善技能",
    "发布前检查", "发布预检", "脱敏预检", "打包 SkillHub",
    "创建 GitHub tag 保护", "双平台发布", "市场调研", "竞品调研",
    "技术选型", "可靠性设计", "错误处理", "Token 降本",
    "技能调试", "评测技能", "触发词评估", "技能复盘",
]
DEFAULT_NEGATIVES = [
    "写一个函数", "画一张图", "查一下天气", "帮我读这个文件",
    "总结一下这段文字", "发一封邮件", "运行单元测试", "查看 git 日志",
    "今天有什么新闻", "翻译这句话",
]

def gen_eval_set(count):
    should = DEFAULT_INTENTS[:count] if count <= len(DEFAULT_INTENTS) else DEFAULT_INTENTS
    should_not = DEFAULT_NEGATIVES[:count] if count <= len(DEFAULT_NEGATIVES) else DEFAULT_NEGATIVES
    return {
        "should_trigger": should,
        "should_not_trigger": should_not,
        "_note": "请人工/LLM 审阅扩充：should_trigger=应触发本技能的真实用户说法；should_not_trigger=不应触发的邻近说法。",
    }

# ---------------------------------------------------------------- description 质量校验（--desc-check）
# 规则来源：方法论 §2.2 description 四策略 + 三条硬性规则（详见 references/description 编写方法论.md）
FIRST_PERSON = [
    re.compile(r"我(?:们|的|会|可以|帮|能|将|想|要|希望|已经|正在)?"),
    re.compile(r"本人|本助手"),
    re.compile(r"\b(?:I|I'm|we|we're|our|my|mine|us)\b", re.I),
]
ACTION_VERBS_CN = [
    "提取", "创建", "生成", "转换", "解析", "校验", "打包", "发布", "审查", "查询", "扫描",
    "评估", "检测", "迁移", "导入", "导出", "绘制", "标注", "固化", "起草", "完善", "沉淀",
    "上传", "下载", "编辑", "格式化", "分析", "识别", "合成", "合并", "拆分", "清理", "去重",
    "回测", "模拟", "监控", "推送", "分类", "摘要", "翻译", "检索", "筛选", "统计", "上报",
    "构建", "部署", "管理", "追踪", "备份", "恢复", "测试", "调试", "获取", "抓取", "聚合",
]
ACTION_VERBS_EN = re.compile(
    r"\b(?:extract|create|generate|convert|parse|validate|build|publish|review|check|scan|"
    r"evaluate|analy[sz]e|download|upload|export|import|migrate|query|search|format|edit|"
    r"summari[sz]e|classif(?:y|ies)|translate|detect|monitor|annotate|plot|render|fetch|"
    r"merge|dedupe|organi[sz]e|track|schedule|backup|restore|test|debug|deploy|manage|"
    r"aggregate|clean|normalize)\b", re.I)
SCENE_PATTERNS = [
    re.compile(r"\.(?:pdf|docx|xlsx|pptx|ppt|zip|json|csv|md|txt|html|yaml|yml|xml|png|jpg|jpeg|mp4|enex|kml|geojson|doc|xls)\b", re.I),
    re.compile(r"\b(?:pdf|word|excel|ppt|powerpoint|zip|json|csv|markdown|skill|api|sql|kline|yaml|xml)\b", re.I),
]
SCENE_CN = [
    "技能", "工作流", "报告", "合同", "体检", "健康", "企业", "工商", "股票", "地图", "瓦片",
    "标注", "隐私", "脱敏", "邮件", "简历", "发票", "知识库", "数据库", "接口", "论文", "公文",
    "会议纪要", "代码", "仓库", "日志", "报表", "图表", "视频", "音频", "录音", "网盘",
    "公园", "园区", "道路", "建筑", "化验单", "账单", "订单", "库存", "客户", "商品",
    "K 线", "研究", "尽调", "投资", "市场", "竞品", "清单", "模板",
]
HOW_SIGNALS = [
    re.compile(r"如何|怎么做|怎样|实现方式|实现方法|使用步骤|操作步骤|具体步骤|详细流程|操作流程|通过以下|步骤说明|做法："),
    re.compile(r"\bhow\s+to\b|\bstep[- ]by[- ]step\b|\bsteps?\s+to\b|\bprocedure\b", re.I),
]
BOUNDARY_SIGNALS = [
    re.compile(r"不用于|不做|不适用|不做什么|不负责|不可用于|不得|仅用于|仅限|仅当|仅支持|"
               r"只用于|专门用于|专用于|专为|时使用|而非|不含|不涉及|排除|除外|边界|红线|"
               r"何时不用|不需要|仅|当.{0,60}时"),
    re.compile(r"\bonly\s+for\b|\bnot\s+for\b|\bwhen\b|\bexclusive\b|\bspecifically\s+for\b|"
               r"\bdedicated\s+to\b|\brather\s+than\b|\bunlike\b|\bnever\b", re.I),
]


def run_desc_check(desc):
    """description 5 项静态质量校验。返回退出码（0=PASS / 1=FAIL）。"""
    checks = []

    bad = [p.pattern for p in FIRST_PERSON if p.search(desc)]
    checks.append(("第三人称（无 我/本助手/I）", not bad,
                   "命中第一人称: %s" % "、".join(bad) if bad else ""))

    has_verb = any(v in desc for v in ACTION_VERBS_CN) or bool(ACTION_VERBS_EN.search(desc))
    checks.append(("含动作动词", has_verb,
                   "未找到动作动词（如 提取/生成/校验/extract/create）" if not has_verb else ""))

    has_scene = any(p.search(desc) for p in SCENE_PATTERNS) or any(k in desc for k in SCENE_CN)
    checks.append(("含场景/文件类型", has_scene,
                   "未找到具体场景或文件类型（如 pdf/zip/技能/体检报告）" if not has_scene else ""))

    how = [p.pattern for p in HOW_SIGNALS if p.search(desc)]
    checks.append(("无 how 描述", not how,
                   "疑似描述做法: %s（how 应留给正文）" % "、".join(how) if how else ""))

    has_boundary = any(p.search(desc) for p in BOUNDARY_SIGNALS)
    checks.append(("含排他边界词", has_boundary,
                   "缺少排他边界（何时不用/不做什么/仅用于）" if not has_boundary else ""))

    print("description : %s" % (desc[:60] + ("…" if len(desc) > 60 else "")))
    fails = 0
    for name, ok, detail in checks:
        print("  %s %s%s" % ("✓" if ok else "✗", name, "（%s）" % detail if detail else ""))
        if not ok:
            fails += 1
    if fails:
        print("FAIL  description 有 %d 项不合格，请对照 references/description 编写方法论.md 修订" % fails)
        return 1
    print("PASS  description 质量达标（5/5）")
    return 0


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="SKILL.md description 触发词评估工具")
    ap.add_argument("skill_dir", nargs="?", help="技能目录（--desc 模式可省略）")
    ap.add_argument("--gen", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--desc-check", action="store_true", help="校验 frontmatter description 质量")
    ap.add_argument("--desc", default=None, help="直接校验给定描述文本（配合 --desc-check）")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--out", default=None)
    ap.add_argument("--threshold", type=float, default=0.7, help="触发覆盖率阈值（默认 0.7）")
    args = ap.parse_args()

    # desc-check 模式：优先于 --gen / 默认 check
    if args.desc_check or args.desc is not None:
        desc = args.desc
        if desc is None:
            if not args.skill_dir or not os.path.isdir(os.path.abspath(args.skill_dir)):
                print("FAIL  目录不存在: %s" % args.skill_dir)
                return 1
            text, path = load_skill_text(os.path.abspath(args.skill_dir))
            if not text:
                print("FAIL  未找到 SKILL.md: %s" % args.skill_dir)
                return 1
            desc = extract_frontmatter_description(text)
            if not desc:
                print("FAIL  frontmatter 缺少 description 字段: %s" % path)
                return 1
        return run_desc_check(desc)

    if not args.skill_dir:
        ap.error("缺少技能目录参数（或使用 --desc-check --desc <文本>）")
    skill_dir = os.path.abspath(args.skill_dir)
    if not os.path.isdir(skill_dir):
        print("FAIL  目录不存在: %s" % skill_dir)
        return 1
    out = args.out or os.path.join(skill_dir, "evals.json")

    if args.gen:
        data = gen_eval_set(args.count)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("PASS  评估集已生成: %s（should %d / should-not %d）" % (
            out, len(data["should_trigger"]), len(data["should_not_trigger"])))
        return 0

    # check 模式（默认）
    text, path = load_skill_text(skill_dir)
    if not text:
        print("FAIL  未找到 SKILL.md: %s" % skill_dir)
        return 1
    triggers = extract_triggers(text)
    desc = extract_frontmatter_description(text)
    intents = DEFAULT_INTENTS
    hit, miss = coverage(triggers, intents)
    cov = len(hit) / len(intents) if intents else 1.0

    print("SKILL.md : %s" % path)
    print("触发词数 : %d" % len(triggers))
    print("description: %s" % (desc[:80] + ("…" if len(desc) > 80 else "")))
    print("预期意图 : %d，命中 %d，覆盖率 %.0f%%（阈值 %.0f%%）" % (len(intents), len(hit), cov*100, args.threshold*100))
    for m in miss:
        print("  MISS   未覆盖意图: %s" % m)
    if miss and cov < args.threshold:
        print("FAIL  覆盖率不足且有未覆盖意图，请补写触发词后重跑")
        return 1
    if miss:
        print("REVIEW 覆盖率达标但仍有 %d 个未覆盖意图，建议人工确认是否纳入触发词" % len(miss))
        return 2
    print("PASS  触发词覆盖达标")
    print("提示  description 质量校验请单独跑: eval_trigger.py <技能目录> --desc-check")
    return 0

if __name__ == "__main__":
    sys.exit(main())

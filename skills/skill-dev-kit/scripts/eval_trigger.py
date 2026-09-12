#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_trigger.py — SKILL.md description 触发词评估工具
======================================================
对标官方规范的「触发词优化」：生成 should-trigger / should-not-trigger
评估集，并静态检查 SKILL.md 的触发词覆盖是否命中预期意图。

用法:
  python3 eval_trigger.py <技能目录> [--gen] [--check] [--desc-check] [--desc "文本"]
                          [--intents FILE] [--scene-words FILE] [--from-description]
                          [--holdout 0.4] [--reps 3]
                          [--count N] [--out evals.json]

  --gen          生成评估集模板（should/should-not 触发词清单，人工/LLM 填充后回读）
  --check        静态检查 SKILL.md 触发词覆盖率（默认动作，二者都省略时执行）
  --desc-check   静态校验 frontmatter description 本体质量
                 （FAIL: 自称构式/动作动词；WARN: 场景/无 how/排他边界/无流程摘要）
  --desc TEXT    直接校验给定描述文本（配合 --desc-check，跳过读技能目录，用于快速试错）
  --holdout FLOAT
                 留出集比例（默认 0 = 关闭；**推荐 0.4**）。开启后按固定种子确定性切分
                 意图清单为训练集/留出集，两侧分别报覆盖率，**判定以留出集覆盖率为准**
                 —— 这是防过拟合的关键：在训练集上调到满分、换个说法就不行，等于没改。
                 留出集不足 2 条时降级 REVIEW，不判 FAIL（数据残缺不等于不合格）。
  --reps INT     重复独立留出切分的次数（默认 1；**推荐 3**）。>1 时输出留出集覆盖率的
                 均值 ± 标准差；标准差偏大 = 评估集切分不稳，对策是**扩量**，不是继续调措辞。
                 ⚠️ 静态工具的口径：它衡量的是「评估集切分稳定性」，**不是**模型随机性。
                 「同一条 query 跑 N 次求稳定触发率」需要真实调用通道，当前未实现。
  --intents FILE 外部意图清单（JSON: {"should_trigger":[...]} 或 .txt 每行一条）
                 —— 判定基准必须由目标技能自己提供，工具不替它编
  --from-description
                 覆盖率按 frontmatter description 口径评测（**平台真实行为**：自动发现
                 只看 description，正文触发词章节平台不加载）。不加此开关时按正文
                 「触发词」章节口径（字面口径，用于检查触发词覆盖完整性）。
  --scene-words FILE
                 目标技能域内的场景词清单（JSON 数组或 .txt 每行一条）；
                 不给时，未识别到场景只出 REVIEW 提示，不判不合格
  --strict       --desc-check 时把 WARN 级项也计入失败
  --count        生成评估集时每类条数（默认 10，--gen 时生效）
  --out          评估集输出文件（默认 <技能目录>/evals.json）

退出码: 0 = 达标(PASS)  1 = 不达标(FAIL)  2 = 需人工确认(REVIEW)

工作原理（check 模式）:
  1. 触发来源二选一（--from-description 给出时）：
     - description 口径：整段 frontmatter description 作为一个判定源（平台口径）；
     - 正文口径：解析「触发词」章节（## 触发词 / ## Triggers / ### 触发词）。
  2. 取意图清单，优先级：--intents > <技能目录>/evals/trigger_eval.json > 无（→ REVIEW）；
  3. 比对意图是否被触发源覆盖，覆盖率不足阈值 → REVIEW(2)。

  ⚠️ 两个口径回答的是不同问题，不共用一把尺：正文口径回答「触发词写全了没」，
  description 口径回答「平台能不能把用户说法路由到这个技能」。只跑正文口径会
  高估可发现性（实测：字面 40% 的技能语义实际触发 ≥90%，反之亦然）。
  缺「触发词」章节时不再静默 REVIEW——会明确提示该技能可发现性全靠 description，
  请加 --from-description。

工作原理（desc-check 模式）:
  对 description 做 6 项静态校验（规则来源：详见 references/SKILL.md 编写规范.md §七）：
  FAIL 级 2 项：自称构式（我可以/本助手/I can…）/ 无动作动词 —— 命中即不合格；
  WARN 级 4 项：缺场景或文件类型 / 含 how 描述 / 缺排他边界 / 含流程摘要
                —— 默认只提示，--strict 时才计入失败。
  「含流程摘要」= 出现「先…再…」「第 N 步」「step 1/2/3」或两个以上的箭头链（A → B → C）：
  description 一旦把流程概括出来，agent 就会走这条捷径、不再读正文，技能退化成一行 prompt。
  用户口语触发词里的「我的订阅 / 我要导出」属正确的关键词罗列，不算自称、也不算流程摘要。
  「Helps with documents」这类泛泛描述必 FAIL。

示例:
  python3 eval_trigger.py ./my-skill --gen --count 20      # 生成 20+20 评估集
  python3 eval_trigger.py ./my-skill --check               # 检查触发词覆盖
  python3 eval_trigger.py ./my-skill --desc-check          # 校验 description 质量
  python3 eval_trigger.py . --desc-check --desc "Helps with documents"  # FAIL 演示
"""
import argparse
import json
import os
import random
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

def _split_trigger_line(s):
    """把一行里的同义说法拆成独立触发词：「A / B / C」→ 3 条。

    整行当一个条目会让宽松匹配失效（长整行不可能成为用户说法的子串），
    只能靠"用户说法恰好是整行的子串"命中，粒度是错的。

    括号不配对说明切到了句内，整行回退，避免切出「技术选型（该不该做成技能」这种残片。
    """
    parts = [p.strip() for p in re.split(r"\s*/\s*|、|；|;", s) if p.strip()]
    for p in parts:
        if p.count("（") != p.count("）") or p.count("(") != p.count(")"):
            return [s]
    return parts if len(parts) > 1 else [s]

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
            out.extend(_split_trigger_line(s))
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

def coverage(triggers, intents, min_trigger_len=3):
    """返回 (覆盖的意图, 未覆盖的意图)。

    命中判据（两个方向，第二个带长度门限）:
      强命中 —— 意图整句被测触发词包含（`itn in t`）：触发词里确实写了这句说法。
      弱命中 —— 触发词是意图的实质子串（`t in itn`）且 len(t) >= min_trigger_len。

    为什么要长度门限：没有它，一个 2 字泛词「发布」会被判成覆盖了
    「发布前检查 / 发布预检 / 双平台发布」3 条具体意图，覆盖率虚高到 100%，
    真正缺的触发词反而看不出来。门限值可用 --min-trigger-len 覆盖。

    ⚠️ 反模式：判定规则不该写死成本技能的偏好。min_trigger_len 是长度约束，
    不是词表，且可参数化——词表才会把本技能语境强加给别的技能。
    """
    tnorm = [norm(t) for t in triggers if t]
    hit, miss = [], []
    for it in intents:
        itn = norm(it)
        if not itn:
            miss.append(it)
            continue
        strong = any(itn in t for t in tnorm)
        weak = any(len(t) >= min_trigger_len and t in itn for t in tnorm)
        (hit if (strong or weak) else miss).append(it)
    return hit, miss

# ---------------------------------------------------------------- 评估集生成（--gen）
# ⚠️ 这两份清单只是「模板素材」，供 --gen 生成骨架后由人工替换。
#    它们取自本技能的语境，**不得用于判定其他技能**（历史缺陷：拿这 20 条去测 8 个
#    技能，7 个判 0%，工具被绕过）。--check 判定只认 --intents 或目标技能自带的
#    evals/trigger_eval.json；两者都没有时输出 REVIEW(2)，不判 FAIL。
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
        "_note": "⚠️ 这是模板示例，取自本工具自身的语境，不是你的评估集。"
                 "必须整体替换为「你技能域内的真实用户说法」，否则测出来的是本工具、不是你的技能。"
                 "填好后另存为 <技能目录>/evals/trigger_eval.json，--check 会自动读取它。",
    }

# ---------------------------------------------------------------- description 质量校验（--desc-check）
# 规则来源：description 五策略 + 三条硬性规则（详见 references/SKILL.md 编写规范.md §七）
# ⚠️ 只匹配「自称构式」——描述里技能在说自己。
#    用户口语触发词里的「我的订阅 / 我要导出 / 我想查余额」是标准的关键词罗列写法，
#    曾经被这条规则判违规：**按规范写出的内容被规范自己的检查器判为违反规范**。
FIRST_PERSON = [
    re.compile(r"我(?:们)?(?:会|可以|能|能够|将|来|帮(?:你|您)?|负责|提供|支持|用于|替你)"),
    re.compile(r"本(?:助手|技能|工具|插件|扩展)"),
    re.compile(r"本人(?:会|可以|能|提供|负责)?"),
    re.compile(r"\b(?:I|we)\s+(?:can|will|'ll|am|'m|help|provide|handle|support)\b", re.I),
    re.compile(r"\bI'm\b|\bwe're\b", re.I),
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
# 「已知场景提示词」，不是合格性白名单。
# 未命中只说明"这个域的场景词不在这份提示里"，不等于描述里没有场景。
# 判定语义：命中 → 加分；未命中 → WARN（--strict 时才算失败），不直接 FAIL。
# 目标技能域内的场景词用 --scene-words <file> 注入。
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
# 「流程摘要」信号 —— description 不得概括流程步骤。
# 为什么：description 是常驻上下文里唯一的内容，正文按需加载。description 一旦把结论
# 说完，agent 就会走这条捷径、正文失去被读取的理由，技能退化成一行 prompt。
# 只判 WARN 不判 FAIL：中文里「先」字高频（优先、首先），措辞形态多变，封闭词表判不合格
# 会误杀正确写法——与「场景词判不出就 WARN」同一条纪律。命中提示人工看一眼即可。
FLOW_SIGNALS = [
    re.compile(r"先[^，。；！？、\n]{0,12}再"),                  # 先…再…
    re.compile(r"先[^，。；！？、\n]{0,12}(?:然后|之后|接着)"),
    re.compile(r"第\s*[一二三四五六七八九十百\d]+\s*步"),
    re.compile(r"依次|逐个(?:执行|处理|派发)|逐条(?:执行|处理)"),
    # 两个以上箭头 = 串起来的步骤链（A → B → C）；单个箭头可能是「输入→输出」的正常写法
    re.compile(r"(?:→|➔|⇒|-->|->)[^\n]*(?:→|➔|⇒|-->|->)"),
    re.compile(r"\bstep\s*\d+\s*(?:[/,、&]\s*\d+)?", re.I),
    re.compile(r"\bfirst\b[^\n]{0,60}\bthen\b", re.I),
]


def run_desc_check(desc, scene_words=None, strict=False):
    """description 6 项静态质量校验，分两级。

    FAIL 级（命中即不合格）：自称构式 / 无动作动词 —— 这两项决定技能会不会被正确触发。
    WARN 级（默认只提示，--strict 时计入失败）：缺场景 / 含 how / 缺排他边界 / 含流程摘要
      —— 这四项与"技能域"和"措辞习惯"强相关，用封闭词表判它们不合格会误杀域外写法。

    返回退出码（0=PASS / 1=FAIL）。
    """
    checks = []  # (名称, 级别, 是否通过, 说明)

    bad = [p.pattern for p in FIRST_PERSON if p.search(desc)]
    checks.append(("自称构式（无 我可以/本助手/I can）", "FAIL", not bad,
                   "命中自称: %s" % "、".join(bad) if bad else ""))

    has_verb = any(v in desc for v in ACTION_VERBS_CN) or bool(ACTION_VERBS_EN.search(desc))
    checks.append(("含动作动词", "FAIL", has_verb,
                   "未识别到动作动词（动词表是封闭的，域外动词可能误判；"
                   "确属误判请人工确认并反馈扩充词表）" if not has_verb else ""))

    scene_pool = list(SCENE_CN) + [w for w in (scene_words or []) if w]
    has_scene = any(p.search(desc) for p in SCENE_PATTERNS) or any(k in desc for k in scene_pool)
    checks.append(("含场景/文件类型", "WARN", has_scene,
                   "未识别到具体场景或文件类型（本域场景词可用 --scene-words 注入）"
                   if not has_scene else ""))

    how = [p.pattern for p in HOW_SIGNALS if p.search(desc)]
    checks.append(("无 how 描述", "WARN", not how,
                   "疑似描述做法: %s（how 应留给正文）" % "、".join(how) if how else ""))

    has_boundary = any(p.search(desc) for p in BOUNDARY_SIGNALS)
    checks.append(("含排他边界词", "WARN", has_boundary,
                   "缺少排他边界（何时不用/不做什么/仅用于）" if not has_boundary else ""))

    flow = [p.pattern for p in FLOW_SIGNALS if p.search(desc)]
    checks.append(("无流程摘要（不写步骤序列）", "WARN", not flow,
                   "疑似概括了流程: %s（description 只写能力标签 + 触发场景，"
                   "步骤序列/流程顺序/判定结论留给正文）" % "、".join(flow) if flow else ""))

    print("description : %s" % (desc[:60] + ("…" if len(desc) > 60 else "")))
    if scene_words:
        print("              （已注入本域场景词 %d 个）" % len(scene_words))
    fail_n = warn_n = 0
    for name, level, ok, detail in checks:
        mark = "✓" if ok else ("✗" if level == "FAIL" else "!")
        print("  %s [%s] %s%s" % (mark, level, name, "（%s）" % detail if detail else ""))
        if ok:
            continue
        if level == "FAIL" or strict:
            fail_n += 1
        else:
            warn_n += 1

    if fail_n:
        print("FAIL  description 有 %d 项不合格，请对照 references/SKILL.md 编写规范.md §七 修订" % fail_n)
        return 1
    if warn_n:
        print("PASS  description 达标（%d 项 WARN 建议；--strict 可将 WARN 计为失败）" % warn_n)
        return 0
    print("PASS  description 质量达标（6/6）")
    return 0


# ---------------------------------------------------------------- 外部清单加载（判定基准由调用方提供）
def load_word_list(path):
    """加载外部词表。支持：JSON 数组 / JSON 对象（优先取 should_trigger）/ 纯文本每行一条。"""
    if not path or not os.path.isfile(path):
        return None, "文件不存在: %s" % path
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        return None, "读取失败: %s" % e
    try:
        data = json.loads(raw)
    except Exception:
        return [l.strip() for l in raw.splitlines()
                if l.strip() and not l.strip().startswith("#")], None
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()], None
    if isinstance(data, dict):
        for key in ("should_trigger", "intents", "words", "scene_words"):
            v = data.get(key)
            if isinstance(v, list) and v:
                return [str(x).strip() for x in v if str(x).strip()], None
        merged = []
        for v in data.values():
            if isinstance(v, list):
                merged.extend(str(x).strip() for x in v if str(x).strip())
        if merged:
            return merged, None
    return None, ("未能从 %s 解析出词表（支持 JSON 数组 / 含 should_trigger 的对象 / 每行一条的文本）" % path)


TRIGGER_EVAL_CANDIDATES = ("evals/trigger_eval.json", "evals.json", "trigger_eval.json")

def resolve_intents(skill_dir, explicit_file):
    """三级回退取意图清单。返回 (intents, source, err)。

    ① --intents <file>                        显式指定，最可信
    ② <技能目录>/evals/trigger_eval.json       目标技能自带的真实用户说法
    ③ 两者都没有 → (None, None, None)：调用方必须给 REVIEW(2)，**不得判 FAIL**
    """
    if explicit_file:
        words, err = load_word_list(explicit_file)
        if err:
            return None, None, err
        return words, "外部清单 %s" % explicit_file, None
    for rel in TRIGGER_EVAL_CANDIDATES:
        p = os.path.join(skill_dir, rel)
        if os.path.isfile(p):
            words, err = load_word_list(p)
            if err:
                return None, None, err
            return words, rel, None
    return None, None, None


# ---------------------------------------------------------------- 留出集切分（防过拟合）
def split_holdout(intents, ratio, seed=0):
    """按固定种子确定性切分意图清单，返回 (训练集, 留出集)。

    为什么要确定性：同一条命令跑两次给出不同的结论，门禁就没法接 CI——
    `random.Random(seed).shuffle` 的 Mersenne Twister 序列跨版本稳定，可复现。
    为什么要留出集：只用同一批意图调 description，等于拿考过的题当考试——
    在训练集上调到满分、换个说法就不行，改进是假的。
    """
    idx = list(range(len(intents)))
    random.Random(seed).shuffle(idx)
    n_hold = int(round(len(intents) * ratio))
    n_hold = max(1, min(n_hold, len(intents) - 1))  # 两侧都不能空
    hold_idx = set(idx[:n_hold])
    train = [intents[i] for i in range(len(intents)) if i not in hold_idx]
    hold = [intents[i] for i in range(len(intents)) if i in hold_idx]
    return train, hold


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description="SKILL.md description 触发词评估工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 最常用：校验本技能 frontmatter description 的质量（6 项静态检查）
  python3 scripts/eval_trigger.py . --desc-check

  # 直接试错一段描述文本（跳过读技能目录）
  python3 scripts/eval_trigger.py --desc-check --desc "Helps with documents"

  # 查触发词覆盖并按留出集判定（防过拟合），意图清单用本技能自己的那份
  python3 scripts/eval_trigger.py . --check --intents evals/trigger_eval.json --holdout 0.4 --reps 3
""")
    ap.add_argument("skill_dir", nargs="?", help="技能目录（--desc 模式可省略）")
    ap.add_argument("--gen", action="store_true",
                    help="生成 should-trigger / should-not-trigger 评估集模板（需 --count 指定条数）")
    ap.add_argument("--check", action="store_true",
                    help="校验正文「触发词」章节的覆盖率（配 --from-description 改平台口径）")
    ap.add_argument("--desc-check", action="store_true", help="校验 frontmatter description 质量")
    ap.add_argument("--desc", default=None, help="直接校验给定描述文本（配合 --desc-check）")
    ap.add_argument("--count", type=int, default=10,
                    help="--gen 时正 / 负样本各生成多少条（默认 10）")
    ap.add_argument("--out", default=None,
                    help="--gen 的评估集输出路径（默认打到标准输出）")
    ap.add_argument("--threshold", type=float, default=0.7, help="触发覆盖率阈值（默认 0.7）")
    ap.add_argument("--intents", default=None, help="外部意图清单文件（JSON/txt），判定基准由你提供")
    ap.add_argument("--from-description", action="store_true",
                    help="按 frontmatter description 口径评测覆盖率（平台真实行为）；"
                         "默认按正文「触发词」章节口径")
    ap.add_argument("--scene-words", default=None, help="本技能域内的场景词清单（JSON/txt）")
    ap.add_argument("--holdout", type=float, default=0.0,
                    help="留出集比例（默认 0=关闭；推荐 0.4）。开启后按固定种子切分意图清单，"
                         "训练/留出两侧分别报覆盖率，判定以留出集为准（防过拟合）")
    ap.add_argument("--reps", type=int, default=1,
                    help="重复独立留出切分的次数（默认 1；推荐 3），输出留出集覆盖率均值±标准差；"
                         "衡量的是评估集切分稳定性，不是模型随机性")
    ap.add_argument("--strict", action="store_true", help="--desc-check 时把 WARN 级项也计入失败")
    ap.add_argument("--min-trigger-len", type=int, default=3,
                    help="宽松匹配的最短触发词长度（默认 3；防止 2 字泛词虚高覆盖）")
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
        scene_words = None
        if args.scene_words:
            scene_words, err = load_word_list(args.scene_words)
            if err:
                print("REVIEW  " + err)
                return 2
        return run_desc_check(desc, scene_words=scene_words, strict=args.strict)

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

    intents, src, err = resolve_intents(skill_dir, args.intents)
    if err:
        print("REVIEW  " + err)
        return 2
    if not intents:
        print("SKILL.md : %s" % path)
        print("触发词数 : %d" % len(triggers))
        print("REVIEW  未找到评估集，无法判定触发词覆盖 —— 无数据不等于不合格，故不给 FAIL。")
        print("        下一步（任选其一）：")
        print("        ① python3 eval_trigger.py %s --gen --count 20   # 生成模板" % skill_dir)
        print("        ② 把 should_trigger 替换为本技能的真实用户说法，另存为 %s/evals/trigger_eval.json" % skill_dir)
        print("        ③ 或 python3 eval_trigger.py %s --check --intents <file>" % skill_dir)
        return 2
    if args.from_description and not desc:
        print("SKILL.md : %s" % path)
        print("FAIL  --from-description 需要 frontmatter description，但该字段为空")
        return 1
    if not triggers and not args.from_description:
        print("SKILL.md : %s" % path)
        print("REVIEW  未找到「## 触发词」章节（有评估集 %d 条）。" % len(intents))
        print("        ⚠ 该技能的可发现性目前全靠 frontmatter description —— 平台自动发现")
        print("        只看 description，正文触发词章节平台不加载。两个口径请分开评测：")
        print("        ① python3 eval_trigger.py %s --check --from-description --intents <file>" % skill_dir)
        print("           # description 口径（对应平台真实路由行为）")
        print("        ② 或补写正文「触发词」章节后重跑本命令（正文口径，查触发词覆盖完整性）")
        return 2

    # 触发来源: description 整段作为一个判定源（平台口径），或正文触发词逐条（字面口径）
    src_note = ""
    if args.from_description:
        triggers = [desc]
        src_note = "（--from-description：平台口径，description 整段参与命中）"

    print("SKILL.md : %s" % path)
    print("触发词数 : %d%s" % (len(triggers), src_note))
    print("description: %s" % (desc[:80] + ("…" if len(desc) > 80 else "")))

    holdout, reps = args.holdout or 0.0, max(1, args.reps or 1)

    # ---- 留出集模式（防过拟合）: 训练/留出分开报, 判定以留出集为准 ----
    if holdout > 0:
        if not (0 < holdout < 1):
            print("REVIEW  --holdout 应在 (0, 1) 区间内（收到 %s）；本次不判 PASS/FAIL" % holdout)
            return 2
        n_hold0 = max(1, min(int(round(len(intents) * holdout)), len(intents) - 1))
        if n_hold0 < 2:
            print("预期意图 : %d（来源 %s）" % (len(intents), src))
            print("REVIEW  评估集只有 %d 条，留出集不足 2 条 —— 切分没有统计意义，不判 PASS/FAIL。" % len(intents))
            print("        下一步：按 references/评测方法论.md 扩量（推荐 ≥20 条，正例 8–10 + 负例 8–10，")
            print("        负例必须取「近误」——看着像、其实该找别的技能），扩量后用同一命令重跑。")
            return 2
        detail, train_covs, hold_covs, hold_misses = [], [], [], set()
        for seed in range(reps):
            tr, ho = split_holdout(intents, holdout, seed)
            th, _ = coverage(triggers, tr, min_trigger_len=args.min_trigger_len)
            hh, hm = coverage(triggers, ho, min_trigger_len=args.min_trigger_len)
            tc = len(th) / len(tr) if tr else 1.0
            hc = len(hh) / len(ho) if ho else 1.0
            detail.append((seed, len(th), len(tr), tc, len(hh), len(ho), hc))
            train_covs.append(tc); hold_covs.append(hc); hold_misses.update(hm)
        cov = sum(hold_covs) / len(hold_covs)
        tmean = sum(train_covs) / len(train_covs)
        std = (sum((c - cov) ** 2 for c in hold_covs) / len(hold_covs)) ** 0.5 if reps > 1 else 0.0

        print("预期意图 : %d（来源 %s）｜留出集 %.0f%%｜种子 0..%d｜重复 %d 次" % (
            len(intents), src, holdout * 100, reps - 1, reps))
        for seed, nh, ntr, tc, nhh, nho, hc in detail:
            print("  种子 %d : 训练 %d/%d (%.0f%%) | 留出 %d/%d (%.0f%%)" % (
                seed, nh, ntr, tc * 100, nhh, nho, hc * 100))
        if reps > 1:
            print("留出集覆盖率 : 均值 %.0f%% ± 标准差 %.0f%%（阈值 %.0f%%）—— 判定以留出集为准" % (
                cov * 100, std * 100, args.threshold * 100))
            if std > 0.15:
                print("  提示  标准差偏大（>15 个百分点）：评估集切分不稳，对策是**扩量**，"
                      "不是继续调措辞（否则调的是噪声）")
        else:
            print("训练集覆盖率 : %.0f%%（仅供参考）" % (tmean * 100))
            print("判定基准 : 留出集覆盖率 %.0f%%（阈值 %.0f%%）—— 防过拟合，判定以留出集为准" % (
                cov * 100, args.threshold * 100))
        for m in sorted(hold_misses):
            print("  MISS   留出集未覆盖意图: %s" % m)
        if tmean >= args.threshold and cov < args.threshold:
            print("REVIEW 疑似过拟合：训练集达标（%.0f%%）但留出集不达标（%.0f%%）。"
                  "建议扩充评估集或换更通用的说法，别在训练集上继续调。" % (tmean * 100, cov * 100))
            return 2
        if hold_misses and cov < args.threshold:
            print("FAIL  留出集覆盖率不足且有未覆盖意图，请补写触发词后重跑")
            return 1
        if hold_misses:
            print("REVIEW 留出集覆盖率达标但仍有 %d 个未覆盖意图，建议人工确认是否纳入触发词" % len(hold_misses))
            return 2
        print("PASS  触发词覆盖达标（含留出集验证）")
        print("提示  description 质量校验请单独跑: eval_trigger.py <技能目录> --desc-check")
        return 0

    # ---- 单臂模式（默认，向后兼容）----
    hit, miss = coverage(triggers, intents, min_trigger_len=args.min_trigger_len)
    cov = len(hit) / len(intents) if intents else 1.0

    print("预期意图 : %d（来源 %s），命中 %d，覆盖率 %.0f%%（阈值 %.0f%%）" % (
        len(intents), src, len(hit), cov*100, args.threshold*100))
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

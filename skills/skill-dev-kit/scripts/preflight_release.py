#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preflight_release.py — 技能发布预检工具
=========================================
发布前一键检查 8 项：敏感信息扫描 / frontmatter 字段校验 / 必含文件检查 / git 未跟踪文件告警 /
归属检查 / 悬空引用检查 / 版本与 tag 一致性 / 评测宣称—证据一致性。
配套发布前 16 项检查清单（references/发布检查清单.md），本脚本自动覆盖第 1/3/5/6/16 项；
后三项属「说了要做就得拿得出证据」的规范项，均为 warning 级，不阻断发布。

用法:
  python3 preflight_release.py <目录> [--platform skillhub|github] [--strict] [--quiet]
                              [--waive <项> --reason <文本>] [--skip-ownership]

  --platform   frontmatter 与必含文件按平台规范校验 (默认: skillhub)
  --strict     低危告警(warning)也视为失败
  --quiet      只输出结果行(FAIL 时的修复指引照常打印——只报"不通过"不给修法是耍流氓)
  --waive <项> 豁免指定告警项, 可多次传入; 必须同时给 --reason(无理由豁免 = 无审计)
  --reason     豁免理由, --waive 时必填; 落盘 <目标目录>/.preflight-waiver.json 留痕
  --skip-ownership  --waive ownership 的别名(跳过归属检查, 但不落盘审计)

退出码: 0 = PASS(仅告警可放行)  1 = FAIL(存在高危问题)  2 = 参数错误(豁免项非法/缺理由)

敏感分级:
  critical  → 必然 FAIL, **且不可豁免** (API key / 云凭据 / 明文 token)
  warning   → 默认仅告警, --strict 时 FAIL; 可 --waive 豁免 (本地路径 / 邮箱 / 疑似密码格式)

password_format 降噪（自动豁免, 无需 --waive）:
  技能自身名（frontmatter name / slug / 目录名）与 CSS `prefers-*` 前缀不再计入——
  三段式技能名与媒体查询属性**必然**命中 x-x-x 模式, 是纯误报（2026-08-29 实测:
  6 技能 39 项 strict 失败里 36 项是它, 误报率 92%）。
  第三方锁定/压缩文件（package-lock.json / yarn.lock / poetry.lock / *.min.js / *.map）
  默认整体跳过并计数留痕——内容由注册表元数据生成, 不是技能资产。

归属检查（分级，两者的性质不同）:
  LICENSE / "Copyright (c)" 行  → **critical**, 恒 FAIL（关联真实权益风险，不是流程项）
  author 字段                    → **warning**, 默认仅告警；--strict 时 FAIL
    依据: author 不在平台必填字段集内（见 REQUIRED_FIELDS），缺 author 实测仍能发布成功。
    曾把两者都判 critical，与 REQUIRED_FIELDS 自相矛盾——同一份规则里两套标准。
    要强约束请显式 --strict，由使用者决定，不由工具替他决定。
    author 告警可单独豁免: --waive author --reason ...（LICENSE Copyright 行不受影响，仍属 critical）

门禁分级(详见 references/发布检查清单.md):
  critical(阻断)  敏感信息命中 / LICENSE 缺失或无 Copyright 行 / 必含文件缺失 / frontmatter 必填字段缺失
                  → FAIL (exit 1), --strict 下同样 FAIL
  warning(告警)   author 缺失 / 本地路径 / 邮箱 / 疑似密码格式 / git 未跟踪文件 /
                  悬空引用 / 版本回退 / 评测宣称无据
                  → WARN (exit 0); --strict 下 FAIL (exit 1)
  可豁免          warning 级全部 → --waive <项> --reason 落盘留痕; critical 级豁免会被拒绝

可豁免项 (--waive 的稳定 key, 见 WAIVABLE_KEYS):
  敏感类   localpath / homepath / email / password_format / phone
  结构类   author / untracked / ownership
  引用类   dangling_ref / version_tag / eval_claim
  ⚠️ key 是稳定标识符, 不随中文说明变化——**不要用"说明"字段当匹配键**, 文案一改就失效。

示例:
  python3 preflight_release.py path/to/my-skill --platform skillhub
  python3 preflight_release.py github-publish/my-skill --platform github --strict
  # 文档示例路径属误报, 豁免并留痕(严格模式下也可放行)
  python3 preflight_release.py . --platform skillhub --strict \
      --waive localpath --waive email --reason "文档示例路径, 非真实个人信息"
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

# ---------------------------------------------------------------- 敏感规则
# 每条 = (豁免key, 级别, 正则, 说明)
#   key 是给 --waive 用的稳定标识符, 与中文"说明"解耦 —— 说明文案随时会改, key 不会。
SENSITIVE_RULES = [
    # (豁免key, 级别, 正则, 说明)
    ("skillhub_key", "critical", re.compile(r"skh_[A-Za-z0-9]{16,}"), "SkillHub API key"),
    ("github_token", "critical", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    ("openai_key", "critical", re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "OpenAI API key"),
    ("tencent_secretid", "critical", re.compile(r"\bAKID[A-Za-z0-9]{10,}"), "腾讯云 SecretId"),
    ("cos_secretid", "critical", re.compile(r'"secret_id"\s*[:=]\s*"[A-Za-z0-9]{16,}"'), "COS SecretId"),
    ("cos_secretkey", "critical", re.compile(r'"secret_key"\s*[:=]\s*"[A-Za-z0-9+/=]{16,}"'), "COS SecretKey"),
    ("token", "critical", re.compile(r'"token"\s*[:=]\s*"[A-Za-z0-9+/=]{30,}"'), "临时 token"),
    ("password", "critical", re.compile(r"password\s*[:=]\s*['\"][^'\"]{6,}['\"]", re.I), "明文密码赋值"),
    ("localpath", "warning", re.compile("/User" + "s/[A-Za-z0-9_]+"), "本机绝对路径"),
    ("homepath", "warning", re.compile("/hom" + "e/[A-Za-z0-9_]+"), "Linux 用户路径"),
    ("email", "warning", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "邮箱地址"),
    ("password_format", "warning", re.compile(r"\b[A-Za-z0-9]{5,9}-[A-Za-z0-9]{5,9}-[A-Za-z0-9]{5,9}\b"), "疑似密码(x-x-x 格式)"),
    ("phone", "warning", re.compile(r"\b1[3-9]\d{9}\b"), "手机号"),
]
# key → (级别, 说明)
RULE_INDEX = {k: (lv, desc) for k, lv, _, desc in SENSITIVE_RULES}
# critical 级: 真敏感, 命中即 FAIL, 且**拒绝豁免**(豁免真敏感 = 门禁形同虚设)
CRITICAL_KEYS = {k for k, (lv, _) in RULE_INDEX.items() if lv == "critical"}
# 非敏感规则的可豁免 warning 项(结构性告警)
EXTRA_WAIVABLE = {
    "author": "frontmatter author 字段缺失",
    "untracked": "git 未跟踪文件",
    "ownership": "归属检查整组 (author + LICENSE Copyright 行)",
    # 下面三项恒为 warning 级，理由同 name / 正文体积：目标平台不校验，属「应当满足」的规范项。
    # 自建门禁严于目标平台会把正确写法误杀（反模式 #22），故一律不判 critical。
    "dangling_ref": "§ 章节引用指向目标文件里不存在的章节",
    "version_tag": "version 低于已有 tag(疑似版本回退)",
    "eval_claim": "声明了评测能力但无 evals/ 证据",
}
# 可豁免全集 = 敏感规则里的 warning 级 + 结构性告警项
WAIVABLE_KEYS = {k for k, (lv, _) in RULE_INDEX.items() if lv == "warning"} | set(EXTRA_WAIVABLE)
# --waive 输出/审计用的项说明
WAIVER_DESC = {k: desc for k, (_, desc) in RULE_INDEX.items()}
WAIVER_DESC.update(EXTRA_WAIVABLE)

# ⚠️ 刻意不用（死代码，勿"修复"）：按扩展名白名单过滤会造成敏感扫描盲区
#    （.env / Dockerfile / 无扩展名配置文件都不在表里）。扫描走 scan_text 的内容探测。
#    注意：下方 LOCKFILE_NAMES 的「按文件名跳过」与这里的「按扩展名白名单」不是一回事——
#    前者是跳过个别已知的第三方生成物（package-lock 等由依赖注册表元数据生成，不是资产），
#    覆盖面窄且有跳过计数留痕；后者是「只扫白名单扩展名」，会把无扩展名配置文件漏掉。
TEXT_EXTS = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".sh", ".cfg", ".ini", ".xml", ".html", ".css", ".js", ".ts"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
# 第三方锁定/压缩文件：内容由包管理器从注册表元数据生成，不是技能资产。
# 实测（2026-08-29，6 技能批量体检）：锁定文件内的小写连字符标识符系统性命中
# password_format 的 x-x-x 模式，39 项 strict 失败里 17 项来自这里（占 44%），
# 且依赖声明写得越规范命中越多——属于纯噪声，默认跳过并计数留痕（可审计）。
# ⚠️ 本注释不举真实形态的示例串：回溯文档会被本工具再读一遍（纪律：不复写触发形态）。
LOCKFILE_NAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock", "composer.lock"}
LOCKFILE_SUFFIXES = (".min.js", ".map")
# WAIVER_FILE 是本脚本自己写的审计产物(内容是项/理由/时间), 不该反过来被敏感扫描命中
WAIVER_FILE = ".preflight-waiver.json"
SKIP_FILES = {".DS_Store", WAIVER_FILE}
# 单文件单规则的逐条命中上限，超出汇总为「另有 N 处」（防输出爆炸，不丢计数）
MAX_HITS_PER_RULE = 5

# ---------------------------------------------------------------- 平台规范
# 平台必填字段。**author 不在此集合**（实测缺 author 仍能发布成功）→
# 归属检查里 author 缺失判 warning 而非 critical；需要强约束时用 --strict。
REQUIRED_FIELDS = {
    "skillhub": ["name", "slug", "displayName", "summary", "description", "version", "license"],
    "github": ["name", "description", "version", "license"],
}
REQUIRED_FILES = {
    "skillhub": ["SKILL.md", "scripts"],
    "github": ["README.md", "LICENSE", "SKILL.md"],
}
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
# name 规范（官方规范硬线）: 1-64 字符 / 小写字母·数字·连字符 / 不以连字符开头或结尾 /
# 禁连续连字符 / 与父目录名一致。下面这条正则一次覆盖前三项（首尾与连续连字符都在内）。
# 分级为 **warning** 而非 critical: 目标平台不校验这几条, 属「应当满足」的规范项;
# 自建门禁严于目标平台会把正确写法误杀（反模式 #22），需要强约束时用 --strict。
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_MAX = 64

# L2 正文体积（官方推荐线 = 5000 token，保留为硬上限；目标值锚点取优秀实践中位数 ~2000）。
# 同样定为 **warning** 级: 平台不校验体积, 属「应当满足」的规范项。
BODY_TOKEN_LIMIT = 5000
BODY_TOKEN_TARGET = 2000


def scan_text(path):
    """读取文件为文本, 非文本返回 None。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(2 * 1024 * 1024)
    except OSError:
        return None
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # 含较多控制字符视为二进制
        printable = sum(1 for b in raw if b in (9, 10, 13) or 32 <= b < 127)
        if printable / len(raw) < 0.8:
            return None
        return raw.decode("utf-8", errors="replace")


def sensitive_scan(root, waived=(), exempt_names=()):
    """返回 (critical列表, warning列表, 扫描文件数, 豁免命中计数{key: n}, 跳过锁定文件数)。

    waived 里的 key 对应 SENSITIVE_RULES 的豁免 key; 命中直接丢弃(不当告警也不当失败),
    但**计数保留**在 suppressed 中, 供审计文件记录"这次到底豁免掉了多少处"——
    豁免 0 处也照样落盘, 让审计能看出这是一次无效豁免(说明该项本就没问题或 key 选错了)。

    exempt_names: password_format 规则的自动豁免词（技能 frontmatter name / slug / 目录名）。
    实测（2026-08-29，6 技能批量体检）：三段式 kebab-case 技能名**必然**命中 x-x-x 模式
    （如 4+8+1 项），占 39 项 strict 失败的大头——技能名是自己的名字，不是凭据。
    只对 password_format 单条规则生效，其余规则不受影响；另豁免 CSS 媒体查询
    `prefers-*` 前缀（同类 x-x-x 误报，前端/设计类技能高发）。
    """
    waived = set(waived)
    exempt_lower = {n.lower() for n in exempt_names if n}
    critical, warning, scanned, skipped_lockfiles = [], [], 0, 0
    suppressed = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES or fn.endswith((".pyc", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".enex", ".db", ".ico")):
                continue
            if fn in LOCKFILE_NAMES or fn.endswith(LOCKFILE_SUFFIXES):
                skipped_lockfiles += 1
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            text = scan_text(full)
            if text is None:
                continue
            scanned += 1
            for key, level, pattern, desc in SENSITIVE_RULES:
                # finditer 全量命中：search 只报第一处，单文件 3 个密码只显示 1 个，
                # 会让修复量被严重低估（改完跑一遍"还剩 2 个"才知道）。
                hits = list(pattern.finditer(text))
                if not hits:
                    continue
                if key == "password_format":
                    hits = [m for m in hits
                            if m.group(0).lower() not in exempt_lower
                            and not m.group(0).lower().startswith("prefers-")]
                    if not hits:
                        continue
                if key in waived:
                    suppressed[key] = suppressed.get(key, 0) + len(hits)
                    continue
                shown = hits[:MAX_HITS_PER_RULE]
                for m in shown:
                    snippet = m.group(0)
                    if len(snippet) > 24:
                        snippet = snippet[:12] + "…" + snippet[-8:]
                    item = f"{rel}: {desc} ({snippet})"
                    (critical if level == "critical" else warning).append(item)
                rest = len(hits) - len(shown)
                if rest > 0:
                    item = f"{rel}: {desc}（另有 {rest} 处同类命中未逐条列出）"
                    (critical if level == "critical" else warning).append(item)
    return critical, warning, scanned, suppressed, skipped_lockfiles


def write_waiver(root, waived, reason, suppressed, fm):
    """豁免落盘留痕 → <目标目录>/.preflight-waiver.json。

    记 项/理由/时间/操作者/版本号 五要素。写失败只告警不阻断: 审计文件写不出来的
    常见原因是目录只读, 那不该让"能过"的检查因为这个变成"过不了"。
    """
    record = {
        "tool": "preflight_release.py",
        "target": root,
        "skill_version": (fm or {}).get("version") or "unknown",
        "operator": os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown",
        "waived_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "waivers": [
            {
                "item": k,
                "desc": WAIVER_DESC.get(k, ""),
                "reason": reason,
                "suppressed_hits": suppressed.get(k, 0),
            }
            for k in sorted(waived)
        ],
    }
    path = os.path.join(root, WAIVER_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"[WARN] 豁免审计文件写入失败: {path} ({e})")
        return None
    return path


def parse_frontmatter(path):
    """提取 SKILL.md 顶部 --- 块的 key: value (零依赖简易解析)。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
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


def git_untracked(root):
    """返回未跟踪文件列表; 非 git 仓库返回 None。"""
    if not os.path.isdir(os.path.join(root, ".git")):
        return None
    try:
        out = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return None
    return [ln[3:].strip() for ln in out.splitlines() if ln.startswith("??")]


COPYRIGHT_RE = re.compile(r"Copyright\s*[（(c©]\s*", re.I)


def body_token_estimate(path):
    """按规范口径估算 SKILL.md **正文**体积（token）。读不到返回 None。

    口径（与 references/核心公式与量化基准.md §2 逐字一致）:
        正文 token ≈ 中文字数 × 1.0 + 非中文字符数 / 4

    ⚠️ 必须先剔掉 frontmatter —— 规范声明的是「正文体」。
    历史缺陷：文档里给的自检命令是整文件口径，含 frontmatter 会虚高（本技能实测差 400+ token），
    照它比对会把一份达标文件误报成超线；两个口径混用属同类错误（计算列必须整列同源）。
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)
    cn = len(re.findall(r"[\u4e00-\u9fff]", body))
    return int(round(cn + (len(body) - cn) / 4))


def ownership_check(root, fm):
    """归属检查: LICENSE Copyright 为 critical, author 为 warning。

    返回 (critical列表, warning列表, info列表)。

    分级依据（曾自相矛盾: REQUIRED_FIELDS 不含 author, 此处却判 critical 禁止发布）:
      - author      → **warning**: 平台必填集里没有它, 缺 author 实测仍能发布成功。
                      归属是"应当有"的流程项, 不是"没有就发不出去"的阻断项。
                      需要强约束时显式 --strict, 由使用者决定, 不由工具替他决定。
      - LICENSE 文件 / Copyright (c) 行 → **critical**: 关联真实权益风险, 不是流程项。
    LICENSE 在 SkillHub 发布包中被排除, 但源码目录必须保留且含正确版权行——故对源码目录恒检查。
    """
    critical, warning, info = [], [], []
    author = (fm or {}).get("author", "").strip()
    if not author:
        warning.append("frontmatter 缺少 author 字段(归属锚点; 非平台必填, --strict 时阻断)")
    else:
        info.append(f"author = {author}")
    lic = os.path.join(root, "LICENSE")
    if not os.path.isfile(lic):
        alt = [p for p in ("LICENSE.md", "LICENSE.txt") if os.path.isfile(os.path.join(root, p))]
        lic = os.path.join(root, alt[0]) if alt else None
    if lic is None:
        critical.append("源码目录缺少 LICENSE 文件(含 Copyright 行的版权锚点)")
    else:
        try:
            text = open(lic, encoding="utf-8").read()
        except OSError:
            text = ""
        if COPYRIGHT_RE.search(text):
            m = next((ln for ln in text.splitlines() if COPYRIGHT_RE.search(ln)), "")
            info.append(f"LICENSE 版权行: {m.strip()[:60]}")
        else:
            critical.append("LICENSE 缺少 'Copyright (c)' 行(版权人未落名)")
    return critical, warning, info


# ---------------------------------------------------------------- 引用校验
# 只校验 § 编号引用（「见 X.md §4.1」这类跨文件章节引用）——结构一改就断，是文档改动后
# 最容易留下的失效引用，也正是人工终检时唯一能查的那件事。
# ⚠️ 刻意不查文件路径存在性：文档里合法地提到大量并不存在的文件名（写法示例、运行时产物、
#    第三方锁定文件），实测路径口径 26/26 全为误报。⚠️ 门禁的误报率必须压到 10% 以内，
#    否则使用者会学会无脑豁免或直接跳过——那比没有门禁更糟，因为它制造了「已检查」的错觉。
HEADING_NUM_RE = re.compile(r"^#{1,6}\s+§?\s*([0-9]+)(?:\.([0-9]+))?", re.M)
HEADING_CN_RE = re.compile(r"^#{1,6}\s+§?\s*([一二三四五六七八九十]+)(?=[\s、.．:：])", re.M)
SEC_REF_RE = re.compile(r"§\s*([0-9]+(?:\.[0-9]+)?|[一二三四五六七八九十]+)")


def _section_index(path):
    """该文件可被引用的章节号集合，形如 {'1','1.1','4.1','五'}。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return set()
    idx = set()
    for m in HEADING_NUM_RE.finditer(text):
        idx.add(m.group(1))
        if m.group(2):
            idx.add(f"{m.group(1)}.{m.group(2)}")
    idx |= {m.group(1) for m in HEADING_CN_RE.finditer(text)}
    return idx


def _pick_target(text, known):
    """在文本前缀里找出被引用的目标文件：取**结束位置最靠后**（即离 § 最近）的那个。

    先按远近、再按长短：`…错误处理与可靠性纪律.md`（第三步）、SKILL.md §十` 里最近的
    是 SKILL.md；而 `` `references/SKILL.md 编写规范.md` §4.1 `` 里 `SKILL.md` 与
    `SKILL.md 编写规范.md` 起始位置相同，长名结束更靠后，因此不会被同名短文件抢走。
    """
    cands = [(text.rfind(n) + len(n), len(n), n) for n in known if n in text]
    return max(cands)[2] if cands else None


def ref_check(root):
    """校验「…<文件>.md §N」这种点明了目标文件的章节引用是否指向真实存在的章节。

    返回 (断链列表, § 引用总数, 未判定列表)。

    ⚠️ 只判定**同行、紧邻 § 之前（40 字符内）**写出目标文件名的引用。这是唯一能可靠
    解析目标的形态；实测「取同行最近的文件名当目标」会双向猜错——既把文件内自引用
    判成别的文件，又把跨文件引用判成自引用，14 项里 14 项全假。其余（含自引用）只
    汇总不判定，交人工核对：漏报可以补看，误报会让整道门禁被学会无视。
    """
    ref_dir = os.path.join(root, "references")
    files = []
    if os.path.isfile(os.path.join(root, "SKILL.md")):
        files.append(os.path.join(root, "SKILL.md"))
    if os.path.isdir(ref_dir):
        files += [os.path.join(ref_dir, f) for f in sorted(os.listdir(ref_dir))
                  if f.endswith(".md")]
    known = {os.path.basename(p) for p in files}
    index = {os.path.basename(p): _section_index(p) for p in files}

    broken, total, unjudged = [], 0, []
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        rel = os.path.relpath(path, root)
        for line in lines:
            for m in SEC_REF_RE.finditer(line):
                sec = m.group(1)
                total += 1
                head = line[max(0, m.start() - 40):m.start()]
                tgt = _pick_target(head, known)
                if tgt is None:
                    unjudged.append(f"{rel} §{sec}")
                    continue
                if sec not in index.get(tgt, set()):
                    broken.append(f"{rel}: §{sec} → {tgt} 无此章节")
    return broken, total, unjudged


# ---------------------------------------------------------------- 版本与 tag
def _ver_tuple(s):
    """"v1.2.3" → (1, 2, 3)；非语义化返回空元组（比较时排在最后，不当"更新"）。"""
    s = (s or "").strip().lstrip("v")
    return tuple(int(x) for x in s.split(".")) if SEMVER.match(s) else ()


def version_tag_check(root, version):
    """version 与 git tag 的一致性。非 git 仓库或仓库无 v* tag → 跳过。

    返回 (warning文本, ✓文本, 跳过文本)，三者恰有一个非 None。
    这里**不把「尚未打 tag」当问题**：预检跑在发布之前，v<version> 本来就还不存在，
    把正常时序判成告警是最典型的自建门禁误杀。真正值得拦的只有一种——版本回退。
    """
    if not os.path.isdir(os.path.join(root, ".git")):
        return None, None, "非 git 仓库，跳过"
    try:
        out = subprocess.run(["git", "-C", root, "tag", "-l", "v*"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None, None, "git 不可用，跳过"
    tags = [t.strip() for t in out.splitlines() if _ver_tuple(t)]
    if not tags:
        return None, None, "仓库内尚无 v* tag，跳过"
    cur = (version or "").strip()
    if f"v{cur}" in tags:
        return None, f"version {cur} 与 tag v{cur} 一致", None
    latest = max(tags, key=_ver_tuple)
    if _ver_tuple(cur) and _ver_tuple(latest) > _ver_tuple(cur):
        return (f"version {cur} 低于已有 tag（最新 {latest}）—— 疑似版本回退", None, None)
    return None, None, f"尚无 v{cur} tag（发布后创建；当前最新 {latest}）"


# ---------------------------------------------------------------- 评测宣称
# 声明"做了评测"的常见说法。命中即要求拿得出 evals/ —— 查的是"说了没做"，
# 不是"有没有做评测"：目标平台不要求 evals/，多数技能也没做，判"没做"就是误杀。
EVAL_CLAIM_RE = re.compile(r"评测闭环|benchmark|评估集|触发词评估|回归重跑|evals/")


def eval_claim_check(root, fm_dir):
    """评测「宣称—证据一致性」。返回 (warning文本, ✓文本)，均可为 None。

    与「无数据不得判 FAIL」并不冲突：这里判的不是"没有评测数据"，而是
    "文档说了有评测资产、目录里却拿不出来"（反模式 #23 立规者未自守）。
    未做声明的技能完全不触发本项。
    """
    texts = []
    for p in (os.path.join(fm_dir, "SKILL.md"),
              os.path.join(root, "README.md"),
              os.path.join(fm_dir, "README.md")):
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    texts.append(f.read())
            except OSError:
                pass
    hits = sorted({h for h in EVAL_CLAIM_RE.findall("\n".join(texts))})
    if not hits:
        return None, None
    ev = os.path.join(root, "evals")
    n = len([f for _, _, fs in os.walk(ev) for f in fs]) if os.path.isdir(ev) else 0
    if n:
        return None, f"评测宣称有据（命中「{'、'.join(hits)}」，evals/ {n} 个文件）"
    return (f"声明了评测能力但拿不出证据：文档命中「{'、'.join(hits)}」，"
            f"而 evals/ 缺失或为空", None)


def main():
    ap = argparse.ArgumentParser(
        description="技能发布预检工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 最常用：发布前按 SkillHub 规范体检当前目录
  python3 scripts/preflight_release.py . --platform skillhub

  # 严格档（低危告警也当失败），只要结果行
  python3 scripts/preflight_release.py . --platform skillhub --strict --quiet

  # 文档示例路径属误报：豁免并留痕（豁免项 key 见 --waive 的帮助文本）
  python3 scripts/preflight_release.py . --platform skillhub --strict \\
      --waive localpath --waive email --reason "文档示例路径, 非真实个人信息"
""")
    ap.add_argument("target", help="待检查的目录")
    ap.add_argument("--platform", choices=["skillhub", "github"], default="skillhub",
                    help="目标平台档（默认 skillhub）——决定必填字段与必含文件清单")
    ap.add_argument("--strict", action="store_true", help="低危告警也视为失败")
    ap.add_argument("--quiet", action="store_true",
                    help="只输出结果行（便于 CI）；FAIL 的修复指引照常打印")
    ap.add_argument("--waive", action="append", default=[], metavar="项",
                    help="豁免指定 warning 项(可多次传入, 必须同时给 --reason)。"
                         f"可豁免: {', '.join(sorted(WAIVABLE_KEYS))}")
    ap.add_argument("--reason", metavar="文本",
                    help="豁免理由; --waive 时必填, 随豁免一起落盘 .preflight-waiver.json 留痕")
    ap.add_argument("--skip-ownership", action="store_true",
                    help="跳过归属检查 —— --waive ownership 的别名(为兼容旧用法不落盘审计; "
                         "需要留痕请改用 --waive ownership --reason ...)。"
                         "仅自用/第三方技能确不需要 author/LICENSE Copyright 时使用")
    args = ap.parse_args()

    # --- 豁免项校验: 先校验再扫描。打错 key / 豁免真敏感都必须当场报错, 不能静默放过 ---
    #     （静默放过的后果: 使用者以为"豁免了"其实没豁免, 或以为只是告警其实是真密钥）
    if args.waive and not (args.reason or "").strip():
        ap.error("--waive 必须同时提供 --reason（无理由的豁免等于没有审计）")
    waived = set()
    for k in args.waive:
        k = (k or "").strip()
        if k in CRITICAL_KEYS:
            ap.error(f"「{k}」是 critical 级, 不可豁免 —— 真敏感必须修(删密钥+轮换), 不能靠豁免放行")
        if k not in WAIVABLE_KEYS:
            ap.error(f"未知豁免项「{k}」。可豁免: {', '.join(sorted(WAIVABLE_KEYS))}")
        waived.add(k)
    # --skip-ownership 等价于 --waive ownership, 但**不落盘**(旧用法行为不变),
    # 因此不进 waived 集合, 单独用 skip_own 控制。
    skip_own = args.skip_ownership or "ownership" in waived
    reason = (args.reason or "").strip()

    root = os.path.abspath(args.target)
    if not os.path.isdir(root):
        print(f"[FAIL] 目录不存在: {root}")
        sys.exit(1)

    # fails 元素为 (问题, 修复指引) —— 只说"缺什么"不说"怎么修"违反纪律 4（本守门员自己先守住）
    fails, warns = [], []
    log = (lambda s: print(s)) if not args.quiet else (lambda s: None)

    # frontmatter 提前解析: password_format 的自动豁免词需要技能名（自己的名字不是凭据）
    fm_dir = root  # SKILL.md 所在目录 —— name 规范性要跟它比（官方规范: name 必须与父目录名一致）
    fm = parse_frontmatter(os.path.join(root, "SKILL.md")) if os.path.exists(os.path.join(root, "SKILL.md")) else None
    if fm is None:
        # github 平台可能是 skills/<name>/SKILL.md
        skill_root = root
        for dp, _, fns in os.walk(root):
            if "SKILL.md" in fns and "skills" in dp.split(os.sep):
                skill_root = dp
                break
        fm_dir = skill_root
        fm = parse_frontmatter(os.path.join(skill_root, "SKILL.md"))
    exempt_names = {fm.get(k, "") for k in ("name", "slug") if fm} | {os.path.basename(root)}

    # 1. 敏感扫描
    critical, warning, scanned, suppressed, skipped_lockfiles = sensitive_scan(root, waived, exempt_names)
    log(f"── 1. 敏感扫描 ({scanned} 个文本文件) ──")
    if skipped_lockfiles:
        log(f"  - 已跳过 {skipped_lockfiles} 个第三方锁定/压缩文件（package-lock 等，非资产，默认排除）")
    for k in sorted(waived):
        if k in suppressed:
            log(f"  - 已豁免: {k}（{WAIVER_DESC[k]}, {suppressed[k]} 处）— 理由: {reason}")
    if not critical and not warning:
        log("  ✓ 未发现敏感信息")
    for item in critical:
        log(f"  ✗ [高危] {item}")
        fails.append((item, "删掉真实凭证并立即轮换（进过仓库的密钥一律视为已泄露）; "
                            "代码里改用环境变量或 ${API_KEY} 占位符。critical 级不接受豁免, 只能修"))
    for item in warning:
        log(f"  ⚠ [告警] {item}")
        if args.strict:
            fails.append((item, "把真实值泛化为占位符/相对路径; 确属文档示例误报, 可 "
                                "--waive <项> --reason \"...\" 豁免（会落盘留痕）"))
        else:
            warns.append(item)

    # 2. frontmatter 校验
    log(f"── 2. frontmatter 校验 (platform={args.platform}) ──")
    if fm is None:
        log("  ✗ 未找到 SKILL.md 或缺少 frontmatter (--- 块)")
        fails.append(("SKILL.md frontmatter 缺失",
                      "在 SKILL.md 顶部补 --- 包裹的 YAML 块, 至少含 name/description/version/license"
                      + ("; skillhub 另需 slug/displayName/summary" if args.platform == "skillhub" else "")))
    else:
        missing = [k for k in REQUIRED_FIELDS[args.platform] if not fm.get(k)]
        if missing:
            log(f"  ✗ 缺少必需字段: {', '.join(missing)}")
            fails.append((f"frontmatter 缺字段: {missing}",
                          f"在 SKILL.md frontmatter 补齐: {', '.join(REQUIRED_FIELDS[args.platform])}"))
        else:
            ver = fm.get("version", "")
            ver_ok = bool(SEMVER.match(ver))
            log(f"  ✓ name={fm.get('name')} version={ver} {'✓' if ver_ok else '✗ 非语义化版本(需 X.Y.Z)'}")
            if not ver_ok:
                fails.append((f"version 格式错误: {ver}",
                              "version 改成语义化 X.Y.Z（如 1.6.1）, 并与发布 tag vX.Y.Z 保持一致"))

            # name 规范性（官方规范硬线；目标平台不校验 → warning 级，--strict 才阻断）
            name = (fm.get("name") or "").strip()
            if name:
                dir_name = os.path.basename(os.path.abspath(fm_dir))
                name_problems = []
                if not NAME_RE.match(name):
                    name_problems.append("不满足「小写字母/数字/连字符, 不以连字符开头或结尾, 无连续连字符 --」")
                if len(name) > NAME_MAX:
                    name_problems.append(f"长度 {len(name)} > 官方上限 {NAME_MAX}")
                if dir_name and dir_name != name:
                    name_problems.append(f"与父目录名不一致（目录名 {dir_name}）")
                for pb in name_problems:
                    msg = f"frontmatter name 不规范: {name} —— {pb}"
                    log(f"  ⚠ {msg}")
                    if args.strict:
                        fails.append((msg, "改成 kebab-case 且与目录名一致（如 my-skill）, "
                                           "并同步发布目录名、GitHub 仓库目录与所有引用"))
                    else:
                        warns.append(msg)
                if not name_problems:
                    log(f"  ✓ name 规范性（kebab-case / 与目录名一致 / ≤{NAME_MAX} 字符）")

            # L2 正文体积（规范建议项；目标 ~2000 / 硬上限 5000；口径见 body_token_estimate）
            est = body_token_estimate(os.path.join(fm_dir, "SKILL.md"))
            if est is None:
                log("  - SKILL.md 正文体积: 读取失败, 跳过")
            elif est > BODY_TOKEN_LIMIT:
                msg = (f"SKILL.md 正文体积 ≈{est} token, 超硬上限 {BODY_TOKEN_LIMIT}"
                       f"（目标值 ~{BODY_TOKEN_TARGET}）")
                log(f"  ⚠ {msg}")
                if args.strict:
                    fails.append((msg, "把清单/方法学/速查等细节下沉到 references/ 按需加载, "
                                       "正文只留结论与指针; 改完用规范 §2 的自检命令复核"))
                else:
                    warns.append(msg)
            else:
                note = ("（已超目标值 ~%d——目标值是优秀实践中位数，不是红线）" % BODY_TOKEN_TARGET
                        if est > BODY_TOKEN_TARGET else "")
                log(f"  ✓ 正文体积 ≈{est} token（硬上限 {BODY_TOKEN_LIMIT}）{note}")

    # 3. 必含文件检查
    log("── 3. 必含文件检查 ──")
    for req in REQUIRED_FILES[args.platform]:
        p = os.path.join(root, req)
        if os.path.isfile(p):
            log(f"  ✓ {req}")
        elif os.path.isdir(p):
            n = len([f for _, _, fs in os.walk(p) for f in fs])
            if n == 0:
                # 空目录能通过检查 = 门禁形同虚设（mkdir scripts 即可绕过）
                log(f"  ✗ 必含目录为空: {req}/（目录存在但无文件）")
                fails.append((f"必含目录为空: {req}/",
                              f"往 {req}/ 里放实际脚本, 或删掉这个空目录（空目录 = 绕过门禁, 不是通过）"))
            else:
                log(f"  ✓ {req}/ ({n} 个文件)")
        else:
            # github 平台放宽: skills/<name>/SKILL.md
            if args.platform == "github" and req == "SKILL.md" and os.path.isdir(os.path.join(root, "skills")):
                found = [dp for dp, _, fns in os.walk(os.path.join(root, "skills")) if "SKILL.md" in fns]
                if found:
                    log(f"  ✓ skills/{os.path.relpath(found[0], os.path.join(root, 'skills'))}/SKILL.md")
                    continue
            log(f"  ✗ 缺少: {req}")
            fails.append((f"缺少必需文件: {req}",
                          f"创建 {req}" + ("（github 平台也可放 skills/<name>/SKILL.md）" if req == "SKILL.md" else "")))

    # 4. git 未跟踪文件
    log("── 4. git 未跟踪文件 ──")
    untracked = git_untracked(root)
    if untracked is None:
        log("  - 非 git 仓库, 跳过")
    elif not untracked:
        log("  ✓ 无未跟踪文件")
    else:
        for u in untracked:
            log(f"  ⚠ 未跟踪: {u}")
        if "untracked" in waived:
            log(f"  - 已豁免: untracked（{len(untracked)} 个）— 理由: {reason}")
        elif args.strict:
            fails.append((f"git 未跟踪文件: {untracked}",
                          "git add <要发布的文件>, 或写进 .gitignore 排除临时产物"))
        else:
            warns.append(f"git 未跟踪文件: {len(untracked)} 个")

    # 5. 归属检查 (author + LICENSE Copyright 行)
    log("── 5. 归属检查 ──")
    if skip_own:
        if "ownership" in waived:
            log(f"  - 已豁免: ownership（整组跳过）— 理由: {reason}")
        else:
            # 文案保持与改造前逐字一致（向后兼容）; 迁移提示只放 --help 与文档
            log("  - --skip-ownership 指定, 跳过")
    else:
        own_critical, own_warning, own_info = ownership_check(root, fm)
        if "author" in waived:
            # 只摘 author 告警, LICENSE Copyright 行(critical)不受影响
            own_warning = [w for w in own_warning if "author" not in w]
            log(f"  - 已豁免: author — 理由: {reason}")
        for i in own_info:
            log(f"  ✓ {i}")
        for c in own_critical:
            log(f"  ✗ [高危] {c}")
            if "缺少 LICENSE 文件" in c:
                hint = ("在源码目录新增 LICENSE（MIT 模板即可）, 首行写: "
                        "Copyright (c) <年份> <版权人>")
            else:
                hint = "在 LICENSE 顶部补一行: Copyright (c) 2026 <版权人>（(c) 也可写作 © 或全角（c））"
            fails.append((c, hint))
        for w in own_warning:
            log(f"  ⚠ [告警] {w}")
            if args.strict:
                fails.append((w, "在 SKILL.md frontmatter 加 author: <归属人>, "
                                 "并与 LICENSE 的 Copyright 行同名"))
            else:
                warns.append(w)
        if not own_critical and not own_warning:
            log("  ✓ 归属锚点齐备 (author + Copyright 行); homepage 仓库真实性请人工/gh api 核验")

    # 6. § 章节引用校验
    log("── 6. § 章节引用校验 ──")
    broken, ref_total, unjudged = ref_check(root)
    if "dangling_ref" in waived:
        log(f"  - 已豁免: dangling_ref（{len(broken)} 处断链）— 理由: {reason}")
    elif broken:
        for item in broken:
            msg = f"章节引用断链: {item}"
            log(f"  ⚠ {msg}")
            if args.strict:
                fails.append((msg, "改成目标文件里真实存在的章节号, 或把编号引用改回文字描述; "
                                   "确属引用外部文档的编号可 --waive dangling_ref --reason \"...\""))
            else:
                warns.append(msg)
    else:
        log(f"  ✓ 已判定的 {ref_total - len(unjudged)} 处章节引用全部存在")
    if unjudged:
        shown = "、".join(unjudged[:8])
        more = f" 等 {len(unjudged)} 处" if len(unjudged) > 8 else ""
        log(f"  - 未判定 {len(unjudged)} 处（§ 前未写明目标文件，多为文件内自引用）: {shown}{more}")

    # 7. 版本与 tag 一致性
    log("── 7. 版本与 tag 一致性 ──")
    v_warn, v_ok, v_skip = version_tag_check(root, (fm or {}).get("version", ""))
    if "version_tag" in waived:
        log(f"  - 已豁免: version_tag — 理由: {reason}")
    elif v_warn:
        log(f"  ⚠ {v_warn}")
        if args.strict:
            fails.append((v_warn, "确认 version 未回退; 若确为分叉版本可 "
                                  "--waive version_tag --reason \"...\""))
        else:
            warns.append(v_warn)
    elif v_ok:
        log(f"  ✓ {v_ok}")
    else:
        log(f"  - {v_skip}")

    # 8. 评测宣称—证据一致性
    log("── 8. 评测宣称—证据一致性 ──")
    e_warn, e_ok = eval_claim_check(root, fm_dir)
    if "eval_claim" in waived:
        log(f"  - 已豁免: eval_claim — 理由: {reason}")
    elif e_warn:
        log(f"  ⚠ {e_warn}")
        if args.strict:
            fails.append((e_warn, "二选一: 补 evals/ 评测资产, 或删掉 SKILL.md / README 里"
                                  "「评测闭环 / benchmark / 评估集 / evals/」这类声明 —— "
                                  "没做评测就不要写做了"))
        else:
            warns.append(e_warn)
    elif e_ok:
        log(f"  ✓ {e_ok}")
    else:
        log("  - 未声明评测能力, 跳过(目标平台不要求 evals/)")

    # 9. 豁免落盘留痕（--skip-ownership 别名不进 waived, 故不落盘 —— 旧用法行为不变）
    if waived:
        wpath = write_waiver(root, waived, reason, suppressed, fm)
        if wpath:
            log(f"  ✓ 豁免已落盘: {wpath}")

    # 结果
    log("")
    if fails:
        print(f"结果: FAIL ({len(fails)} 项高危问题, 禁止发布)")
        # 修复指引不受 --quiet 抑制: CI 里只看见 "FAIL" 却不知道改哪儿, 门禁就只是在制造噪音
        print("修复指引:")
        for i, (item, hint) in enumerate(fails, 1):
            print(f"  {i}. {item}")
            print(f"     └ 修: {hint}")
        sys.exit(1)
    if warns:
        print(f"结果: PASS (含 {len(warns)} 项告警, 建议人工确认)")
    else:
        print("结果: PASS (全部通过)")


if __name__ == "__main__":
    main()

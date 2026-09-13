#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preflight_release.py — 技能发布预检工具
=========================================
发布前一键检查 9 节：敏感信息扫描 / frontmatter 字段校验 / 必含文件检查 / git 未跟踪文件告警 /
归属检查 / 悬空引用检查 / 版本与 tag 一致性 / 评测宣称—证据一致性 / **结构规范检查**。
配套发布前 16 项检查清单（references/发布检查清单.md），本脚本自动覆盖第 1/3/5/6/16 项；
后三项属「说了要做就得拿得出证据」的规范项，均为 warning 级，不阻断发布。

第 9 节（结构规范检查）为 2026-09-12 吸收第三方结构校验器而来，含 10 项能力：
引用完整性 / description 触发面 / 保留词 / 无 README / 孤儿引用 / references 元数据 /
索引漂移 / 引号卫生 / 打包卫生 / 路由表 doNotUse。其中「影响使用」的 5 类为 warning
（`--strict` 阻断），整洁类 5 项只登记不判定（依据硬口径：不影响技能使用的问题一律不计为问题）。

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
                  悬空引用 / 版本回退 / 评测宣称无据 /
                  结构规范：引用完整性 / description 触发面 / 保留词 / 引号卫生
                  → WARN (exit 0); --strict 下 FAIL (exit 1)
  登记(不判定)     包内含 README / 孤儿引用 / references 缺加载元数据 / 索引体量漂移
                  → 只打印 `-` 行，不进 fails/warns，不影响退出码
  可豁免          warning 级全部 → --waive <项> --reason 落盘留痕; critical 级豁免会被拒绝

可豁免项 (--waive 的稳定 key, 见 WAIVABLE_KEYS):
  敏感类   localpath / homepath / email / password_format / phone
  结构类   author / untracked / ownership
  引用类   dangling_ref / version_tag / eval_claim / desc_face / reserved_word / quote_hygiene
  打包类   pack_hygiene
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
    "dangling_ref": "引用指向目标文件里不存在的章节 / 包内不存在的路径",
    "version_tag": "version 低于已有 tag(疑似版本回退)",
    "eval_claim": "声明了评测能力但无 evals/ 证据",
    # §9 结构规范检查——同属「应当满足」的规范项，一律 warning。
    "desc_face": "description 触发面：缺排他边界 / 触发词示例 / 自称构式 / 无动作动词",
    "reserved_word": "frontmatter 含品牌保留词 claude / anthropic",
    "quote_hygiene": "frontmatter 值含裸冒号 / 英文冒号 / 未加引号的多行纯量",
    # §9.9 打包卫生 —— warning。打包脚本排除名单只含 .pyc/.pyo 与 __pycache__，
    # 而 .bak/.tmp/~$*/.swp **不在名单里** ⇒ 这类文件真会被打进 SkillHub 包（真缺口）。
    "pack_hygiene": "打包卫生：临时/备份文件（.bak/.tmp/~$*/.swp）会被打进 SkillHub 包",
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
# 实测（批量体检）：锁定文件内的小写连字符标识符系统性命中
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

# ------------------------------------------------- 误报降噪：标识符 ≠ 凭据
# 实证（全量自研技能）：password_format 规则 0 真问题 / 60 行误报，
# 命中串 16 类**全部**是标识符——技能名片段（health-report-trend）、pip 包名
# （pyobjc-framework-Vision）、HTTP 头名（Access-Control-Allow）、CSS 属性名
# （webkit-scrollbar-thumb）、测试夹具名（contrast-normal-boundary）、仓库名
# （awesome-claude-skills）。手机号 7 行误报是 GitHub 用户名与测试假号；本机路径 2 行是
# 文档里的 `/Users/xxx` 占位符。
# ⚠️ 不用 --waive 压噪音（豁免是给零星个例的出口，不是清理批量噪音的拖把）——
#    **必须改规则本身**，否则换个技能名就复发。
# 判据：密码/密钥的实际形态是随机串（大小写数字混杂）；由**真实单词**拼成的 kebab 串是命名。
WORD_SEG_RE = re.compile(r"^[A-Za-z]+$")
VOWEL_RE = re.compile(r"[aeiouyAEIOUY]")
# 标准 HTTP 头 / CSS 厂商前缀（对「含数字因而过不了词形判据」的命中串兜底）
IDENTIFIER_PREFIXES = (
    "Access-Control-", "X-", "Content-", "Cache-", "Accept-", "Strict-", "Cross-",
    "Referrer-", "User-", "Sec-", "WWW-", "Upgrade-", "If-", "Set-Cookie",
    "-webkit-", "-moz-", "-ms-", "-o-", "webkit-", "moz-", "prefers-",
)
# 泛化占位符（文档里的示例值，不是真实信息）
PLACEHOLDER_TOKENS = {"xxx", "yyy", "zzz", "your", "yourname", "username", "user", "me",
                      "name", "example", "someone", "foo", "bar"}
# 常见样例号：测试夹具用的假号码，不是真实手机号
SAMPLE_PHONES = {"13800138000", "13800138001", "13900139000", "13100131000",
                 "18600186000", "18888888888", "13000000000"}


def _looks_like_identifier(s):
    """纯词形 kebab 串（每段全字母且含元音）→ 标识符，不是凭据。"""
    segs = [p for p in s.split("-") if p]
    return len(segs) >= 2 and all(WORD_SEG_RE.match(p) and VOWEL_RE.search(p) for p in segs)


def declared_dep_names(root):
    """收集已声明的依赖包名（requirements*.txt / package.json / *deps*.json）。

    依赖名天然是 kebab/npm 形态，会被密码正则命中；而「已声明为依赖」是强证据——
    它在依赖表里，不是凭据。
    """
    names = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            low = fn.lower()
            is_req = low.startswith("requirements") and low.endswith(".txt")
            is_json = low in ("package.json", "deps.json") or low.endswith(".deps.json")
            if not (is_req or is_json):
                continue
            text = scan_text(os.path.join(dirpath, fn)) or ""
            if is_json:
                try:
                    data = json.loads(text)
                except Exception:
                    continue
                stack = [data]
                while stack:
                    node = stack.pop()
                    if isinstance(node, dict):
                        stack.extend(node.keys())
                        stack.extend(node.values())
                    elif isinstance(node, list):
                        stack.extend(node)
                    elif isinstance(node, str):
                        for tok in re.findall(r"[A-Za-z][\w.\-]{2,}", node):
                            names.add(tok.lower())
            else:
                for line in text.splitlines():
                    line = line.split("#")[0].strip()
                    if not line:
                        continue
                    nm = re.split(r"[<>=!\[\];,\s]", line)[0].strip().lower()
                    if nm:
                        names.add(nm)
    return names


def _pw_exempt(s, exempt_names, dep_names):
    """password_format 命中串是否属「标识符」而非凭据（四层，逐层放宽）。"""
    low = s.lower()
    if low in exempt_names:                       # ① 技能自身名
        return True
    if any(low and low in n.lower() for n in exempt_names):   # ①' 技能名的片段（前缀被截）
        return True
    if low in dep_names:                          # ② 已声明的依赖名
        return True
    if s.startswith(IDENTIFIER_PREFIXES):         # ③ 标准 HTTP 头 / CSS 厂商前缀
        return True
    return _looks_like_identifier(s)              # ④ 纯词形 kebab 串 = 命名，不是随机串


def _phone_exempt(m, text):
    """手机号命中是否属误报：测试假号 / 低数字多样性 / 路径段（GitHub 用户名）。"""
    s = m.group(0)
    if s in SAMPLE_PHONES or len(set(s)) <= 4:
        return True
    if text[m.end():m.end() + 1] == "/" or text[max(0, m.start() - 1):m.start()] == "/":
        return True     # 形如 github.com/<11 位>/<repo> 或 "13098806890/repo" —— 是用户名，不是号码
    return text[max(0, m.start() - 11):m.start()].endswith("github.com/")


def _path_exempt(s):
    """本机/Home 路径命中是否属误报：`/Users/xxx`、`/home/your` 这类文档占位符。"""
    tail = s.rsplit("/", 1)[-1].lower()
    return tail in PLACEHOLDER_TOKENS or tail.startswith(("<", "$", "{"))

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

    exempt_names: 「标识符豁免」用的技能自身名（frontmatter name / slug / 目录名）。
    实证（多轮累积）：三段式 kebab-case 技能名与其
    **片段**必然命中 x-x-x 模式（health-report-trend 就是 health-report-trend-analysis
    被截出的前缀）；pip 包名 / HTTP 头名 / CSS 属性名 / 夹具名同理。这些是命名，不是凭据。
    只对 password_format / phone / localpath 三条规则生效，其余规则不受影响。

    ⚠️ 两条规则的分工（勿混淆）：
      · 本节豁免 = 「本就不该算命中」——发生在 --waive 之前，不进 suppressed，不算用户豁免；
      · --waive  = 「确实是命中，但本次放行」——落盘审计，计 suppressed。
      把前者塞进后者会用豁免拖把清理批量噪音，掩盖真实信噪比。
    """
    waived = set(waived)
    dep_names = declared_dep_names(root)
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
                # 误报降噪：先按规则做「标识符/占位符」豁免，再算豁免与告警。
                # ⚠️ 豁免发生在 --waive 之前，且**不计入 suppressed**：这两类不是「用户主动
                #    豁免掉的命中」，而是「本就不该算命中」，混在一起会让审计看不出真实豁免量。
                if key == "password_format":
                    hits = [m for m in hits if not _pw_exempt(m.group(0), exempt_names, dep_names)]
                elif key == "phone":
                    hits = [m for m in hits if not _phone_exempt(m, text)]
                elif key in ("localpath", "homepath"):
                    hits = [m for m in hits if not _path_exempt(m.group(0))]
                if not hits:
                    continue
                if key in waived:
                    suppressed[key] = suppressed.get(key, 0) + len(hits)
                    continue
                # 同文件同规则内按命中串去重：同一个值在一行里出现 3 次只是重复，
                # 不是 3 个问题（实测 lqy 的 deploy.sh 同一路径报 2 行、邮箱在 4 个文件各报 1 行）。
                uniq, seen_vals = [], set()
                for m in hits:
                    if m.group(0) in seen_vals:
                        continue
                    seen_vals.add(m.group(0))
                    uniq.append(m)
                shown = uniq[:MAX_HITS_PER_RULE]
                for m in shown:
                    snippet = m.group(0)
                    if len(snippet) > 24:
                        snippet = snippet[:12] + "…" + snippet[-8:]
                    item = f"{rel}: {desc} ({snippet})"
                    (critical if level == "critical" else warning).append(item)
                rest = len(uniq) - len(shown)
                if rest > 0:
                    item = f"{rel}: {desc}（另有 {rest} 处同类命中未逐条列出）"
                    (critical if level == "critical" else warning).append(item)
    return critical, warning, scanned, suppressed, skipped_lockfiles


def _collapse_hits(items):
    """把「同一命中串散在多个文件」折叠成一行汇总。

    ⚠️ 为什么是汇总而不是逐条：同一个邮箱/路径在 N 个文件里出现，是**一个问题**被重复记录，
    逐条列会让报告被同一条信息淹掉（实测 lqy 的同一个邮箱占 4 行）。折叠保留文件清单与处数，
    信息不丢但不再淹没；不同命中串仍各自成行，不会把真问题合并掉。
    """
    groups, order = {}, []
    for it in items:
        m = re.match(r"^(.*?): (.*)$", it)
        key, where = (m.group(2), m.group(1)) if m else (it, "")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(where)
    out = []
    for key in order:
        files = groups[key]
        if len(files) == 1:
            out.append(f"{files[0]}: {key}")
        else:
            shown = "、".join(f for f in files[:3] if f) + ("…" if len(files) > 3 else "")
            out.append(f"{key} —— {len(files)} 处（{shown}）")
    return out


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
    """提取 SKILL.md 顶部 --- 块的 key: value (零依赖简易解析, 值支持跨行折行)。

    返回值可被当作多层标量：`keep_empty` 见下。
    """
    fields, _ = parse_frontmatter_ex(path)
    return fields


def parse_frontmatter_ex(path):
    """返回 (fields, multiline_keys)。

    - `fields[key]` 已按 YAML 纯量规则把**缩进续行折成一行**。易错点：只取 `key:` 那一行，
      实测 `health-report-trend-analysis` 的 description 被读到 87 字（真值 290 字），
      后续校验全建立在残缺文本上——诊断会指向错误的原因（症状像「缺触发词」，
      真因是「值被解析器截断」）。诊断错因比漏报更坏，因为它把人引到错误的修法上。
    - `multiline_keys` 记录哪些 key 用了未加引号的多行纯量写法。这种写法 YAML 合法，
      但**跨解析器脆弱**（门禁 B 与部分平台解析器只取首行）⇒ 交引号卫生检查告警。
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None, set()
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return None, set()
    fields, multiline = {}, set()
    key = None
    for line in m.group(1).splitlines():
        raw = line.rstrip()
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        # 缩进续行：归并进上一个 key 的值（YAML 纯量折行）
        # ⚠️ 块序列（`- item`）与块标量（`|` / `>`）不算「多行纯量」：
        #    `tags:\n  - a\n  - b` 是标准 YAML 列表，所有解析器都认；判它脆弱是误报。
        if key and raw[:1] in (" ", "\t"):
            if raw.strip().startswith("-") or fields.get(key) in ("|", ">", "|-", ">-"):
                continue
            fields[key] = (fields[key] + " " + raw.strip()).strip()
            multiline.add(key)
            continue
        km = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", raw.strip())
        if km:
            key = km.group(1)
            fields[key] = km.group(2).strip().strip("\"'")
        else:
            key = None
    return fields, multiline


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
    易错点：文档里给的自检命令是整文件口径，含 frontmatter 会虚高（本技能实测差 400+ token），
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


# ---------------------------------------------------------------- 结构规范检查（§9）
# 来源：2026-09-12「吸收第三方结构校验器」决策（依据见工作区
# `双门禁必要性评估与吸收方案_20260912.md`）。保留其**不可替代**的 8 项能力：
#   引用完整性 / description 触发面 / 保留词 / 无 README / 孤儿引用 /
#   references 元数据 / 索引漂移 / 引号卫生
# 丢弃 preflight 已覆盖的 3 项：frontmatter 有效 · name↔目录一致 · 长度体积。
#
# 分级原则（沿用反模式 #22「自建门禁严于目标平台会把正确写法误杀」）：
#   影响使用  → warning，`--strict` 时阻断（引用完整性 / description 触发面 / 保留词 / 引号卫生）
#   整洁类    → info，**只登记不判定**。依据 2026-09-12 硬口径「不影响技能使用的问题一律
#               不计为问题」（包内含 README、孤儿引用、references 缺加载元数据均属此列）。
PKG_REL_RE = re.compile(r"(?<![\w/.\-])(?:\./)?(?:scripts|references|evals|assets)/\S+")
REF_META_KEYS = ("加载条件", "命中标签")
# 版本档案按惯例可不被正文引用；README 属包内文档，两者都不计入孤儿。
ORPHAN_WHITELIST = {"Changelog.md", "README.md", "CHANGELOG.md"}
RESERVED_WORDS = ("claude", "anthropic")

# §9.6 升级：判定「强路由句式」的三类成分（info 级统计口径，见 ref_meta_strong_phrase）
STRONG_SIGNAL_RE = re.compile(r"当|若|\bif\b|命中|出现")
STRONG_TARGET_RE = re.compile(r"\.md|references")
STRONG_TIME_RE = re.compile(r"之前|before|先")

# §9.9 打包卫生：`make_skillhub_zip.py` 的排除名单只覆盖 .pyc/.pyo 与 __pycache__，
# 下列形态**不在名单里** ⇒ 真会被打进发布包（warning）。
# 缓存文件不在扫描范围内——它们出不了包，且门禁自身运行就可能生成，报了只是噪音。
PACK_JUNK_SUFFIXES = (".bak", ".tmp", ".swp")
PACK_JUNK_PREFIXES = ("~$",)

# §9.10 路由表 doNotUse 列：表头含下列任一关键词即认作「路由表」
ROUTE_TABLE_HDR_KEYS = ("路由", "加载", "场景")
# 表头已写明「不路由到哪」的等价写法（英文按小写比较）
ROUTE_DONOTUSE_KEYS = ("不路由", "do not route", "donotuse", "不建议路由")


def file_ref_check(root):
    """扫 SKILL.md 正文**反引号内**的包内相对路径，判定文件是否存在。

    返回 (缺失列表, 跳过计数, 检查计数)。

    ⚠️ 四条防误报硬规则（每条都来自 2026-09-12 实测误报，缺一条就会重犯）：
      1. 串内含 `...` → 跳过（徽章示例 `...blue.svg` 被当成真实引用）
      2. 串含 `xxx` / `yyy` / `your*` / `<` `>` → 跳过（占位示例、外部技能路径）
      3. **整串即路径时按完整串解析，禁止按空格切分** —— `references/SKILL.md 编写规范.md`
         会被切成 `references/SKILL.md`（我方命名合法，**勿改名**）
      4. 命中 `<skill>/…` 形态 → SKIP（外部技能路径），不判 FAIL
    另外：`scripts/` 这类目录引用、以及相对 `references/` 解析的引用都算命中。
    """
    skill_md = os.path.join(root, "SKILL.md")
    text = scan_text(skill_md)
    if not text:
        return [], 0, 0
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)
    prefix_re = re.compile(r"^(?:\./)?(?:scripts|references|evals|assets)/")
    missing, skipped, checked = [], 0, 0
    seen = set()
    for seg in re.findall(r"`([^`\n]+)`", body):
        seg = seg.strip()
        if not seg:
            continue
        # 规则 1 / 2 / 4：占位符、省略写法、外部技能路径、通配/花括号一律跳过
        if any(ch in seg for ch in "<>{}"):
            skipped += 1
            continue
        if "..." in seg or "$" in seg:
            skipped += 1
            continue
        if re.search(r"(?:^|[^\w])(?:xxx|yyy|zzz|your\w*)(?:$|[^\w])", seg, re.I):
            skipped += 1
            continue
        if prefix_re.match(seg):
            # 规则 3：**整串即路径时按完整串解析**（`references/SKILL.md 编写规范.md` 含空格，
            # 按空格切分会被截成 `references/SKILL.md`）。逐个吸收后续词，取**第一个真实存在**
            # 的组合；一个都不存在时保留首个词。这样 `scripts/x.py --help` 不会被整串当路径，
            # 而 `references/全生命周期 10 步 + 认知底座.md` 这种多词文件名也不会被截断。
            toks = seg.split()
            best = toks[0]
            if not _ref_exists(root, best):
                acc = best
                for t in toks[1:]:
                    if t.startswith("-"):
                        break
                    acc += " " + t
                    if _ref_exists(root, acc):
                        best = acc
                        break
            cands = [best]
        else:
            cands = [m.group(0) for m in PKG_REL_RE.finditer(seg)]
        for cand in cands:
            cand = cand.rstrip("：:，,。;；）)】")
            if not cand or cand in seen:
                continue
            seen.add(cand)
            checked += 1
            if _ref_exists(root, cand):
                continue
            missing.append(cand)
    return missing, skipped, checked


def _ref_exists(root, cand):
    """引用是否可解析：相对技能根，或相对 references/（引用可能写在 references 内部）。"""
    for base in (root, os.path.join(root, "references")):
        if os.path.exists(os.path.normpath(os.path.join(base, cand))):
            return True
    return False


def desc_face_check(root):
    """调用**同目录** eval_trigger.py 的 `--desc-check`，取回 description 触发面未过项。

    复用而非重写：该脚本早已实现排他边界检查，且词表本身认「不适用」，比被吸收方更全
    （吸收的实质是**接线**，不是重新实现）。返回 (FAIL级项, WARN级项, 备注)。
    """
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_trigger.py")
    if not os.path.isfile(script):
        return [], [], "同目录下无 eval_trigger.py，跳过"
    try:
        # PYTHONDONTWRITEBYTECODE=1：不让子进程在被扫技能目录里写 __pycache__——
        # 门禁是只读的，不该在被扫对象上留下任何痕迹（回扫硬约束「被扫目录零污染」）。
        child_env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, script, root, "--desc-check"],
                           capture_output=True, text=True, timeout=60, env=child_env)
    except Exception as e:                       # noqa: BLE001 —— 工具缺失不该让发布门禁崩
        return [], [], f"调用 eval_trigger.py 失败（{e}），跳过"
    fails, warns = [], []
    for line in (p.stdout or "").splitlines():
        m = re.match(r"\s*[✗!]\s*\[(FAIL|WARN)\]\s*(.+)$", line)
        if not m:
            continue
        name = re.split(r"[（(]", m.group(2), maxsplit=1)[0].strip()
        (fails if m.group(1) == "FAIL" else warns).append(name)
    return fails, warns, None


def reserved_word_check(fm):
    """frontmatter 保留词（claude / anthropic 忽略大小写）。

    ⚠️ **只查 frontmatter**：正文里写 `CLAUDE.md` 是技术事实（引用官方文件名），合法。
    """
    return sorted(k for k, v in (fm or {}).items()
                  if any(w in str(v).lower() for w in RESERVED_WORDS))


def orphan_ref_check(root):
    """references/ scripts/ assets/ 下未被 SKILL.md 提及的文件（按文件名或 stem）。

    整洁类：只登记。`evals/` 刻意不查——评测夹具本就不该被正文逐个点名。
    """
    text = scan_text(os.path.join(root, "SKILL.md")) or ""
    orphans = []
    for sub in ("references", "scripts", "assets"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for dp, dns, fns in os.walk(d):
            dns[:] = [x for x in dns if x not in SKIP_DIRS]
            for fn in fns:
                if fn.startswith(".") or fn in ORPHAN_WHITELIST:
                    continue
                if fn in text or os.path.splitext(fn)[0] in text:
                    continue
                orphans.append(os.path.relpath(os.path.join(dp, fn), root))
    return sorted(orphans)


def ref_meta_check(root):
    """references/*.md 是否带渐进披露元数据（加载条件 / 命中标签）。返回 (缺, 总)。"""
    d = os.path.join(root, "references")
    if not os.path.isdir(d):
        return 0, 0
    mds = sorted(f for f in os.listdir(d) if f.endswith(".md"))
    lack = 0
    for fn in mds:
        text = (scan_text(os.path.join(d, fn)) or "").lstrip()
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
        if not m or not all(k in m.group(1) for k in REF_META_KEYS):
            lack += 1
    return lack, len(mds)


def ref_meta_strong_phrase(root):
    """§9.6 升级项（**info 级，绝不用作判定**）：统计 references 加载元数据是否为「强路由句式」。

    「强路由句式」= 键值里同时出现三类成分：
      ① 信号词（当 / 若 / if / 命中 / 出现）—— 说明「什么时候」加载
      ② 指向文件（含 .md 或 references）—— 说明「加载什么」
      ③ 时序词（之前 / before / 先）—— 说明「相对什么动作之前」

    只统计**已含两个键**的 references（缺键的由 ref_meta_check 原判定覆盖，不在这里重复计）。
    返回 (非强路由句式份数, 已判份数)。刻意只报**计数**不逐个刷屏：这份统计是「值得看一看」
    的提示，不是待办清单——逐条列出会把报告淹掉，反而没人看。
    """
    d = os.path.join(root, "references")
    if not os.path.isdir(d):
        return 0, 0
    weak = judged = 0
    for fn in sorted(f for f in os.listdir(d) if f.endswith(".md")):
        text = (scan_text(os.path.join(d, fn)) or "").lstrip()
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
        if not m:
            continue
        lines = m.group(1).splitlines()
        vals = []
        for i, line in enumerate(lines):
            for k in REF_META_KEYS:
                if not line.strip().startswith(k):
                    continue
                val = line.strip()[len(k):].lstrip(":：").strip()
                j = i + 1
                while j < len(lines) and lines[j][:1] in (" ", "\t") and lines[j].strip():
                    val += " " + lines[j].strip()
                    j += 1
                vals.append(val)
        if len(vals) < len(REF_META_KEYS):
            continue
        judged += 1
        v = " ".join(vals)
        if not (STRONG_SIGNAL_RE.search(v) and STRONG_TARGET_RE.search(v)
                and STRONG_TIME_RE.search(v)):
            weak += 1
    return weak, judged


def index_drift_check(root):
    """references/README.md 的体量列（`N 行`）与实际行数漂移 >5 行。返回 (漂移列表, 行数)。"""
    d = os.path.join(root, "references")
    readme = os.path.join(d, "README.md")
    text = scan_text(readme)
    if not text:
        return [], 0
    drifted, rows = [], 0
    for m in re.finditer(r"\[`([A-Za-z0-9_\-]+\.md)`\]", text):
        f = os.path.join(d, m.group(1))
        if not os.path.isfile(f):
            continue
        start = text.rfind("\n", 0, m.start()) + 1
        end = text.find("\n", m.end())
        row = text[start:end if end > 0 else len(text)]
        w = re.search(r"(\d+)\s*行\s*/", row)
        if not w:
            continue
        rows += 1
        actual = (scan_text(f) or "").count("\n") + 1
        if abs(int(w.group(1)) - actual) > 5:
            drifted.append(f"{m.group(1)}(索引 {w.group(1)} / 实际 {actual})")
    return drifted, rows


def quote_hygiene_check(root, ml_keys):
    """frontmatter 引号卫生。返回问题列表。

    三类冒号/截断坑，都必须拦在上传之前：
      ① 未加引号的值含「: 」裸冒号 → YAML 解析直接失败
      ② 值含英文冒号（即便加了引号）→ 部分平台按首个英文冒号截断，症状是「技能莫名不触发」
      ③ 未加引号的多行纯量 → 跨解析器脆弱（2026-09-12 实测：`health-report-trend-analysis`
         的 description 只被读到首行 87 字 / 真值 290 字，触发面后半段整体丢失）
    """
    text = scan_text(os.path.join(root, "SKILL.md")) or ""
    m = re.match(r"^---[ \t]*\n(.*?)\n---", text, re.S)
    if not m:
        return []
    issues = []
    for line in m.group(1).splitlines():
        if not line.strip() or line[:1] in (" ", "\t", "-"):
            continue
        mm = re.match(r"^([A-Za-z_][\w.\-]*)\s*:\s*(.*)$", line)
        if not mm:
            continue
        key, val = mm.group(1), mm.group(2).strip()
        if not val or val in ("|", ">", "|-", ">-", "[", "{"):
            continue
        if val[:1] not in ("'", '"'):
            if re.search(r":\s+", val):
                issues.append(f"{key} 值含裸冒号且未加引号（YAML 解析必失败）")
            probe = re.sub(r"(?i)https?://", "", val)
            if ":" in probe:
                issues.append(f"{key} 值含英文冒号（平台可能按首个冒号截断，触发面丢失）")
    for key in sorted(ml_keys):
        issues.append(f"{key} 值为未加引号的多行纯量（部分解析器只取首行，内容会被截断）")
    return issues


def pack_hygiene_check(root):
    """§9.9 打包卫生。返回**会被真打进包**的临时/备份文件列表（已排序、相对技能根）。

    只认 `.bak` / `.tmp` / `~$*` / `.swp`：打包脚本的排除名单只含 `.pyc` / `.pyo` 与
    `__pycache__`，这些形态不在名单里 ⇒ 会**真被打进 SkillHub 包**，是实打实的缺口。

    **刻意不报缓存文件**（`__pycache__/` 目录、`*.pyc`/`*.pyo`）：它们被打包脚本静默排除，
    出不了包；而且门禁自身运行时就可能生成它们——把「自己跑出来的缓存」写进自己的报告，
    只会给使用者制造需要解释的噪音。故一律不看。
    跳过 .git/（版本库内部文件不参与打包，扫它们等于制造噪音）。
    """
    junk = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        if os.path.basename(dirpath) == "__pycache__":
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.endswith(PACK_JUNK_SUFFIXES) or fn.startswith(PACK_JUNK_PREFIXES):
                junk.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(junk)


def _is_table_sep(line):
    """markdown 表格的分隔行（`|---|---|`）——只含 | - : 与空白，且至少各有一个。"""
    s = line.strip()
    if not s or any(ch not in "|-: " for ch in s):
        return False
    return "-" in s and "|" in s


def route_donotuse_check(root):
    """§9.10 路由表是否含 doNotUse 列（「不路由到」）。返回 'missing' / 'ok' / None。

    None = SKILL.md 里根本没有路由表 ⇒ 调用方打跳过行。**绝不报错、绝不误报**：
    只有「表头行含 路由/加载/场景 且下一行是表格分隔行」这一种形态才认作路由表，
    没有这种表就什么都不说——把「没有这张表」判成问题是典型误杀（多数技能不写路由表）。
    """
    text = scan_text(os.path.join(root, "SKILL.md"))
    if not text:
        return None
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)
    lines = body.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("|") or i + 1 >= len(lines) or not _is_table_sep(lines[i + 1]):
            continue
        if not any(k in s for k in ROUTE_TABLE_HDR_KEYS):
            continue
        low = s.lower()
        return "ok" if any(k in low for k in ROUTE_DONOTUSE_KEYS) else "missing"
    return None


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
    fm, ml_keys = (parse_frontmatter_ex(os.path.join(root, "SKILL.md"))
                   if os.path.exists(os.path.join(root, "SKILL.md")) else (None, set()))
    if fm is None:
        # github 平台可能是 skills/<name>/SKILL.md
        skill_root = root
        for dp, _, fns in os.walk(root):
            if "SKILL.md" in fns and "skills" in dp.split(os.sep):
                skill_root = dp
                break
        fm_dir = skill_root
        fm, ml_keys = parse_frontmatter_ex(os.path.join(skill_root, "SKILL.md"))
    exempt_names = {fm.get(k, "") for k in ("name", "slug") if fm} | {os.path.basename(root)}

    # 1. 敏感扫描
    critical, warning, scanned, suppressed, skipped_lockfiles = sensitive_scan(root, waived, exempt_names)
    critical, warning = _collapse_hits(critical), _collapse_hits(warning)
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

    # 9. 结构规范检查（影响使用项 warning，整洁项 info 只登记）
    log("── 9. 结构规范检查 ──")

    def _sec(level, msg, hint):
        """§9 统一出口：warning 进判定（--strict 阻断），info 只登记不判定。"""
        if level == "warn":
            log(f"  ⚠ [告警] {msg}")
            if args.strict:
                fails.append((msg, hint))
            else:
                warns.append(msg)
        else:
            log(f"  - {msg}")

    def _emit(key, msg, hint):
        """warning 级出口：`--waive` 的 key 在此生效。"""
        if key in waived:
            log(f"  - 已豁免: {key} — 理由: {reason}")
            return
        _sec("warn", msg, hint)

    # 9.1 description 触发面（复用 eval_trigger.py --desc-check）
    d_fails, d_warns, d_note = desc_face_check(root)
    if d_note:
        log(f"  - description 触发面: {d_note}")
    elif d_fails or d_warns:
        parts = []
        if d_fails:
            parts.append("硬性项未过（" + "、".join(d_fails) + "）")
        if d_warns:
            parts.append("建议项未过（" + "、".join(d_warns) + "）")
        _emit("desc_face",
              "description 触发面: " + "；".join(parts),
              "按 references/SKILL.md 编写规范.md §二 五要素 #1 补「适用 / 不适用」与口语触发词示例；"
              "明细跑 scripts/eval_trigger.py <技能目录> --desc-check")
    else:
        log("  ✓ description 触发面达标（无自称构式 / 有动作动词 / 有排他边界与触发词示例）")

    # 9.2 引用完整性（正文反引号内的包内相对路径）
    miss_ref, skip_ref, chk_ref = file_ref_check(root)
    if miss_ref:
        shown = "、".join(miss_ref[:4]) + ("…" if len(miss_ref) > 4 else "")
        _emit("dangling_ref",
              f"引用完整性: {len(miss_ref)} 处路径在包内不存在（{shown}）",
              "改成真实路径或删掉该引用；若为文档漂移（文档写的文件名已改），改文档；"
              "确属引用外部技能/文档可 --waive dangling_ref --reason \"...\"")
    else:
        log(f"  ✓ 引用完整性（已核 {chk_ref} 处包内路径"
            + (f"；按占位符/外部路径跳过 {skip_ref} 处" if skip_ref else "") + "）")

    # 9.3 无 README.md（整洁类：只登记。发布线建议按 Anthropic 规范移出包体）
    readme = os.path.join(root, "README.md")
    if os.path.isfile(readme):
        _sec("info",
             "包内含 README.md —— 发布线建议移出技能包（内容可并入 references/ 或仓库根 README）",
             "")
    else:
        log("  ✓ 无 README.md")

    # 9.4 保留词（只查 frontmatter）
    rw = reserved_word_check(fm)
    if rw:
        _emit("reserved_word",
              f"frontmatter 含保留词 claude/anthropic: {', '.join(rw)}",
              "改掉这些字段值里的品牌保留词（正文提及官方文件名不受影响）")
    else:
        log("  ✓ 保留词（frontmatter 无 claude/anthropic）")

    # 9.5 孤儿引用（整洁类：只登记）
    orph = orphan_ref_check(root)
    if orph:
        shown = "、".join(orph[:3]) + ("…" if len(orph) > 3 else "")
        _sec("info",
             f"孤儿引用: {len(orph)} 个文件存在但 SKILL.md 未提及（{shown}）", "")
    else:
        log("  ✓ 无孤儿引用")

    # 9.6 references 加载元数据（整洁类：只报计数）
    lack, total = ref_meta_check(root)
    if total == 0:
        log("  - references 加载元数据: 无 references/ 目录，跳过")
    elif lack:
        _sec("info",
             f"references 加载元数据: {lack}/{total} 份缺「{'/'.join(REF_META_KEYS)}」（索引无法按条件路由）",
             "")
    else:
        log(f"  ✓ references 加载元数据（{total} 份齐备）")
    # 9.6 升级：键「存在」≠ 键值可用 —— 额外统计键值是否「强路由句式」（**info 级，不判定**）
    weak_phr, judged_phr = ref_meta_strong_phrase(root)
    if judged_phr:
        if weak_phr:
            _sec("info",
                 f"references 路由句式: {weak_phr}/{judged_phr} 份非强路由句式"
                 f"（未同时出现 信号词/指向文件/时序词）—— 建议项，不影响发布", "")
        else:
            log(f"  ✓ references 路由句式（{judged_phr} 份均为强路由句式）")

    # 9.7 索引体量漂移（整洁类：只报计数）
    drift, rows = index_drift_check(root)
    if not rows:
        log("  - 索引体量漂移: 无 references/README.md 或索引无体量列，跳过")
    elif drift:
        _sec("info",
             f"索引体量漂移: {len(drift)} 份（{'、'.join(drift[:3])}）—— 会误导加载成本估算", "")
    else:
        log(f"  ✓ 索引体量与实际行数一致（{rows} 份，±5 行内）")

    # 9.8 frontmatter 引号卫生
    q_issues = quote_hygiene_check(root, ml_keys)
    if q_issues:
        _emit("quote_hygiene",
              "frontmatter 引号卫生: " + "；".join(q_issues),
              "给值加引号（YAML 失败）或改用中文全角「：」；多行纯量改写成单行或整体加引号")
    else:
        log("  ✓ frontmatter 引号卫生（无裸冒号 / 英文冒号 / 多行纯量）")

    # 9.9 打包卫生（只认会被真打进包的临时/备份文件；缓存文件不看——见函数说明）
    junk = pack_hygiene_check(root)
    if junk:
        shown = "、".join(junk[:3]) + (f" 等 {len(junk)} 个" if len(junk) > 3 else "")
        _emit("pack_hygiene",
              f"打包卫生: {len(junk)} 个临时/备份文件会被打进 SkillHub 包（{shown}）",
              "删除后重新打包，或确认不需要随包；确需保留可 "
              "--waive pack_hygiene --reason \"...\"")
    else:
        log("  ✓ 打包卫生（无 .bak/.tmp/~$/.swp）")

    # 9.10 路由表 doNotUse 列（信息级：条件触发，无路由表则跳过，绝不误报）
    route = route_donotuse_check(root)
    if route is None:
        log("  - 路由表 doNotUse: 无路由表，跳过")
    elif route == "missing":
        _sec("info",
             "路由表缺 doNotUse 列 —— 优秀实践要求路由表同时写明「不路由到哪」，"
             "只写「该读什么」会让不该触发的场景也被引到本技能", "")
    else:
        log("  ✓ 路由表 doNotUse（表头已含「不路由 / Do NOT route」）")

    # 10. 豁免落盘留痕（--skip-ownership 别名不进 waived, 故不落盘 —— 旧用法行为不变）
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

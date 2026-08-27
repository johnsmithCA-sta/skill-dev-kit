#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preflight_release.py — 技能发布预检工具
=========================================
发布前一键检查 5 项：敏感信息扫描 / frontmatter 字段校验 / 必含文件检查 / git 未跟踪文件告警 / 归属检查。
配套发布前 16 项检查清单（references/发布检查清单.md），本脚本自动覆盖第 1/3/5/6/16 项。

用法:
  python3 preflight_release.py <目录> [--platform skillhub|github] [--strict] [--quiet]

  --platform   frontmatter 与必含文件按平台规范校验 (默认: skillhub)
  --strict     低危告警(warning)也视为失败
  --quiet      只输出结果行

退出码: 0 = PASS(仅告警可放行)  1 = FAIL(存在高危问题)

敏感分级:
  critical  → 必然 FAIL (API key / 云凭据 / 明文 token)
  warning   → 默认仅告警, --strict 时 FAIL (本地路径 / 邮箱 / 疑似密码格式)

归属检查 (critical):
  author    → frontmatter author 字段必须非空
  copyright → 源码目录 LICENSE 必须含 "Copyright (c)" 行 (SkillHub 发布包排除 LICENSE, 但源码目录保留, 恒检查)

示例:
  python3 preflight_release.py path/to/my-skill --platform skillhub
  python3 preflight_release.py github-publish/my-skill --platform github --strict
"""
import argparse
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------- 敏感规则
SENSITIVE_RULES = [
    # (级别, 正则, 说明)
    ("critical", re.compile(r"skh_[A-Za-z0-9]{16,}"), "SkillHub API key"),
    ("critical", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    ("critical", re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "OpenAI API key"),
    ("critical", re.compile(r"\bAKID[A-Za-z0-9]{10,}"), "腾讯云 SecretId"),
    ("critical", re.compile(r'"secret_id"\s*[:=]\s*"[A-Za-z0-9]{16,}"'), "COS SecretId"),
    ("critical", re.compile(r'"secret_key"\s*[:=]\s*"[A-Za-z0-9+/=]{16,}"'), "COS SecretKey"),
    ("critical", re.compile(r'"token"\s*[:=]\s*"[A-Za-z0-9+/=]{30,}"'), "临时 token"),
    ("critical", re.compile(r"password\s*[:=]\s*['\"][^'\"]{6,}['\"]", re.I), "明文密码赋值"),
    ("warning", re.compile("/User" + "s/[A-Za-z0-9_]+"), "本机绝对路径"),
    ("warning", re.compile("/hom" + "e/[A-Za-z0-9_]+"), "Linux 用户路径"),
    ("warning", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "邮箱地址"),
    ("warning", re.compile(r"\b[A-Za-z0-9]{5,9}-[A-Za-z0-9]{5,9}-[A-Za-z0-9]{5,9}\b"), "疑似密码(x-x-x 格式)"),
    ("warning", re.compile(r"\b1[3-9]\d{9}\b"), "手机号"),
]

TEXT_EXTS = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".sh", ".cfg", ".ini", ".xml", ".html", ".css", ".js", ".ts"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
SKIP_FILES = {".DS_Store"}

# ---------------------------------------------------------------- 平台规范
REQUIRED_FIELDS = {
    "skillhub": ["name", "slug", "displayName", "summary", "description", "version", "license"],
    "github": ["name", "description", "version", "license"],
}
REQUIRED_FILES = {
    "skillhub": ["SKILL.md", "scripts"],
    "github": ["README.md", "LICENSE", "SKILL.md"],
}
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


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


def sensitive_scan(root):
    """返回 (critical列表, warning列表, 扫描文件数)。"""
    critical, warning, scanned = [], [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES or fn.endswith((".pyc", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".enex", ".db", ".ico")):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            text = scan_text(full)
            if text is None:
                continue
            scanned += 1
            for level, pattern, desc in SENSITIVE_RULES:
                m = pattern.search(text)
                if m:
                    snippet = m.group(0)
                    if len(snippet) > 24:
                        snippet = snippet[:12] + "…" + snippet[-8:]
                    item = f"{rel}: {desc} ({snippet})"
                    (critical if level == "critical" else warning).append(item)
    return critical, warning, scanned


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


def ownership_check(root, fm):
    """归属检查 (critical): author 非空 + LICENSE 含 Copyright 行。

    返回 (critical列表, info列表)。LICENSE 在 SkillHub 发布包中被排除,
    但源码目录必须保留且含正确版权行——故对源码目录恒检查。
    """
    critical, info = [], []
    author = (fm or {}).get("author", "").strip()
    if not author:
        critical.append("frontmatter 缺少 author 字段(归属锚点)")
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
    return critical, info


def main():
    ap = argparse.ArgumentParser(description="技能发布预检工具")
    ap.add_argument("target", help="待检查的目录")
    ap.add_argument("--platform", choices=["skillhub", "github"], default="skillhub")
    ap.add_argument("--strict", action="store_true", help="低危告警也视为失败")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--skip-ownership", action="store_true",
                    help="跳过归属检查(仅自用/第三方技能确不需要 author/LICENSE Copyright 时使用)")
    args = ap.parse_args()

    root = os.path.abspath(args.target)
    if not os.path.isdir(root):
        print(f"[FAIL] 目录不存在: {root}")
        sys.exit(1)

    fails, warns = [], []
    log = (lambda s: print(s)) if not args.quiet else (lambda s: None)

    # 1. 敏感扫描
    critical, warning, scanned = sensitive_scan(root)
    log(f"── 1. 敏感扫描 ({scanned} 个文本文件) ──")
    if not critical and not warning:
        log("  ✓ 未发现敏感信息")
    for item in critical:
        log(f"  ✗ [高危] {item}")
        fails.append(item)
    for item in warning:
        log(f"  ⚠ [告警] {item}")
        if args.strict:
            fails.append(item)
        else:
            warns.append(item)

    # 2. frontmatter 校验
    log(f"── 2. frontmatter 校验 (platform={args.platform}) ──")
    fm = parse_frontmatter(os.path.join(root, "SKILL.md")) if os.path.exists(os.path.join(root, "SKILL.md")) else None
    if fm is None:
        # github 平台可能是 skills/<name>/SKILL.md
        skill_root = root
        for dp, _, fns in os.walk(root):
            if "SKILL.md" in fns and "skills" in dp.split(os.sep):
                skill_root = dp
                break
        fm = parse_frontmatter(os.path.join(skill_root, "SKILL.md"))
    if fm is None:
        log("  ✗ 未找到 SKILL.md 或缺少 frontmatter (--- 块)")
        fails.append("SKILL.md frontmatter 缺失")
    else:
        missing = [k for k in REQUIRED_FIELDS[args.platform] if not fm.get(k)]
        if missing:
            log(f"  ✗ 缺少必需字段: {', '.join(missing)}")
            fails.append(f"frontmatter 缺字段: {missing}")
        else:
            ver = fm.get("version", "")
            ver_ok = bool(SEMVER.match(ver))
            log(f"  ✓ name={fm.get('name')} version={ver} {'✓' if ver_ok else '✗ 非语义化版本(需 X.Y.Z)'}")
            if not ver_ok:
                fails.append(f"version 格式错误: {ver}")

    # 3. 必含文件检查
    log("── 3. 必含文件检查 ──")
    for req in REQUIRED_FILES[args.platform]:
        p = os.path.join(root, req)
        if os.path.isfile(p):
            log(f"  ✓ {req}")
        elif os.path.isdir(p):
            n = len([f for _, _, fs in os.walk(p) for f in fs])
            log(f"  ✓ {req}/ ({n} 个文件)")
        else:
            # github 平台放宽: skills/<name>/SKILL.md
            if args.platform == "github" and req == "SKILL.md" and os.path.isdir(os.path.join(root, "skills")):
                found = [dp for dp, _, fns in os.walk(os.path.join(root, "skills")) if "SKILL.md" in fns]
                if found:
                    log(f"  ✓ skills/{os.path.relpath(found[0], os.path.join(root, 'skills'))}/SKILL.md")
                    continue
            log(f"  ✗ 缺少: {req}")
            fails.append(f"缺少必需文件: {req}")

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
        if args.strict:
            fails.append(f"git 未跟踪文件: {untracked}")
        else:
            warns.append(f"git 未跟踪文件: {len(untracked)} 个")

    # 5. 归属检查 (author + LICENSE Copyright 行)
    log("── 5. 归属检查 ──")
    if args.skip_ownership:
        log("  - --skip-ownership 指定, 跳过")
    else:
        own_critical, own_info = ownership_check(root, fm)
        for i in own_info:
            log(f"  ✓ {i}")
        for c in own_critical:
            log(f"  ✗ [高危] {c}")
            fails.append(c)
        if not own_critical:
            log("  ✓ 归属锚点齐备 (author + Copyright 行); homepage 仓库真实性请人工/gh api 核验")

    # 结果
    log("")
    if fails:
        print(f"结果: FAIL ({len(fails)} 项高危问题, 禁止发布)")
        sys.exit(1)
    if warns:
        print(f"结果: PASS (含 {len(warns)} 项告警, 建议人工确认)")
    else:
        print("结果: PASS (全部通过)")


if __name__ == "__main__":
    main()

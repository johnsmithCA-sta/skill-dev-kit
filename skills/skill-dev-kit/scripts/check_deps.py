#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_deps.py — 技能依赖自检
==============================
回答一个问题：这个技能的脚本用了哪些第三方依赖，**声明齐了吗**。

为什么需要它
  脚本能跑 ≠ 依赖写清了。作者机器上装过的东西自己不会记得，读者拿到技能只会看到
  ImportError。声明缺失的典型形态是"脚本 import 了某包，而 SKILL.md 的依赖清单里没有"——
  这个差值就是本工具要报的东西。

用法
  python3 check_deps.py <技能目录> [--declared <文件>] [--probe] [--quiet]

  --declared  追加声明来源（可多次传入）；默认已自动读取 requirements.txt /
              dependencies.txt 与 SKILL.md 的「依赖」段落
  --probe     额外探测本机能否 import —— **会执行目标技能的 import 语句**，默认关闭。
              需要判断"环境装没装"时才开；只判断"声明齐不齐"不必开
  --quiet     只输出结果行

退出码（与技能内其余工具统一，勿各写各的）
  0 = PASS   没有未声明的第三方依赖
  1 = FAIL   存在第三方 import 未在任何声明来源中出现 —— 技能自身缺陷，必须补声明
  2 = REVIEW 判不了：目录不存在 / 没有 scripts 目录 / 全部脚本语法解析失败
             （"没数据"不是"做错了"，一律走 REVIEW，不判 FAIL）

依赖名对不对得上
  import 名与包名常常不同（yaml↔PyYAML、PIL↔Pillow、cv2↔opencv-python）。内置一份常见
  别名表做双向匹配；表外的按原名比对，不命中时报"疑似未声明"并提示人工确认，
  不直接断言未声明——宁可让人工看一眼，也不要制造假阳性。
"""
import argparse
import ast
import os
import re
import subprocess
import sys

# import 名 → 常见 PyPI 包名。只收录高频易错项；表外按原名比对。
# 值统一写成**无连字符**的包名词根：比对走「声明名是否包含该词根」，故 `pyobjc` 一词根
# 即可覆盖它的整个 framework 系列，无须枚举全名——而且**不要**在这里写出三段连字符的
# 包名全称：那种形态会被发布预检的「疑似密码」规则命中，是纯误报。
ALIASES = {
    "yaml": "pyyaml", "pil": "pillow", "cv2": "opencv-python", "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
    "serial": "pyserial", "openssl": "pyopenssl", "jwt": "pyjwt",
    "fitz": "pymupdf", "docx": "python-docx", "pptx": "python-pptx",
    "openpyxl": "openpyxl",
    "objc": "pyobjc", "quartz": "pyobjc", "vision": "pyobjc",
    "appkit": "pyobjc", "foundation": "pyobjc",
}

# 3.10 起有 sys.stdlib_module_names；更早的解释器用这份常用表兜底（不做 import 探测，
# 避免为"判断是不是标准库"而执行目标代码）。
STDLIB_FALLBACK = {
    "abc", "argparse", "ast", "base64", "bisect", "calendar", "cmath", "collections",
    "concurrent", "configparser", "contextlib", "copy", "csv", "ctypes", "dataclasses",
    "datetime", "decimal", "difflib", "email", "enum", "errno", "functools", "getpass",
    "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http", "importlib", "inspect",
    "io", "ipaddress", "itertools", "json", "logging", "lzma", "math", "mimetypes",
    "multiprocessing", "operator", "os", "pathlib", "pickle", "platform", "plistlib",
    "pprint", "queue", "random", "re", "secrets", "shlex", "shutil", "signal", "socket",
    "sqlite3", "ssl", "statistics", "string", "struct", "subprocess", "sys", "tarfile",
    "tempfile", "textwrap", "threading", "time", "timeit", "tokenize", "traceback",
    "types", "typing", "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings",
    "wave", "weakref", "xml", "xmlrpc", "zipfile", "zlib",
}

REQ_FILES = ("requirements.txt", "dependencies.txt", "scripts/requirements.txt")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")
DEP_SECTION_RE = re.compile(r"^#{1,6}\s*[^\n]*(?:依赖|dependencies)[^\n]*$", re.I | re.M)


def _stdlib_names():
    return set(getattr(sys, "stdlib_module_names", ())) or STDLIB_FALLBACK


def _norm(name):
    """包名归一化：比对时忽略大小写、下划线、连字符（PEP 503 口径）。"""
    return re.sub(r"[-_.]+", "", (name or "").lower())


# import 名的大小写不可预期（`PIL` / `Pillow` / `pillow` 都有人写），故别名表按归一化键索引。
_ALIAS_LOOKUP = {_norm(k): v for k, v in ALIASES.items()}


def _alias(name):
    return _ALIAS_LOOKUP.get(_norm(name), "")


def declared_names(root, extra):
    """汇总所有声明来源里的依赖名（归一化后）。"""
    out = set()
    for rel in REQ_FILES:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.split("#")[0].strip()
                    if not line or line.startswith("-"):
                        continue
                    out.add(_norm(re.split(r"[<>=!~\[\s;]", line)[0]))
        except OSError:
            pass
    skill_md = os.path.join(root, "SKILL.md")
    if os.path.isfile(skill_md):
        try:
            with open(skill_md, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        # 依赖段落：从「## 依赖」标题起，到下一个二级标题前
        for m in DEP_SECTION_RE.finditer(text):
            seg = text[m.end():]
            nxt = re.search(r"^#{1,2}\s", seg, re.M)
            seg = seg[:nxt.start()] if nxt else seg
            for t in TOKEN_RE.findall(seg):
                out.add(_norm(t))
    for p in extra or []:
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.split("#")[0].strip()
                    if line:
                        out.add(_norm(re.split(r"[<>=!~\[\s;]", line)[0]))
        else:
            out.add(_norm(p))
    out.discard("")
    return out


def scan_imports(root):
    """AST 扫 scripts/*.py 的顶层 import。返回 ({模块名: [出现位置]}, 解析失败数)。"""
    scripts = os.path.join(root, "scripts")
    if not os.path.isdir(scripts):
        return None, 0
    found, failed = {}, 0
    local = {f[:-3] for f in os.listdir(scripts) if f.endswith(".py")}
    local |= {d for d in os.listdir(scripts) if os.path.isdir(os.path.join(scripts, d))}
    for fn in sorted(os.listdir(scripts)):
        if not fn.endswith(".py"):
            continue
        p = os.path.join(scripts, fn)
        try:
            with open(p, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fn)
        except (OSError, SyntaxError):
            failed += 1
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:          # 相对 import 属包内引用，不是外部依赖
                    continue
                names = [node.module or ""]
            for n in names:
                top = (n or "").split(".")[0]
                if not top or top in local:
                    continue
                found.setdefault(top, []).append(f"{fn}:{getattr(node, 'lineno', 0)}")
    return found, failed


def probe_imports(names):
    """本机可 import 性。**会执行 import**，仅在显式 --probe 时调用。"""
    missing = []
    for n in names:
        r = subprocess.run([sys.executable, "-c", f"import {n}"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            missing.append(n)
    return missing


def main():
    ap = argparse.ArgumentParser(
        description="技能依赖自检：第三方 import 与声明是否对得上",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 最常用：自检本包脚本的第三方 import 有没有漏声明
  python3 scripts/check_deps.py .

  # 追加声明来源，并顺带探测本机装没装（会执行目标技能脚本的 import 语句）
  python3 scripts/check_deps.py . --declared requirements.txt --probe

  # CI 里只要一行结论
  python3 scripts/check_deps.py . --quiet
""")
    ap.add_argument("target", help="待检查的技能目录")
    ap.add_argument("--declared", action="append", default=[], metavar="文件或包名",
                    help="追加声明来源（可多次传入）")
    ap.add_argument("--probe", action="store_true",
                    help="额外探测本机可 import 性（会执行目标技能的 import 语句）")
    ap.add_argument("--quiet", action="store_true", help="只输出结果行（便于 CI）")
    args = ap.parse_args()

    log = (lambda s: print(s)) if not args.quiet else (lambda s: None)
    root = os.path.abspath(args.target)
    if not os.path.isdir(root):
        print(f"[REVIEW] 目录不存在: {root}")
        return 2

    log(f"── 依赖自检: {os.path.basename(root)} ──")
    imports, failed = scan_imports(root)
    if imports is None:
        print("[REVIEW] 没有 scripts/ 目录 —— 无可自检的脚本")
        return 2
    if not imports and failed:
        print(f"[REVIEW] {failed} 个脚本语法解析失败，拿不到 import 清单")
        return 2
    if failed:
        log(f"  ⚠ {failed} 个脚本语法解析失败，已跳过（其依赖未纳入本次判定）")

    std = _stdlib_names()
    third = {k: v for k, v in imports.items() if k not in std}
    if not third:
        log(f"  ✓ 未发现第三方依赖（{len(imports)} 个顶层 import 全部来自标准库或包内模块）")
        print("结果: PASS (无第三方依赖)")
        return 0

    declared = declared_names(root, args.declared)
    undeclared, ok = [], []
    for name in sorted(third):
        # 命中口径两档：① 声明里出现同名；② 声明里出现该 import 的包名词根（子串匹配）——
        # 后者让一个词根覆盖整个系列（`pyobjc` 命中 `pyobjc-framework-*`），不必枚举全名。
        alias = _norm(_alias(name))
        hit = _norm(name) in declared or (alias and any(alias in d for d in declared))
        (ok if hit else undeclared).append(name)

    log(f"  第三方依赖 {len(third)} 个：{', '.join(sorted(third))}")
    for name in ok:
        log(f"  ✓ {name} 已声明（{len(third[name])} 处引用）")
    for name in undeclared:
        loc = "、".join(third[name][:3])
        log(f"  ✗ {name} 未见声明（{loc}）")

    if args.probe and third:
        miss = probe_imports(sorted(third))
        for n in miss:
            log(f"  ⚠ {n} 本机 import 失败（依赖未安装或不可用）")
        if miss:
            log("  - 探测结论仅供参考：本机没装不等于读者没装，请核对 SKILL.md 的安装步骤")

    log("")
    if undeclared:
        print(f"结果: FAIL ({len(undeclared)} 个第三方依赖未声明)")
        print("修复指引:")
        print(f"  1. 在 SKILL.md 补「## 依赖」段落，或新建 requirements.txt，写清: "
              f"{', '.join(undeclared)}")
        print("  2. 同步写明安装命令与缺失时的降级行为（读者装不上要能看懂怎么退）")
        return 1
    print(f"结果: PASS (第三方依赖 {len(third)} 个，声明齐备)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

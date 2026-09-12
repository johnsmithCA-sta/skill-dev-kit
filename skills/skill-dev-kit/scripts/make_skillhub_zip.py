#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_skillhub_zip.py — SkillHub 发布 ZIP 一键打包工具
======================================================
读取 SKILL.md frontmatter 的 version 作为版本号, 打包目录为
<顶层目录名>-v<version>.zip, 自动排除 .git/__pycache__ 等, 并校验 ≤10MB。

用法:
  python3 make_skillhub_zip.py <技能目录> [--out <输出路径>] [--no-version] [--keep-license]

  --out           指定输出 zip 路径 (默认: 技能目录同级/<顶层名>-v<version>.zip)
  --no-version    文件名不带版本号 (兼容旧版固定名)
  --keep-license  保留 LICENSE 文件 (默认排除: SkillHub 平台不允许 LICENSE 文件类型)

退出码: 0 = 成功  1 = 失败(超过 10MB / 无 version / 目录不存在)

踩坑记录(2026-08-16): SkillHub 发布接口返回 400 "不允许的文件类型: LICENSE"。
License 由 SKILL.md frontmatter 的 license 字段声明即可, 单独 LICENSE 文件必须排除。
"""
import argparse
import os
import re
import sys
import zipfile

MAX_SIZE = 10 * 1024 * 1024  # SkillHub 限制 ≤10MB
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".DS_Store",
             "output"}  # 2026-09-06: 排除运行时产物目录——health-report 的 .gitignore 明示 output/
# 可能含个人健康数据禁止入库；评测运行产物（stdout/stderr/timing）同属此类
SKIP_EXT = {".pyc", ".pyo"}
SKIP_FILES = {".DS_Store", ".preflight-waiver.json"}  # 2026-09-09: 豁免留痕件是本地审计产物, 不随包发布
SKIP_NAMES = {"LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"}  # SkillHub 不允许, 默认排除


def read_version(skill_dir):
    """从 SKILL.md frontmatter 提取 version。"""
    path = os.path.join(skill_dir, "SKILL.md")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r"^---\s*\n(.*?)\n---", text, re.S | re.M)
    if not m:
        return None
    for line in m.group(1).splitlines():
        km = re.match(r"^\s*version\s*:\s*([^\s#]+)", line)
        if km:
            return km.group(1).strip("\"'")
    return None


def make_zip(skill_dir, out_path, keep_license=False):
    """打包目录, 顶层文件夹名保留在 zip 内。"""
    top = os.path.basename(os.path.normpath(skill_dir))
    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(skill_dir):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn in SKIP_FILES or os.path.splitext(fn)[1] in SKIP_EXT:
                    continue
                if not keep_license and fn in SKIP_NAMES:
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.join(top, os.path.relpath(full, skill_dir))
                zf.write(full, rel)
                count += 1
    return count


def main():
    ap = argparse.ArgumentParser(
        description="SkillHub 发布 ZIP 一键打包",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 最常用：打包本技能（输出到同级目录，文件名带 frontmatter 里的 version）
  python3 scripts/make_skillhub_zip.py .

  # 指定输出路径，并保留 LICENSE 文件（默认排除）
  python3 scripts/make_skillhub_zip.py . --out /tmp/my-skill.zip --keep-license

  # 文件名不带版本号（兼容旧版固定名）
  python3 scripts/make_skillhub_zip.py . --no-version
""")
    ap.add_argument("skill_dir", help="技能目录 (含 SKILL.md)")
    ap.add_argument("--out", help="输出 zip 路径")
    ap.add_argument("--no-version", action="store_true", help="文件名不带版本号")
    ap.add_argument("--keep-license", action="store_true", help="保留 LICENSE 文件 (默认排除)")
    args = ap.parse_args()

    skill_dir = os.path.abspath(args.skill_dir)
    if not os.path.isdir(skill_dir):
        print(f"[FAIL] 目录不存在: {skill_dir}")
        sys.exit(1)

    version = read_version(skill_dir)
    top = os.path.basename(skill_dir)
    if args.out:
        out_path = args.out
    else:
        parent = os.path.dirname(skill_dir)
        if version and not args.no_version:
            out_path = os.path.join(parent, f"{top}-v{version}.zip")
        else:
            out_path = os.path.join(parent, f"{top}.zip")

    count = make_zip(skill_dir, out_path, keep_license=args.keep_license)
    size = os.path.getsize(out_path)
    ok = size <= MAX_SIZE
    print(f"✓ 打包完成: {out_path}")
    print(f"  文件数: {count} | 大小: {size/1024:.1f} KB ({size/1024/1024:.2f} MB) | version: {version or '未读取'}")
    if not ok:
        print(f"[FAIL] 超过 SkillHub 10MB 限制, 请精简后重试")
        os.remove(out_path)
        sys.exit(1)
    if not version:
        print("[告警] 未从 SKILL.md 读到 version, 建议补齐 frontmatter")
    print("结果: PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()

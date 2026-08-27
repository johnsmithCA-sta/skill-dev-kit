#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_gh_ruleset.py — GitHub tag 保护 ruleset 一键创建工具
===========================================================
用完整 JSON body 通过 gh api 创建 ruleset (规避 -f/--input 混用的 422 坑)。
默认创建 tag 保护: 禁止删除 tag + 禁止强制覆盖 (non-fast-forward)。

用法:
  python3 setup_gh_ruleset.py [--repo owner/repo] [--name "Tag Protection"]
        [--pattern "refs/tags/*"] [--rules deletion,non_fast_forward]
        [--enforcement active|evaluate|disabled] [--dry-run] [--list]

  --repo      owner/repo; 缺省时从当前目录 git remote origin 解析
  --pattern   完整 ref 语法 (如 "refs/tags/*"); 不传则对所有 tag 生效 (推荐)
  --dry-run   只打印将发送的 JSON body, 不真正创建
  --list      列出现有 rulesets 后退出

退出码: 0 = 成功  1 = 失败 / 同名 ruleset 已存在(需手动处理)
"""
import argparse
import json
import os
import subprocess
import sys

DEFAULT_RULES = ["deletion", "non_fast_forward"]
DEFAULT_PATTERN = ""  # 默认空: 对所有 tag 生效 (推荐, 避免 ref 语法 422 坑)
DEFAULT_NAME = "Tag Protection"


def gh(*args, input_text=None):
    """调用 gh CLI, 返回 (ok, stdout)。"""
    cmd = ["gh"] + list(args)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            input=input_text,
        )
    except FileNotFoundError:
        print("[FAIL] 未找到 gh CLI, 请先安装并加入 PATH (export PATH=$HOME/.local/bin:$PATH)")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("[FAIL] gh 调用超时 (网络问题?), 请重试")
        sys.exit(1)
    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, proc.stdout.strip()


def resolve_repo(cwd):
    """从 git remote origin 解析 owner/repo。"""
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        out = ""
    if not out:
        return None
    out = out.replace("https://github.com/", "").replace("git@github.com:", "").replace(".git", "")
    parts = [p for p in out.split("/") if p]
    return "/".join(parts[:2]) if len(parts) >= 2 else None


def build_body(name, pattern, rules, enforcement):
    """默认不带 conditions (对所有 tag 生效, 与已验证的 evernote-to-ima 一致)。

    踩坑记录(2026-08-16): 传 pattern="v*" 时 conditions.ref_name.include=["v*"]
    会触发 422 Validation Failed —— GitHub 要求完整 ref 语法如 "refs/tags/*"。
    省略 conditions (或空 {}) 即对所有 tag 生效, 是最稳妥的配置。
    """
    body = {
        "name": name,
        "target": "tag",
        "enforcement": enforcement,
        "rules": [{"type": r} for r in rules],
    }
    if pattern:
        body["conditions"] = {"ref_name": {"include": [pattern], "exclude": []}}
    return body


def list_rulesets(repo):
    ok, out = gh("api", f"repos/{repo}/rulesets", "--jq", ".[] | .name + \" | \" + .target + \" | \" + .enforcement")
    if not ok:
        print(f"[FAIL] 查询 rulesets 失败: {out}")
        sys.exit(1)
    return [ln for ln in out.splitlines() if ln.strip()]


def main():
    ap = argparse.ArgumentParser(description="GitHub tag 保护 ruleset 一键创建")
    ap.add_argument("--repo", help="owner/repo, 缺省从 git remote 解析")
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--pattern", default=DEFAULT_PATTERN)
    ap.add_argument("--rules", default=",".join(DEFAULT_RULES), help="逗号分隔的规则类型")
    ap.add_argument("--enforcement", default="active", choices=["active", "evaluate", "disabled"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    repo = args.repo or resolve_repo(os.getcwd())
    if not repo:
        print("[FAIL] 无法解析仓库: 请用 --repo owner/repo 或在该 git 仓库目录下运行")
        sys.exit(1)
    print(f"仓库: {repo}")

    if args.list:
        items = list_rulesets(repo)
        if not items:
            print("  当前无 rulesets")
        else:
            for it in items:
                print(f"  - {it}")
        sys.exit(0)

    rules = [r.strip() for r in args.rules.split(",") if r.strip()]
    body = build_body(args.name, args.pattern, rules, args.enforcement)
    body_json = json.dumps(body, ensure_ascii=False, indent=2)

    # dry-run 只打印不创建, 先于同名检测
    if args.dry_run:
        print("── dry-run: 将发送的 JSON body ──")
        print(body_json)
        print("结果: PASS (dry-run 未实际创建)")
        sys.exit(0)

    # 同名检测 (仅实际创建时)
    existing = list_rulesets(repo)
    dup = [it for it in existing if it.startswith(args.name + " ")]
    if dup:
        print(f"[FAIL] 同名 ruleset 已存在: {dup[0]}")
        print("  处理: 换 --name, 或先删除旧 ruleset 再创建")
        sys.exit(1)

    ok, out = gh(
        "api", "-X", "POST", f"repos/{repo}/rulesets", "--input", "-",
        input_text=body_json,
    )
    if not ok:
        print(f"[FAIL] 创建失败: {out}")
        print("  提示: 确认 gh 已认证且有仓库 admin 权限 (gh auth status)")
        sys.exit(1)
    try:
        data = json.loads(out)
        print(f"✓ ruleset 创建成功: {data.get('name')} (id={data.get('id')})")
        print(f"  target={data.get('target')} | enforcement={data.get('enforcement')}")
        print(f"  规则: {', '.join(r.get('type') for r in data.get('rules', []))}")
        print(f"  管理页: {data.get('_links', {}).get('html', {}).get('href', '')}")
    except json.JSONDecodeError:
        print(f"✓ ruleset 创建成功 (响应解析失败, 原始输出): {out[:200]}")
    sys.exit(0)


if __name__ == "__main__":
    main()

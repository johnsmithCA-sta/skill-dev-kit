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
  --pattern   完整 ref 语法 (默认 "refs/tags/*"); 写 v* 会 422, 传空串等于规则没建
  --dry-run   只打印将发送的 JSON body, 不真正创建
  --list      列出现有 rulesets (含 conditions; refs 为空会标注「形同虚设」) 后退出

创建后会**回读 conditions 自证**：为空表示规则不匹配任何 ref（形同虚设），此时退出码为 1。

退出码: 0 = 成功且条件自证通过  1 = 失败 / 同名 ruleset 已存在 / 条件自证未通过
"""
import argparse
import json
import os
import re
import subprocess
import sys

DEFAULT_RULES = ["deletion", "non_fast_forward"]
# ⚠️ 必须**显式**写 conditions（2026-10-01 实测更正）：
#   旧版本默认留空，注释还写着「省略 conditions 即对所有 tag 生效」——**实测不成立**。
#   线上一个 conditions 为空的 ruleset 长期形同虚设：删 tag 不被拦，而 GitHub 不报错、
#   脚本也不报错。空 conditions 语义上就是「不匹配任何 ref」，不是「匹配全部」。
#   正确写法是完整 ref 语法 `refs/tags/*`（`v*` 这类写法会触发 422）。
DEFAULT_PATTERN = "refs/tags/*"
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
    # 支持 https://host/owner/repo(.git) 与 git@host:owner/repo(.git) 两种形态。
    # 用「scheme/host + 路径」的正则一次剥离，不再写死主机名 ——
    # 写死 github.com 会漏掉 GitHub Enterprise / 自建 Git，且字面量本身就是脱敏扫描的误报源。
    m = re.match(r"^(?:https?://|git@)([^/:]+)[/:](.+?)(?:\.git)?/?$", out)
    if not m:
        return None
    parts = [p for p in m.group(2).split("/") if p]
    return "/".join(parts[:2]) if len(parts) >= 2 else None


def build_body(name, pattern, rules, enforcement):
    """构造 ruleset body；conditions **始终写入**。

    踩坑记录：传 pattern="v*" 时 conditions.ref_name.include=["v*"] 会触发 422 Validation
    Failed —— GitHub 要求**完整 ref 语法**（`refs/tags/*`）。正确做法是把 pattern 写对，
    **不是**省略 conditions：空的 conditions 不匹配任何 ref，规则等于没建（详见 DEFAULT_PATTERN 注释）。
    """
    body = {
        "name": name,
        "target": "tag",
        "enforcement": enforcement,
        "rules": [{"type": r} for r in rules],
        "conditions": {"ref_name": {"include": [pattern], "exclude": []}},
    }
    return body


def verify_conditions(repo, rid):
    """回读刚创建的 ruleset，确认 `conditions.ref_name.include` 非空。返回是否通过。

    为什么必须回读：**「建好了」与「真的在拦」是两件事**。conditions 为空的 ruleset 不匹配任何 ref，
    删 tag 照样成功，而创建接口返回成功、GitHub 也不会警告 —— 唯一能发现的办法就是拿返回体自证。
    """
    ok, out = gh("api", f"repos/{repo}/rulesets/{rid}")
    if not ok:
        print(f"  ⚠️ 条件回读失败（{out[:80]}）—— 自证未完成，请人工核对 conditions")
        return False
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        print("  ⚠️ 条件回读解析失败 —— 自证未完成，请人工核对 conditions")
        return False
    inc = ((data.get("conditions") or {}).get("ref_name") or {}).get("include") or []
    if inc:
        print(f"  ✓ 条件自证：ref_name.include = {inc}（非空 ⇒ 才真的在拦）")
        return True
    print("  ✗ conditions 为空 ⇒ **该 ruleset 形同虚设**（不匹配任何 ref、删 tag 不被拦）"
          "—— 请用 --pattern refs/tags/* 重建")
    return False


def print_probe_hint():
    """打印行为探针指引。⚠️ 探针必须是**可牺牲**的 tag。"""
    print("  行为探针（建议做一次）：")
    print("    1) 建可牺牲的探针 tag —— **别拿真版本 tag 试删除**"
          "（2026-10-01 有先例：用真 tag 试，把 release 打成了 draft）")
    print("       git tag probe-rule-check && git push origin probe-rule-check")
    print("    2) gh api -X DELETE repos/<owner>/<repo>/git/refs/tags/probe-rule-check")
    print("       期望：被拒（Repository rule violations / Cannot delete this tag）")
    print("    3) 清理探针要先临时把 ruleset 置 disabled，删完再恢复 active")


def list_rulesets(repo):
    """列出现有 rulesets（含 conditions）。返回 [(id, name, target, enforcement, include_list)]。

    ⚠️ **列表接口不返回 conditions** —— `GET /rulesets` 的字段里根本没有它，只有
    `_links/created_at/enforcement/id/name/node_id/source/source_type/target/updated_at`。
    直接用列表结果判「refs 是否为空」，会对**每一个** ruleset 都误报「形同虚设」
    （这条假阳性在本工具首次实战时就把一个**已修好**的 ruleset 又报了一遍）。
    ⇒ 必须逐个取详情 `GET /rulesets/{id}`；取不到时 `include` 记 None（**不判定**，宁可不报也不误报）。
    """
    ok, out = gh("api", f"repos/{repo}/rulesets", "--jq",
                 '.[] | (.id | tostring) + " | " + .name + " | " + .target + " | " + .enforcement')
    if not ok:
        print(f"[FAIL] 查询 rulesets 失败: {out}")
        sys.exit(1)
    rows = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        parts = [p.strip() for p in ln.split("|", 3)]
        if len(parts) < 4:
            continue
        rid, name, target, enforcement = parts
        include = None
        ok2, det = gh("api", f"repos/{repo}/rulesets/{rid}")
        if ok2:
            try:
                d = json.loads(det)
                include = ((d.get("conditions") or {}).get("ref_name") or {}).get("include") or []
            except json.JSONDecodeError:
                include = None
        rows.append((rid, name, target, enforcement, include))
    return rows


def main():
    ap = argparse.ArgumentParser(
        description="GitHub tag 保护 ruleset 一键创建",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 最常用：所在仓库先干跑，只打印将发送的 JSON body（不创建）
  python3 scripts/setup_gh_ruleset.py --dry-run

  # 列出现有 rulesets（仓库默认从当前目录的 git remote 解析）
  python3 scripts/setup_gh_ruleset.py --list

  # 带可选参数：改名称与规则类型，仍然只干跑
  python3 scripts/setup_gh_ruleset.py --dry-run --name "Tag Protection" --rules deletion,non_fast_forward
""")
    ap.add_argument("--repo", help="owner/repo, 缺省从 git remote 解析")
    ap.add_argument("--name", default=DEFAULT_NAME, help=f"ruleset 名称（默认 {DEFAULT_NAME}）")
    ap.add_argument("--pattern", default=DEFAULT_PATTERN,
                    help=f"生效的 ref 匹配（默认 {DEFAULT_PATTERN}）。必须是**完整 ref 语法**，"
                         "写 v* 会 422；**不要传空串**——空 conditions 不匹配任何 ref，规则等于没建")
    ap.add_argument("--rules", default=",".join(DEFAULT_RULES), help="逗号分隔的规则类型")
    ap.add_argument("--enforcement", default="active", choices=["active", "evaluate", "disabled"],
                    help="生效模式：active 生效 / evaluate 只评估不拦 / disabled 停用")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印将发送的 JSON，不实际创建")
    ap.add_argument("--list", action="store_true", help="列出现有 rulesets")
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
            for rid, name, target, enforcement, include in items:
                if include is None:
                    refs_txt, flag = "conditions 未取到，未判定", ""
                elif include:
                    refs_txt, flag = "、".join(include), ""
                else:
                    refs_txt = "（空）"
                    flag = "   ⚠️ refs 为空 ⇒ 形同虚设（不匹配任何 ref，删 tag 不被拦）"
                print(f"  - {name} | {target} | {enforcement} | refs={refs_txt} | id={rid}{flag}")
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
        rid = data.get("id")
    except json.JSONDecodeError:
        print(f"✓ ruleset 创建成功 (响应解析失败, 原始输出): {out[:200]}")
        rid = None

    # 创建成功 ≠ 真的在拦：回读条件自证，空 conditions 直接判失败（响亮失败 > 静默无效）
    ok_cond = verify_conditions(repo, rid) if rid else False
    if not ok_cond:
        print("  ⚠️ 自证未通过：请核对上面的 conditions，必要时重建")
    print_probe_hint()
    sys.exit(0 if ok_cond else 1)


if __name__ == "__main__":
    main()

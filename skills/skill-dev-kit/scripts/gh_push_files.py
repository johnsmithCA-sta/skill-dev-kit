#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gh_push_files.py — git push 不可用时的兜底：用 GitHub Contents API 推送整个目录
=====================================================================================
何时用
  git push 连续失败且降级无效时（典型签名：走代理报
  `CONNECT tunnel failed, response 502`；直连报 `Recv failure: Operation timed out`；
  或 `Error in the HTTP2 framing layer`）。此时 gh 仍然可用，改走 API。

适用场景
  · 首次推送一个本地建的仓库（无需 git remote 可用）
  · 只改少数文件、不需要本地 git 历史
  不适用：需要保留完整提交历史 / 大量文件（逐文件 PUT 会慢）

用法
  python3 gh_push_files.py <本地目录> <owner/repo> [branch] [commit message]
  # 例：python3 gh_push_files.py ./my-skill johnsmithCA-sta/my-skill main "feat: v1.0.0"

注意
  · 已存在的文件会自动带上 sha（先 GET 再 PUT），因此可重复运行做增量同步
  · 每次运行都是**独立提交**，不做 git 历史重写
  · 依赖已登录的 gh CLI（`gh auth status` 通过）
"""
import argparse
import base64
import json
import os
import subprocess
import sys

EXCLUDE_DIRS = {".git", "__pycache__", ".DS_Store", "node_modules"}


def gh(method, path, payload=None):
    cmd = ["gh", "api", "-X", method, path, "-H", "Accept: application/vnd.github+json"]
    if payload is not None:
        cmd += ["--input", "-"]
    p = subprocess.run(cmd,
                       input=json.dumps(payload) if payload is not None else None,
                       capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def walk_files(root):
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in EXCLUDE_DIRS]
        for f in sorted(fn):
            full = os.path.join(dp, f)
            yield full, os.path.relpath(full, root).replace(os.sep, "/")


def main():
    ap = argparse.ArgumentParser(
        description="git push 不可用时的兜底：逐文件推送整个目录到远端仓库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  # 最常用：把当前技能目录整体推到目标仓库的 main 分支
  python3 scripts/gh_push_files.py . "$REPO_SLUG"

  # 指定分支与提交信息
  python3 scripts/gh_push_files.py . "$REPO_SLUG" release "chore: 同步发布包"

  # 四个位置参数同序，只有后两个可省略
  python3 scripts/gh_push_files.py . "$REPO_SLUG" main "feat: 首次推送"
""")
    ap.add_argument("repo_dir", help="要推送的本地目录（如 . 表示当前目录）")
    ap.add_argument("slug", help="目标仓库，owner/repo 形式；建议由环境变量传入，"
                                 "不要把真实仓库名写死在本技能里")
    ap.add_argument("branch", nargs="?", default="main", help="目标分支（默认 main）")
    ap.add_argument("message", nargs="?", default="sync via Contents API", help="提交信息")
    args = ap.parse_args()

    repo_dir, slug = args.repo_dir, args.slug
    branch, message = args.branch, args.message

    rc, _, err = gh("GET", f"repos/{slug}")
    if rc != 0:
        print(f"❌ 仓库不可达或未认证：{slug}\n   {err[:200]}")
        return 1

    ok, failed = [], []
    for full, rel in walk_files(repo_dir):
        with open(full, "rb") as fh:
            content = base64.b64encode(fh.read()).decode()
        payload = {"message": message, "content": content, "branch": branch}
        rc, out, _ = gh("GET", f"repos/{slug}/contents/{rel}?ref={branch}")
        if rc == 0 and out:                       # 已存在 → 带上 sha 覆盖
            try:
                payload["sha"] = json.loads(out)["sha"]
            except Exception:
                pass
        rc, out, err = gh("PUT", f"repos/{slug}/contents/{rel}", payload)
        if rc == 0:
            ok.append(rel)
            print(f"  ✓ {rel}")
        else:
            failed.append(rel)
            print(f"  ✗ {rel} → {err[:160]}")

    print(f"\n成功 {len(ok)} / 失败 {len(failed)}")
    if failed:
        print("失败清单：" + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

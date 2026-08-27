# skill-dev-kit — 技能固化与发布工具包

把可复用工作流固化为 Skill 并安全发布的全周期工具包。

## 内容

- `skills/skill-dev-kit/SKILL.md` — 主技能：固化判定 → 目录三件套 → 四层测试闭环 → 两轮脱敏审查 → 发布前检查清单 → 双平台发布（SkillHub / GitHub）→ 复盘反哺
- `skills/skill-dev-kit/scripts/` — 5 个零依赖脚本：
  - `preflight_release.py` 发布前一键预检（敏感扫描 / frontmatter 校验 / 必含文件 / git 未跟踪告警）
  - `make_skillhub_zip.py` 一键打包（自动排除 LICENSE，版本命名）
  - `setup_gh_ruleset.py` GitHub tag 保护 ruleset
  - `eval_trigger.py` 触发词评估
  - `eval_loop.py` 评测循环
- `skills/skill-dev-kit/references/` — 发布检查清单、脚本速查、方法论沉淀
- `skills/skill-dev-kit/evals/` — 自评测用例与 benchmark

## 归属

作者与许可证见 [`LICENSE`](LICENSE)（MIT, Copyright (c) 2026 johnsmithCA-sta）。
发布渠道：[SkillHub](https://skillhub.cn)（同名技能）与本仓库。

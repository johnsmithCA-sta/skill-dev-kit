# skill-dev-kit — 技能固化与发布工具包

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg) ![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg) ![Release](https://img.shields.io/badge/Release-v1.13.1-green.svg) ![SkillHub](https://img.shields.io/badge/SkillHub-@user_65c8c185%2Fskill-dev-kit-orange.svg)

**English** — Toolkit for turning a hard-won workflow into a reusable Agent Skill, and shipping it safely: release preflight, packaging, tag protection, trigger-phrase evaluation and an eval loop. Zero third-party dependencies, pure Python stdlib.

Writing a skill is easy. **Daring to publish it is the hard part** — did any secret leak through, is the attribution right, will the platform route the trigger phrases correctly, which step of the release chain will blow up. This kit turns that pre-publish uncertainty into executable checks.

**Install / 安装**

```bash
skillhub install skill-dev-kit --namespace user_65c8c185
# or / 或
git clone https://github.com/johnsmithCA-sta/skill-dev-kit.git
```

---

把「踩过坑的工作流」固化为可复用 Skill，并安全发布到 SkillHub 与 GitHub 的全周期工具包。内置发布门禁、评测闭环与 14 份方法论参考文档，让下一个同类技能跳过重复探索，开发成本预计降低 30%–50%。

## 它解决什么问题

写一个 Skill 不难，难的是**敢不敢发**：敏感信息有没有漏、归属权益清不清楚、触发词能不能被平台正确路由、发布链条哪一步会翻车。本工具包把这套「发布前的确定性」做成可执行资产：

- **16 项发布前检查清单**：从敏感扫描、版本治理、归属核验到发布后验证，逐项勾选，全部通过才放行；清单按**改动类型分级**——小改动只跑该跑的人工项，自动项永远全跑不裁。
- **发布预检门禁**：一键扫描敏感信息、校验 frontmatter、核对必含文件与归属锚点、检查文档间的章节引用是否还成立、核对版本与 tag 是否回退、验证「声明了评测能力」有没有对应证据；高危项阻断发布，告警项带理由豁免并落盘留痕，每条失败附带修复指引——可直接接入 CI。
- **依赖自检**：静态扫出脚本 import 了哪些第三方包，对照依赖声明报出漏写的那些——脚本能跑不等于读者能跑。
- **五层测试闭环**：端到端 → 合成 → 增强 → 真实数据，外加**基线对照**（同 prompt 跑不带技能的版本）与错误路径 100% 拦截。正确路径通过不算数——带技能版本须在关键指标上可量化优于基线。
- **双平台发布流程**：SkillHub 目录直发 + GitHub tag 保护，10 步流程逐标「可重试 / 不可逆」，每类失败配好降级路径。
- **面向用户端写作红线**：SKILL.md / README 只写「怎么用」——版本治理章、实测日期与过程数据、变更来源与内部动因、维护者指令、「付费上架」类商业意图、`v1.x 新增` 标注、单一平台品牌绑定一律不入文，并给出逐类改写规则（见 `references/SKILL.md 编写规范.md` §4.1）。
- **14 份方法论参考文档**：编写规范、评测方法论、市场调研、反模式清单、调试三步法、知识产权边界判定——按需渐进加载。

## 独创性

- **门禁分级与豁免审计**：critical 只能修、warning 可带理由豁免且留痕落盘——「豁免 0 处也记录」，让每次放行可审计、可追责。
- **双口径触发评估**：正文触发词口径回答「触发词写全了没」，description 口径回答「平台能不能把用户说法路由过来」——两个口径不共用一把尺，可发现性第一次可度量。
- **三态评测循环**：PASS / FAIL / REVIEW 三态退出码，无数据不判不合格、低分不放行——评测结果可以直接当 CI 门禁用。
- **面向用户端写作红线**：把「文档该给谁看」从经验上升为可勾选清单——10 类开发过程信息逐条列出禁止写法与改写动作，配判定问句「这一行，使用者看了能帮他决定怎么用吗」（§4.1）。
- **知识产权边界与护城河判定**：发布前先反向检查「入包的是谁的知识产权」，用「可推导性 × 能力依赖性」两条检验决定随包文档去留；对外文档与执行文档双轨分离，版本说明只讲用户可感知的提升。
- **零依赖**：全部脚本仅用 Python 标准库，可选 gh / skillhub CLI，拷到任何机器即跑。

## 快速开始

```bash
# 发布前预检（敏感扫描 + frontmatter + 必含文件 + 归属 + 章节引用 + 版本 tag + 评测证据）
python3 scripts/preflight_release.py <技能目录> --platform skillhub

# 依赖自检（脚本 import 的第三方包，依赖清单里写了吗）
python3 scripts/check_deps.py <技能目录>

# 触发词评估（正文口径 / 平台口径）
python3 scripts/eval_trigger.py <技能目录> --check
python3 scripts/eval_trigger.py <技能目录> --check --from-description

# 评测循环（含自身 11 用例 benchmark）
python3 scripts/eval_loop.py --aggregate

# 批量体检（一次对一批技能跑同一套检查与结构统计，报告只留本地）
python3 scripts/batch_skill_audit.py --limit 5

# SkillHub 目录直发（先 dry-run）
skillhub publish <技能目录> --dry-run --json
```

完整清单、命令与踩坑表见 `skills/skill-dev-kit/references/`。

## 适用场景

- 把反复执行的 8+ 步工作流固化为可分发技能
- 发布前做脱敏、归属、门禁与可发现性的系统性自查
- 为团队沉淀可复用的技能开发方法论与质量基线

## 归属

作者与许可证见 [`LICENSE`](LICENSE)（MIT, Copyright (c) 2026 johnsmithCA-sta）。
发布渠道：[SkillHub](https://skillhub.cn)（同名技能）与本仓库。

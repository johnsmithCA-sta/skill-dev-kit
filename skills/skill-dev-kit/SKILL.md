---
name: skill-dev-kit
slug: skill-dev-kit
displayName: 技能固化与发布工具包
summary: 把可复用工作流固化为 Skill 并安全发布的全周期工具包：内置 16 项发布前检查清单（含归属与权益门禁）+ 5 个零依赖自动化脚本（发布预检 preflight_release / 打包归档 make_skillhub_zip / GitHub tag 保护 setup_gh_ruleset / 触发词评估 eval_trigger / 评测循环 eval_loop），并沉淀四层测试闭环、两轮脱敏审查、双平台发布流程与踩坑表，让后续同类技能跳过重复探索。
description: 技能固化与发布工具包。当用户要"把工作流固化为 Skill、起草或完善 SKILL.md、做发布前脱敏与安全预检、打包 SkillHub zip、创建 GitHub tag 保护 ruleset、走双平台（SkillHub/GitHub）发布流程、沉淀可复用方法论、做技能触发词评估或评测循环"时使用。覆盖：固化判定（可复用×多步骤×有踩坑）→ 目录三件套（SKILL.md/scripts/references）→ SKILL.md 五要素 → 四层测试闭环 → 两轮脱敏审查（privacy-audit L1 自动扫描 + 市场专业审查）→ 发布前 16 项检查清单（含 author/Copyright 归属门禁）→ 5 脚本自动化 → 触发词评估与评测循环 → 双平台发布 → 复盘与自动化反哺。内置脚本零第三方依赖（仅 Python 标准库 + 可选 gh/skillhub CLI），可直接接入 CI 门禁。
version: 1.6.0
last_updated: 2026-08-27
license: MIT
author: johnsmithCA-sta
homepage: https://github.com/johnsmithCA-sta/skill-dev-kit
agent_created: true

---

# 技能固化与发布工具包（skill-dev-kit）

把"踩坑"变成"模板"——本技能是方法论的可执行化资产。新技能开发时直接套用清单与脚本，预计可把同类技能开发成本降低 **30%–50%**。

## 触发词

- 固化为技能 / 沉淀为 Skill / 做成技能 / 做成 Skill
- 起草 SKILL.md / 完善技能 / 技能脚手架
- 发布前检查 / 发布预检 / 脱敏预检 / 安全自查
- 打包 SkillHub / 创建 GitHub tag 保护 / 双平台发布
- 技能方法论 / 固化经验 / 发布检查清单
- 市场调研 / 竞品调研 / 市场空白定位
- 技术选型（该不该做成技能 / 做成脚本还是技能）/ 可靠性设计 / 错误处理
- Token 降本 / 成本优化 / 怎么省 token
- 技能调试（没触发 / 不生效）/ 评测技能 / 跑 benchmark / 触发词评估
- 技能复盘 / 复盘模板

## 一、何时值得固化（判定公式）

**可复用 × 多步骤（≥8 步） × 有踩坑教训 → 固化为 Skill**

- 社区补充判据（官方版）：一个任务已反复向 AI 解释 **≥5 次**、预计未来还会做 **≥10 次**——最好的 Skill 来自反复的挫败感；或你拥有 AI 不具备的领域知识/组织规范。
- 不该固化：一次性任务、含敏感信息的内容、已有 skill 覆盖的场景。
- 核心规则：可执行工作流 → 沉淀为 Skill（可再次执行）；信息性事实 → 只记 memory。**Skill 优先于 memory**。

> 四场景对照表（批量化查询/数据迁移/动态追踪/发布审查 × 频率×步数×坑×价值）见 `references/全生命周期 10 步 + 认知底座.md`，对号入座。
> 判据验证：高频/多步/有非显然教训 → 固化；一次性/无踩坑 → 不固化。

## 二、技能目录三件套

```
skill-name/
├── SKILL.md        # 行为规范：触发词 + 流程 + 依赖 + 边界 + 示例
├── scripts/        # 可执行脚本（参数化，纯标准库优先）
└── references/     # 渐进披露细节：口径/方法学/接入指南（按需加载）
```

**SKILL.md 五要素（缺一不可）**：① 触发词覆盖所有说法 ② 分步流程含完整命令 ③ 依赖清单 ④ 边界与安全红线 ⑤ 使用示例（一次完整对话模拟）。

**脚本参数化（脱敏与复用前提）**：硬编码路径/账号 → 改环境变量或命令行参数；硬编码文件名列表 → 改目录自动扫描。

## 三、发布前必过：16 项检查清单

> 完整清单见 `references/发布检查清单.md`（逐项勾选，全部通过后方可发布）；`preflight_release.py` 自动覆盖第 1/3/5/6/16 项。三条红线速记：

1. **敏感扫描**：个人路径/账号/密码/token/领域数据全部参数化或泛化（privacy-audit L1 退出码 0 通过）。
2. **LICENSE 必须排除**：发布目录/zip 内不含 LICENSE——SkillHub 拒收（HTTP 400"不允许的文件类型: LICENSE"）。
3. **changelog 最终确认**：SkillHub 同版本不可重发、发布后无法修改；发布后记录 URL、版本、审核状态。

## 四、五个自动化脚本（速查）

> 位于本技能 `scripts/`，纯 Python 标准库。完整命令、退出码、示例与踩坑见 `references/脚本速查.md`。

| 脚本 | 用途 | 核心命令 | 退出码 |
|---|---|---|---|
| preflight_release.py | 发布预检：敏感/frontmatter/必含文件/git 未跟踪/归属（author + LICENSE Copyright） | `preflight_release.py <目录> --platform skillhub` | 0=PASS / 1=FAIL |
| make_skillhub_zip.py | 打包归档（**非发布必经**，SkillHub CLI 支持目录直发；用于离线归档或 --keep-license 定制包） | `make_skillhub_zip.py <技能目录>` | 0=成功 / 1=失败 |
| setup_gh_ruleset.py | GitHub tag 保护 ruleset（完整 JSON body 规避 422） | `setup_gh_ruleset.py --dry-run` 后 `setup_gh_ruleset.py` | 0=成功 / 1=失败 |
| eval_trigger.py | 触发词评估：--gen 生成评估集 / --check 覆盖率 / --desc-check 描述质量 | `eval_trigger.py <技能目录> --check`（或 `--desc-check`） | 0=PASS / 1=FAIL / 2=REVIEW |
| eval_loop.py | 评测循环：断言评分聚合为 benchmark.json | `eval_loop.py <evals目录> --aggregate` | 0=成功 / 1=失败 |

> **自身评测闭环**：`evals/`(build_self_eval.py 生成 11 用例) + `eval_loop.py` → `benchmark.json`(自身均分 1.00 PASS)；回归重跑二者即可。

## 五、四层测试闭环

| 层级 | 做法 | 验收 |
|---|---|---|
| 合成样例 | 最小闭环（1 份含关键特征） | 验证核心链路 |
| 增强样例 | 覆盖全特性 | 全特性通过 |
| 真实数据 | 规模化验证 | 0 失败 / 逐条抽查 |
| 错误路径 | 错误输入必须被拦截 | 拦截率 100% |

> 正确路径通过不算数——错误路径（错误密码、非法校验码、边界误报）必须被正确拦截才算闭环。验收三件套：数量统计 + 逐条抽查 + 失败清单。

## 六、发布前市场调研（轻量化）

> 发布前轻量化环节，**不做全量普查**。完整模板见 `references/市场调研模板.md`，直接套用。

- **固定规则**：按市场规模排序，只调研**最大的前 5 家**；全量普查一律作废。
- **产出**：5 份固定件（调研对比表 + 生态格局 3 条洞察 + 独创性分析 + 商业竞争力速评 + 结论）。
- **硬上限**：只调研 5 家；扩展须经人工确认。

## 七、两轮脱敏与安全审查

| 轮次 | 做法 | 工具 |
|---|---|---|
| 第一轮 | grep 关键词 + privacy-audit 技能 L1 自动扫描 | `privacy-audit`（退出码 0 通过 / 1 高危禁止发布 / 2 需人工确认） |
| 第二轮 | 市场专业审查技能 | `skill-scanner`（朱雀实验室）/ `skills-security-check`（云鼎实验室） |

- 脱敏清单（发布前必扫）：个人路径、身份信息、业务编号、领域数据、机构实名、凭据（token/api_key/password/secret）。
- **脱敏原则：数据驱动化 > 简单删除**（不删功能、只去数据）：个性化描述→运行时聚合；「年份+数值」硬编码→泛化表述；文件名列表→目录扫描。
- **定级标准**（对接 skill-scanner / skills-security-check）：Benign 76–100 可信 / Suspicious 31–75 人工确认 / Malicious 0–30 禁止发布。
- 常见误报：技能名连字符可能被误判为密码——人工确认；运行时产物含用户数据属正常功能，脱敏对象是技能本体。

## 八、双平台发布流程

> 逐项命令与细节见 `references/发布检查清单.md`（16 项 + 一键执行顺序）；此处只列骨架。

0. 发布前市场调研（§六）+ 可选触发词/评测自检（`eval_trigger --check` / `eval_loop --aggregate`）。
1. 脱敏两轮审查 → 技能本体 0 敏感命中（§七）。
2. frontmatter 补全：SkillHub 需 name/slug/displayName/summary/description/version/license（+ author/homepage 归属锚点，见 §九）。
3. `preflight_release.py` 过一遍（自动覆盖清单 1/3/5/6/16）。
4. 人工核对发布文件清单——LICENSE 必须排除，CLI 的 dry-run 与直发都不会替你排除它。
5. **SkillHub 目录直发（默认路径）**：`skillhub publish <目录> --dry-run --json` 预检 → 同命令去 `--dry-run` 加 `--changelog` 实发；**无需先打包 zip**（`make_skillhub_zip.py` 降级为归档可选）。
6. GitHub：`gh skill publish --tag vX.Y.Z` + `setup_gh_ruleset.py`。
7. 发布后验证：以 publish 返回 `tags.latest` 为准（搜索索引有缓存延迟），记录 URL/版本/审核状态。
8. 版本治理：Git 提交、tag 与 version 一致、向 `references/Changelog.md` 追加一行、ruleset 防篡改（详见知识分层 references）。
9. 季度评审 + **失效触发随诊即改**（依赖变更/误判累积≥3次/生态变更，见知识分层 §三）；问题版本 feature flag 禁用。

> 平台差异：SkillHub 上传 ≤10MB、按次计费、同版本不可重发；GitHub 需 `skills/<name>/SKILL.md` + README/LICENSE/CONTRIBUTING、无商业化。git push 不通用 `gh api` Contents API 兜底。

## 九、边界与安全红线

- 隐私硬约束：健康/财务/身份数据全本地处理，脱敏版才可分享；技能本体 0 敏感命中才能发布。
- 凭据环境变量化 + 数据驱动化脱敏：禁止硬编码凭证与领域数据。
- 版本不可逆：SkillHub 同版本不可重发、发布后无法修改，changelog 需最终确认。
- 安全审查工具定期更新：静态扫描无法覆盖未来更新引入的风险。
- **发布内容（目录或 zip）不得含 LICENSE 文件**——SkillHub 拒收（见 §三红线 2）。

**资产边界（防膨胀红线，新增资产先自问）**：

1. 领域能力不进编排技能——可独立复用的能力（如脱敏审查）保持独立技能，仅被引用。
2. 复盘文档不入技能——成本分析 / 评估报告是「项目档案」，留工作区。
3. 技能只收「可执行知识」——清单/脚本/模板/方法论纪律可入；档案与一次性结论不可。
4. 新增资产三问定位：≥2 技能复用→进本技能；仅本技能用→进其 references；仅本项目结论→留工作区。
5. **核心知识产权不入包**——商业评估报告、付费方法论、未公开策略/数据资产一律不入技能目录（含 references/evals），只在个人档案库留存。
6. **来源与案例不暴露**——正文/脚本/评测用例中不得出现具体训练案例名、方法论来源文档名或其路径；方法论只以「社区共识/官方规范/个人实战」口径署名。

**归属与权益（三档判定）**：

| 档位 | 必做动作 |
|---|---|
| 已发布自研 | author + LICENSE `Copyright (c)` 行 + homepage 仓库 URL **三处一致**且仓库真实存在；提交用签名密钥 |
| 未发布自用 | frontmatter 预留 author/homepage 元数据即可，LICENSE 可后补 |
| 第三方安装 | **不碰**——不改 author、不标自己为版权人 |

发布前 5 分钟：preflight（归属为 critical，缺 author/Copyright 直接拦截）→ homepage `gh api` 可达 → 三处一致 → 确不需归属时 `--skip-ownership` 并声明理由。

## 十、踩坑表（直接使用，避免重蹈覆辙）

| 坑 | 根因 | 方案 |
|---|---|---|
| SkillHub 拒收 LICENSE | 平台不允许该文件类型（400） | 发布目录排除 LICENSE，frontmatter `license:` 字段声明 |
| 目录直发把 LICENSE 带上去 | skillhub CLI 收集文件仅排除 .git/__pycache__ 等，**不排除 LICENSE**；dry-run 只做 metadata 校验不检文件白名单 | 直发前人工确认目录无 LICENSE（或先 zip 路径用 make_skillhub_zip 排除），被 400 拒后删文件重发 |
| dry-run 盲区 | 只校验 metadata+打包，不查文件类型白名单 | 正式发布前人工核对文件清单 |
| 正则误报（手机号/坐标常量） | 缺数字边界 / 缺校验器 | 加 `(?<![0-9])…(?![0-9])` 边界 + MOD11-2/Luhn/GB32100 校验器 |
| 级别归一化漏报 | 字段 level 带括号注释 | JSON 级别规范化 + `normalize_level()` 兜底 |
| 翻页/接口假成功 | 空字段判成功 | 关键字段非空校验 + 多源降级 |
| tag 保护 422 | ref 语法不完整 | 用 `refs/tags/*` 或省略 conditions |

## 十一、使用示例

> 用户：「把这个数据获取+校验流程固化为技能并发布到 SkillHub」

1. 判定：可复用×多步骤×有踩坑 → 固化（§一）。
2. 建目录三件套，写 SKILL.md（五要素，§二；description 对照 `references/SKILL.md 编写规范.md` §七）。
3. 四层测试闭环跑通（§五）→ 市场调研 Top5（§六）→ 两轮脱敏（§七）。
4. `preflight_release.py ./my-skill --platform skillhub` → PASS（含归属检查）→ 逐项过 16 项清单。
5. `skillhub publish ./my-skill --dry-run --json` 预检 → 确认目录无 LICENSE → 去 `--dry-run` 实发 → 记录 URL/版本（§八）。

## 参考文档（渐进披露，按需加载）

| 文件 | 内容 | 何时查 |
|---|---|---|
| 发布检查清单.md | 16 项清单 + 一键执行顺序 | 发布前 |
| 脚本速查.md | 5 脚本完整命令/退出码/CI 接入 | 用脚本时 |
| SKILL.md 编写规范.md | 五要素 + 生产骨架 + description 四策略（§七） | 起草/改技能时 |
| 核心公式与量化基准.md | 10 条量化基准 + 工具参数 + Token 降本纪律（§5） | 评审/降本时 |
| 反模式清单.md | 20 条反模式 → 正确做法 + 自查表 | 写码前扫一遍 |
| 错误处理与可靠性纪律.md | 10 条可靠性纪律含代码示例 | 设计脚本时 |
| 调试三步法.md | 未触发/不一致/输出异常活诊断 | 技能出问题时 |
| 全生命周期 10 步 + 认知底座.md | Skill 本质 + 选型三岔口 + 四场景对照 + 路线图 | 新技能立项时 |
| 知识分层与版本治理.md | 三层 memory + 版本治理 + 失效触发条件 | 做版本决策时 |
| 市场调研模板.md | Top5 固定规则 + 5 份固定件 | 发布前调研 |
| 复盘报告模板.md | 五段式复盘模板 | 交付后复盘 |
| Changelog.md | 本技能版本史（开发侧档案） | 追溯变更时 |

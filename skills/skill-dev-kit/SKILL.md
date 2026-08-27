---
name: skill-dev-kit
slug: skill-dev-kit
displayName: 技能固化与发布工具包
summary: 把可复用工作流固化为 Skill 并安全发布的全周期工具包：内置 15 项发布前检查清单 + 5 个零依赖自动化脚本（发布预检 preflight_release / 一键打包 make_skillhub_zip / GitHub tag 保护 setup_gh_ruleset / 触发词评估 eval_trigger / 评测循环 eval_loop），并沉淀四层测试闭环、两轮脱敏审查、双平台发布流程与踩坑表，让后续同类技能跳过重复探索。
description: 技能固化与发布工具包。当用户要"把工作流固化为 Skill、起草或完善 SKILL.md、做发布前脱敏与安全预检、打包 SkillHub zip、创建 GitHub tag 保护 ruleset、走双平台（SkillHub/GitHub）发布流程、沉淀可复用方法论、做技能触发词评估或评测循环"时使用。覆盖：固化判定（可复用×多步骤×有踩坑）→ 目录三件套（SKILL.md/scripts/references）→ SKILL.md 五要素 → 四层测试闭环 → 两轮脱敏审查（privacy-audit L1 自动扫描 + 市场专业审查）→ 发布前 15 项检查清单 → 5 脚本自动化 → 触发词评估与评测循环 → 双平台发布 → 复盘与自动化反哺。内置脚本零第三方依赖（仅 Python 标准库 + 可选 gh/skillhub CLI），可直接接入 CI 门禁。
version: 1.4.0
last_updated: 2026-08-24
license: MIT
author: johnsmithCA-sta
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

**四场景对照（用判定公式对号入座）**：

| 场景类型 | 频率 | 步数 | 主要踩坑 | 固化价值 |
|---|---|---|---|---|
| 批量化查询/尽调 | 高频 | 30+ 步 | 数据源假成功、口径冲突 | 高 |
| 一次性数据迁移 | 中频 | 30+ 步 | 系统级加密/格式锁定 | 中高 |
| 年度动态追踪分析 | 年度 | 多阶段×多脚本 | OCR 乱码、隐私硬编码 | 高 |
| 发布前必做审查 | 每次发布 | 多轮扫描 | 工具白名单盲区 | 中 |

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

## 三、发布前必过：15 项检查清单

> 完整清单见 `references/发布检查清单.md`（逐项勾选，全部通过后方可发布）；`preflight_release.py` 自动覆盖第 1/3/5/6 项。三条红线速记：

1. **敏感扫描**：个人路径/账号/密码/token/领域数据全部参数化或泛化（privacy-audit L1 退出码 0 通过）。
2. **LICENSE 必须排除**：发布目录/zip 内不含 LICENSE——SkillHub 拒收（HTTP 400"不允许的文件类型: LICENSE"）。
3. **changelog 最终确认**：SkillHub 同版本不可重发、发布后无法修改；发布后记录 URL、版本、审核状态。

## 四、五个自动化脚本（速查）

> 位于本技能 `scripts/`，纯 Python 标准库。完整命令、退出码、示例与踩坑见 `references/脚本速查.md`。

| 脚本 | 用途 | 核心命令 | 退出码 |
|---|---|---|---|
| preflight_release.py | 发布预检：敏感/frontmatter/必含文件/git 未跟踪 | `preflight_release.py <目录> --platform skillhub` | 0=PASS / 1=FAIL |
| make_skillhub_zip.py | 一键打包：自动版本名 + ≤10MB + 默认排除 LICENSE | `make_skillhub_zip.py <技能目录>` | 0=成功 / 1=失败 |
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
- **脱敏原则：数据驱动化 > 简单删除**（不删功能、只去数据）：
  - 硬编码的个性化描述 → 运行时数据驱动聚合（维度定义 + 聚合函数）。
  - 硬编码的「年份+数值」advice → 泛化为通用表述（保留知识、剔除个案）。
  - 硬编码的文件名列表 → 目录自动扫描（呼应 §二 脚本参数化）。
- **定级标准**（对接 skill-scanner / skills-security-check 输出解读）：Benign 可信 76–100 / Suspicious 可疑 31–75 / Malicious 恶意 0–30；落在 Suspicious 一律人工确认，Malicious 禁止发布。
- 常见误报：技能名连字符（a-b-c）可能被正则误判为密码——人工确认即可；运行时产物含用户数据属正常功能，技能本体才是脱敏对象。

## 八、双平台发布流程

0. **发布前市场调研**（轻量化，§六）：套用 `references/市场调研模板.md`，仅调研 Top5 竞品，产出差异化结论。
0.5 **触发词与评测自检**（可选增强）：`eval_trigger.py --check` 确认触发词覆盖达标；有 evals 用例时 `eval_loop.py --aggregate` 跑 benchmark。
1. **脱敏两轮审查** → 技能本体 0 敏感命中。
2. **frontmatter 补全**：SkillHub 需 name/slug/displayName/summary/description/version/license；GitHub 需 name/description/version/license。
3. **preflight --dry-run 先过一遍**（覆盖清单 1/3/5/6）。
4. **人工核对发布目录文件清单**（LICENSE 必须排除，见 §三红线）。
5. **打包** → `make_skillhub_zip.py`（不含 LICENSE）。
6. **发布**：`skillhub publish <zip> --changelog "..."`（SkillHub）/ `gh skill publish --tag vX.Y.Z` + `setup_gh_ruleset.py`（GitHub）。
7. **发布后验证**远程完整性，记录 URL/版本/审核状态。
8. **版本治理**：Git 提交本技能源码；`version` 与发布 tag 一致（否则不自动更新）；在 SKILL.md 末 `## Changelog` 追加一行（变更类型 + 来源）；用 tag 保护 ruleset 防 Release 被篡改（见 `setup_gh_ruleset.py`）。详见 `references/知识分层与版本治理.md`。
9. **季度评审**：每季度检查过期/失效内容、社区生态变化、可融入的新案例；问题版本用 feature flag 禁用，保留已知良好基线。

> 平台差异：SkillHub 目录任意（zip≤10MB）、按次计费、同版本不可重发；GitHub 需 `skills/<name>/SKILL.md`、含 README/LICENSE/CONTRIBUTING、无商业化。git push 不通时用 `gh api` Contents API 兜底更新远程文件。

## 九、边界与安全红线

- 隐私硬约束：健康/财务/身份数据全本地处理，脱敏版才可分享；技能本体 0 敏感命中才能发布。
- 凭据环境变量化 + 数据驱动化脱敏：禁止硬编码凭证与领域数据。
- 版本不可逆：SkillHub 同版本不可重发、发布后无法修改，changelog 需最终确认。
- 安全审查工具定期更新：静态扫描无法覆盖未来更新引入的风险。
- **本技能若发布到 SkillHub，zip 内不得含 LICENSE 文件**（见 §三红线 2）。

**资产边界（防膨胀红线，新增资产先自问）**：

1. 领域能力不进编排技能——可独立复用的能力（如脱敏审查）保持独立技能，仅被引用。
2. 复盘文档不入技能——成本分析 / 评估报告是「项目档案」，留工作区，不进技能目录。
3. 技能只收「可执行知识」——清单 / 脚本 / 模板 / 方法论可入技能，档案与一次性结论不可。
4. 新增资产三问定位：能被 ≥2 个技能复用 → 进本技能；仅本技能用 → 进该技能 references；仅本项目结论 → 留工作区。

## 十、踩坑表（直接使用，避免重蹈覆辙）

| 坑 | 根因 | 方案 |
|---|---|---|
| SkillHub 拒收 LICENSE | 平台不允许该文件类型（400） | 发布目录排除 LICENSE，frontmatter `license:` 字段声明 |
| dry-run 盲区 | 只校验 metadata+打包，不查文件类型白名单 | 正式发布前人工核对文件清单 |
| 正则误报（手机号/坐标常量） | 缺数字边界 / 缺校验器 | 加 `(?<![0-9])…(?![0-9])` 边界 + MOD11-2/Luhn/GB32100 校验器 |
| 级别归一化漏报 | 字段 level 带括号注释 | JSON 级别规范化 + `normalize_level()` 兜底 |
| 翻页/接口假成功 | 空字段判成功 | 关键字段非空校验 + 多源降级 |
| tag 保护 422 | ref 语法不完整 | 用 `refs/tags/*` 或省略 conditions |

## 十一、使用示例

> 用户：「把这个数据获取+校验流程固化为技能并发布到 SkillHub」

1. 判定：可复用×多步骤×有踩坑 → 固化（§一）。
2. 建目录三件套，写 SKILL.md（五要素齐全，§二）；description 编写对照 `references/description 编写方法论.md`。
3. 四层测试闭环跑通（§五）。
3.5 发布前市场调研：套用 `references/市场调研模板.md`，仅调研 Top5，产出差异化结论（§六）。
3.6 触发词与评测自检（可选）：`eval_trigger.py --check` 确认覆盖；有 evals 时 `eval_loop.py --aggregate` 跑 benchmark（§八 0.5）。
4. 两轮脱敏审查：先 `privacy-audit` L1 扫描（退出码 0），再 `skill-scanner`（§七）。
5. 逐项过 15 项清单（§三，完整版见 `references/发布检查清单.md`）。
6. `preflight_release.py ./my-skill --platform skillhub` → PASS。
7. `make_skillhub_zip.py ./my-skill` → 得 `my-skill-v1.0.0.zip`（无 LICENSE）。
8. `skillhub publish ./my-skill-v1.0.0.zip --changelog "..."` → 记录 URL/版本。

## 参考文档（渐进披露，按需加载）

- `references/发布检查清单.md`：发布前 15 项检查清单完整版 + 一键执行顺序。
- `references/脚本速查.md`：5 脚本完整命令、退出码、示例、踩坑与 CI 接入。
- `references/市场调研模板.md`：发布前轻量化市场调研模板（Top5 固定规则 + 5 份固定件 + 生态格局三段式）。
- `references/description 编写方法论.md`：description 触发命门——四策略 + 三条硬性规则 + 正反例 + 自查清单。
- `references/错误处理与可靠性纪律.md`：10 条可靠性纪律（可靠性数学/结构化输出/错误分级退避/is_error/幂等/护栏/返回信封/非法状态不可表示/HITL/降级链防假成功），每条含可执行代码示例。
- `references/Token 降本纪律.md`：消耗归因基准（调试28%/大文件24%/写码19%/上下文17%/OCR12%）+ 四条强制纪律（可压缩 50-60%）+ 量化驱动方法 + 降本自查清单。
- `references/反模式清单.md`：18 条反模式（15 条核心 + 工具技能不自检 + 2 条个人实战：硬编码文件名列表、正则缺边界）→ 正确做法对照 + 发布前自查。
- `references/核心公式与量化基准.md`：10 条量化基准（固化判定/触发阈值/L1≈100/L2<5000/工具输出/活跃工具/可靠性数学/降本/结构化输出/60-40 切分）+ 工具参数基准 + 使用时机。
- `references/调试三步法.md`：技能上线后三类故障活诊断（未触发/执行不一致/输出异常），每步含检查清单+对策+现有资产衔接，30 秒定位。
- `references/SKILL.md 编写规范.md`：frontmatter 命名 + 五要素 + 生产级最小骨架（Goal/Inputs/Constraints/Steps/Verification）填空模板 + 写作原则 + 跨模型兼容。
- `references/复盘报告模板.md`：五段式结构（时间线/流程/问题表/经验/改进）+ 「问题→自动化工具」转化，模板留技能、内容留工作区（兼容红线②）。
- `references/知识分层与版本治理.md`：三层 memory 体系 + 铁律 + 版本治理（Git化/bump/季度清理/feature flag）+ 自身版本管理（last_updated+Changelog）。
- `references/全生命周期 10 步 + 认知底座.md`：Skill vs MCP/Command/Memory 关系（厨房vs菜谱）+ 技术选型三岔路口表 + 决策铁律 + 10 步全生命周期路线图。

> 说明：四案例整合方法论《Skill固化经验与方法论.md》属项目档案，不入本技能包（见「资产边界」红线②）。如需查阅，见工作区 `.workbuddy/artifacts/Skill固化经验与方法论.md` 或 ima/资料库副本。

## Changelog

| 日期 | 版本 | 变更类型 | 变更内容 | 来源 |
|---|---|---|---|---|
| 2026-08-19 | 1.1.0 | 新增 | 发布清单 12→15 项；新增 references/description 编写方法论、脚本速查；正文瘦身至 <5000 token；frontmatter 增补 last_updated | 对标评估 |
| 2026-08-24 | 1.2.0 | 新增 | 阶段 1 工程化资产：eval_trigger 新增 --desc-check（5 项 description 静态校验）；新增 references/错误处理与可靠性纪律、Token 降本纪律、反模式清单、核心公式与量化基准（+4 引用）；P3：脚本速查 /tmp 路径修正、preflight 正则自命中规避（/Users、/home 改字符串拼接，检测行为不变） | 工程化资产化 |
| 2026-08-24 | 1.3.0 | 新增 | 阶段 2 生命周期与运营：新增 references/调试三步法、SKILL.md 编写规范、复盘报告模板、知识分层与版本治理、全生命周期 10 步+认知底座（+5 引用）；SKILL.md §一 补社区判据(≥5次/≥10次)+四场景对照、§七 补「数据驱动化>简单删除」原则+定级标准(B/S/M)、§八 补版本治理+季度评审步骤；正文 <5000 token | 生命周期资产化 |
| 2026-08-24 | 1.4.0 | 新增 | 阶段 3 自身评测闭环：evals/(11 用例)+benchmark.json(均分 1.00)；顺带补触发词(M6)+意图清单(M3)，覆盖 20/20、desc 5/5 | 自评测与治理 |

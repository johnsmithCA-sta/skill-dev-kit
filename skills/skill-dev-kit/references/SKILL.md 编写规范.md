# SKILL.md 编写规范（生产级骨架 + description 触发命门）

> 来源：社区共识 + 官方规范（Anthropic Agent Skills）提纯。新技能 SKILL.md 的「填空模板」——从 frontmatter 到五要素到生产骨架一次到位；含 description 编写方法论（触发命门）。
> 配套：体积预算见 `references/核心公式与量化基准.md`（L2 正文 <5000 token；Token 降本纪律见同文件 §5）。

---

## 一、frontmatter 命名规范

| 字段 | 规则 |
|---|---|
| name | 小写 + 连字符 kebab-case，**禁止下划线/驼峰** |
| description | 「做什么 + 何时用」，第三人称、无 how（见 §七） |
| version | 语义化版本，与发布 tag 一致 |
| 其余字段 | 各平台不同（SkillHub 需 slug/displayName/summary；GitHub 仅需 name/description/version/license） |

> ⚠️ SKILL.md 文件名大小写敏感；技能文件夹内**禁止放 README.md**（避免与发布目录 README 冲突）。

---

## 二、个人实战五要素（缺一不可）

1. **触发词**：覆盖用户所有可能的说法（口语变体 + 任务类型）。
2. **分步流程**：可直接照做的步骤，含完整命令。
3. **依赖清单**：环境要求（Python 版本、可选工具）。
4. **边界与安全**：明确红线（隐私约束、敏感数据不上云、凭证用后即删）。
5. **使用示例**：一次完整对话的模拟流程——缺失会导致审查不过，**务必补齐**。

---

## 三、生产级最小骨架（填空模板）

```markdown
---
name: <skill-name>          # kebab-case
description: <做什么 + 何时用>   # 第三人称、无 how
version: 0.1.0
license: MIT
---

# <技能名>

<一句话价值主张：把什么变成什么>

## Goal（可验证输出物）
<完成时应交付的具体产物，可被断言校验>

## Inputs（必填 / 可选）
- 必填：<用户必须提供的>
- 可选：<有默认值或可从环境推断的>

## Constraints（不做什么 + 质量门槛 + 逃逸条款）
- 不处理：<明确边界>
- 质量门槛：<如"错误路径必须拦截""结构化输出">
- 逃逸条款：当本技能的 MUST/NEVER 与用户明确意图/其他指令冲突或不适用时，
  优先保障用户数据与意图，并显式说明偏离理由与替代动作——不得静默偏离。

## Steps（读取 → 处理 → 验证）
1. <读取：输入来源 + 方式>
2. <处理：核心逻辑，含完整命令>
3. <验证：验收三件套 数量统计 + 逐条抽查 + 失败清单>

## Verification Checklist
- [ ] 关键字段齐全
- [ ] 结果可复现
- [ ] 引用资源已标注路径

## 触发词
- <说法 1> / <说法 2> / ...

## 使用示例
> 用户："<真实诉求>"

1. ... 8. ...
```

---

## 四、写作原则（共识）

- **模板模式优于散文**：放 `## Report Template` / `ALWAYS use this structure`，让模型填空而非自由发挥。
- **2–3 个少样本示例**：明确边界情况处理方式，「好的示例胜过十条规则」。
- **指令强度编码**：MUST / NEVER / ALWAYS 区分强制与建议；把含糊的「可以」改成强约束。
- **反斜杠路径反模式**：用相对路径或环境变量，禁用 `/Users/xxx` 硬编码（也是脱敏第一道防线）。
- **不给过多库选项**：给默认 + 退路，避免模型在选项间犹豫。
- **「魔数」必须注释理由**：`max_retries = 4  # 指数退避封顶 60s，覆盖 95% 瞬时故障`。
- **别把「何时使用」写进 body**（应放 description）——最高频错误。
- **单技能单职责**，不做「万能指令」。
- **固化必带逃逸条款**：SKILL.md 的 MUST/NEVER 是「可更新指南」而非不可置疑的法律。Constraints 节必须写明：与用户明确意图冲突时优先保障用户意图 + 显式说明偏离理由（防「硬编码铁律不容偏离」反模式 #19）。
- **按任务类型定指令强度**：确定性/流程型任务写死步骤；探索型/发散型任务只给方向与约束、不写死步骤（防反模式 #20）。写 Steps 前先判断任务属于哪类。

---

## 五、跨模型兼容

用**计划上线的所有模型**测试：
- **轻量模型（如 Haiku）**：需更显式分步指导，避免隐含前提。
- **强模型（如 Opus）**：应避免过度解释，给骨架 + 关键约束即可，防啰嗦漂移。

---

## 六、常见反模式（对照自查）

| 反模式 | 正确 |
|---|---|
| 所有内容塞一个文件 | 渐进式披露，references 按需加载 |
| description 模糊 | 功能+场景双维度，动作动词+文件类型 |
| 长提示词=好结果 | 精简、模块化、策略性冗余关键指令 |
| 工具命名含糊（search/do_thing） | verb_noun + 前缀命名空间 |
| 把「何时使用」写进 body | 触发信息只放 description |

---

## 七、description 编写方法论（触发命门）

> 定位：**description 是技能唯一的触发凭据**——模型通过语义匹配决定是否加载技能。描述写不好，技能等于不存在。

### 7.0 为什么它是「命门」

- description 决定**是否触发**，不决定**执行质量**；执行不一致时查正文指令特异性，而不是改 description。
- 触发阈值：**简单单步任务不触发、复杂多步任务必触发**——测试触发率低 90% 的原因是「测试指令太简单」。
- 监控真实使用中的意外触发与过度依赖；把「某 prompt 没触发」的反馈当**新测试用例**补进评估集。

### 7.1 高精准 description 四策略

| # | 策略 | 做法 | 示例 |
|---|---|---|---|
| 1 | 功能 + 场景双维度 | 动作动词 + 具体文件类型/领域 + 场景 | 「提取 PDF 表格转 CSV」「创建带修订标记的 Word 文档用于法律审查」远胜于「文档处理」 |
| 2 | 推动性语言 | 加「必须优先触发此技能」类指令——模型默认倾向自己处理简单任务，描述要「略显强势」 | "MUST trigger when the user asks to convert PDF tables" |
| 3 | 关键词罗列 | 末尾罗列高频口语化触发词/请求变体 | "Trigger words: 提取表格、PDF 转 Excel、表格转换…" |
| 4 | 排他边界 | 写明「不做什么 / 何时不用」，防误触发 | "Not for data visualization or chart generation." |

### 7.2 三条硬性规则

1. **必须第三人称**：「Extracts text from PDF files」而非「I can help you…」。
2. **只写「做什么 + 何时用」**，把「怎么做」留给正文——description 试图解释 how 是高频错误。
3. **泛泛描述必死**：「Helps with documents」触发条件过宽，会在错误时机激活或从不激活。

### 7.3 触发机制要点（与正文的分工）

- description 只管触发 → 触发信息只放 description；**「何时使用此技能」写进 body 是最高频错误**。
- 正文负责执行质量 → 触发正确但执行不一致，改正文指令特异性（MUST/NEVER 强度编码、分步清单）。
- 触发词章节（SKILL.md 正文）与 description 互补：description 供语义匹配，触发词章节供人工/脚本检视，两者需同步维护。

### 7.4 正反例对照

| # | 反例 | 问题 | 正例 |
|---|---|---|---|
| 1 | Helps with documents. | 泛泛，无功能无场景 | Extracts tables from PDF documents and converts them to CSV for spreadsheet analysis. |
| 2 | I can help you create Word documents. | 第一人称 + 只有动作无场景 | Creates professionally formatted Word documents with tracked revisions for legal review. MUST trigger on 合同/修订/法律文档. |
| 3 | This skill processes data. | 无动作动词、无对象、无边界 | Cleans and normalizes Excel/CSV data: detects duplicates, format errors and missing fields before report generation. Not for data visualization. |
| 4 | 这个技能可以处理文档。 | 无动作动词、无文件类型、无场景 | 从 PDF/图片提取表格并转为可编辑 CSV，用于数据整理与报表；用户说「提取表格」「PDF 转 Excel」时必须优先触发。不用于文档排版。 |

### 7.5 自查清单（写完 description 逐条过）

- [ ] 第三人称？（无 I/we/我/本助手）
- [ ] 有动作动词？（Extracts / Creates / Converts / 提取 / 生成 / 校验…）
- [ ] 有具体对象？（文件类型 / 领域 / 数据形态）
- [ ] 有场景 / 触发时机？（何时用）
- [ ] 无 how 描述？（没有「怎么做」的步骤细节）
- [ ] 末尾有口语化触发词？
- [ ] 有排他边界？（不做什么 / 何时不用）
- [ ] 用计划上线的所有模型实测过触发？（60/40 切分测触发率）

### 7.6 与工具链的衔接

- `scripts/eval_trigger.py --check`：静态校验「## 触发词」章节覆盖率（预期意图命中率，阈值默认 0.7）。
- `scripts/eval_trigger.py --gen`：生成 should-trigger / should-not-trigger 评估集，供人工/LLM 扩充后回测触发行为。
- `scripts/eval_trigger.py --desc-check`：静态校验 §7.5 前 5 项规则（第三人称 / 动作动词 / 场景 / 无 how / 排他边界）。

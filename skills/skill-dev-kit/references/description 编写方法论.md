# description 编写方法论（SKILL.md 触发命门）

> 定位：**description 是技能唯一的触发凭据**——模型通过语义匹配决定是否加载技能。描述写不好，技能等于不存在。
> 来源：社区共识 + 官方方法论（Anthropic skill-creator 实践）提纯，经个人技能开发实战验证。
> 适用：编写 / 修改任何技能 SKILL.md frontmatter 的 `description` 字段；新技能开发时随「SKILL.md 五要素」一并产出。

## 0. 为什么它是「命门」

- description 决定**是否触发**，不决定**执行质量**；执行不一致时查正文指令特异性，而不是改 description。
- 触发阈值：**简单单步任务不触发、复杂多步任务必触发**——测试触发率低 90% 的原因是「测试指令太简单」。
- 监控真实使用中的意外触发与过度依赖；把「某 prompt 没触发」的反馈当**新测试用例**补进评估集。

## 1. 高精准 description 四策略

| # | 策略 | 做法 | 示例 |
|---|---|---|---|
| 1 | 功能 + 场景双维度 | 动作动词 + 具体文件类型/领域 + 场景 | 「提取 PDF 表格转 CSV」「创建带修订标记的 Word 文档用于法律审查」远胜于「文档处理」 |
| 2 | 推动性语言 | 加「必须优先触发此技能」类指令——模型默认倾向自己处理简单任务，描述要「略显强势」 | "MUST trigger when the user asks to convert PDF tables" |
| 3 | 关键词罗列 | 末尾罗列高频口语化触发词/请求变体 | "Trigger words: 提取表格、PDF 转 Excel、表格转换…" |
| 4 | 排他边界 | 写明「不做什么 / 何时不用」，防误触发 | "Not for data visualization or chart generation." |

## 2. 三条硬性规则

1. **必须第三人称**：「Extracts text from PDF files」而非「I can help you…」。
2. **只写「做什么 + 何时用」**，把「怎么做」留给正文——description 试图解释 how 是高频错误。
3. **泛泛描述必死**：「Helps with documents」触发条件过宽，会在错误时机激活或从不激活。

## 3. 触发机制要点（与正文的分工）

- description 只管触发 → 触发信息只放 description；**「何时使用此技能」写进 body 是最高频错误**。
- 正文负责执行质量 → 触发正确但执行不一致，改正文指令特异性（MUST/NEVER 强度编码、分步清单）。
- 触发词章节（SKILL.md 正文）与 description 互补：description 供语义匹配，触发词章节供人工/脚本检视，两者需同步维护。

## 4. 正反例对照

| # | 反例 | 问题 | 正例 |
|---|---|---|---|
| 1 | Helps with documents. | 泛泛，无功能无场景 | Extracts tables from PDF documents and converts them to CSV for spreadsheet analysis. |
| 2 | I can help you create Word documents. | 第一人称 + 只有动作无场景 | Creates professionally formatted Word documents with tracked revisions for legal review. MUST trigger on 合同/修订/法律文档. |
| 3 | This skill processes data. | 无动作动词、无对象、无边界 | Cleans and normalizes Excel/CSV data: detects duplicates, format errors and missing fields before report generation. Not for data visualization. |
| 4 | 这个技能可以处理文档。 | 无动作动词、无文件类型、无场景 | 从 PDF/图片提取表格并转为可编辑 CSV，用于数据整理与报表；用户说「提取表格」「PDF 转 Excel」时必须优先触发。不用于文档排版。 |

## 5. 自查清单（写完 description 逐条过）

- [ ] 第三人称？（无 I/we/我/本助手）
- [ ] 有动作动词？（Extracts / Creates / Converts / 提取 / 生成 / 校验…）
- [ ] 有具体对象？（文件类型 / 领域 / 数据形态）
- [ ] 有场景 / 触发时机？（何时用）
- [ ] 无 how 描述？（没有「怎么做」的步骤细节）
- [ ] 末尾有口语化触发词？
- [ ] 有排他边界？（不做什么 / 何时不用）
- [ ] 用计划上线的所有模型实测过触发？（60/40 切分测触发率）

## 6. 与工具链的衔接

- `scripts/eval_trigger.py --check`：静态校验「## 触发词」章节覆盖率（预期意图命中率，阈值默认 0.7）。
- `scripts/eval_trigger.py --gen`：生成 should-trigger / should-not-trigger 评估集，供人工/LLM 扩充后回测触发行为。
- 本节标准可作为 `--desc-check`（规划中）的静态校验规则来源：第三人称 / 动作动词 / 场景 / 无 how / 排他边界。

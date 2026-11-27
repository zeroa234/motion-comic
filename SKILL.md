---
name: motion-comic-production
description: Turn static manga/comic pages and synchronized voice/SFX audio into broadcast-ready motion comics via a decoupled four-layer pipeline (L0 page parsing & cleanup, L1 timeline-anchored directing, L2 hybrid 2.5D + AI video compositing, L3 automated & visual QC). Use whenever producing, editing, troubleshooting, or migrating a motion comic workflow—or when swapping underlying CV, TTS, AI video, or rendering stacks without rewriting core production rules.
compatibility: Core methodology, data contracts (references/), and contract validator (scripts/validate_contracts.py) are completely stack-agnostic. Concrete execution binds through adapters/ (reference local GPU stack documented in adapters/stack-reference-local.md).
---

# Motion Comic Production（解耦式动态漫画生产技能）

本技能将**稳定的动态漫画工程方法论（`references/`）**与**可替换的技术栈实现（`adapters/`）**彻底解耦。
执行任务时，先按工程层原则做导演、对轴、选型与质检决策，再通过目标适配器映射到具体工具、模型与 CLI。

---

## 核心设计原则（不可违背）

1. **思路与实现分离**：工程决策只依赖“抽象能力 + 层间数据契约”，不绑定任何特定模型、渲染库或推理框架。
2. **真时间轴单一事实源（Single Source of Truth）**：除首镜头起点外，禁止在编排中硬编码秒数；所有页切点、关键分格入点、气泡弹出与动作节律必须锚定到真实音频 `timeline.json`。
3. **双轨渐进生产（Fast Baseline → Selective Hybrid）**：永远先跑通低成本、100% 保真原画的纯 2.5D 快产基线并通过 L3 质检，再对高表现力核心镜头择优挂载 AI 视频增强槽位。
4. **声明式覆盖与稳定键绑定**：所有手工干预（分格覆盖、UI 白名单、AI 增强镜头）必须走外置声明式配置，并使用稳定语义键（如 `page:panel`）而非易漂移的序号（如 `shot_07`）。
5. **降级透明但门禁零容忍**：渲染后端允许在缺片时降级到 2.5D 防止崩溃，但必须写入元数据日志；最终交付门禁要求 `fallback_count == 0`。

---

## 五阶段工作流与按需读取路由

开工前先判定**素材源头模式（Mode A / B / C）**，按源头裁剪 L0 步骤（绝不对无字原创图或精修单格重复执行分格检测与去字修补）：

- **Mode A（现成漫画原页改编）**：原图已合层含分格与气泡 → 走完整 L0 逆向拆层（超分 → 分格 → UI 保护 → 抠气泡 → 去字 → 深度）。
- **Mode B（原创手绘 / 本地 AI 从零生成）**：源头按单镜直出纯净无字图（可带运镜余量与前背景透明分层）→ **直接跳过分格检测、气泡抠层与去字修补**，仅做深度估计（若走 2.5D）与轻量 `manifest.json` 打包，气泡改为正向叠加或纯字幕。
- **Mode C（原作漫画大幅二次编辑 / 重构）**：先借用 L0 粗裁/粗去字作为底稿，经扩图（Outpaint）、重绘遮挡、上色、拆层或生成首尾双关键帧后，**按 Mode B 纯净单格回灌 `manifest.json`**（跳过二次自动去字，防止破坏精修画面）。

> 三种模式在进入 L1 前均收敛为统一的 L0 `manifest.json` 契约，**L1 → L2 → L3 全链路 100% 复用**。细则见 [references/preprocessing-heuristics.md](references/preprocessing-heuristics.md)。

按阶段推进，每通过一个阶段先核验检查点再进入下一阶段：

```text
[Stage 0] 音频与真时间轴就绪（Audio Master + timeline.json + 可选字幕）+ 判定素材源模式(Mode A/B/C)
    ↓ 检查点：音频可播、timeline 包含逐句人声与音效锚点、L0 路径已裁剪
[Stage 1] L0 资产准备（Mode A 完整拆层 / Mode B 源头纯净打包 / Mode C 精修回灌）
    ↓ 检查点：产出标准 manifest.json + 调试预览，核验无误擦 UI/漏分格/重复修补
[Stage 2] L1 声明式编排与对轴（page-map.json → story.json）
    ↓ 检查点：validate_story 零硬错、关键情绪/音效峰值落入目标分格、删减气泡已核对
[Stage 3] L2 双轨渲染（先出 Fast 2.5D 基线；再按需生成 AI 片段并合出 Hybrid 版）
    ↓ 检查点：无回退、色域/画风一致、AI 循环无重影/倒放穿帮
[Stage 4] L3 自动化质检与视觉审计（黑帧 / 音画 / fallback / 标定图 / 抽帧肉眼复核）
    ↓ 检查点：qc_report.ok == true + qc_sheet & zones_overlay 肉眼放行
```

### 按任务按需读取文档（切勿一次性全量注入）

| 当前任务 | 必读文档（技术栈无关层） | 对应实现层 / 工具（按当前环境选择） |
|---|---|---|
| 理解整体分层、数据契约、或准备替换技术栈 | [references/architecture-and-contracts.md](references/architecture-and-contracts.md) | [adapters/README.md](adapters/README.md) + `scripts/validate_contracts.py` |
| 准备漫画原页：超分、分格、去字、聊天界面/UI 保护、深度图 | [references/preprocessing-heuristics.md](references/preprocessing-heuristics.md) | [adapters/stack-reference-local.md](adapters/stack-reference-local.md) + [assets/templates/keep-boxes.template.json](assets/templates/keep-boxes.template.json) |
| 编写/修正 `page-map.json`、音画对轴、分格切分、气泡随台词弹出 | [references/audio-timeline-sync.md](references/audio-timeline-sync.md) | [adapters/audio-timeline-adapter.md](adapters/audio-timeline-adapter.md) + [assets/templates/page-map.template.json](assets/templates/page-map.template.json) |
| 2.5D 运镜、局部形变 `zones`、流体粒子、AI 选镜与循环策略 | [references/motion-and-hybrid-directing.md](references/motion-and-hybrid-directing.md) | [adapters/stack-reference-local.md](adapters/stack-reference-local.md) + [assets/templates/enhanced-spec.template.json](assets/templates/enhanced-spec.template.json) |
| 成片验收、黑帧/音画校验、坐标标定与版本交付 | [references/qc-and-delivery-gates.md](references/qc-and-delivery-gates.md) | [adapters/stack-reference-local.md](adapters/stack-reference-local.md) |

---

## 替换或升级技术栈的标准动作

当出现更好的分格模型、去字模型、深度模型、TTS 引擎、图生视频（I2V/FL2V）模型或渲染器时：
1. 阅读 [references/architecture-and-contracts.md](references/architecture-and-contracts.md) 确认该层的输入/输出契约；
2. 阅读 [adapters/README.md](adapters/README.md) 的模块替换矩阵与验证门槛；
3. 在 `adapters/` 新增或更新对应适配文档与代码接入，确保产出严格满足契约；
4. 用同一份 `story.json` 与 L3 门禁跑回归对比（同时测**偏静态特写**与**高动态镜头**），达标后切换默认适配器，**无需改动 `references/` 中的通用工程法则**。

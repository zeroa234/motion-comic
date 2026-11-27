# Motion Comic Production Skill（解耦式动态漫画生产技能）

一个面向 AI Coding / Creative Agents（Claude Code、Codex、Antigravity、OpenClaw 等）的**通用动态漫画（Motion Comic）工程 Skill**，专注于将**现成静态漫画原页 + 同步配音/音效**高效制作成高保真有声动态漫画视频。

与市面上“小说 → AI 逐镜生图 → 简单推拉”的漫剧提示词合集不同，本 Skill 沉淀了一套**工程方法论与底层实现彻底解耦**的四层生产规范：无论未来分格模型、去字模型、深度模型、TTS、图生视频（I2V/FL2V）模型或 GPU 渲染器如何换代，**核心工程规则与层间数据契约无需重写**，只需按需替换 `adapters/` 中对应模块即可平滑升级。

---

## 核心设计：两层彻底解耦

```text
├── SKILL.md                              # Agent Skill 入口：5 阶段状态机与按需文档路由
├── references/                           # 【稳定核心层：完全技术栈无关】
│   ├── architecture-and-contracts.md     # L0→L1→L2→L3 四层架构、6 大可替换能力槽与数据契约
│   ├── preprocessing-heuristics.md       # 静态漫画拆层：条件超分、阅读序分格、UI/聊天屏保护、单次羽化去字、白边自由字保护、16-bit 深度
│   ├── audio-timeline-sync.md            # 真时间轴驱动、符号锚点对轴、分格权重与峰值锁死、气泡随台词弹出与删减冲突排查
│   ├── motion-and-hybrid-directing.md    # 快产 2.5D + 精细混合 AI 双轨模型、黑白/全彩分化、动作拓扑选型矩阵、局部形变与粒子防冲突
│   └── qc-and-delivery-gates.md          # 自动化硬门禁、双圈标定图、视觉抽检清单与版本交付纪律
├── adapters/                             # 【可替换实现层：按当前技术栈自由热插拔】
│   ├── README.md                         # 模块热替换矩阵、回归测试标准与自定义适配器模板
│   ├── stack-reference-local.md          # 参考本地 GPU 栈映射（YOLO + LaMa + Depth + ModernGL + ComfyUI I2V/FL2V + NVENC）
│   └── audio-timeline-adapter.md         # 音频域适配规范（对接任意 TTS / 录音 + 对齐器 → timeline.json）
├── assets/templates/                     # 可直接拷贝开工的声明式契约模板
│   ├── timeline.template.json
│   ├── page-map.template.json
│   ├── enhanced-spec.template.json
│   └── keep-boxes.template.json
└── scripts/
    └── validate_contracts.py             # 零第三方依赖（Python 标准库）的层间契约校验工具
```

---

## 四层单向流水线

```text
Audio Master + timeline.json (+ .srt)
              │
              ▼
   [L0] 静态漫画解析与拆层  ──▶ manifest.json + orig.png / clean.png / depth16.png / bubbles/*.png
              │
              ▼
   [L1] 导演编排与锚点对轴  ──▶ story.json (+ 可选内容哈希缓存的 AI 视频片段)
              │
              ▼
   [L2] 双轨 GPU 合成渲染   ──▶ video.mp4 + video.mp4.render_meta.json
              │
              ▼
   [L3] 自动化门禁与视觉审计 ──▶ qc_report.json + qc_sheet.jpg + zones_overlay.jpg
```

### 为什么这套方法能扛住技术栈快速演进？
- **零模型名硬编码于方法论中**：`references/` 只定义能力接口、物理规律与避坑准则（例如：为什么周期往复要走首尾同帧闭环，而液体/烟雾/单向爆发严禁首尾同帧和 `pingpong`；为什么黑白漫去字必须单色化且单次羽化；为什么严禁硬编码秒数）。
- **稳定语义键与契约校验**：所有手工覆盖均基于 `page:panel` 与 `voice@line` 锚点，并通过零依赖脚本 `scripts/validate_contracts.py` 在换栈后即刻验证契约兼容性。
- **双轨渐进策略**：先用纯 2.5D 快产基线锁死 100% 原画保真与音画对轴，再仅对 10%–25% 高回报核心镜头挂载 AI 视频增强，并保留透明可审计的 `fallback` 机制。

---

## 安装与使用

### 1. 作为 Agent Skill 安装

方式 A — 使用 `skills` CLI：
```bash
npx skills add zeroa234/motion-comic
```

方式 B — 直接克隆到任意支持 Agent Skills 规范的目录（如 `.claude/skills/`、`.agents/skills/`、`.pi/skills/` 等）：
```bash
git clone https://github.com/zeroa234/motion-comic.git motion-comic-production
```

### 2. 运行零依赖契约自检（Python 3.10+）

无需安装任何深度学习或图形依赖，即可校验你的管线产物是否满足层间契约：

```bash
# 校验音频时间轴
python scripts/validate_contracts.py timeline assets/templates/timeline.template.json

# 校验 L1 编排配置并解析所有符号锚点
python scripts/validate_contracts.py page-map assets/templates/page-map.template.json \
  --timeline assets/templates/timeline.template.json

# 校验 L0 页面清单（加 --check-files 同时检查图像文件是否存在）
python scripts/validate_contracts.py manifest prepared/001/manifest.json --check-files

# 校验 L1 编译后的 story.json（支持传入新注册的自定义渲染器）
python scripts/validate_contracts.py story story.json --extra-renderers live2d_rig

# 校验 L3 质检报告交付门禁
python scripts/validate_contracts.py qc-report qc/qc_report.json
```

### 3. 替换底层技术栈

当你想将 L0 检测/去字、TTS、视频生成模型（如换新一代开源/云端 I2V/FL2V 模型）或 L2 渲染后端（如换 WebGPU / Godot / Remotion）替换掉时：
1. 查看 [adapters/README.md](adapters/README.md) 对应行的输入/输出契约与回归验证标准；
2. 在 `adapters/` 新增你的 `stack-<your-stack>.md` 映射文档；
3. 用同一套 `story.json` 与 `validate_contracts.py` / L3 门禁跑通验收即可，无需修改核心工程文档。

---

## License

[MIT](LICENSE)

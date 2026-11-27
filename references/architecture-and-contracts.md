# 四层解耦架构与数据契约（Stack-Agnostic）

本规范定义动态漫画生产管线的**稳定边界**。无论底层视觉模型、视频生成模型、TTS 或渲染后端如何换代，只要上下游遵守此处的**抽象能力**与**数据契约**，整条管线即可按层热替换。

---

## 1. 四层单向依赖架构

```text
Audio Pipeline (外部音频域)
    └─ 产出：Audio Master + timeline.json + 可选字幕(.srt/.ass)
                                  │
                                  ▼
L0 资产入口层 (Asset Prep / Ingest)
    ├─ Mode A：现成漫画原页 ──▶ 自动分格 / UI 保护 / 抠气泡 / 去字 / 深度
    ├─ Mode B：原创手绘 / AI 直出 ──▶ 跳过分格与去字，直接纯净单格打包 (+ 深度/可选分层)
    └─ Mode C：原作大幅二编 ──▶ 粗裁起稿 → 扩图/重绘/上色/关键帧 → 纯净单格回灌
        │ (三种入口收敛为同一 manifest 契约：prepared/<unit>/manifest.json)
        ▼
L1 导演编排层 (Director / Planner)──▶ 产出：story.json (+ 可选 AI 增强片段缓存)
        │ (只向下游暴露声明式 story 契约)
        ▼
L2 合成渲染层 (Compositor)        ──▶ 产出：video.mp4 + video.mp4.render_meta.json
        │ (后端插件化注册，支持受控 fallback)
        ▼
L3 质检审计层 (QC & Verifier)     ──▶ 产出：qc_report.json + qc_sheet.jpg + zones_overlay.jpg
```

### 强约束（架构红线）
- **禁止跨层反向依赖**：L0 不知道剧本和音频；L1 不依赖具体 GPU 渲染 API；L2 只认 `story.json` 与 L0 产物路径；L3 仅通过契约文件与最终 MP4 独立验收。
- **项目无关（Project-Agnostic）**：引擎代码与路径配置不得硬编码任何具体作品目录、模型绝对路径或服务端口，所有环境依赖必须经配置层/环境变量注入。
- **幂等与内容寻址缓存**：L0 解析与 AI 视频生成必须基于**输入文件内容哈希 + 关键参数哈希**做幂等缓存，避免修改局部镜头时重复计算未变素材。

---

## 2. 六大核心能力槽（可独立替换的插件边界）

| 能力槽 | 所在层 | 职责抽象 | 可替换示例（仅举方向） |
|---|---|---|---|
| **S1 音频与时间轴生成器** | 外部前置 | 产出人声/音效混音母带与逐事件时间戳表 | 任意本地/云端 TTS + Forced Aligner / 真人录音 + WhisperX 对齐 |
| **S2 页面拆层器** | L0 | 超分、分格排序、UI 保护、气泡抠层、局部修补去字、深度图 | YOLO / VLM 检测；LaMa / 扩散模型修补；Depth-Anything / 漫画专用深度模型 |
| **S3 导演编译器** | L1 | 将极简 `page-map` + `timeline` + `manifest` + `enhanced-spec` 编译为全量声明式 `story.json` | 确定性规则编译器 / LLM 辅助自动分镜器 |
| **S4 生成式视频后端** | L1/L2 | 将静态分格（单帧或首尾双帧）转为可控时长的动态片段 | 本地 I2V/FL2V（ComfyUI 等） / 云端视频 API / Live2D 骨骼导出 |
| **S5 实时/离线合成器** | L2 | 按 `story.json` 执行 2.5D 视差、局部形变、视频插值循环、气泡叠层、粒子与硬字幕编码 | ModernGL / WebGPU / Vulkan / Godot / Remotion / FFmpeg GPU 滤镜 |
| **S6 质检审计器** | L3 | 校验契约合法性、黑帧、音画同步、降级记录、无效形变与视觉标定图 | Python OpenCV + FFprobe / 多模态视觉审计模型（VLM） |

---

## 3. 层间数据契约规范

### 3.1 音频时间轴契约（`timeline.json`）
上游音频系统无论怎么生成，交付给动态漫画管线时只需提供一个 JSON 事件数组：
- **人声事件**：至少包含 `voice`（语者/轨道标识）、`line`（行号）、`t`（起始秒数）、可选 `speech: [onset_sec, end_sec]`（真实发声起止，用于剔除行首静音，精确触发气泡弹出）。
- **音效事件**：至少包含 `sfx`（音效逻辑名）、`t`（起始秒数）、`dur`（持续秒数）、可选 `under: true`（标记为垫底持续节律音效，用于驱动画面周期形变）。
- **可选扩展**：`duo` / 节律变速配置，用于描述持续音效随台词推进的倍率变化。

### 3.2 L0 页面清单契约（`prepared/<page>/manifest.json`）
每页预处理后必须输出自描述清单及标准相对路径文件：
- **页级元数据**：`schema`、`source_hash`、`size: [w, h]`、`is_monochrome`（黑白/彩色自动判定）、`is_chat_page`（全屏聊天/手机界面标识）、`panel_source`、`panels[]`、`bubbles[]`。
- **分格级（`panels[]`）**：
  - `id`（稳定分格 ID，如 `p01`）、`rect: [x0, y0, x1, y1]`（归一化页坐标）、`size: [pw, ph]`、`content_hash`、`dir`；
  - 目录下最小完备文件集：
    - `orig.png`（未去字原分格图，用于 UI/聊天页兜底与人工对照；在 Mode B/C 纯净源头模式下可与 `clean.png` 同源）；
    - `clean.png`（无字纯净底图，作为 2.5D 与 AI 视频的标准输入）；
    - `depth16.png`（16-bit 归一化深度图，避免 8-bit 量化阶梯伪影；纯 `video_clip` 镜头或聊天页可填中性平深度）；
    - 可选多层资产：`fg.png` / `bg.png`（透明前景与完整背景，Mode B 手绘直出或 Mode C 精修拆层可直接提供以获得无拉丝大视差）；
  - `bubbles[]`：按**分格内局部阅读序**排好序的气泡列表（Mode B/C 纯字幕或无气泡镜头可为空数组 `[]`），每项含 `id`、`file`（透明底 PNG 相对路径，支持逆向抠图或正向排版导出）、`panel_norm: [x0, y0, x1, y1]`（分格内归一化坐标）。

### 3.3 L1 导演声明契约（`story.json`）
`story.json` 是 L1 与 L2 的唯一沟通介质，**必须是纯声明式、可静态校验的 JSON**：
- **全局字段**：`schema`、`timeline`、`audio`、`prepared_dir`、`out`、`window: {start, end}`、`canvas: {width, height, fps, ssaa}`、`encode`、`bubble_mode`（推荐默认 `cue_sync`）、`fluid_style`、可选 `subtitles`。
- **镜头列表（`shots[]`）**：
  - 标识与绑定：`shot_id`、`page`、`panel`；
  - 渲染路由：`renderer`（如 `fast_25d` / `video_clip`）+ `fallback`（受控降级目标）；
  - 时间区间：`start` / `end`（支持数值或时间锚点表达式，解析后必须严格单调递增且时长 `> 0`）；
  - 运镜与转场：`fit`、`cam_from: [cx, cy, zoom]`、`cam_to: [cx, cy, zoom]`、`transition`、`transition_dur`；
  - 动态表现：`parallax_amp`、`depth_scale`、`rhythm[]`、`breath_amp`、`zones[]`、`show_bubbles`、`visible_bubbles`、`bubble_cues`、`use_orig`；
  - AI 片段控制（仅 `video_clip` 生效）：`clip_path`、`video_loop`、`video_trim`、`video_time_offset`、`video_desaturate`、`video_sharpen`。
- **静态校验硬规则（进入 L2 前必过）**：
  1. 必填顶层字段完整、`shots` 非空；
  2. 所有镜头时间单调递增且无非正时长；
  3. `renderer` 与 `fallback` 均在后端注册表内；
  4. 无空壳形变告警（`zones` 显式配置了全 0 幅度需告警）；
  5. 若关闭 `cue_sync` 且同时开启硬字幕与原气泡，需发出遮挡冲突告警。

### 3.4 L2 渲染元契约（`<video>.render_meta.json`）与 L3 质检契约（`qc_report.json`）
- **L2 伴生元数据**：记录每个镜头实际执行的后端名、是否触发 `fallback` 及原因（`missing_file` / `unknown_renderer` / `forced_fast`）、总 `fallback_count`。
- **L3 质检报告**：输出 `ok: bool`、`resolution`、`fps`、`expected_dur` / `actual_dur` / `dur_err`、`has_audio` / `audio_dur`、`black_shots[]`、`fallback_count`、`noop_zones[]`、`warnings[]`；失败必须返回**非零退出码**以便 CI / Agent 自动拦截。

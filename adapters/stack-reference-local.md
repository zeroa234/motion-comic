# 参考适配器：本地 GPU 四层动态漫画栈（Reference Local GPU Stack）

本适配器记录一套经过长篇实战验证的**本地单卡 GPU 参考实现**，用于演示如何将 [../references/](../references/architecture-and-contracts.md) 中的通用工程思路落地为可执行管线。
如更换其中任意组件，请参考 [README.md](README.md) 的热替换矩阵，仅替换对应能力槽即可。

---

## 1. 能力槽映射（Capability Binding）

| 能力槽 | 参考实现选型 | 关键特性 |
|---|---|---|
| **L0 条件超分** | 动漫保真 2× 超分模型（如 Real-CUGAN 2×） | 宽 `< 1600px` 自动触发，高分辨率原图跳过 |
| **L0 分格与气泡检测** | YOLO 系列漫画分格/气泡检测权重 | 支持行重叠聚类阅读序排序、`--panels-override` 与 `--keep-boxes` |
| **L0 局部去字修补** | 局部裁块 LaMa（CUDA） | 单次像素去重羽化；黑白页单色化；自由字走笔画紧致掩码防渗白 |
| **L0 深度估计与可选拆层** | Depth-Anything-V2（16-bit）+ 可选 BiRefNet | 聊天记录页跳过推理直出平深度；支持 `--low-vram` 分阶段显存卸载 |
| **L1 导演编译器** | `story.py` + `schema.py` | 消费 `page-map.json` + `timeline.json` + `manifest.json` + 可选 `enhanced-spec.json`，输出 `story.json` |
| **L1/L2 AI 视频增强** | 本地 ComfyUI HTTP API（支持 I2V 单首帧 & FL2V 首尾帧） | 语义节点定位（不硬编码节点 ID）、SHA256 真哈希幂等缓存、默认跳过无用音频解码 |
| **L2 2.5D / 混合合成器** | 无头 ModernGL（2× SSAA）+ FFmpeg 硬件编码（NVENC） | 微分同胚深度视差 + 各向同性 `zones` + GPU 亚帧插值 + 连续积分节律 + GPU Metaball 流体 + `cue_sync` 气泡 + 并行硬字幕 + 滑窗资源释放 |
| **L3 质检审计器** | OpenCV + FFprobe (`qc.py`) | 3 点黑帧抽检 + 音画时长核验 + `render_meta` 降级核验 + `noop_zones` 检测 + `qc_sheet.jpg` / `zones_overlay.jpg` + 失败返回非零退出码 |

---

## 2. 环境配置注入（禁止硬编码本机路径）

实现应通过统一配置模块读取环境变量覆盖默认值，确保跨机器/跨项目可移植：

| 环境变量 | 作用 |
|---|---|
| `MOTION_COMIC_MODELS_DIR` | L0 视觉权重目录（分格、气泡、修补、深度） |
| `COMFYUI_MODELS_DIR` | 可选共享视觉/超分模型目录 |
| `COMFYUI_URL` | 本地或远程视频生成工作流服务地址（如 `http://127.0.0.1:8188`） |
| `COMFYUI_TEMPLATES_DIR` | 单首帧 / 首尾帧工作流模板 JSON 目录 |
| `MOTION_COMIC_ACCEL_LORA` | 可选步数加速 LoRA 文件名 |
| `MOTION_COMIC_STYLE_LORA` | 可选默认风格 LoRA（`name:strength`；设为空串或 `none` 禁用） |
| `FFMPEG_BIN` / `FFPROBE_BIN` | FFmpeg / FFprobe 可执行路径（默认自动探测 `PATH`） |

---

## 3. 标准五步 CLI 映射

假设引擎包挂载为 `motion_comic`（例如 `python -m src.motion_comic <cmd>`）：

```bash
# 1. L0 资产预处理（支持 --include-free-text / --low-vram / --panels-override / --keep-boxes / --no-protect-chat-ui / --save-intermediate）
python -m src.motion_comic prep \
  --pages-dir <pages_dir> \
  --out-dir <prep_dir> \
  --skip-existing

# 2. L1 编排快产基线 story.json
python -m src.motion_comic story \
  --page-map <page-map.json> \
  --out <story-fast25d.json>

# 3. L2 渲染纯 2.5D 快产基线并做 L3 质检（先验证对轴与视觉干净度）
python -m src.motion_comic render <story-fast25d.json> --out <out-fast25d.mp4>
python -m src.motion_comic qc <story-fast25d.json> <out-fast25d.mp4> --out-dir <qc-fast25d> --draw-zones

# 4. (可选) L1/L2 为精选镜头生成 AI 视频片段
# 4a. 周期往复镜头 → 首尾同帧无缝闭环（FL2V）
python -m src.motion_comic enhance i2v \
  --image <panel_clean.png> --out <clip_loop.mp4> \
  --seamless-loop \
  --prompt "subtle rhythmic breathing and hair sway, static framing" \
  --megapixels 0.5 --timeout 480

# 4b. 相邻两格过渡 → 异帧首尾插值（FL2V）
python -m src.motion_comic enhance i2v \
  --image <panel_a_clean.png> --last-image <panel_b_clean.png> --out <clip_trans.mp4> \
  --prompt "smooth continuous camera transition and pose shift between frames" \
  --megapixels 0.5 --timeout 480

# 4c. 单向爆发/流体/状态变化 → 单首帧（I2V）；全彩/水彩漫务必传 --no-default-lora
python -m src.motion_comic enhance i2v \
  --image <panel_clean.png> --out <clip_burst.mp4> \
  --no-default-lora \
  --prompt "gentle tears rolling down cheeks, hair swaying in wind, preserving original warm watercolor palette" \
  --megapixels 0.5 --timeout 480

# 5. L1 注入 enhanced-spec.json 生成混合版 story.json，渲染并通过 L3 质检
python -m src.motion_comic story \
  --page-map <page-map.json> \
  --enhanced-spec <enhanced-spec.json> \
  --out <story-hybrid.json>
python -m src.motion_comic render <story-hybrid.json> --out <out-hybrid.mp4>
python -m src.motion_comic qc <story-hybrid.json> <out-hybrid.mp4> --out-dir <qc-hybrid> --draw-zones
```

---

## 4. 本栈关键实测经验（栈特定避坑）

1. **黑白 vs 全彩 AI 增强开关**：
   - 黑白日漫：默认风格 LoRA 可强化赛璐珞线条，`enhanced-spec` 中设 `"video_desaturate": 1.0`、`"video_sharpen": 0.15`。
   - 全彩/水彩漫：生成时务必传 `--no-default-lora`（防扁平风格 LoRA 抹平手部与渐变），并在 `enhanced-spec` 设 `"video_desaturate": 0.0`。
2. **显存与工作流兼容性**：
   - 使用量化视频扩散模型时保留 ComfyUI 默认动态显存管理（避免强加 `--highvram` 导致 OOM）；
   - 通过节点 `class_type` 与连线拓扑反查输入/输出节点，避免模板增删节点后硬编码数字 ID 失效；
   - 默认像素预算约 `0.5 MP`（配合 2× VSR 超分至约 `2.1 MP`），在锐度、暗部静态无噪点闪烁与动态稳定度之间较平衡。
3. **无头环境硬件渲染兜底**：
   - Windows 本机优先使用原生 OpenGL + `h264_nvenc`；
   - 若远程桌面断连或无显示器导致 WGL 回落 CPU 软渲染（如 GDI Generic），可切至 Linux/WSL2 无头 EGL（如 `GALLIUM_DRIVER=d3d12` 指定独显适配器）并显式配置 `:fontsdir` 指向系统字体目录，确保硬字幕字体一致且维持 GPU 速度。
4. **L2 后端注册与降级契约**：
   - `RendererRegistry` 维护 `fast_25d` 与 `video_clip` 等后端，新后端只需实现 `validate_shot(shot, base_root) -> err | None` 并注册即可接入，缺片时退回 `fallback` 并将事件写入 `<out>.render_meta.json`。

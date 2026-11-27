# 技术栈适配器规范与替换指南（Stack Adapters）

本目录存放**与具体模型、引擎、CLI、环境变量强绑定**的实现映射。
主干文档 [../SKILL.md](../SKILL.md) 与 [../references/](../references/architecture-and-contracts.md) 不得直接依赖这里的任何具体技术栈名称，从而确保未来替换任意组件时**无需重写工程方法论**。

---

## 1. 现有参考适配器

| 适配器文档 | 覆盖范围 | 适用场景 |
|---|---|---|
| [stack-reference-local.md](stack-reference-local.md) | 完整 L0–L3 本地 GPU 参考栈（YOLO 分格 + LaMa 去字 + Depth-Anything-V2 + ModernGL 2.5D + ComfyUI I2V/FL2V + FFmpeg/NVENC） | 本机单卡高保真全链路生产（支持纯 2.5D 快产与混合 AI 双轨） |
| [audio-timeline-adapter.md](audio-timeline-adapter.md) | 外部音频域 → `timeline.json` + 混音母带 + `.srt`/`.ass` | 对接任意多角色本地 TTS、云端 TTS 或真人录音 + 强制对齐器 |

---

## 2. 按层热替换矩阵（如何升级技术栈）

当你需要把某一层升级为更新的模型或服务时，只需满足下表契约，其余三层保持不动：

| 替换目标 | 只需遵守的输入/输出契约 | 替换后必跑的回归验证 |
|---|---|---|
| **换 L0 分格/去字/深度模型**（如换 VLM 检测、扩散修补、新深度模型） | 产出符合 `motion-comic-l0/v2` 的 `manifest.json` + `orig.png` + `clean.png` + `depth16.png` + 独立透明气泡 PNG | ① 跑 `scripts/validate_contracts.py manifest`；<br>② 核验黑白页零彩噪、无二次修补糊斑、聊天 UI 未被误擦、白边自由字无渗灰 |
| **换音频 / TTS / 对齐栈**（如换新多语 TTS、Edge TTS、WhisperX、真人配音） | 产出混音母带音频 + `timeline.json`（含 `voice`、`line`、`t`、`speech`、可选 `sfx`/`under`）+ 可选 `.srt` | ① 跑 `scripts/validate_contracts.py timeline`；<br>② 验证 `page-map.json` 所有符号锚点可解析且无负时长 |
| **换 AI 视频生成模型**（如从本地 I2V 换新一代开源模型或云端 I2V/FL2V API） | 接收 `clean.png`（及可选尾帧）+ 提示词，按内容哈希缓存输出标准 MP4 到 `clip_path`，支持单首帧与首尾帧两种模式 | ① **双样本 A/B**：同时测“偏静态微动特写”与“高动态动作/流体镜头”；<br>② 验证黑白去饱和锁色与全彩原色调保真；<br>③ 核验循环接缝无重影/无姿态漂移 |
| **换 L2 渲染/合成引擎**（如从 ModernGL 换 WebGPU / Vulkan / Godot / Remotion / FFmpeg） | 消费 `story.json` 与 L0 资产，输出目标分辨率 MP4 + `<video>.render_meta.json`（含 `fallback_count` 与事件列表） | ① 用同一份 `story.json` 渲染；<br>② 跑 L3 门禁：时长误差 `<= 0.25s`、音画 `<= 0.35s`、零黑帧、`fallback_count == 0`；<br>③ 核验 2× SSAA 无摩尔纹抖动与 `cue_sync` 气泡对齐 |
| **新增 L2 渲染后端**（如新增 Live2D / 骨骼拆件后端） | 在后端注册表中新增 `renderer` 名与校验函数，并声明兼容的 `fallback` | ① `story.json` 静态校验放行新 `renderer`；<br>② 缺资产时能正确降级并在 `render_meta.json` 留痕 |

---

## 3. 新增自定义适配器的标准模板

为新环境或新技术栈创建 `adapters/stack-<name>.md` 时，建议按固定 5 节编写：
1. **能力槽映射表**（S1–S6 分别绑定了什么工具/模型/API）；
2. **环境与配置注入**（全部以环境变量或配置文件表达，禁止写死个人绝对路径）；
3. **标准 CLI / 调用命令**（L0 `prep` → L1 `story` → AI `enhance` → L2 `render` → L3 `qc`）；
4. **该栈特有参数与避坑点**（显存策略、LoRA 开关、分辨率甜点、无头加速兜底等）；
5. **契约兼容声明**（声明兼容的 `manifest` / `story` / `qc` schema 版本）。

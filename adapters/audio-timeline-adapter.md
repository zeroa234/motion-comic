# 音频域适配规范（Audio & Timeline Adapter）

动态漫画管线不关心音频是如何制作出来的（多角色本地 TTS、云端配音 API、或真人录音均可），只要求音频域在交付阶段输出**满足统一契约的三件套**：

1. **混音成品母带**（`.wav` / `.m4a`，推荐响度规范化且真峰值 `<= -1 dBTP`）；
2. **真实时间轴文件**（`timeline.json`）；
3. **可选字幕文件**（`.srt` / `.ass`，用于底部硬字幕渲染）。

---

## 1. `timeline.json` 最小契约格式

参考模板见 [../assets/templates/timeline.template.json](../assets/templates/timeline.template.json)。

`timeline.json` 为按时间顺序排列的 JSON 事件数组，每条事件遵循以下两种形态：

### 1.1 人声事件（Voice Event）
```json
{
  "voice": "A:t1",
  "line": 1,
  "t": 0.40,
  "speech": [0.46, 3.12],
  "text": "这间旧书店的地下室，果然还留着那本手稿。"
}
```
- `voice`（必填）：角色与轨道唯一标识（如 `"A:t1"`、`"narrator"`），与 `line` 组合成锚点键 `"{voice}@{line}"`；
- `line`（必填）：整数行号；
- `t`（必填）：该句在混音母带中的起始时间（秒）；
- `speech`（强烈推荐）：`[onset_sec, end_sec]`，剔除句首静音后的真实开口与闭口时刻。L1 用 `speech[0]` 精确触发 `cue_sync` 气泡弹出，用 `speech[1]` 作为 `anchor$` 句尾切镜锚点；若省略则退化为 `t`。

### 1.2 音效事件（SFX Event）
```json
{
  "sfx": "env_door_slam",
  "t": 3.45,
  "dur": 0.85,
  "under": false
}
```
- `sfx`（必填）：音效逻辑名，锚点键为 `"sfx:<name>"`（同名多次出现时通过 `"index": 0, 1, ...` 指定）；
- `t`（必填）：起始时间（秒）；
- `dur`（推荐）：持续时长（秒），用于计算 `"sfx:<name>$"` 结束锚点及 `under` 节律区间；
- `under`（可选布尔）：为 `true` 时表示持续垫底节律音效（如心跳、脚步、风浪、周期动作），L1 将自动据此推导画面 `rhythm` 段并按优先级仲裁重叠区间。

---

## 2. 常见音频技术栈接入路径

| 音频来源 | 如何产出 `timeline.json` | 关键注意事项 |
|---|---|---|
| **多角色本地/云端 TTS 混音管线** | 逐句生成音频 → Forced Aligner / VAD 检测每句真实 `speech: [onset, end]` → 混音器拼接并直接导出 `timeline.json` + `.srt` | 严禁凭字数估算时间；必须基于**实际混音落盘时间**导出 `timeline.json`，否则长片 5 分钟后必累积漂移 |
| **真人配音 / 现成广播剧母带** | 使用 WhisperX / Qwen3-Forced-Aligner / MFA 对母带做逐句对齐 → 将对齐片段转写成 `voice`+`line` 事件；手动或靠音频事件检测标注关键 `sfx` 时间戳 | 同一句被拆段时保持 `line` 编号与剧本一致，方便 `page-map.json` 维护 |
| **并行多角色重叠对白** | 两个角色事件允许时间重叠；生成 `.srt`/`.ass` 时保留重叠时间区间，由 L2 渲染器上下分行显示（避免后句截断前句） | 同格内 `cue_sync` 气泡会按时间窗内所有 `speech[0]` 去重排序（间隔 `< 0.15s` 合并） |

---

## 3. 音频与画面协同的工程建议

- **口部/近场人声类音效 vs 环境/动作垫底音**：口部或强前景音效尽量放在台词空当，避免掩蔽对白清晰度；环境、衣物、心跳、节奏动作音可作为 `under: true` 垫在台词下并自动驱动 L2 画面节律。
- **任何音频改动后的一键重编**：只要 `page-map.json` 全部使用符号锚点（禁止硬编码秒数），重新混音生成新 `timeline.json` 后，重跑 L1 `story` 即可全自动对齐全片分格、气泡与节律，无需手工挪帧。

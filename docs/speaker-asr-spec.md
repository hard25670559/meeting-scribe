# 說話者辨識與 ASR 強化規格書

## 專案背景

本文件基於 Meeting Scribe 現有系統（詳見 `SPEC.md`），規劃下一階段的功能強化方向，目標是解決現有的 ASR hallucination 問題，並加入說話者辨識能力，讓逐字稿從「說了什麼」升級為「誰說了什麼」。

---

## 現有系統回顧

```
主執行緒：音訊擷取 → VAD 語音切段 → Queue
ASR 執行緒：Queue → Whisper ASR → 逐字稿輸出
```

### 現有問題

| 問題 | 說明 |
|------|------|
| ASR Hallucination | Whisper 在靜音或噪音輸入時會捏造文字（如「中文字幕志願者 XXX」、大量重複字元） |
| VAD 精度不足 | Silero VAD 偵測「有聲音活動」，但無法區分人聲與背景噪音，導致髒資料送進 Whisper |
| 無說話者資訊 | 逐字稿無法區分誰在說話 |

---

## 目標

1. **降低 Hallucination**：強化 VAD 的人聲辨識精度，搭配微調 Whisper，讓 ASR 學會在輸入是噪音時輸出空字串
2. **說話者辨識**：辨別一段音訊中有哪些人在說話（Diarization），並識別出這個人是誰（Identification）
3. **聲紋記憶**：建立聲紋資料庫，首次見到的說話者可事後標記，之後自動辨識
4. **為線上服務做準備**：ASR 保留水平擴展能力（現有分散式架構），pyannote.audio 跑在 Capture Service 端

---

## 新整體架構

```
音訊輸入
  ↓
① VAD（Silero VAD）
  判斷是否有聲音活動，切出語音片段
  ↓
  ┌─────────────────────────────────┐
  │                                 │
② pyannote.audio                 ③ Whisper ASR
  Speaker Diarization                （現有分散式架構）
  + Speaker Identification           WAV → 文字
  誰說了這段？這個人是誰？
  │                                 │
  └──────────────┬──────────────────┘
                 ↓
            合併結果
  [張三 00:00:03] 今天開會討論...
  [李四 00:00:30] 我覺得這個方案...
  [未知 00:01:00] 補充一下...
```

### 模組部署位置

| 模組 | 部署位置 | 水平擴展 |
|------|---------|---------|
| VAD（Silero） | Capture Service 端 | 不需要 |
| pyannote.audio | Capture Service 同機 | 不需要 |
| Whisper ASR | ASR Worker（現有） | 支援，未來線上服務需要 |

---

## 各模組規格

### 模組一：VAD 強化

**現況**：Silero VAD 只偵測「有聲音活動」，無法過濾背景音樂、冷氣噪音等非人聲

**強化方向**：
- 調高 `speech_threshold`（建議 0.6~0.7），讓 VAD 更嚴格
- 加入音量下限過濾（現有邏輯），過低音量片段直接丟棄
- 依賴 pyannote.audio 的人聲偵測能力進一步把關

**技術選型**：維持 Silero VAD，不替換

---

### 模組二：說話者辨識（Speaker Diarization + Identification）

**技術選型：pyannote.audio**

| 項目 | 說明 |
|------|------|
| 套件 | `pyannote.audio` |
| 授權 | MIT（需申請 Hugging Face token） |
| 輸入 | WAV 音訊片段 |
| 輸出 | 說話者標記（誰說了哪段）+ 聲紋向量 |
| 執行位置 | Capture Service 同機 |
| 模型 | `pyannote/speaker-diarization-3.1` |

**功能說明**：

pyannote.audio 同時完成兩件事：

```
WAV 輸入
  ↓
Diarization：誰說了哪段
  片段A (00:00-00:30) → Speaker_0
  片段B (00:30-01:00) → Speaker_1

Identification：這個 Speaker 是誰（比對聲紋資料庫）
  Speaker_0 → 聲紋比對 → 張三（相似度 0.97）
  Speaker_1 → 聲紋比對 → 未知（最高相似度 0.31，低於閾值）
```

---

### 模組三：聲紋資料庫

**聲紋本質**：一段語音經過 Speaker Encoder 輸出的固定維度向量，代表說話者的聲音特徵

**比對方式**：餘弦相似度（Cosine Similarity）

```
新聲音 → 向量
  ↓
與資料庫所有人的向量比對
  張三：相似度 0.97 ← 超過閾值，認定為張三
  李四：相似度 0.23
```

**建立方式**：

| 方式 | 說明 | 適用情境 |
|------|------|---------|
| 事前登記 | 讓說話者錄幾句話，存入資料庫 | 固定成員的例行會議 |
| 事後標記 | 會議結束後，人工告知 Speaker_0 是張三，自動存入 | 首次見到的說話者 |

**儲存格式**：

```json
{
  "speakers": [
    {
      "name": "張三",
      "embedding": [0.23, -0.87, 0.45, ...],
      "registered_at": "2026-03-11T10:00:00"
    },
    {
      "name": "李四",
      "embedding": [0.61, 0.12, -0.33, ...],
      "registered_at": "2026-03-11T10:00:00"
    }
  ]
}
```

**識別閾值**：相似度低於閾值視為「未知說話者」，預設 0.75（可設定）

---

### 模組四：Whisper Fine-tuning

**目標**：讓 Whisper 學會在輸入是靜音或噪音時輸出空字串，根除 hallucination

#### 問題根源

Whisper 訓練資料幾乎都是「語音 → 文字」的配對，極少有「靜音 → 空字串」的樣本，導致模型不知道可以什麼都不輸出，遇到噪音就捏造文字。

#### 訓練策略

**架構選擇**：只微調 Decoder，凍結 Encoder

```
Encoder（音頻理解）→ 凍結，不更新
Decoder（文字生成）→ 微調，用 LoRA
```

原因：hallucination 發生在 Decoder 生成階段，Encoder 的音頻理解能力沒問題

**微調方法：LoRA（Low-Rank Adaptation）**

| 項目 | 說明 |
|------|------|
| 方法 | LoRA，只訓練插入的小矩陣，主權重不動 |
| 工具 | Hugging Face `transformers` + `peft` |
| VRAM 需求 | 約 16GB（相比全量微調的 40GB+） |
| 訓練目標 | `large-v3-turbo`（Decoder 只有 4 層，成本更低）|

**訓練資料格式**：

| 音頻內容 | 標籤 |
|---------|------|
| 靜音片段 | `""` （空字串） |
| 背景噪音（冷氣、鍵盤聲） | `""` |
| 正常語音 | 正確轉錄文字 |

負樣本來源：
- 從現有錄音中截取靜音段
- 從 VAD 過濾掉的片段（這些就是噪音）

正樣本來源：
- 現有逐字稿對應的 WAV 片段

**後處理補強（fine-tuning 之前就可以做）**：

```python
HALLUCINATION_PATTERNS = [
    r"中文字幕志願者[：:].{0,20}",
    r"字幕[校對製作翻譯]{2,}[：:].{0,20}",
    r"(.)\1{10,}",  # 任何字元重複超過 10 次
]
```

---

## 輸出格式

### 現有格式
```
[00:00:03.264 - 00:00:08.224] 所以真正要問的問題並不是說
```

### 新格式
```
[張三 00:00:03.264 - 00:00:08.224] 所以真正要問的問題並不是說
[李四 00:00:30.000 - 00:00:35.000] 我覺得這個方案可行
[未知_1 00:01:00.000 - 00:01:05.000] 補充一下
```

---

## 設定檔新增項目

```yaml
# 說話者辨識設定
speaker:
  enabled: true                        # 是否啟用說話者辨識
  diarization_model: pyannote/speaker-diarization-3.1
  identification_threshold: 0.75       # 聲紋比對相似度閾值，低於此值視為未知說話者
  database_path: ./speakers.json       # 聲紋資料庫路徑
  hf_token: null                       # Hugging Face token（pyannote 需要）

# Fine-tuned 模型設定（未來）
asr:
  model: large-v3-turbo                # 可替換為 fine-tuned 版本的路徑
  # model: ./models/finetuned-large-v3-turbo
```

---

## 開發階段規劃

### 階段一：後處理過濾（立即）

目標：不動模型，立刻改善輸出品質

- [ ] 在 ASR 輸出後加入正規表達式過濾，清除已知 hallucination 模式
- [ ] 調整 `speech_threshold` 至 0.65，減少噪音片段送進 Whisper

### 階段二：自動資料收集（與階段一同步進行）

目標：讓系統邊跑邊自動整理 fine-tuning 訓練資料

- [ ] 在 ASR 辨識流程中加入資料分類邏輯：
  - 觸發 hallucination 模式的片段 → 存入 `training_data/negative/`（WAV + 空字串標籤）
  - 正常辨識結果 → 存入 `training_data/positive/`（WAV + 辨識文字）
- [ ] 持續跑幾天，累積至正樣本 300 筆以上、負樣本 100 筆以上

```
transcripts/training_data/
├── positive/   ← 正常辨識（WAV + 辨識文字）
└── negative/   ← hallucination 片段（WAV + 空字串）
```

### 階段三：Whisper Fine-tuning（資料足夠後）

目標：微調 `large-v3-turbo` Decoder，讓模型學會噪音輸入時輸出空字串

**硬體選擇**：Mac M4 Max（PyTorch MPS + 128GB unified memory）

- [ ] 設置 LoRA fine-tuning 環境（PyTorch MPS + Hugging Face `peft`）
- [ ] 訓練配置：
  - `gradient_checkpointing=True`
  - `batch_size=1`，`gradient_accumulation_steps=8`
- [ ] 微調 `large-v3-turbo` Decoder（凍結 Encoder）
- [ ] 驗證 hallucination 改善效果
- [ ] 整合 fine-tuned 模型至現有系統

### 階段四：說話者辨識（階段三完成後）

目標：逐字稿從「說了什麼」升級為「誰說了什麼」

- [ ] 整合 pyannote.audio
- [ ] 建立聲紋資料庫讀寫模組
- [ ] 實作事後標記 CLI 指令（`python main.py --label-speakers`）
- [ ] 更新逐字稿輸出格式，加入說話者標記

---

## 技術依賴新增

```
pyannote.audio>=3.1.0
pyannote.core>=5.0.0
peft>=0.10.0          # LoRA fine-tuning（階段三）
datasets>=2.0.0       # 訓練資料處理（階段三）
```

> `pyannote.audio` 需申請 Hugging Face token 並同意模型授權條款

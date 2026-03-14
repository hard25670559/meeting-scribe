# Whisper Fine-tuning 計畫

## 目標

讓 Whisper large-v3 學會在「非人聲」音訊（靜默、背景音樂、雜訊）輸入時輸出空字串，抑制幻覺（hallucination）。

---

## 現有資源

### 標記完成的資料（510 筆）

| 標記 | 數量 | 訓練用途 |
|------|------|----------|
| 無音效 | 353 | WAV → `""` （主要訓練目標） |
| 辨識錯誤 | 97 | WAV → correction 欄位的正確文字 |
| 正確辨識 | 37 | 不進訓練集（或作為正樣本保留原始 pair） |
| 無法辨識 | 23 | 不進訓練集（片段太短，無法判斷） |

- 資料來源：`hallucination_review/review.csv`
- 音訊格式：WAV 16kHz（位於 `transcripts/transcript_*/` 目錄下）

### 幻覺 Pattern 來源

從 YouTube Podcast 錄音中以正規表達式抓取的水印/片尾語：

| Pattern | 筆數 | 幻覺率 |
|---------|------|--------|
| `字幕`（含 字幕志願者、中文字幕 等） | 244 | 95% |
| `MING PAO` | 64 | 98% |
| `感謝[觀收]看` / `謝謝[觀收]看` | 50 | 98% |
| `明鏡[及與]點點欄目` | 45 | 78% |
| `我們下[期集]再見` | 35 | 66% |
| `下[期集]見` | 20 | 90% |
| `明鏡需要您的支援` | 14 | 93% |
| `by bwd6` | 12 | 92% |
| `優優獨播劇場` / `YoYo Television Series` | 11 | 73% |

---

## 硬體環境

| 環境 | 規格 | 用途 |
|------|------|------|
| Windows | NVIDIA GPU 8GB VRAM, faster-whisper (CUDA) | 日常推論 |
| Mac | M4 Max 128GB 統一記憶體 | **訓練** + 推論（mlx-whisper） |

---

## 訓練方案

### 方法：凍結 Encoder + 只對 Decoder 做 LoRA

- **Base model**：`openai/whisper-large-v3`
- **凍結 Encoder**：Encoder 負責音訊特徵提取，不需修改
- **只訓練 Decoder**：幻覺是 Decoder 在沒有語音對應時仍生成文字的問題
- **使用 LoRA**：355 筆資料做 full fine-tune 容易過擬合，LoRA 只訓練少量 adapter 參數

### 超參數

| 參數 | 值 | 說明 |
|------|-----|------|
| learning_rate | 1e-5 | 微調用小學習率，避免破壞預訓練權重 |
| epochs | 3 | 資料量少，不宜訓練太多輪 |
| batch_size | 8 | M4 Max 128GB 記憶體充足 |
| warmup_steps | 50 | 開始時用更小的 lr 暖機 |
| weight_decay | 0.01 | 正則化，防止過擬合 |
| early_stopping | patience=2 | 驗證 loss 連續 2 次不降就停止 |
| LoRA rank | 16 | adapter 的大小，16 對小資料集夠用 |
| LoRA alpha | 32 | 通常設為 rank 的 2 倍 |
| LoRA target | decoder attention layers | q_proj, v_proj |

### 資料分割

```
510 筆標記資料
├── 訓練用：無音效 (353) + 辨識錯誤 (97) = 450 筆
│   ├── 訓練集 90%：~405 筆
│   └── 驗證集 10%：~45 筆
└── 不進訓練集：正確辨識 (37) + 無法辨識 (23) = 60 筆
```

---

## 執行步驟

### Step 1：匯出訓練資料（Windows）

執行匯出腳本，從 `review.csv` 產生：
```
finetune_data/
├── audio/          # 複製過來的 WAV 檔案
├── train.json      # 訓練集 {"audio": "path", "text": "..."}
└── eval.json       # 驗證集
```

訓練 pair 規則：
- 標記 `無音效` → `{"audio": "xxx.wav", "text": ""}`
- 標記 `辨識錯誤` 且有填 correction → `{"audio": "xxx.wav", "text": "correction欄位的正確文字"}`

### Step 2：複製到 Mac

將 `finetune_data/` 資料夾整個複製到 Mac。

### Step 3：在 Mac 上訓練

```bash
# 安裝依賴
pip install transformers datasets peft accelerate soundfile

# 執行訓練腳本
python finetune.py \
  --data_dir ./finetune_data \
  --model openai/whisper-large-v3 \
  --output_dir ./whisper-large-v3-finetuned \
  --device mps
```

預估訓練時間：M4 Max 上約 **5-15 分鐘**。

### Step 4：轉換模型格式

訓練完成後，需要轉換成兩種推論框架的格式：

#### 4a. 轉 CTranslate2（Windows faster-whisper 用）
```bash
pip install ctranslate2

# 先合併 LoRA adapter 回 base model
python merge_lora.py \
  --base_model openai/whisper-large-v3 \
  --lora_path ./whisper-large-v3-finetuned \
  --output_dir ./whisper-large-v3-merged

# 轉換格式
ct2-whisper-converter \
  --model ./whisper-large-v3-merged \
  --output_dir ./whisper-large-v3-ct2 \
  --quantization float16
```

#### 4b. 轉 MLX（Mac mlx-whisper 用）
```bash
pip install mlx mlx-whisper

python convert_to_mlx.py \
  --model ./whisper-large-v3-merged \
  --output_dir ./whisper-large-v3-mlx
```

### Step 5：部署使用

**Windows**：將 `whisper-large-v3-ct2/` 複製回 Windows，修改 `config.yaml`：
```yaml
asr:
  model: ./models/whisper-large-v3-ct2   # 指向本地模型路徑
```

**Mac**：將 `whisper-large-v3-mlx/` 放在 Mac 本地：
```yaml
asr:
  model: ./models/whisper-large-v3-mlx
```

---

## 評估方式

訓練完成後，用以下方式驗證效果：

1. **幻覺抑制測試**：用標記為 `無音效` 的驗證集音訊跑推論，確認輸出為空字串
2. **正常語音測試**：用標記為 `正確辨識` 的音訊跑推論，確認正常語音不受影響
3. **A/B 比較**：同一段完整錄音，分別用原始模型和 fine-tuned 模型跑一次，比較 transcript 差異

### 成功標準

- 無音效片段的幻覺輸出減少 > 80%
- 正常語音辨識品質無明顯下降（WER 差異 < 2%）

---

## 後續規劃

- 持續收集更多標記資料（目標 1,000+ 筆）
- 資料量足夠後可嘗試 Decoder full fine-tune
- 將 hallucination pattern 過濾整合到 ASR pipeline 中自動收集訓練資料（ROADMAP 階段二）

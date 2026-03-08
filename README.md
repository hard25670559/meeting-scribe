# Meeting Scribe

跨平台系統音訊擷取與即時語音轉逐字稿工具。同時擷取電腦的音訊輸出與麥克風輸入，透過 Faster Whisper 即時轉換為帶時間戳的繁體中文逐字稿，供後續會議整理使用。

## 功能特色

- 同時擷取系統音訊與麥克風，即時轉換為逐字稿
- 使用 Faster Whisper（large-v3）進行高準確度語音辨識
- 辨識結果自動轉換為繁體中文（OpenCC s2twp 台灣慣用詞）
- 逐行即時寫入檔案，避免程式崩潰時遺失資料
- VAD 語音片段同步存為 WAV 檔，供除錯與回聽
- 支援 Windows、Linux、macOS 三大平台

## 架構概覽

```
主執行緒：系統音訊 + 麥克風 → 音訊擷取 → 多聲道混合為單聲道 → VAD 語音切段 → 存 WAV → Queue
ASR 執行緒：Queue（WAV 路徑）→ Faster Whisper → OpenCC 簡轉繁 → 逐字稿輸出
```

錄音與 VAD 在主執行緒持續運行，ASR 辨識在獨立執行緒中處理。Queue 只傳遞 WAV 檔案路徑（非音訊資料），ASR 從硬碟讀取音訊，減少記憶體佔用。

### 技術選型

| 元件 | 技術 | 說明 |
|------|------|------|
| 音訊擷取 | soundcard | 跨平台音訊擷取 |
| VAD | Silero VAD | 語音活動偵測，切分語音段落 |
| ASR | Faster Whisper | Whisper 加速版，支援多語言 |
| 繁體轉換 | OpenCC | s2twp 模式，含台灣慣用詞 |

## 快速開始

### 前置需求

- Python 3.10+
- macOS 需額外安裝 [BlackHole](https://github.com/ExistentialAudio/BlackHole)（`brew install blackhole-2ch`）

### 安裝

```bash
# 建立虛擬環境
python -m venv .venv
source .venv/bin/activate  # macOS / Linux
# .venv\Scripts\activate   # Windows

# 安裝依賴
pip install -r requirements.txt

# 複製設定檔
cp config.yaml.example config.yaml
```

### 執行

```bash
python main.py
```

首次執行會自動下載 Whisper 模型（large-v3 約 3GB），之後啟動會列出可用音訊裝置供選擇。選擇裝置後開始錄音與辨識，按 `Ctrl+C` 停止。

### 輸出結構

每次錄製會建立專屬資料夾：

```
transcripts/
└── transcript_20260308_143000/
    ├── transcript_20260308_143000.txt   # 逐字稿
    ├── 00m05.123s-00m08.456s.wav        # VAD 語音片段
    ├── 00m12.789s-00m15.012s.wav
    └── ...
```

逐字稿格式：

```
[00:00:05.123 - 00:00:08.456] 今天的會議主題是...
[00:00:12.789 - 00:00:15.012] 我們來討論一下進度
```

## 設定

編輯 `config.yaml`（參考 `config.yaml.example`）：

```yaml
audio:
  device: null          # 音訊裝置名稱，null 時啟動會詢問
  sample_rate: 16000

vad:
  silence_threshold: 1.5  # 靜音多久視為一段結束（秒）

asr:
  model: large-v3        # Whisper 模型大小
  language: zh            # 辨識語言，null 為自動偵測
  device: auto            # 推理裝置：auto / cpu / cuda
  convert_traditional: true

output:
  directory: ./transcripts
```

## macOS 音訊設定

macOS 需透過 BlackHole 虛擬音訊裝置擷取系統音訊：

1. 安裝 BlackHole：`brew install blackhole-2ch`
2. 開啟「音訊 MIDI 設定」（Audio MIDI Setup）
3. 建立**多重輸出裝置**：勾選耳機/喇叭 + BlackHole 2ch（讓你聽到聲音 + 程式擷取）
4. 建立**聚合裝置**：勾選麥克風 + BlackHole 2ch（同時擷取兩個音源）
5. 系統音訊輸出切換至多重輸出裝置
6. 程式擷取時選擇聚合裝置

## 專案結構

```
meeting-scribe/
├── main.py                  # 程式進入點
├── config.yaml.example      # 設定檔範本
├── requirements.txt         # Python 依賴
├── docs/
│   ├── SPEC.md              # 開發規格書
│   └── implementation.md    # 開發規劃文件
└── src/
    ├── config.py             # 設定檔讀取
    ├── audio/
    │   └── capture.py       # 音訊擷取模組（跨平台）
    ├── vad/
    │   └── detector.py      # VAD 語音活動偵測
    ├── asr/
    │   └── transcriber.py   # ASR 語音辨識
    └── output/
        └── writer.py        # 逐字稿輸出
```

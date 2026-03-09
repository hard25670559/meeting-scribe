# Meeting Scribe - 開發規格書

## 專案概述

Meeting Scribe 是一個跨平台的系統音訊擷取與語音轉逐字稿工具。同時擷取電腦的音訊輸出與麥克風輸入，透過 ASR（自動語音辨識）模型即時轉換為逐字稿，供後續會議整理使用。

## 目標

- 同時擷取系統音訊輸出與麥克風輸入，即時轉換為帶時間戳的逐字稿
- 支援 Windows、Linux、macOS 三大平台
- 輸出的逐字稿可供 LLM 進行會議摘要整理

---

## 技術架構

### 架構流程

```
主執行緒：系統音訊 + 麥克風 → 音訊擷取層 → 多聲道混合為單聲道 → VAD 語音切段 ─→ Queue
ASR 執行緒：Queue → Faster Whisper ASR → OpenCC 簡轉繁 → 逐字稿輸出
```

> 錄音與 VAD 在主執行緒持續運行，ASR 辨識在獨立執行緒中處理，透過 Queue 傳遞語音片段，確保辨識期間錄音不中斷。

### 技術選型

| 元件 | 技術 | 說明 |
|------|------|------|
| 語言 | Python 3.12–3.13 | Windows 需 3.12（CUDA wheel 限制）；Mac/Linux 可用 3.13 |
| 音訊擷取（Windows）| pyaudiowpatch | WASAPI Loopback，原生支援系統音訊擷取 |
| 音訊擷取（macOS/Linux）| soundcard | 跨平台音訊擷取套件 |
| 取樣率轉換（Windows）| scipy.signal.resample_poly | 裝置原生取樣率（如 44100Hz）→ 16kHz |
| VAD | Silero VAD | 語音活動偵測，切分語音段落 |
| ASR | Faster Whisper | Whisper 加速版，支援多語言 |
| 模型 | large-v3 (預設) | 中文辨識準確度最高，可設定切換 |
| GPU 推理 | PyTorch CUDA | Windows NVIDIA GPU 自動偵測並安裝 CUDA 版 torch |

### 跨平台音訊擷取方式

| 平台 | 擷取方式 | 額外安裝 |
|------|---------|---------|
| Windows | pyaudiowpatch WASAPI Loopback + scipy resample | pyaudiowpatch、scipy（已在 requirements.txt 加入 Windows marker）|
| Linux | PulseAudio / PipeWire Monitor（soundcard 原生支援） | 無 |
| macOS | BlackHole 虛擬音訊裝置 + soundcard | 需安裝 BlackHole |

---

## 功能規格

### 核心功能

#### 1. 音訊擷取

- 使用 `soundcard` 套件同時擷取系統音訊輸出與麥克風輸入
- 自動偵測作業系統平台
- 列出可用音訊裝置供使用者選擇
- 記住使用者上次選擇的裝置（存入設定檔）
- macOS 偵測不到 BlackHole 時，顯示安裝引導說明
- 多聲道音訊混合為單聲道（mono）16kHz 供 ASR 使用
- 明確指定讀取裝置所有聲道（soundcard 預設可能只讀 2 聲道，macOS 聚合裝置需讀取全部 4 聲道）

#### 2. VAD 語音切段

- 使用 Silero VAD 偵測語音活動
- 偵測到語音開始時開始錄製片段
- 偵測到語音結束（靜音超過閾值）時結束片段並送辨識
- 可設定靜音閾值時間（`silence_threshold`，預設 1.5 秒）
- 可設定語音判定機率閾值（`speech_threshold`，預設 0.5）；調高可讓靜音更快被判定，切段更激進

#### 3. ASR 語音辨識

- 使用 Faster Whisper 進行語音轉文字
- ASR 辨識在獨立執行緒中運行，透過 Queue 接收 VAD 切好的語音片段的 WAV 檔案路徑（非音訊資料本身），從硬碟讀取音訊進行辨識，減少記憶體佔用
- VAD 切出的片段在送入 ASR 前檢查最大音量，音量過低的片段直接丟棄，避免 Whisper 靜音幻覺（hallucination）
- 預設使用 `large-v3` 模型，可透過設定切換
- 支援指定辨識語言（預設中文 `zh`）
- 支援自動語言偵測模式
- 辨識結果自動轉換為繁體中文（使用 OpenCC `s2twp` 模式，含台灣慣用詞轉換），可透過設定開關

#### 4. 逐字稿與音訊輸出

- 每次錄製建立專屬資料夾：`transcripts/transcript_YYYYMMDD_HHMMSS/`
- 即時輸出辨識結果至終端機
- 帶時間戳格式：`[HH:MM:SS.mmm - HH:MM:SS.mmm] 辨識文字`（含毫秒，避免同秒內片段無法區分）
- 逐行即時寫入檔案（每筆辨識結果立即 append 至檔案），避免程式意外崩潰時遺失已辨識的內容
- 檔案命名格式：`transcript_YYYYMMDD_HHMMSS.txt`
- VAD 切出的每個語音片段同時存為 WAV 檔（`MMmSS.mmms-MMmSS.mmms.wav`），含毫秒避免同秒內檔名衝突，供除錯與回聽
- 輸出目錄可設定（預設為當前目錄下的 `transcripts/`）

### 使用者介面

- CLI（命令列介面）
- 啟動後顯示可用音訊裝置列表
- 使用者選擇裝置後開始錄音與辨識
- `Ctrl+C` 立即停止錄音與所有處理，儲存已完成的逐字稿並結束（不等待未完成的 ASR 辨識）
- 使用 `os._exit()` 強制終止程序，避免 soundcard 等 C 擴充的阻塞呼叫導致 `sys.exit()` 無法生效
- 錄音期間即時顯示 debug 資訊：各聲道音量與 ASR Queue 待處理數量，格式：`[DEBUG] ch0:0.0000 | ch1:0.0000 | ... | Queue: N`

---

## 設定檔

使用 YAML 格式的設定檔 `config.yaml`：

```yaml
# 音訊設定
audio:
  device: null          # 音訊裝置名稱，null 時啟動會詢問
  sample_rate: 16000    # 取樣率

# VAD 設定
vad:
  silence_threshold: 1.5  # 靜音多久視為一段結束（秒）；越小切越碎，建議 0.5~2.0
  speech_threshold: 0.5   # speech_prob 超過此值才算有人說話（0.0~1.0）；越大切越激進，建議 0.5~0.7

# ASR 設定
asr:
  model: large-v3        # Whisper 模型大小
  language: zh            # 辨識語言，null 為自動偵測
  device: auto            # 推理裝置：auto / cpu / cuda
  convert_traditional: true  # 簡體轉繁體中文（s2twp 台灣慣用詞）

# 輸出設定
output:
  directory: ./transcripts  # 逐字稿輸出目錄
  format: txt               # 輸出格式
```

---

## 專案結構

```
meeting-scribe/
├── main.py                  # 程式進入點
├── config.yaml              # 預設設定檔
├── requirements.txt         # Python 依賴
├── docs/
│   ├── SPEC.md              # 開發規格書
│   └── implementation.md    # 開發規劃文件
└── src/
    ├── __init__.py
    ├── config.py             # 設定檔讀取
    ├── audio/
    │   ├── __init__.py
    │   └── capture.py       # 音訊擷取模組（跨平台）
    ├── vad/
    │   ├── __init__.py
    │   └── detector.py      # VAD 語音活動偵測
    ├── asr/
    │   ├── __init__.py
    │   └── transcriber.py   # ASR 語音辨識
    └── output/
        ├── __init__.py
        └── writer.py        # 逐字稿輸出
transcripts/                     # 輸出目錄（自動建立）
└── transcript_YYYYMMDD_HHMMSS/  # 每次錄製的專屬資料夾
    ├── transcript_YYYYMMDD_HHMMSS.txt  # 逐字稿
    ├── 00m05.123s-00m08.456s.wav  # VAD 語音片段（含毫秒）
    └── ...
```

---

## 依賴套件

```
faster-whisper>=1.0.0
soundcard>=0.4.0
silero-vad>=5.0
numpy>=1.24.0
pyyaml>=6.0
opencc-python-reimplemented>=0.1.7
pyaudiowpatch>=0.2.12; sys_platform == "win32"
scipy>=1.10.0; sys_platform == "win32"
```

> `torch` 不列入 requirements.txt，由 `main.py` 的 `_ensure_cuda_torch()` 在 runtime 自動判斷並安裝適合版本（CPU 版與 CUDA 版來自不同 index，無法用同一行安裝）。

---

## 平台前置需求

### Windows
- Python **3.12**（3.13+ 與 PyTorch CUDA wheel 不相容）
- 安裝套件後第一次執行，程式會自動偵測 NVIDIA GPU 並安裝 CUDA 版 torch
- 詳細說明參考 [docs/windows-cuda-setup.md](windows-cuda-setup.md)

### Linux
- Python 3.10+
- PulseAudio 或 PipeWire（大多數發行版已預裝）

### macOS
- Python 3.12 或 3.13（3.14+ 尚未有 torch wheel，3.13 已驗證可用）
- 安裝 BlackHole：`brew install blackhole-2ch`
- 多重輸出裝置設定（讓你聽到聲音 + BlackHole 擷取）：
  1. 開啟「音訊 MIDI 設定」（Applications → Utilities → Audio MIDI Setup）
  2. 左下角 `+` → 建立「多重輸出裝置」
  3. 勾選耳機/喇叭 + BlackHole 2ch
  4. 主要裝置選 BlackHole 2ch
  5. 系統設定 → 聲音 → 輸出 → 選擇多重輸出裝置
- 聚合裝置設定（同時擷取麥克風 + 系統音訊）：
  1. 左下角 `+` → 建立「聚合裝置」
  2. 只勾選：麥克風（如 Yeti Nano）+ BlackHole 2ch
  3. 時脈來源選麥克風裝置
  4. 程式擷取時選擇此聚合裝置

---

## 執行方式

```bash
# 建立 venv（需指定 Python 3.12）
uv venv --python 3.12

# 安裝依賴（Windows 會自動安裝 pyaudiowpatch 和 scipy）
uv pip install -r requirements.txt

# 啟動
# Windows：第一次執行會自動安裝 CUDA torch，完成後需重新執行一次
uv run python main.py
```

---

## 未來擴充方向（不在本次開發範圍）

- 整合 LLM 自動產出會議摘要
- 支援即時字幕顯示（GUI / Web）
- 支援多講者辨識（Speaker Diarization）
- 支援 SRT / VTT 字幕格式輸出
- Docker 容器化部署

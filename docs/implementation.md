# Meeting Scribe 開發規劃文件

> 最後更新：2026-03-10
> 狀態：開發中

## 概述

依據 SPEC.md 規格書，開發一個跨平台的系統音訊擷取與語音轉逐字稿工具。程式擷取電腦音訊輸出與麥克風輸入，透過 VAD 切段後送入 Faster Whisper 進行即時語音辨識，輸出繁體中文逐字稿。

### 架構流程

```
主執行緒：系統音訊 + 麥克風 → 音訊擷取層 → 多聲道混合為單聲道 → VAD 語音切段 ─→ Queue
ASR 執行緒：Queue → Faster Whisper ASR → OpenCC 簡轉繁 → 逐字稿輸出
```

> 錄音與 VAD 在主執行緒持續運行，ASR 辨識在獨立執行緒中處理，透過 Queue 傳遞語音片段，確保辨識期間錄音不中斷。

---

## 模組 1：設定檔讀取 (`src/config.py`)

### 需求描述
- 讀取 `config.yaml` 設定檔，提供全域設定存取
- 支援 CLI 參數覆蓋設定檔的值

### 技術規格

```yaml
audio:
  device: null            # 音訊裝置名稱，null 時啟動會詢問
  sample_rate: 16000      # 取樣率

vad:
  silence_threshold: 1.5  # 靜音多久視為一段結束（秒）；越小切越碎，建議 0.5~2.0
  speech_threshold: 0.5   # speech_prob 超過此值才算有人說話（0.0~1.0）；越大切越激進，建議 0.5~0.7

asr:
  model: large-v3         # Whisper 模型大小
  language: zh            # 辨識語言，null 為自動偵測
  device: auto            # 推理裝置：auto / cpu / cuda
  convert_traditional: true  # 簡體轉繁體中文（s2twp 台灣慣用詞）

output:
  directory: ./transcripts  # 逐字稿輸出目錄
  format: txt               # 輸出格式
```

### 實作細節
- [ ] 使用 `pyyaml` 讀取 `config.yaml`
- [ ] 定義預設值，設定檔不存在時使用預設值
- [ ] 支援 CLI 參數覆蓋（`--language`, `--model`, `--output`）
- [ ] 記住使用者上次選擇的音訊裝置（回寫設定檔）

---

## 模組 2：音訊擷取 (`src/audio/capture.py`)

### 需求描述
- 使用 `soundcard` 套件擷取音訊輸入
- 支援跨平台（Windows / Linux / macOS）
- 支援同時擷取系統音訊與麥克風（透過聚合裝置或程式層面合併）
- 多聲道音訊混合為單聲道（mono）16kHz 供 ASR 使用

### 跨平台擷取方式

| 平台 | 系統音訊 | 麥克風 | 合併方式 |
|------|---------|--------|---------|
| Windows | WASAPI Loopback | 麥克風裝置 | 程式層面同時擷取兩個輸入 |
| Linux | PulseAudio / PipeWire Monitor | 麥克風裝置 | module-loopback 或程式層面合併 |
| macOS | BlackHole 2ch | 麥克風裝置 | 聚合裝置（系統層面合併） |

### 實作細節
- [ ] 自動偵測作業系統平台
- [ ] 列出可用音訊裝置供使用者選擇
- [ ] 記住使用者上次選擇的裝置（存入設定檔）
- [ ] macOS 偵測不到 BlackHole 時，顯示安裝引導說明
- [ ] 明確指定讀取裝置所有聲道（soundcard 預設只讀 2 聲道，macOS 聚合裝置需讀全部 4 聲道）
- [ ] 擷取音訊後混合所有聲道為單聲道（mono）
- [ ] 取樣率轉換至 16kHz（Whisper 要求）
- [ ] 以串流方式持續產出音訊區塊（chunk）供 VAD 處理

### 注意事項
- macOS 聚合裝置的聲道順序：麥克風在聲道 1-2，BlackHole 在聲道 3-4，程式需讀取所有聲道並混合
- 單聲道麥克風（如 Yeti Nano）只有左聲道有資料，混合時需正確處理
- Windows WASAPI Loopback 為系統音訊，麥克風需另開輸入串流

---

## 模組 3：VAD 語音切段 (`src/vad/detector.py`)

### 需求描述
- 使用 Silero VAD 偵測語音活動
- 將連續音訊串流切分為語音片段，送入 ASR 辨識

### 技術規格
- VAD 模型：Silero VAD
- 靜音閾值：可設定（預設 1.5 秒）
- 輸入格式：單聲道 16kHz PCM

### 實作細節
- [ ] 載入 Silero VAD 模型
- [ ] 持續接收音訊區塊，偵測語音活動
- [ ] 偵測到語音開始時，開始累積音訊片段
- [ ] 偵測到靜音超過閾值時，結束片段並送出辨識
- [ ] 記錄每個片段的開始與結束時間戳

### 注意事項
- VAD 在主執行緒中持續運行，確保錄音不中斷
- 切好的語音片段透過 Queue 傳遞給 ASR 執行緒
- 片段過長時考慮強制切段（避免記憶體過度使用）

---

## 模組 4：ASR 語音辨識 (`src/asr/transcriber.py`)

### 需求描述
- 使用 Faster Whisper 將語音片段轉為文字
- 辨識結果自動轉換為繁體中文

### 技術規格
- ASR 引擎：Faster Whisper
- 預設模型：`large-v3`
- 預設語言：`zh`（中文）
- 推理裝置：auto（自動選擇 GPU / CPU）
- 繁體轉換：OpenCC `s2twp` 模式（簡體 → 台灣繁體，含慣用詞轉換）

### 實作細節
- [ ] 初始化 Faster Whisper 模型（依設定選擇模型大小與裝置）
- [ ] 在獨立執行緒中運行，透過 Queue 接收 WAV 檔案路徑（非音訊資料本身），從硬碟讀取音訊進行辨識
- [ ] 辨識結果使用 OpenCC `s2twp` 轉換為繁體中文
- [ ] `convert_traditional: false` 時跳過轉換
- [ ] 辨識完成後呼叫 writer 輸出結果

### 注意事項
- ASR 在獨立執行緒中運行，避免辨識時阻塞主執行緒的錄音與 VAD
- large-v3 模型約需 3GB+ 記憶體，首次執行會自動下載
- 中英文混合場景：`language: zh` 時大部分英文術語能正確保留
- 若需自動語言偵測，設定 `language: null`

---

## 模組 5：逐字稿輸出 (`src/output/writer.py`)

### 需求描述
- 即時輸出辨識結果至終端機
- 逐行即時寫入逐字稿檔案
- VAD 切出的語音片段存為 WAV 檔，供除錯與回聽

### 技術規格
- 即時輸出格式：`[HH:MM:SS.mmm - HH:MM:SS.mmm] 辨識文字`（含毫秒）
- 每次錄製建立專屬資料夾：`transcripts/transcript_YYYYMMDD_HHMMSS/`
- 逐字稿檔名：`transcript_YYYYMMDD_HHMMSS.txt`
- 語音片段檔名：`MMmSS.mmms-MMmSS.mmms.wav`（起始時間-結束時間，含毫秒避免同秒內檔名衝突）
- 輸出目錄：可設定（預設 `./transcripts/`）

### 輸出目錄結構
```
transcripts/
└── transcript_20260308_143000/
    ├── transcript_20260308_143000.txt
    ├── 00m05.123s-00m08.456s.wav
    ├── 00m12.789s-00m15.012s.wav
    └── ...
```

### 實作細節
- [ ] 每次錄製以時間戳建立專屬資料夾（`session_dir`）
- [ ] 接收辨識結果，即時印出至終端機（含時間戳）
- [ ] 每筆辨識結果立即逐行 append 寫入檔案（不累積至記憶體最後才寫），避免程式意外崩潰時遺失已辨識內容
- [ ] 程式啟動時建立輸出檔案，每次 `add_entry` 時以 append 模式寫入
- [ ] VAD 切出的每個語音片段存為 WAV 檔至 `session_dir`
- [ ] 程式結束時（Ctrl+C）印出儲存摘要（段數、時長）
- [ ] 自動建立輸出目錄（若不存在）
- [ ] 檔案以 UTF-8 編碼儲存

---

## 模組 6：主程式進入點 (`main.py`)

### 需求描述
- CLI 介面，串接所有模組
- 支援 CLI 參數

### 實作細節
- [ ] 解析 CLI 參數（`--language`, `--model`, `--output`）
- [ ] 讀取設定檔，CLI 參數覆蓋設定值
- [ ] 列出可用音訊裝置，使用者選擇後開始錄音
- [ ] 建立 `queue.Queue` 作為 VAD → ASR 的傳遞通道
- [ ] 啟動 ASR worker 執行緒（`threading.Thread`），持續從 Queue 取出 WAV 檔案路徑進行辨識
- [ ] 主執行緒執行音訊擷取 → VAD 迴圈，VAD 切好的片段先存為 WAV 檔，再將檔案路徑與時間戳放入 Queue
- [ ] 送入 Queue 前檢查片段最大音量，音量過低（≤ 0.01）直接丟棄，避免 Whisper 靜音幻覺（仍存 WAV 但不放入 Queue）
- [ ] 主迴圈每次取得音訊區塊後，在 capture 的聲道 debug 行後方附加顯示 ASR Queue 待處理數量（`asr_queue.qsize()`）
- [ ] 捕捉 `Ctrl+C`（SIGINT），立即停止錄音，儲存已完成的逐字稿後結束（不等待未完成的 ASR 辨識）
- [ ] 顯示啟動資訊（模型大小、語言、裝置等）

### 多執行緒架構

```
主執行緒                          ASR 執行緒
┌─────────────────────┐          ┌─────────────────────┐
│ 音訊擷取（串流）     │          │ 從 Queue 取出片段    │
│       ↓             │          │       ↓             │
│ VAD 語音切段         │  Queue   │ Faster Whisper 辨識  │
│       ↓             │ ──────→  │       ↓             │
│ 片段放入 Queue       │          │ OpenCC 簡轉繁        │
│                     │          │       ↓             │
│ （持續錄音不中斷）    │          │ 逐字稿輸出           │
└─────────────────────┘          └─────────────────────┘
```

### 注意事項
- 主執行緒負責錄音與 VAD，確保 ASR 辨識期間錄音持續進行
- ASR 執行緒設為 daemon thread，主程式結束時自動終止
- `Ctrl+C` 時立即結束，不等待 Queue 中未處理的片段，直接儲存已完成的逐字稿
- 使用 `os._exit()` 強制終止，因為 `sys.exit()` 在 soundcard 阻塞呼叫期間無法生效

---

## 跨平台音訊前置設定

### macOS

#### 必要軟體
- BlackHole 2ch：`brew install blackhole-2ch`
- 安裝後需重新開機讓驅動生效

#### 多重輸出裝置（讓你聽到聲音 + BlackHole 擷取）
1. 開啟「音訊 MIDI 設定」
2. 左下角 `+` → 建立多重輸出裝置
3. 勾選：耳機/喇叭 + BlackHole 2ch
4. 主要裝置選 BlackHole 2ch
5. 系統設定 → 聲音 → 輸出 → 選擇多重輸出裝置

#### 聚合裝置（同時擷取麥克風 + 系統音訊）
1. 左下角 `+` → 建立聚合裝置
2. 只勾選：麥克風（如 Yeti Nano）+ BlackHole 2ch
3. 時脈來源選麥克風裝置
4. 程式擷取時選擇此聚合裝置

#### 聲道對應
- 聲道 1-2：麥克風（排在前面的裝置）
- 聲道 3-4：BlackHole（系統音訊）
- 程式將所有聲道混合為單聲道

### Windows
- 無額外安裝需求
- WASAPI Loopback 原生支援系統音訊擷取
- 麥克風需程式層面另開輸入串流合併

### Linux
- PulseAudio 或 PipeWire（大多數發行版已預裝）
- 可用 `pactl load-module module-loopback` 合併麥克風
- 或程式層面同時擷取兩個音源

---

## 依賴套件

```
faster-whisper>=1.0.0
soundcard>=0.4.0
silero-vad>=5.0
numpy>=1.24.0
pyyaml>=6.0
opencc-python-reimplemented>=0.1.7
```

---

## 待確認事項

- [ ] Windows / Linux 平台同時擷取麥克風 + 系統音訊的具體實作方式（程式層面雙串流合併 vs 系統層面合併）
- [ ] VAD 片段過長時的強制切段閾值（建議 30 秒）
- [ ] Apple Silicon MPS 支援（目前 Mac 使用 CPU int8，可考慮加入 `torch.backends.mps.is_available()` 偵測）

---

## 討論記錄

| 日期 | 討論內容 | 結論 |
|------|----------|------|
| 03-08 | 中英文混合辨識 | `language: zh` 時大部分英文術語能保留，維持預設即可 |
| 03-08 | 辨識結果繁體中文 | 使用 OpenCC `s2twp` 後處理，新增 `convert_traditional` 設定 |
| 03-08 | macOS 同時錄麥克風 + 系統音訊 | 使用聚合裝置合併，程式擷取聚合裝置即可 |
| 03-08 | 聚合裝置聲道順序 | 麥克風排前面（聲道 1-2），BlackHole 排後面（聲道 3-4），程式混合所有聲道 |
| 03-08 | 單聲道麥克風問題 | Yeti Nano 等單聲道麥克風只有左聲道有資料，混合為 mono 時不影響 |
| 03-08 | ASR 阻塞錄音問題 | 採用多執行緒架構，主執行緒負責錄音+VAD，ASR 在獨立執行緒透過 Queue 處理 |
| 03-08 | Ctrl+C 結束行為 | 立即停止所有處理，儲存已完成的逐字稿，不等待未完成的 ASR 辨識 |
| 03-08 | soundcard 聲道數問題 | soundcard 預設只讀 2 聲道，macOS 聚合裝置需明確指定讀取全部聲道（4ch） |
| 03-08 | Whisper 靜音幻覺 | VAD 切出的片段送入 ASR 前檢查音量，音量過低直接丟棄 |
| 03-08 | 逐字稿寫入方式 | 改為逐行即時 append 寫入檔案，避免崩潰時遺失已辨識內容 |
| 03-08 | 輸出目錄結構 | 每次錄製建立專屬資料夾，逐字稿與 WAV 語音片段放在同一資料夾 |
| 03-08 | Queue 待處理數量 debug | 主迴圈在聲道 debug 行後方附加顯示 `Queue: N`，方便觀察 ASR 處理速度 |
| 03-08 | Queue 記憶體佔用優化 | Queue 改為只存 WAV 檔案路徑而非音訊陣列，ASR 從硬碟讀取，因現已存 WAV 故改動小且硬碟讀取時間相對 ASR 推理可忽略 |
| 03-08 | 時間戳精度 | 時間戳與 WAV 檔名加入毫秒，避免同秒內片段無法區分或檔名衝突 |
| 03-10 | Windows 音訊擷取 | soundcard WASAPI Loopback 在部分裝置上取樣率轉換品質差，改用 pyaudiowpatch + scipy.signal.resample_poly |
| 03-10 | Windows 聲道數問題 | soundcard 強制讀取 4 聲道導致 2 聲道裝置（EDIFIER）音訊失真，改用 pyaudiowpatch 直接讀取裝置原生聲道數 |
| 03-10 | Ctrl+C 無法中斷 | pyaudio 大塊讀取（chunk）時阻塞 signal handler，改為 512 frames 小塊讀取讓 Ctrl+C 能即時響應 |
| 03-10 | GPU 未被使用 | PyPI 預設安裝 CPU 版 torch，需從 PyTorch CUDA index 重裝 |
| 03-10 | Python 3.14 不相容 | PyTorch CUDA wheel 只到 cp313，改用 Python 3.12 建立 venv |
| 03-10 | torchaudio DLL 失敗 | Windows 上 torchaudio CUDA DLL 載入失敗（WinError 127），在 detector.py 用 sys.modules 注入空殼模組繞過 |
| 03-10 | 無限安裝迴圈 | _ensure_cuda_torch() 同時安裝 torchaudio 時，uv 因相依性把 torch 降版為 CPU，移除 torchaudio 安裝後解決 |
| 03-10 | requirements.txt 補齊 | 新增 pyaudiowpatch 和 scipy，加上 `sys_platform == "win32"` marker 避免影響 Mac/Linux |
| 03-10 | VAD speech_threshold 可設定 | Mac 音訊乾淨導致切段比 Windows 更激進，新增 `speech_threshold` 參數讓使用者自行調整語音判定敏感度 |

---

## 變更記錄

| 日期 | 變更內容 |
|------|----------|
| 03-08 | 初始版本，依據 SPEC.md 建立開發規劃 |
| 03-08 | 新增 OpenCC 繁體中文轉換需求 |
| 03-08 | 新增 macOS 聚合裝置設定（同時擷取麥克風 + 系統音訊） |
| 03-08 | 新增跨平台音訊前置設定說明 |
| 03-08 | 新增多執行緒架構（主執行緒錄音+VAD，ASR 獨立執行緒透過 Queue） |
| 03-08 | Ctrl+C 改為立即結束，不等待 ASR 處理完畢 |
| 03-08 | 修正 soundcard 預設只讀 2 聲道，改為明確指定讀取裝置全部聲道 |
| 03-08 | 新增送入 ASR 前的音量過濾，避免 Whisper 靜音幻覺 |
| 03-08 | 逐字稿輸出改為逐行即時 append 寫入檔案 |
| 03-08 | 每次錄製建立專屬資料夾，VAD 語音片段存為 WAV 檔供除錯回聽 |
| 03-08 | 新增 ASR Queue 待處理數量 debug 輸出 |
| 03-08 | Queue 改為傳遞 WAV 檔案路徑，ASR 從硬碟讀取音訊，減少記憶體佔用 |
| 03-08 | 時間戳與 WAV 檔名加入毫秒精度，避免同秒內片段衝突 |
| 03-10 | Windows 音訊擷取改用 pyaudiowpatch，修正取樣率轉換與聲道數問題 |
| 03-10 | Ctrl+C 改為 512 frames 小塊讀取，修正 signal handler 無法即時觸發的問題 |
| 03-10 | 新增 _ensure_cuda_torch()，程式啟動時自動偵測 NVIDIA GPU 並安裝 CUDA torch |
| 03-10 | detector.py 新增 torchaudio 空殼 mock，繞過 Windows DLL 載入失敗問題 |
| 03-10 | requirements.txt 新增 pyaudiowpatch 和 scipy（Windows only platform marker）|
| 03-10 | 新增 docs/windows-cuda-setup.md，記錄 Windows CUDA 環境問題排查過程 |
| 03-10 | SPEC.md 更新技術選型、平台需求、依賴套件說明 |
| 03-10 | 新增 VAD `speech_threshold` 可設定參數，更新 config.yaml、config.yaml.example、src/config.py、src/vad/detector.py、main.py、SPEC.md |

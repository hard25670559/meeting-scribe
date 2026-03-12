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
| ASR（跨平台）| Faster Whisper | CTranslate2 引擎，支援 CPU / CUDA，跨平台 |
| ASR（Apple Silicon）| mlx-whisper | Apple MLX 框架，Apple Silicon GPU 加速，需 ffmpeg |
| 模型 | large-v3 / large-v3-turbo（可設定）| large-v3 準確度最高；turbo 約快 8x，準確度接近 |
| GPU 推理（Windows）| PyTorch CUDA | NVIDIA GPU 自動偵測並安裝 CUDA 版 torch |
| GPU 推理（Apple Silicon）| Apple MLX | mlx-whisper backend 自動使用 Apple Silicon GPU |

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

- 支援兩種推理後端（`backend`），可透過設定切換：
  - `faster-whisper`：跨平台，Windows 支援 CUDA GPU 加速，Mac 使用 CPU
  - `mlx-whisper`：僅 Apple Silicon Mac，使用 Apple MLX 框架進行 GPU 加速，需安裝 ffmpeg；啟動時自動偵測 ffmpeg，未安裝時提示安裝指令
- ASR 辨識在獨立執行緒中運行，透過 Queue 接收 VAD 切好的語音片段的 WAV 檔案路徑（非音訊資料本身），從硬碟讀取音訊進行辨識，減少記憶體佔用
- VAD 切出的片段在送入 ASR 前檢查最大音量，音量過低的片段直接丟棄，避免 Whisper 靜音幻覺（hallucination）
- 預設使用 `large-v3` 模型，可透過設定切換；推薦 `large-v3-turbo`（速度約快 8 倍，準確度接近）
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

### 記憶體管理與優化

為避免長時間運行時的記憶體洩漏，程式採用以下最佳實踐：

#### VAD 模組
- 語音片段緩衝區在輸出後明確釋放（`del self._speech_buffer`）
- Silero VAD 模型狀態在需要時正確重置

#### ASR 模組
- 轉錄完成後明確釋放 Whisper 的 segments 物件（`del segments, info`）
- 避免模型推理過程中的快取堆積

#### 音訊擷取模組（Windows 特有）
- 使用 `.copy()` 製作 numpy array 複本而非 `frombuffer()` 視圖，避免引用計數問題
- 音訊緩衝區在使用後明確釋放（`del buf`）

#### 主程式
- 定期進行垃圾回收（每 10 個語音片段執行 `gc.collect()`）
- 主執行緒中每個音訊區塊處理後立即釋放（`del audio_chunk` 等）
- 音量過低的語音片段刪除，節省磁碟空間和虛擬記憶體佔用
- ASR 執行緒每處理 5 個片段進行一次垃圾回收

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
  backend: faster-whisper  # 推理後端：faster-whisper | mlx-whisper
                           # faster-whisper：跨平台，Windows CUDA 加速，Mac 用 CPU
                           # mlx-whisper：僅 Apple Silicon Mac，GPU 加速，需安裝 ffmpeg
  model: large-v3          # Whisper 模型大小：large-v3 / large-v3-turbo / medium / small / base / tiny
  language: zh             # 辨識語言，null 為自動偵測
  device: auto             # 推理裝置（faster-whisper 用）：auto / cpu / cuda
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
mlx-whisper>=0.4.0; sys_platform == "darwin"
```

> `mlx-whisper` 僅在 macOS 上安裝（`sys_platform == "darwin"`），Windows / Linux 不受影響。使用 `mlx-whisper` backend 還需額外安裝 ffmpeg：`brew install ffmpeg`

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
- 使用 `mlx-whisper` backend 時需額外安裝 ffmpeg：`brew install ffmpeg`（Apple Silicon 推薦）
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

## 分散式 ASR 架構

### 架構概述

系統由兩個獨立、裝置無關的服務組成，可自由部署在任意機器上：

| 服務 | 職責 |
|------|------|
| **Capture Service** | 音訊擷取、VAD 切段、產生 WAV、呼叫 Dispatcher 調度任務、收集結果寫入逐字稿 |
| **ASR Worker Service** | 接收 WAV、Whisper 語音辨識、回傳文字結果、回報壓力評分 |

每台機器可自由選擇運行哪些服務：

| 部署情境 | Capture | ASR Worker |
|---------|:---:|:---:|
| 單機全包 | O | O |
| 只做擷取，辨識交給其他機器 | O | X |
| 只做辨識 | X | O |
| 一台擷取 + 多台辨識 | 1 | N |

```
┌─ 機器 A ──────────────────────┐      ┌─ 機器 B ──────────────┐
│                               │      │                       │
│  Capture Service              │      │                       │
│  ├─ 音訊擷取 + VAD            │      │                       │
│  ├─ 產生 WAV                  │      │                       │
│  └─ Dispatcher（調度器）       │      │                       │
│       ├─ 查詢壓力評分          │      │                       │
│       ├─ 分配任務              │ ───→ │  ASR Worker Service   │
│       └─ 收集結果 → 逐字稿     │      │  ├─ 接收 WAV          │
│              │                │      │  ├─ Whisper 辨識       │
│              ↓                │      │  └─ 回傳文字結果       │
│  ASR Worker Service（本機）    │      │                       │
│  ├─ 接收 WAV                  │      └───────────────────────┘
│  ├─ Whisper 辨識              │
│  └─ 回傳文字結果              │      ┌─ 機器 C ──────────────┐
│                               │      │  ASR Worker Service   │
│                               │ ───→ │  （更多 Worker...）    │
└───────────────────────────────┘      └───────────────────────┘
```

### 啟動方式

參數優先級：**CLI 參數 > 環境變數 > 預設值**

```bash
# 同時運行 Capture + ASR Worker（單機全包）
python main.py --capture --asr-worker

# 只運行 Capture + Dispatcher（辨識交給其他機器）
python main.py --capture

# 只運行 ASR Worker 服務
python main.py --asr-worker --port 8001

# 指定推理裝置
python main.py --asr-worker --device cuda --port 8001

# 同一台機器運行多個 Worker（不同 port）
python main.py --asr-worker --port 8001
python main.py --asr-worker --port 8002
```

### 服務發現

Capture Service 的 config 中列舉 ASR Worker 的位址：

```yaml
dispatcher:
  workers:
    - http://localhost:8001
    - http://localhost:8002
    - http://192.168.1.50:8001
    - http://192.168.1.50:8002
```

啟動流程：
1. Capture 啟動時，對 config 中每個 Worker 發送健康檢查（`GET /health`）
2. Worker 回報自身狀態（模型是否載入、硬體資源等）
3. 通過檢查的 Worker 加入可用清單
4. 未通過的 Worker 回報錯誤訊息給使用者
5. 運行期間持續檢查 Worker 狀態

### 通訊協定

使用 HTTP REST（FastAPI），ASR Worker 對外暴露以下 API：

| Method | Endpoint | 說明 |
|--------|----------|------|
| `POST` | `/transcribe` | 上傳 WAV 檔案，回傳 `{ task_id, estimated_time }` |
| `GET` | `/task/{task_id}` | 查詢任務狀態與結果 |
| `DELETE` | `/task/{task_id}` | 取消任務 |
| `GET` | `/status` | 回傳壓力評分（基礎分 + 不健康懲罰） |
| `GET` | `/health` | Worker 自身健康檢查（模型、硬體） |
| `PUT` | `/health` | Dispatcher 標記 Worker 健康狀態 |

### Dispatcher 調度機制

Dispatcher 由 Capture Service 呼叫，負責非同步管理多個任務的分配與結果收集。

#### 任務分配流程

```
Capture 產生 WAV
  ↓
Dispatcher 查詢所有可用 Worker 的壓力評分（GET /status）
  ↓
選擇評分最低（最閒）的 Worker
  ↓
發送任務（POST /transcribe）→ Worker 回傳 { task_id, estimated_time }
  ↓
Dispatcher 不等待，繼續處理下一個 WAV（非同步）
  ↓
等到 estimated_time 後去拿結果（GET /task/{task_id}）
  ├─ 完成 → 拿到文字 → 按時間順序插入逐字稿 ✓
  ├─ 處理中 → 先去做別的事，過一段時間再回來拿（循環）
  └─ 停滯/超過閾值 → 進入容錯流程
```

#### 逐字稿順序

多個 Worker 同時處理不同片段，結果回來的順序可能不同。逐字稿寫入時按照音訊片段的時間戳排序插入，確保時間順序正確。

#### Worker 不可用時的處理

- **Worker 還能工作**（即使被標記不健康）：仍然可以分配任務，依壓力評分排序，分數高的排後面
- **Worker 無法訪問**（斷線、錯誤中斷）：不再分配任務
- **所有 Worker 壓力都很高**：任務仍然分配，選壓力最低的，只是處理速度較慢
- **重複結果處理**：若任務已被轉派並從其他 Worker 拿到結果，原 Worker 後續恢復後繼續工作即可，不影響整體流程

### 壓力評分系統

壓力評分由 Worker 內部計算，Dispatcher 主動詢問（`GET /status`）取得。

#### 評分公式

```
總壓力分數 = 基礎分數 + 不健康懲罰分數
```

#### 基礎分數（0~100）

```python
base = (
    normalize(pending_tasks) × w1 +
    normalize(avg_processing_time) × w2 +
    gpu_usage × w3 +
    cpu_usage × w4 +
    memory_usage × w5
)
```

- `pending_tasks`：排隊中 + 處理中的任務總數
- `avg_processing_time`：近 N 筆任務的平均處理時間
- `gpu_usage`：GPU 使用率（%）
- `cpu_usage`：CPU 使用率（%）
- `memory_usage`：記憶體使用率（%）

#### 指標正規化

各指標使用**歷史數據百分比**正規化至 0~100：

- Worker 累積自身歷史數據，用歷史最大值當作 100%
- 歷史最大值使用 **EMA（指數移動平均）** 平滑更新，避免極端值造成瞬間跳變：

```python
smoothed_max = smoothed_max + (new_value - smoothed_max) × smoothing_factor
```

- `smoothing_factor` 小（如 0.1）→ 平滑，極端值影響小
- `smoothing_factor` 大（如 0.5）→ 敏感，反應快

#### 權重組合

Worker 根據自身推理裝置類型（GPU/CPU）選擇對應的權重組合：

**GPU Worker 權重：**

| 指標 | 權重 | 說明 |
|------|------|------|
| pending_tasks | 0.35 | 最直接反映忙碌程度 |
| avg_processing_time | 0.25 | 反映處理能力 |
| gpu_usage | 0.25 | GPU Worker 的核心瓶頸 |
| cpu_usage | 0.10 | 相對不重要 |
| memory_usage | 0.05 | 通常不是瓶頸 |

**CPU Worker 權重：**

| 指標 | 權重 | 說明 |
|------|------|------|
| pending_tasks | 0.35 | 最直接反映忙碌程度 |
| avg_processing_time | 0.25 | 反映處理能力 |
| gpu_usage | 0.00 | 無 GPU，不計算 |
| cpu_usage | 0.35 | CPU Worker 的核心瓶頸 |
| memory_usage | 0.05 | 通常不是瓶頸 |

Worker 在啟動時根據模型載入的裝置（`cuda` / `cpu`）自動選擇權重組合。

#### 冷啟動

Worker 剛啟動時尚無歷史數據，但公式仍可運算：
- `pending_tasks = 0`、`avg_processing_time = 0` → 任務指標為 0
- GPU/CPU/Memory 使用率來自即時系統資源 → 有實際數值
- 基礎分自然偏低，Dispatcher 會優先分配任務
- 隨任務累積，歷史數據逐漸建立，分數開始反映真實壓力

### 健康機制

Worker 的健康狀態分為兩個獨立維度：

| | Worker 自身健康 | Dispatcher 標記健康 |
|---|---|---|
| **判斷者** | Worker 自己 | Dispatcher |
| **依據** | 模型是否載入、硬體是否正常、服務是否能運作 | 任務超時、進度停滯、回應異常 |
| **意義** | 「這台機器能不能跑」 | 「你最近表現有問題，先不派任務給你」 |
| **API** | `GET /health`（Worker 自我回報） | `PUT /health`（Dispatcher 外部標記） |

兩者獨立，不互相覆蓋。Worker 自身健康正常但被 Dispatcher 標記不健康的情況是可能的（例如連續任務超時）。

### 不健康懲罰與衰減機制

懲罰機制**僅適用於任務表現問題**（Worker 可連線、能工作，但表現不佳）。

以下情況**不使用懲罰機制**，而是由 Dispatcher 直接處理：
- **Worker 自身不健康**（`GET /health` 回報異常）：不派任務，等 Worker 自行恢復後重新通過健康檢查才加回可用清單
- **Worker 無法連線**（連線超時/無回應）：從可用清單移除，不派任務，Dispatcher 定期嘗試重新連線，連上後重新進行健康檢查

#### 懲罰初始值

依標記原因給予不同的初始懲罰分數（僅限任務表現問題）：

| 標記原因 | 嚴重程度 | 懲罰初始值 |
|---------|---------|-----------|
| 任務超時且進度停滯 | 高 | 80 |
| 任務超時但有進展，超過最大容忍閾值 | 中 | 50 |

初始值由 Dispatcher 端的 config 設定，透過 `PUT /health` 傳送給 Worker。

#### 衰減機制

不健康懲罰在每次 Dispatcher 查詢壓力評分時觸發衰減：

```python
if unhealthy_penalty > 0:
    decay = (100 - base_score) × decay_coefficient
    unhealthy_penalty = max(0, unhealthy_penalty - decay)
```

- 基礎分越低（Worker 越健康）→ 衰減越快 → 恢復越快
- 基礎分越高（Worker 仍在掙扎）→ 衰減越慢 → 持續被排除
- `decay_coefficient` 可透過 config 調整（預設 0.15）

#### 恢復條件

使用**動態健康閾值**，基於每個 Worker 的歷史平均基礎分：

```python
recovery_threshold = historical_avg_base × recovery_ratio

if total_score <= recovery_threshold:
    mark_healthy(worker)
```

- `historical_avg_base`：Worker 歷史平均基礎分數（Dispatcher 持續追蹤更新）
- `recovery_ratio`：略大於 1（如 1.1~1.2），代表「回到你自己的正常水準就好」
- 每個 Worker 的閾值不同，處理速度天生較慢的機器不會被永久歧視

### 容錯機制

容錯是 Dispatcher 的職責。

#### 任務結果收集流程

Dispatcher 以事件迴圈方式非同步管理所有已發出的任務：

```
Dispatcher 主迴圈（持續運行）
  │
  ├─ 有新 WAV 要分配？ → 查詢壓力評分 → 選 Worker → 發送任務
  │
  └─ 遍歷所有已發出的任務，檢查是否該去拿結果：
       ├─ 還沒到 estimated_time → 跳過
       ├─ 到了 estimated_time → GET /task/{task_id}
       │    ├─ 完成 → 收結果，按時間順序插入逐字稿 ✓
       │    ├─ 處理中 → 更新下次檢查時間，繼續迴圈
       │    └─ 超過閾值 → 進入容錯流程
       └─ 上次問過還在處理中，下次檢查時間還沒到 → 跳過
```

每個任務各自有「下次該去問的時間」，到了就問，沒到就跳過，Dispatcher 不會傻等任何一個任務。

#### 超過閾值的判定

當 Dispatcher 去 `GET /task/{task_id}` 時，根據回應結果判定：

```
GET /task/{task_id}
  ├─ 成功取得回應
  │    ├─ 任務完成 → 收結果，按時間順序插入逐字稿 ✓
  │    ├─ 任務處理中，進度有變化 → 更新下次檢查時間，繼續迴圈
  │    ├─ 任務處理中，進度停滯 → 容錯（懲罰）
  │    └─ 累計耗時超過最大容忍時間 → 容錯（懲罰）
  │
  └─ 無法取得回應（連線超時/錯誤）
       → 容錯（移出可用清單，不懲罰）
```

各異常情況的處理差異：

| 異常情況 | 說明 | 後續處理 |
|---------|------|---------|
| **進度停滯** | Worker 可連線，但任務進度沒有變化 | 標記不健康（加懲罰）→ 取消任務 → 轉派 |
| **超過最大容忍時間** | Worker 可連線且有進展，但耗時遠超預估 | 標記不健康（加懲罰）→ 取消任務 → 轉派 |
| **連線超時/錯誤** | Worker 完全連不上或回應異常 | 從可用清單移除 → 直接轉派（取消也送不出去） |

共同行為：**將任務轉派給其他可用的 Worker**。

差異在於：
- 進度停滯 / 超過容忍時間 → 使用**懲罰機制**（Worker 還能工作，只是表現差）
- 連線超時 / 錯誤 → **不使用懲罰**（Worker 無法工作，直接移出可用清單，等恢復）

#### 任務取消

Worker 收到取消請求（`DELETE /task/{task_id}`）時：

| 任務狀態 | 行為 |
|---------|------|
| 排隊中（未開始） | 從 Queue 移除，不執行 |
| 處理中（Whisper 推理中） | 中斷推理，釋放 GPU/CPU 資源 |

取消機制的目的是讓 Worker 盡快騰出資源，去處理下一個任務或恢復健康狀態。

### Worker 內部架構

- 每個 Worker 實例載入一份 Whisper 模型
- 單一模型實例**無法並發處理多個任務**（sequential）
- Worker 內部有 Queue，任務依序消化：一次處理一個，其餘排隊
- 若要在同一台機器上並行處理多個任務，需啟動多個 Worker 實例（不同 port）
- 每個 `large-v3` 實例約需 3GB（VRAM 或 RAM）

```
Worker 實例（單一模型）
├─ Queue：[任務3, 任務4, 任務5]  ← 排隊等待
└─ 目前處理中：任務2              ← 一次只處理一個
```

### 分散式 ASR 設定檔

#### Capture Service 端

```yaml
# Dispatcher 設定
dispatcher:
  workers:
    - http://localhost:8001
    - http://localhost:8002
    - http://192.168.1.50:8001
    - http://192.168.1.50:8002
  scoring:
    decay_coefficient: 0.15       # 不健康懲罰衰減係數
    recovery_ratio: 1.2           # 恢復閾值 = 歷史平均 × 此值
    smoothing_factor: 0.3         # EMA 平滑係數
  penalty:                        # 不健康懲罰初始值（僅限任務表現問題）
    task_timeout_stalled: 80      # 任務超時且進度停滯
    task_timeout_slow: 50         # 任務超時但有進展，超過最大容忍閾值
```

#### ASR Worker 端

```yaml
# ASR Worker 設定
asr_worker:
  port: 8001                      # 服務 port
  device: auto                    # 推理裝置：auto / cpu / cuda
  model: large-v3                 # Whisper 模型
  language: zh                    # 辨識語言
  convert_traditional: true       # 簡繁轉換

  # 壓力評分權重（GPU Worker 預設）
  scoring:
    weights:
      pending_tasks: 0.35
      avg_processing_time: 0.25
      gpu_usage: 0.25
      cpu_usage: 0.10
      memory_usage: 0.05
```

---

### 優雅關閉（Graceful Shutdown）

> **本節為規劃記錄，暫不實作。**

Capture Service 和 ASR Worker 都需要優雅關閉機制，確保中斷時不遺失已處理的資料，並能在重啟後恢復未完成的工作。

需考慮的情境：

**Capture Service 關閉時：**
- 已發出但未收到結果的任務
- 已產生但未分配的 WAV
- 是否通知所有 Worker

**ASR Worker 關閉時：**
- 正在處理中的任務
- Queue 裡排隊的任務
- 是否通知 Dispatcher 下線

兩者的核心概念相同：確保資料不遺失，並提供恢復機制。

---

## 未來擴充方向（不在本次開發範圍）

- 整合 LLM 自動產出會議摘要
- 支援即時字幕顯示（GUI / Web）
- 支援多講者辨識（Speaker Diarization）
- 支援 SRT / VTT 字幕格式輸出
- Docker 容器化部署
- 安全性（API 認證）

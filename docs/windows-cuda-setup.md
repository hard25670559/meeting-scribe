# Windows CUDA / GPU 環境問題排查記錄

> 最後更新：2026-03-10
> 適用環境：Windows 11 + NVIDIA GPU（本機為 RTX 4060）

---

## 背景

專案原本以 CPU 版 torch 開發，在 Windows + NVIDIA GPU 環境執行時發現 GPU 完全沒有被使用，
且過程中遭遇多個 Windows 特有的安裝與相依性問題。本文記錄每個問題的原因與最終解法。

---

## 問題 1：torch 裝的是 CPU 版，GPU 沒被使用

### 原因

PyPI 上的 `torch` 預設是 CPU 版，不包含 CUDA runtime。
要讓 Faster Whisper 使用 NVIDIA GPU 進行推理，必須從 PyTorch 官方的 CUDA wheel index 安裝：

```
https://download.pytorch.org/whl/cu121
```

### 解法

手動安裝 CUDA 版 torch：

```bash
uv pip install torch --index-url https://download.pytorch.org/whl/cu121
```

### 驗證

```python
import torch
print(torch.cuda.is_available())  # True 表示安裝成功
```

---

## 問題 2：Python 3.14 無法安裝 CUDA torch

### 原因

PyTorch 的 wheel 只打包到 `cp313`（Python 3.13），Python 3.14 沒有對應的 wheel 檔案，
安裝時會出現「找不到符合條件的套件」錯誤。

### 解法

改用 Python 3.12 重建 venv：

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
```

> **注意**：Python 版本需求已更新為 3.12，不支援 3.13+（截至 2026-03 PyTorch 尚未支援）

---

## 問題 3：torchaudio DLL 載入失敗（WinError 127）

### 原因

torchaudio CUDA 版在 Windows 上的 DLL（`torch_audio.dll`）依賴特定 CUDA runtime，
環境不齊全時 import 會拋出：

```
OSError: [WinError 127] 找不到指定的程序
```

Silero VAD 的 `load_silero_vad()` 內部會執行 `import torchaudio`，
因此即使我們自己的程式沒有用到 torchaudio，VAD 初始化仍會失敗。

### 解法

在 `import torchaudio` 之前攔截，失敗時注入一個空殼模組到 `sys.modules`，
讓 silero_vad 誤以為 torchaudio 已載入，跳過後續的 import 嘗試：

```python
# src/vad/detector.py
import sys, types
if 'torchaudio' not in sys.modules:
    try:
        import torchaudio
    except OSError:
        # DLL 載入失敗，注入空殼模組
        sys.modules['torchaudio'] = types.ModuleType('torchaudio')

from silero_vad import load_silero_vad  # 不會再嘗試 import torchaudio
```

### 為什麼這樣做是安全的

Silero VAD 只使用 `torch` 進行推理，torchaudio 只是被 import，並沒有實際呼叫任何功能。
用空殼模組替代不會影響 VAD 的正確性。

---

## 問題 4：啟動時進入無限安裝迴圈

### 原因

最初的 `_ensure_cuda_torch()` 同時安裝 `torch` 和 `torchaudio`：

```python
# 有問題的版本
subprocess.run([
    "uv", "pip", "install", "torch", "torchaudio",
    "--index-url", cuda_index
])
```

uv 在解析相依性時，`torchaudio` 的版本約束會把 torch 降版回 CPU 版本，形成無限迴圈：

```
偵測到 CPU torch
  → 安裝 CUDA torch
    → uv 因 torchaudio 相依降版 torch 為 CPU
      → 偵測到 CPU torch
        → 安裝 CUDA torch
          → ...（無限重複）
```

### 解法

從 `_ensure_cuda_torch()` 中完全移除 `torchaudio`，只安裝 `torch`：

```python
result = subprocess.run([
    "uv", "pip", "install", "torch",
    "--reinstall-package", "torch",
    "--index-url", cuda_index
])
```

torchaudio 的問題已由問題 3 的空殼 mock 解決，不需要安裝 torchaudio。

---

## 最終解決方案：`_ensure_cuda_torch()` 自動偵測與安裝

### 設計目標

讓程式在新 Windows 環境第一次執行時，能自動完成 CUDA torch 安裝，不需要使用者手動操作。

### 執行邏輯

```
執行 main.py
  ├─ 非 Windows → 跳過（Mac/Linux 不需要處理）
  ├─ torch 已支援 CUDA → 跳過
  ├─ 找不到 nvidia-smi → 跳過（沒有 NVIDIA GPU，使用 CPU）
  └─ 找到 NVIDIA GPU
       → 安裝 CUDA torch
       → 提示重新執行程式
       → sys.exit(0)
```

### 程式碼（main.py）

```python
def _ensure_cuda_torch():
    """Windows + NVIDIA GPU 時，確保安裝 CUDA 版 torch"""
    if platform.system() != "Windows":
        return
    try:
        import torch
        if torch.cuda.is_available():
            return  # 已經是 CUDA 版
    except ImportError:
        pass

    # 檢查是否有 NVIDIA GPU
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return  # 沒有 NVIDIA GPU
        gpu_name = result.stdout.strip().splitlines()[0]
    except Exception:
        return  # nvidia-smi 不存在

    print(f"偵測到 NVIDIA GPU：{gpu_name}")
    print("目前 torch 不支援 CUDA，正在安裝 CUDA 版本（約 2GB）...")
    cuda_index = "https://download.pytorch.org/whl/cu121"
    result = subprocess.run([
        "uv", "pip", "install", "torch",
        "--reinstall-package", "torch",
        "--index-url", cuda_index
    ])
    if result.returncode != 0:
        print("自動安裝失敗，請手動執行：")
        print(f"  uv pip install torch --index-url {cuda_index}")
        print("若 Python 版本過新（>3.13），請改用 Python 3.12 重建 venv。")
        sys.exit(1)
    print("安裝完成，請重新執行程式。")
    sys.exit(0)
```

### 在新 Windows 環境的執行流程

```
第一次執行
  → 偵測到 NVIDIA GPU
  → 自動下載安裝 CUDA torch（約 2GB，需等待）
  → 程式退出，提示重新執行

第二次執行
  → torch.cuda.is_available() == True
  → 跳過安裝，正常啟動
  → Whisper 使用 GPU 推理（float16 精度）
```

---

## requirements.txt 設計說明

### torch 為何不放進 requirements.txt

`torch` 有兩種版本使用不同的安裝來源：

| 版本 | 安裝指令 |
|------|---------|
| CPU 版 | `pip install torch`（PyPI）|
| CUDA 版 | `pip install torch --index-url https://download.pytorch.org/whl/cu121` |

兩者無法用同一行 `pip install` 處理，因此交由 `_ensure_cuda_torch()` 在 runtime 動態判斷。

### Windows 專屬套件使用 platform marker

```
pyaudiowpatch>=0.2.12; sys_platform == "win32"
scipy>=1.10.0; sys_platform == "win32"
```

這樣在 Mac/Linux 執行 `pip install -r requirements.txt` 時不會嘗試安裝這兩個 Windows 專屬套件。

---

## 跨平台對照

| 項目 | Windows | macOS |
|------|---------|-------|
| 音訊擷取 | pyaudiowpatch（WASAPI Loopback）| soundcard + BlackHole |
| 取樣率轉換 | scipy.signal.resample_poly | soundcard 原生處理 |
| GPU 推理 | NVIDIA CUDA（自動安裝）| CPU int8（Apple Silicon 無 CUDA）|
| torchaudio | 空殼 mock 繞過 DLL 問題 | 通常可正常載入 |
| Python 版本 | 3.12（3.13+ 不相容）| 3.12 建議 |

---

## 常見錯誤對照

| 錯誤訊息 | 原因 | 解法 |
|----------|------|------|
| `No module named 'torch'` | torch 未安裝 | `uv pip install torch` |
| `torch.cuda.is_available() == False` | 安裝的是 CPU 版 | 參考問題 1 重裝 CUDA 版 |
| `OSError: [WinError 127]` | torchaudio DLL 問題 | detector.py 的 mock 已處理，不應再出現 |
| `No matching distribution found for torch` | Python 版本過新 | 改用 Python 3.12 |
| 安裝後仍是 CPU torch | torchaudio 相依衝突 | 參考問題 4，不要同時安裝 torchaudio |

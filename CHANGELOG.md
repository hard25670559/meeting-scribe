# Changelog

所有版本的重要變更記錄於此文件。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

---

## [Unreleased]

## [0.4.0] - 2026-03-11

### Added
- 新增 `mlx-whisper` backend，Apple Silicon Mac 可使用 GPU 加速辨識（比 CPU 快 3-5 倍）
- 新增 `backend` 設定項（`faster-whisper` / `mlx-whisper`），可透過 `config.yaml` 切換
- 支援 `large-v3-turbo` 模型（速度約快 8x，準確度接近 large-v3）
- 啟動時自動偵測 ffmpeg，未安裝時顯示安裝提示

## [0.3.0] - 2026-03-10

### Added
- 新增 VAD `speech_threshold` 可設定參數（0.0~1.0），調高可讓靜音更快被判定

## [0.2.0] - 2026-03-10

### Added
- 支援 Windows NVIDIA GPU 自動偵測，首次執行自動安裝 CUDA 版 torch
- 重構音訊擷取模組，Windows 改用 pyaudiowpatch WASAPI Loopback
- 新增取樣率自動轉換（scipy resample_poly）

## [0.1.0] - 2026-03-09

### Added
- 初始版本，建立 Meeting Scribe 核心架構
- 同時擷取系統音訊與麥克風輸入
- VAD 語音切段（Silero VAD）
- ASR 語音辨識（Faster Whisper large-v3）
- 辨識結果自動轉換繁體中文（OpenCC s2twp）
- 帶時間戳的逐字稿輸出，逐行即時寫入
- VAD 語音片段同步存為 WAV 檔
- 支援 Windows、Linux、macOS 三大平台

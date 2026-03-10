# Roadmap

本文件記錄 Meeting Scribe 的未來開發計劃。
詳細規格請參考 [docs/speaker-asr-spec.md](docs/speaker-asr-spec.md) 與 [docs/SPEC.md](docs/SPEC.md)。

---

## 近期（進行中）

### ASR 品質強化與說話者辨識
> 規格文件：[docs/speaker-asr-spec.md](docs/speaker-asr-spec.md)

**階段一：後處理過濾（立即）**
- [ ] 加入 Hallucination 後處理過濾（正規表達式清除已知錯誤模式）
- [ ] 調整 `speech_threshold` 至 0.65，減少噪音片段送進 Whisper

**階段二：自動訓練資料收集（與階段一同步）**
- [ ] ASR 辨識流程中自動分類存檔（正樣本 / 負樣本）
- [ ] 累積至 400 筆以上訓練資料

**階段三：Whisper Fine-tuning（資料足夠後）**
- [ ] 使用 LoRA 微調 `large-v3-turbo` Decoder
- [ ] 讓模型學會噪音輸入時輸出空字串
- [ ] 整合 fine-tuned 模型至現有系統

**階段四：說話者辨識**
- [ ] 整合 pyannote.audio（Diarization + Identification）
- [ ] 建立聲紋資料庫
- [ ] 逐字稿輸出加入說話者標記（`[張三 00:00:03] 今天...`）

---

## 中期

### 分散式 ASR 水平擴展
> 規格文件：[docs/SPEC.md - 分散式 ASR 架構](docs/SPEC.md)

- [ ] Capture Service + ASR Worker 分離部署
- [ ] Dispatcher 調度機制（壓力評分、容錯、任務轉派）
- [ ] 支援一台擷取 + 多台辨識的部署方式
- [ ] 為線上服務做準備

---

## 長期

- [ ] 整合 LLM 自動產出會議摘要
- [ ] 支援即時字幕顯示（GUI / Web）
- [ ] 支援 SRT / VTT 字幕格式輸出
- [ ] Docker 容器化部署
- [ ] API 認證與安全性

import os
import wave
import queue
import signal
import threading

from src.config import get_config, save_device_to_config
from src.audio.capture import AudioCapture, select_device
from src.vad.detector import VADDetector
from src.asr.transcriber import Transcriber
from src.output.writer import TranscriptWriter


def asr_worker(asr_queue, transcriber, writer):
    """ASR 執行緒：持續從 Queue 取出 WAV 檔案路徑進行辨識"""
    while True:
        item = asr_queue.get()
        if item is None:
            # 收到結束信號
            break
        wav_path, start_time, end_time = item
        text = transcriber.transcribe_file(wav_path)
        if text:
            writer.add_entry(text, start_time, end_time)


def main():
    config = get_config()

    print("=" * 50)
    print("  Meeting Scribe - 語音轉逐字稿工具")
    print("=" * 50)
    print()

    # 1. 選擇音訊裝置
    device = select_device(config["audio"]["device"])
    save_device_to_config(device.name)

    # 2. 初始化各模組
    sample_rate = config["audio"]["sample_rate"]

    print()
    print("初始化 VAD 模型...")
    vad = VADDetector(
        sample_rate=sample_rate,
        silence_threshold=config["vad"]["silence_threshold"],
    )
    print("VAD 模型就緒。")

    print()
    transcriber = Transcriber(
        model_size=config["asr"]["model"],
        language=config["asr"]["language"],
        device=config["asr"]["device"],
        convert_traditional=config["asr"]["convert_traditional"],
    )

    writer = TranscriptWriter(
        output_dir=config["output"]["directory"],
    )

    capture = AudioCapture(device, sample_rate=sample_rate)

    # 3. 建立 Queue 與 ASR 執行緒
    asr_queue = queue.Queue()
    asr_thread = threading.Thread(
        target=asr_worker,
        args=(asr_queue, transcriber, writer),
        daemon=True,
    )

    # 4. 設定 Ctrl+C 立即結束
    def signal_handler(sig, frame):
        print("\n\n正在停止...")
        capture.stop()

        # 直接儲存已完成的逐字稿，不等待未完成的 ASR 辨識
        writer.save()
        os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # 5. 顯示啟動資訊
    print()
    print("-" * 50)
    print(f"  模型：{config['asr']['model']}")
    lang = config["asr"]["language"] or "自動偵測"
    print(f"  語言：{lang}")
    print(f"  裝置：{device.name}")
    print(f"  繁體轉換：{'開啟' if config['asr']['convert_traditional'] else '關閉'}")
    print(f"  靜音閾值：{config['vad']['silence_threshold']} 秒")
    print(f"  輸出目錄：{config['output']['directory']}")
    print("-" * 50)
    print("錄音中... 按 Ctrl+C 停止")
    print()

    # 6. 啟動 ASR 執行緒
    asr_thread.start()

    # 7. DEBUG: WAV 片段存到 writer 的 session 資料夾
    segment_count = 0

    def save_segment_wav(audio_segment, start_time, end_time, sample_rate):
        """將 VAD 切出的片段存成 WAV 檔"""
        nonlocal segment_count
        segment_count += 1
        start_str = f"{int(start_time // 60):02d}m{start_time % 60:06.3f}s"
        end_str = f"{int(end_time // 60):02d}m{end_time % 60:06.3f}s"
        filename = f"{start_str}-{end_str}.wav"
        filepath = writer.session_dir / filename

        # float32 → int16 for WAV
        import numpy as np
        audio_int16 = (audio_segment * 32767).clip(-32768, 32767).astype(np.int16)

        with wave.open(str(filepath), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        return filepath

    # 8. 主執行緒：音訊擷取 → VAD → 片段放入 Queue
    import numpy as np
    for audio_chunk in capture.start():
        # 在 capture 的 channel debug 後方附加 queue 資訊
        print(f" | Queue: {asr_queue.qsize()}", end="", flush=True)
        result = vad.process_chunk(audio_chunk)
        if result:
            audio_segment, start_time, end_time = result
            # 儲存每個 VAD 片段為 WAV
            wav_path = save_segment_wav(audio_segment, start_time, end_time, sample_rate)
            # 過濾音量過低的片段，避免 Whisper 靜音幻覺
            segment_level = np.abs(audio_segment).max()
            if segment_level > 0.01:
                asr_queue.put((wav_path, start_time, end_time))
            else:
                print(f"\n[跳過] 音量過低 ({segment_level:.4f})，丟棄片段")


if __name__ == "__main__":
    main()

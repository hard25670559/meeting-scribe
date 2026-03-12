import time
import numpy as np
import torch


class VADDetector:
    """使用 Silero VAD 偵測語音活動，將音訊串流切分為語音片段"""

    def __init__(self, sample_rate=16000, silence_threshold=1.5, speech_threshold=0.5):
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.speech_threshold = speech_threshold

        # silero_vad 會 import torchaudio，但我們不需要它的功能
        # 若 torchaudio DLL 載入失敗，注入空模組來繞過
        import sys, types
        if 'torchaudio' not in sys.modules:
            try:
                import torchaudio  # noqa
            except OSError:
                sys.modules['torchaudio'] = types.ModuleType('torchaudio')

        from silero_vad import load_silero_vad
        self.model = load_silero_vad()
        self.model.eval()

        # 狀態
        self._in_speech = False
        self._speech_buffer = []
        self._silence_start = None
        self._speech_start_time = None
        self._current_time = 0.0
        self.last_speech_prob = 0.0

    def reset(self):
        """重置 VAD 狀態"""
        self._in_speech = False
        self._speech_buffer = []
        self._silence_start = None
        self._speech_start_time = None
        self._current_time = 0.0
        self.model.reset_states()

    def process_chunk(self, audio_chunk):
        """
        處理一個音訊區塊，回傳完成的語音片段（若有）。

        Args:
            audio_chunk: numpy array, 單聲道 float32 音訊

        Returns:
            若偵測到一段完整語音，回傳 (audio_segment, start_time, end_time)
            否則回傳 None
        """
        chunk_duration = len(audio_chunk) / self.sample_rate

        # Silero VAD 需要 512 samples 的視窗（16kHz 時）
        # 將 chunk 分成 512 samples 的小段來偵測
        window_size = 512
        result = None

        for i in range(0, len(audio_chunk), window_size):
            window = audio_chunk[i:i + window_size]
            if len(window) < window_size:
                # 不足一個視窗，補零
                window = np.pad(window, (0, window_size - len(window)))

            tensor = torch.from_numpy(window).float()
            speech_prob = self.model(tensor, self.sample_rate).item()
            self.last_speech_prob = speech_prob

            is_speech = speech_prob > self.speech_threshold
            window_time = window_size / self.sample_rate

            if is_speech:
                if not self._in_speech:
                    # 語音開始
                    self._in_speech = True
                    self._speech_start_time = self._current_time
                    self._speech_buffer = []

                self._speech_buffer.append(window)
                self._silence_start = None

            else:
                if self._in_speech:
                    # 仍在語音段落中，但偵測到靜音
                    self._speech_buffer.append(window)

                    if self._silence_start is None:
                        self._silence_start = self._current_time

                    silence_duration = self._current_time - self._silence_start + window_time
                    if silence_duration >= self.silence_threshold:
                        # 靜音超過閾值，結束這段語音
                        audio_segment = np.concatenate(self._speech_buffer)
                        start_time = self._speech_start_time
                        end_time = self._current_time

                        self._in_speech = False
                        # 明確釋放緩衝區
                        del self._speech_buffer
                        self._speech_buffer = []
                        self._silence_start = None
                        self._speech_start_time = None

                        result = (audio_segment, start_time, end_time)

            self._current_time += window_time

        return result

    def flush(self):
        """
        強制輸出目前累積的語音片段（用於程式結束時）。

        Returns:
            若有累積的語音，回傳 (audio_segment, start_time, end_time)
            否則回傳 None
        """
        if self._in_speech and self._speech_buffer:
            audio_segment = np.concatenate(self._speech_buffer)
            start_time = self._speech_start_time
            end_time = self._current_time

            self._in_speech = False
            # 明確釋放緩衝區
            del self._speech_buffer
            self._speech_buffer = []
            self._silence_start = None
            self._speech_start_time = None

            return (audio_segment, start_time, end_time)
        return None

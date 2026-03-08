import numpy as np
from faster_whisper import WhisperModel


class Transcriber:
    """使用 Faster Whisper 進行語音辨識，支援繁體中文轉換"""

    def __init__(self, model_size="large-v3", language="zh", device="auto",
                 convert_traditional=True):
        self.language = language
        self.convert_traditional = convert_traditional
        self._converter = None

        # 決定推理裝置
        if device == "auto":
            compute_type = "float16"
            try:
                import torch
                if torch.cuda.is_available():
                    device_type = "cuda"
                else:
                    device_type = "cpu"
                    compute_type = "int8"
            except ImportError:
                device_type = "cpu"
                compute_type = "int8"
        else:
            device_type = device
            compute_type = "float16" if device == "cuda" else "int8"

        print(f"載入 Whisper 模型：{model_size}（裝置：{device_type}，精度：{compute_type}）")
        self.model = WhisperModel(model_size, device=device_type, compute_type=compute_type)
        print("模型載入完成。")

        # 初始化 OpenCC 轉換器
        if self.convert_traditional:
            self._init_converter()

    def _init_converter(self):
        """初始化 OpenCC 簡轉繁轉換器"""
        try:
            from opencc import OpenCC
            self._converter = OpenCC("s2twp")
        except ImportError:
            print("警告：未安裝 opencc-python-reimplemented，無法進行簡繁轉換。")
            self._converter = None

    def transcribe_file(self, wav_path):
        """
        從 WAV 檔案路徑辨識語音。

        Args:
            wav_path: WAV 檔案路徑

        Returns:
            辨識出的文字字串
        """
        # Faster Whisper 接受檔案路徑
        segments, info = self.model.transcribe(
            str(wav_path),
            language=self.language,
            vad_filter=False,  # 我們已經做過 VAD
        )

        # 組合所有片段的文字
        text = "".join(segment.text for segment in segments).strip()

        # 簡轉繁
        if text and self._converter:
            text = self._converter.convert(text)

        return text

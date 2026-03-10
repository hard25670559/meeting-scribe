import numpy as np

# mlx-whisper 模型名稱對應表
_MLX_MODEL_MAP = {
    "large-v3":       "mlx-community/whisper-large-v3",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "medium":         "mlx-community/whisper-medium",
    "small":          "mlx-community/whisper-small",
    "base":           "mlx-community/whisper-base",
    "tiny":           "mlx-community/whisper-tiny",
}


class Transcriber:
    """使用 Faster Whisper 或 MLX Whisper 進行語音辨識，支援繁體中文轉換"""

    def __init__(self, model_size="large-v3", language="zh", device="auto",
                 convert_traditional=True, backend="faster-whisper"):
        self.language = language
        self.convert_traditional = convert_traditional
        self.backend = backend
        self._converter = None
        self.model = None

        if backend == "mlx-whisper":
            self._init_mlx(model_size)
        else:
            self._init_faster_whisper(model_size, device)

        # 初始化 OpenCC 轉換器
        if self.convert_traditional:
            self._init_converter()

    def _init_faster_whisper(self, model_size, device):
        from faster_whisper import WhisperModel

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

        print(f"載入 Whisper 模型：{model_size}（backend：faster-whisper，裝置：{device_type}，精度：{compute_type}）")
        self.model = WhisperModel(model_size, device=device_type, compute_type=compute_type)
        print("模型載入完成。")

    def _init_mlx(self, model_size):
        import shutil
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "未偵測到 ffmpeg，mlx-whisper 需要 ffmpeg 讀取音訊。\n"
                "請安裝 ffmpeg：brew install ffmpeg"
            )

        try:
            import mlx_whisper  # noqa: F401
        except ImportError:
            raise ImportError(
                "mlx-whisper 未安裝，請執行：uv pip install -r requirements.txt\n"
                "注意：mlx-whisper 僅支援 Apple Silicon Mac。"
            )

        self.mlx_repo = _MLX_MODEL_MAP.get(model_size, f"mlx-community/whisper-{model_size}")
        print(f"載入 Whisper 模型：{model_size}（backend：mlx-whisper，repo：{self.mlx_repo}）")
        print("模型載入完成。")

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
        if self.backend == "mlx-whisper":
            text = self._transcribe_mlx(wav_path)
        else:
            text = self._transcribe_faster_whisper(wav_path)

        # 簡轉繁
        if text and self._converter:
            text = self._converter.convert(text)

        return text

    def _transcribe_faster_whisper(self, wav_path):
        segments, info = self.model.transcribe(
            str(wav_path),
            language=self.language,
            vad_filter=False,
        )
        return "".join(segment.text for segment in segments).strip()

    def _transcribe_mlx(self, wav_path):
        import mlx_whisper
        result = mlx_whisper.transcribe(
            str(wav_path),
            path_or_hf_repo=self.mlx_repo,
            language=self.language,
        )
        return result.get("text", "").strip()

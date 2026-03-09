import os
import yaml
import argparse
from pathlib import Path


DEFAULT_CONFIG = {
    "audio": {
        "device": None,
        "sample_rate": 16000,
    },
    "vad": {
        "silence_threshold": 1.5,
        "speech_threshold": 0.5,
    },
    "asr": {
        "model": "large-v3",
        "language": "zh",
        "device": "auto",
        "convert_traditional": True,
    },
    "output": {
        "directory": "./transcripts",
        "format": "txt",
    },
}


def find_config_path():
    """尋找設定檔路徑，優先使用當前目錄的 config.yaml"""
    candidates = [
        Path("config.yaml"),
        Path(__file__).parent.parent / "config.yaml",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def load_config(config_path=None):
    """讀取設定檔，若不存在則使用預設值"""
    config = _deep_copy_dict(DEFAULT_CONFIG)

    path = config_path or find_config_path()
    if path and Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f) or {}
        _deep_merge(config, file_config)

    return config


def save_device_to_config(device_name, config_path=None):
    """將使用者選擇的音訊裝置名稱回寫設定檔"""
    path = config_path or find_config_path()
    if not path:
        path = Path("config.yaml")

    config = {}
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    if "audio" not in config:
        config["audio"] = {}
    config["audio"]["device"] = device_name

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def parse_args():
    """解析 CLI 參數"""
    parser = argparse.ArgumentParser(description="Meeting Scribe - 語音轉逐字稿工具")
    parser.add_argument("--language", type=str, help="辨識語言（如 zh, en），不指定則使用設定檔值")
    parser.add_argument("--model", type=str, help="Whisper 模型大小（如 large-v3, medium）")
    parser.add_argument("--output", type=str, help="逐字稿輸出目錄")
    parser.add_argument("--device", type=str, help="音訊裝置名稱")
    parser.add_argument("--config", type=str, help="設定檔路徑")
    return parser.parse_args()


def get_config():
    """取得最終設定（設定檔 + CLI 參數覆蓋）"""
    args = parse_args()
    config = load_config(args.config)

    if args.language is not None:
        config["asr"]["language"] = args.language if args.language != "auto" else None
    if args.model is not None:
        config["asr"]["model"] = args.model
    if args.output is not None:
        config["output"]["directory"] = args.output
    if args.device is not None:
        config["audio"]["device"] = args.device

    return config


def _deep_copy_dict(d):
    """深拷貝字典"""
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _deep_copy_dict(v)
        else:
            result[k] = v
    return result


def _deep_merge(base, override):
    """將 override 的值合併進 base（就地修改）"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v

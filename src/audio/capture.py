import sys
import platform
import numpy as np
import soundcard as sc


def get_platform():
    """偵測作業系統平台"""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    elif system == "Windows":
        return "windows"
    elif system == "Linux":
        return "linux"
    return system.lower()


def list_input_devices():
    """列出所有可用的輸入（麥克風）裝置"""
    return sc.all_microphones(include_loopback=True)


def list_output_devices():
    """列出所有可用的輸出裝置"""
    return sc.all_speakers()


def find_device_by_name(name, devices):
    """根據名稱在裝置列表中尋找裝置"""
    for device in devices:
        if name.lower() in device.name.lower():
            return device
    return None


def check_blackhole_available():
    """檢查 macOS 是否安裝 BlackHole"""
    devices = list_input_devices()
    for device in devices:
        if "blackhole" in device.name.lower():
            return True
    return False


def print_macos_setup_guide():
    """顯示 macOS BlackHole 安裝引導"""
    print("\n未偵測到 BlackHole 音訊裝置。")
    print("請依照以下步驟安裝：")
    print("  1. 執行 brew install blackhole-2ch")
    print("  2. 重新開機")
    print("  3. 開啟「音訊 MIDI 設定」")
    print("  4. 建立「多重輸出裝置」：勾選耳機/喇叭 + BlackHole 2ch")
    print("  5. 建立「聚合裝置」：勾選麥克風 + BlackHole 2ch")
    print("  6. 系統音訊輸出切換至「多重輸出裝置」")
    print()


def select_device(config_device_name=None):
    """選擇音訊輸入裝置，回傳 soundcard 裝置物件"""
    plat = get_platform()
    devices = list_input_devices()

    if not devices:
        print("錯誤：未偵測到任何音訊輸入裝置。")
        sys.exit(1)

    # macOS 特殊檢查
    if plat == "macos" and not check_blackhole_available():
        print_macos_setup_guide()

    # 如果設定檔有指定裝置，嘗試自動選擇
    if config_device_name:
        device = find_device_by_name(config_device_name, devices)
        if device:
            print(f"使用裝置：{device.name}")
            return device
        print(f"警告：找不到裝置「{config_device_name}」，請重新選擇。\n")

    # 顯示裝置列表供使用者選擇
    print("可用的音訊輸入裝置：")
    for i, device in enumerate(devices):
        print(f"  [{i}] {device.name}")
    print()

    while True:
        try:
            choice = input("請選擇裝置編號：").strip()
            idx = int(choice)
            if 0 <= idx < len(devices):
                selected = devices[idx]
                print(f"已選擇：{selected.name}")
                return selected
            print(f"請輸入 0 到 {len(devices) - 1} 之間的數字。")
        except ValueError:
            print("請輸入有效的數字。")
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            sys.exit(0)


class AudioCapture:
    """音訊擷取器，以串流方式產出音訊區塊"""

    def __init__(self, device, sample_rate=16000, chunk_duration=0.5):
        self.device = device
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_duration)
        self._running = False

    def start(self):
        """開始擷取音訊，以 generator 方式產出單聲道音訊區塊（numpy array）"""
        self._running = True
        print(f"[DEBUG] device.name: {self.device.name}")
        print(f"[DEBUG] device.channels: {self.device.channels}")
        # 嘗試強制讀取 4 個聲道（聚合裝置：2ch 麥克風 + 2ch BlackHole）
        try:
            rec_channels = max(self.device.channels, 4)
        except Exception:
            rec_channels = 4
        print(f"[DEBUG] 嘗試讀取聲道數: {rec_channels}")
        with self.device.recorder(samplerate=self.sample_rate, channels=rec_channels) as recorder:
            first_chunk = True
            while self._running:
                # 錄製一個區塊，shape: (chunk_samples, channels)
                data = recorder.record(numframes=self.chunk_samples)
                if first_chunk:
                    print(f"[DEBUG] data shape: {data.shape}, dtype: {data.dtype}")
                    first_chunk = False
                ch_levels = [np.abs(data[:, ch]).max() for ch in range(data.shape[1])]
                ch_info = " | ".join(f"ch{ch}:{lv:.4f}" for ch, lv in enumerate(ch_levels))
                print(f"\r[DEBUG] {ch_info}", end="", flush=True)
                # 混合所有聲道為單聲道
                mono = np.mean(data, axis=1).astype(np.float32)
                yield mono

    def stop(self):
        """停止擷取"""
        self._running = False

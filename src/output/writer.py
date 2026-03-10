import os
from datetime import datetime
from pathlib import Path


def format_timestamp(seconds):
    """將秒數轉換為 HH:MM:SS.mmm 格式"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


class TranscriptWriter:
    """逐字稿輸出管理器，即時輸出至終端機並逐行寫入檔案"""

    def __init__(self, output_dir="./transcripts"):
        self.output_dir = Path(output_dir)
        self.entry_count = 0
        self.last_end_time = 0
        self.start_datetime = datetime.now()

        # 以時間戳建立本次錄製的專屬資料夾
        timestamp = self.start_datetime.strftime("%Y%m%d_%H%M%S")
        self.session_dir = self.output_dir / f"transcript_{timestamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        filename = f"transcript_{timestamp}.txt"
        self.filepath = self.session_dir / filename

    def add_entry(self, text, start_time, end_time):
        """
        新增一筆辨識結果，即時輸出至終端機並寫入檔案。

        Args:
            text: 辨識出的文字
            start_time: 片段開始時間（秒）
            end_time: 片段結束時間（秒）
        """
        if not text:
            return

        entry = {
            "text": text,
            "start_time": start_time,
            "end_time": end_time,
        }

        self.entry_count += 1
        self.last_end_time = end_time

        # 即時輸出至終端機（先清掉 debug 行再換行印出）
        line = self._format_entry(entry)
        print(f"\r{' ' * 150}\r{line}")

        # 逐行 append 寫入檔案
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _format_entry(self, entry):
        """格式化單筆逐字稿"""
        start = format_timestamp(entry["start_time"])
        end = format_timestamp(entry["end_time"])
        return f"[{start} - {end}] {entry['text']}"

    def save(self):
        """程式結束時印出儲存摘要"""
        if self.entry_count == 0:
            print("沒有辨識結果需要儲存。")
            return None

        print(f"\n逐字稿已儲存：{self.filepath}")
        print(f"共 {self.entry_count} 段，")
        if self.last_end_time:
            print(f"總時長：{format_timestamp(self.last_end_time)}")

        return self.filepath

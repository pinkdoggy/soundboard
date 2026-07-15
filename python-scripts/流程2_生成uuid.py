#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON 編碼 UUID 工具
跨平台版本（Windows / macOS / Linux）

功能：
  將 ../config/sounds.json 重新命名為 sounds-old.json，
  然後呼叫 ufid64.py 處理並輸出新的 sounds.json。

用法：
  python json_encode_uuid.py
  python json_encode_uuid.py --config-dir <自訂config路徑>
  python json_encode_uuid.py --input <輸入檔> --output <輸出檔>
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path


def get_script_dir() -> Path:
    """取得腳本所在目錄"""
    return Path(__file__).resolve().parent


def find_python() -> str:
    """尋找可用的 Python 執行器"""
    return sys.executable


def run_ufid64(input_path: Path, output_path: Path, script_dir: Path) -> int:
    """執行 ufid64.py 腳本"""
    python_exe = find_python()
    script_path = script_dir / "ufid64.py"
    
    if not script_path.exists():
        print(f"[ERROR] 找不到腳本：{script_path}")
        return 1
    
    # 設定環境變數確保 UTF-8
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "UTF-8"
    
    cmd = [python_exe, str(script_path), str(input_path), "-o", str(output_path)]
    
    print()
    print(f'執行：ufid64.py "{input_path}" -o "{output_path}"')
    
    try:
        result = subprocess.run(cmd, env=env)
        return result.returncode
    except Exception as e:
        print(f"[ERROR] 執行失敗：{e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="JSON 編碼 UUID 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--config-dir", "-c",
        help="config 資料夾路徑（預設為腳本上一層的 config 目錄）"
    )
    parser.add_argument(
        "--input", "-i",
        help="輸入檔案路徑（覆蓋預設）"
    )
    parser.add_argument(
        "--output", "-o",
        help="輸出檔案路徑（覆蓋預設）"
    )
    
    args = parser.parse_args()
    
    script_dir = get_script_dir()
    
    # 決定路徑
    if args.input and args.output:
        # 使用自訂輸入輸出
        input_path = Path(args.input)
        output_path = Path(args.output)
        old_path = None  # 不做重新命名
    else:
        # 使用預設的 config 目錄結構
        if args.config_dir:
            config_dir = Path(args.config_dir)
        else:
            # 預設：腳本所在目錄的上一層的 config 目錄
            config_dir = script_dir.parent / "config"
        
        output_path = config_dir / "sounds.json"
        old_path = config_dir / "sounds-old.json"
        input_path = old_path
    
    # 顯示資訊
    print(f"[INFO] 腳本所在：{script_dir}")
    if args.input and args.output:
        print(f"[INFO] 輸入檔：{input_path}")
        print(f"[INFO] 輸出檔：{output_path}")
    else:
        print(f"[INFO] 目標資料夾：{config_dir}")
        print(f"[INFO] 輸入(舊)：{old_path}")
        print(f"[INFO] 輸出(新)：{output_path}")
    
    # 如果不是自訂模式，執行重新命名
    if old_path is not None:
        if output_path.exists():
            print(f'重新命名 "{output_path}" -> "{old_path}"')
            try:
                shutil.move(str(output_path), str(old_path))
            except Exception as e:
                print(f"[ERROR] 重新命名失敗：{e}")
                return 1
        else:
            print(f'[提示] 找不到 "{output_path}"（將嘗試直接使用已存在的 "{old_path}" 作為輸入）')
    
    # 檢查輸入檔是否存在
    if not input_path.exists():
        print(f"[ERROR] 找不到輸入檔：{input_path}")
        return 1
    
    # 執行 ufid64.py
    rc = run_ufid64(input_path, output_path, script_dir)
    
    print()
    if rc != 0:
        print(f"[失敗] ufid64.py 結束代碼：{rc}")
    else:
        print(f"[完成] 已輸出：{output_path}")
    
    return rc


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n[中斷] 使用者取消操作")
        exit_code = 1
    except Exception as e:
        print(f"[錯誤] {e}")
        exit_code = 1
    
    # 互動模式下暫停（類似 batch 的 pause）
    # 檢測是否為雙擊執行（無參數且非 pipe）
    if len(sys.argv) == 1 and sys.stdin.isatty():
        input("\n按 Enter 鍵結束...")
    
    sys.exit(exit_code)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流程：清理 → 轉檔 → 生成 JSON
跨平台版本（Windows / macOS / Linux）

用法：
  python workflow_clean_convert_json.py <輸入資料夾> <輸出資料夾> [轉檔參數...] [--json <JSON路徑>]
  
範例：
  python workflow_clean_convert_json.py "D:/來源" "E:/輸出"
  python workflow_clean_convert_json.py "D:/來源" "E:/輸出" --recursive --force
  python workflow_clean_convert_json.py "D:/來源" "E:/輸出" --json "E:/輸出/library.json"
  
無參數執行時進入互動模式。
"""

import os
import sys
import subprocess
import configparser
from pathlib import Path


def get_script_dir() -> Path:
    """取得腳本所在目錄"""
    return Path(__file__).resolve().parent


def find_python() -> str:
    """尋找可用的 Python 執行器"""
    # 優先使用當前 Python
    return sys.executable


def load_ini(ini_path: Path) -> dict:
    """載入 INI 設定檔"""
    config = {"IN": "", "OUT": ""}
    if ini_path.exists():
        try:
            with open(ini_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip().upper()
                        if key in config:
                            config[key] = value.strip()
        except Exception:
            pass
    return config


def save_ini(ini_path: Path, in_path: str, out_path: str):
    """儲存 INI 設定檔"""
    try:
        with open(ini_path, "w", encoding="utf-8") as f:
            f.write(f"IN={in_path}\n")
            f.write(f"OUT={out_path}\n")
    except Exception as e:
        print(f"[警告] 無法寫入設定檔：{e}")


def pick_dir(prompt: str, default: str = "") -> str:
    """互動式選擇資料夾"""
    print()
    print(f"選擇 {prompt}：")
    
    has_default = default and Path(default).exists()
    
    if default:
        if has_default:
            print(f'  [D] 使用上次： "{default}"')
        else:
            print(f'  （注意：上次路徑不存在："{default}"）')
    
    print("  [E] 手動輸入完整路徑")
    
    while True:
        if has_default:
            choice = input("選擇 (D/E): ").strip().upper()
            if choice == "D":
                return default
            elif choice == "E":
                path = input(f"請輸入{prompt}： ").strip()
                if path:
                    return path
            else:
                print("請輸入 D 或 E")
        else:
            choice = input("選擇 (E): ").strip().upper()
            if choice == "E" or choice == "":
                path = input(f"請輸入{prompt}： ").strip()
                if path:
                    return path


def run_script(script_name: str, args: list, script_dir: Path) -> bool:
    """執行 Python 腳本"""
    python_exe = find_python()
    script_path = script_dir / script_name
    
    if not script_path.exists():
        print(f"[ERROR] 找不到腳本：{script_path}")
        return False
    
    cmd = [python_exe, str(script_path)] + args
    
    # 設定環境變數確保 UTF-8
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "UTF-8"
    
    try:
        result = subprocess.run(cmd, env=env)
        return result.returncode == 0
    except Exception as e:
        print(f"[ERROR] 執行失敗：{e}")
        return False


def parse_args(args: list) -> tuple:
    """
    解析命令列參數
    返回：(in_path, out_path, json_path, convert_args)
    """
    in_path = None
    out_path = None
    json_path = None
    convert_args = []
    
    i = 0
    while i < len(args):
        arg = args[i]
        
        if arg.lower() == "--json":
            i += 1
            if i < len(args):
                json_path = args[i]
            else:
                return None, None, None, None  # 錯誤：--json 後沒有路徑
        elif in_path is None:
            in_path = arg
        elif out_path is None:
            out_path = arg
        else:
            convert_args.append(arg)
        
        i += 1
    
    return in_path, out_path, json_path, convert_args


def print_usage():
    """印出使用說明"""
    script_name = Path(__file__).name
    print(f"""
用法：
  python {script_name} <輸入資料夾> <輸出資料夾> [轉檔v3 其他參數...] [--json <JSON輸出路徑>]

範例（非遞迴）：
  python {script_name} "D:/來源" "E:/輸出"

範例（遞迴 + 覆寫）：
  python {script_name} "D:/來源" "E:/輸出" --recursive --force

範例（指定 JSON）：
  python {script_name} "D:/來源" "E:/輸出" --json "E:/輸出/library.json"
""")


def main():
    script_dir = get_script_dir()
    ini_path = script_dir / "workflow.ini"
    
    # 載入上次設定
    last_config = load_ini(ini_path)
    
    # 解析命令列參數
    args = sys.argv[1:]
    
    if args:
        # Console 模式
        in_path, out_path, json_path, convert_args = parse_args(args)
        
        if not in_path or not out_path:
            print_usage()
            return 1
        
        if not json_path:
            json_path = str(Path(out_path) / "mp3_index.json")
    else:
        # 互動模式
        print()
        print("===============================")
        print("  清理 > 轉檔 > 生成 JSON")
        print("  互動設定模式")
        print("===============================")
        
        in_path = pick_dir("輸入資料夾", last_config.get("IN", ""))
        if not in_path:
            print("[失敗] 未選擇輸入資料夾")
            return 1
        
        out_path = pick_dir("輸出資料夾", last_config.get("OUT", ""))
        if not out_path:
            print("[失敗] 未選擇輸出資料夾")
            return 1
        
        json_path = str(Path(out_path) / "mp3_index.json")
        convert_args = []
    
    # 儲存設定
    save_ini(ini_path, in_path, out_path)
    
    # 步驟 1：檔名清理
    print()
    print(f'[1/3] 檔名清理.py -i "{in_path}"')
    if not run_script("檔名清理.py", ["-i", in_path], script_dir):
        print("[失敗] 檔名清理失敗")
        return 1
    
    # 步驟 2：轉檔
    print()
    convert_cmd_args = ["-i", in_path, "-o", out_path] + convert_args
    print(f'[2/3] 轉檔v3.py {" ".join(convert_cmd_args)}')
    if not run_script("轉檔v3.py", convert_cmd_args, script_dir):
        print("[失敗] 轉檔失敗")
        return 1
    
    # 步驟 3：生成 JSON
    print()
    print(f'[3/3] JSON生成v3.py -i "{out_path}" -o "{json_path}"')
    if not run_script("JSON生成v3.py", ["-i", out_path, "-o", json_path], script_dir):
        print("[失敗] JSON 生成失敗")
        return 1
    
    print()
    print("[完成] 已依序完成：檔名清理 → 轉檔 → 生成 JSON")
    print(f"JSON 輸出：{json_path}")
    
    return 0


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
    if len(sys.argv) == 1:
        input("\n按 Enter 鍵結束...")
    
    sys.exit(exit_code)

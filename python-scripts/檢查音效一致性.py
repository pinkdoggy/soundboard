#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
檢查音效一致性腳本

比對 sounds 資料夾中的實際檔案與 sounds.json 中的條目，
找出不一致的地方（缺少 JSON 條目或檔案不存在）。

使用方式：
    python 檢查音效一致性.py
    
從專案根目錄執行：
    python python-scripts/檢查音效一致性.py
"""

import json
import os
import sys

def get_project_root():
    """取得專案根目錄（此腳本的上層目錄）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(script_dir)

def check_sound_consistency():
    """檢查 sounds 資料夾與 sounds.json 的一致性"""
    
    project_root = get_project_root()
    sounds_json_path = os.path.join(project_root, 'config', 'sounds.json')
    sounds_folder = os.path.join(project_root, 'sounds')
    
    # 檢查路徑是否存在
    if not os.path.exists(sounds_json_path):
        print(f'❌ 找不到 sounds.json: {sounds_json_path}')
        sys.exit(1)
    
    if not os.path.exists(sounds_folder):
        print(f'❌ 找不到 sounds 資料夾: {sounds_folder}')
        sys.exit(1)
    
    # 讀取 sounds.json 中的檔名
    with open(sounds_json_path, 'r', encoding='utf-8') as f:
        sounds_json = json.load(f)
    
    json_files = set(s['file'] for s in sounds_json)
    
    # 掃描 sounds 資料夾中的實際檔案
    actual_files = set()
    for root, dirs, files in os.walk(sounds_folder):
        for file in files:
            if file.lower().endswith('.mp3'):
                # 取得相對於 sounds 資料夾的路徑
                rel_path = os.path.relpath(os.path.join(root, file), sounds_folder)
                actual_files.add(rel_path)
    
    # 比對
    in_folder_not_json = actual_files - json_files
    in_json_not_folder = json_files - actual_files
    
    # 輸出結果
    print('=' * 60)
    print(f'📁 sounds 資料夾內的檔案: {len(actual_files)} 個')
    print(f'📋 sounds.json 中的條目: {len(json_files)} 個')
    print('=' * 60)
    
    if in_folder_not_json:
        print(f'\n⚠️  在資料夾中但不在 JSON 中 ({len(in_folder_not_json)} 個):')
        for f in sorted(in_folder_not_json):
            print(f'   • {f}')
    
    if in_json_not_folder:
        print(f'\n❌ 在 JSON 中但資料夾找不到 ({len(in_json_not_folder)} 個):')
        for f in sorted(in_json_not_folder):
            print(f'   • {f}')
    
    if not in_folder_not_json and not in_json_not_folder:
        print('\n✅ 完全一致！')
    
    # 檢查可能的字元差異（如全形/半形）
    if in_folder_not_json and in_json_not_folder:
        print('\n' + '=' * 60)
        print('🔍 可能的檔名字元差異（相似但不完全相同）:')
        print('=' * 60)
        
        found_similar = False
        for json_file in sorted(in_json_not_folder):
            # 正規化比對：將全形字元轉半形
            json_normalized = json_file.replace('～', '~').replace('！', '!').replace('？', '?')
            
            for actual_file in in_folder_not_json:
                actual_normalized = actual_file.replace('～', '~').replace('！', '!').replace('？', '?')
                
                if json_normalized == actual_normalized:
                    found_similar = True
                    print(f'\n   JSON:     {json_file}')
                    print(f'   資料夾:   {actual_file}')
                    # 找出差異字元
                    for i, (c1, c2) in enumerate(zip(json_file, actual_file)):
                        if c1 != c2:
                            print(f'   差異位置 {i}: "{c1}" (U+{ord(c1):04X}) vs "{c2}" (U+{ord(c2):04X})')
        
        if not found_similar:
            print('   （未發現明顯的字元差異配對）')
    
    # 回傳結果供程式化使用
    return {
        'actual_count': len(actual_files),
        'json_count': len(json_files),
        'in_folder_not_json': sorted(in_folder_not_json),
        'in_json_not_folder': sorted(in_json_not_folder),
        'is_consistent': len(in_folder_not_json) == 0 and len(in_json_not_folder) == 0
    }

if __name__ == '__main__':
    result = check_sound_consistency()
    
    # 如果不一致，以非零狀態碼結束（方便 CI/CD 使用）
    if not result['is_consistent']:
        sys.exit(1)

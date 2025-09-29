#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
轉音檔_v2_fallback.py
在原 v2 基礎上增加：
- 當兩段式 EBU R128 loudnorm（分析→套用）失敗時，針對該檔自動改用「單段式 loudnorm」作為後備方案，
  以提高穩健性；成功時會於訊息中標註（fallback）。
- 其餘行為與參數維持一致（I/TP/LRA、取樣率、聲道/編碼策略等）。

支援副檔名：.mp4 .mp3 .m4a .wav .flac
需要：系統可執行 ffmpeg/ffprobe。
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from tqdm import tqdm

SUPPORTED_EXTS = {".mp4", ".mp3", ".m4a", ".wav", ".flac"}
DEFAULT_OUT_DIR_NAME = "已轉換"

@dataclass
class LoudnormTarget:
    I: float = -14.0
    TP: float = -1.5
    LRA: float = 11.0


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def have_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


def run_cmd(cmd: list) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr) as text."""
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        out = p.stdout.decode(errors="replace")
        err = p.stderr.decode(errors="replace")
        return p.returncode, out, err
    except FileNotFoundError as e:
        return 127, "", f"找不到可執行檔：{e}"
    except Exception as e:
        return 1, "", f"執行指令時發生未預期錯誤：{e}"


def ffprobe_audio_info(path: Path) -> Dict:
    """用 ffprobe 取得音訊資訊（取樣率、平均位元率、聲道數、編碼器）。"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,channels,sample_rate,bit_rate",
        "-of", "json",
        str(path),
    ]
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"ffprobe 失敗：{err.strip()}")
    data = json.loads(out or "{}")
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError("找不到音訊串流（可能是損毀檔或不支援格式）")
    s = streams[0]
    sample_rate = int(s.get("sample_rate") or 0)
    bit_rate = int(s.get("bit_rate") or 0)
    channels = int(s.get("channels") or 0)
    codec_name = s.get("codec_name") or ""
    return {
        "sample_rate": sample_rate,
        "bit_rate": bit_rate,
        "channels": channels,
        "codec_name": codec_name,
    }


def build_measure_cmd(in_path: Path, target: LoudnormTarget) -> list:
    # 量測階段：輸出丟棄到 null，印出 JSON 供第二階段使用
    filt = (
        f"loudnorm=I={target.I}:TP={target.TP}:LRA={target.LRA}:"
        f"print_format=json"
    )
    return [
        "ffmpeg", "-hide_banner", "-nostats", "-y",
        "-i", str(in_path),
        "-vn",
        "-af", filt,
        "-f", "null", "-",
    ]


def parse_measurement(stderr_text: str) -> Dict[str, float]:
    """從 ffmpeg loudnorm stderr 擷取 JSON 區塊並回傳 dict。"""
    start = stderr_text.find("{")
    end = stderr_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("找不到 loudnorm 量測 JSON 輸出；請檢查來源檔是否有音訊")
    j = stderr_text[start : end + 1]
    data = json.loads(j)
    needed = {
        "input_i": float(data["input_i"]),
        "input_tp": float(data["input_tp"]),
        "input_lra": float(data["input_lra"]),
        "input_thresh": float(data["input_thresh"]),
        "target_offset": float(data.get("target_offset", 0.0)),
    }
    return needed


def _encode_args_for(src_info: Dict, keep_channels: bool, target_sr: int) -> list:
    """依來源資訊決定 mp3 編碼參數與取樣率/聲道設定。"""
    audio_args = ["-c:a", "libmp3lame"]

    # 取樣率策略（與原版相同）：
    # - 若輸入是 mp3 且取樣率 == target_sr -> 不更改取樣率（維持原值）
    # - 否則 -> 設定為 target_sr
    set_ar = None
    if src_info.get("codec_name") == "mp3" and src_info.get("sample_rate") == target_sr:
        set_ar = None
    else:
        set_ar = target_sr

    # 位元率策略：
    # - 若是 mp3 並且未更改取樣率 -> 儘量維持原平均位元率（-b:a 指定 kbps）
    # - 其他情況 -> 採用 VBR V4（-q:a 4）
    if set_ar is None:
        if src_info.get("codec_name") == "mp3" and src_info.get("bit_rate", 0) > 0:
            kbps = max(32, int(math.floor(src_info["bit_rate"] / 1000)))
            audio_args += ["-b:a", f"{kbps}k"]
        else:
            audio_args += ["-q:a", "4"]
    else:
        audio_args += ["-q:a", "4", "-ar", str(set_ar)]

    if not keep_channels:
        audio_args += ["-ac", "1"]

    audio_args += ["-id3v2_version", "3"]
    return audio_args


def build_apply_cmd(
    in_path: Path,
    out_path: Path,
    keep_channels: bool,
    target_sr: int,
    src_info: Dict,
    target: LoudnormTarget,
    force_overwrite: bool,
) -> list:
    """建立兩段式 loudnorm 套用階段指令；measured_* 由外層補上。"""
    loudnorm_apply = (
        "loudnorm=I={I}:TP={TP}:LRA={LRA}:"
        "measured_I={mI}:measured_TP={mTP}:measured_LRA={mLRA}:"
        "measured_thresh={mTh}:offset={off}:linear=true"
    ).format(
        I=target.I, TP=target.TP, LRA=target.LRA,
        mI="{mI}", mTP="{mTP}", mLRA="{mLRA}", mTh="{mTh}", off="{off}"
    )

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    cmd += ["-y" if force_overwrite else "-n"]
    cmd += ["-i", str(in_path), "-vn", "-map_metadata", "0"]
    cmd += ["-af", loudnorm_apply]
    cmd += _encode_args_for(src_info, keep_channels, target_sr)
    cmd += [str(out_path)]
    return cmd


def build_singlepass_cmd(
    in_path: Path,
    out_path: Path,
    keep_channels: bool,
    target_sr: int,
    src_info: Dict,
    target: LoudnormTarget,
    force_overwrite: bool,
) -> list:
    """建立單段式 loudnorm 後備方案指令（不需分析 JSON）。"""
    loudnorm_single = f"loudnorm=I={target.I}:TP={target.TP}:LRA={target.LRA}"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    cmd += ["-y" if force_overwrite else "-n"]
    cmd += ["-i", str(in_path), "-vn", "-map_metadata", "0"]
    cmd += ["-af", loudnorm_single]
    cmd += _encode_args_for(src_info, keep_channels, target_sr)
    cmd += [str(out_path)]
    return cmd


def _try_fallback_singlepass(
    in_path: Path,
    out_path: Path,
    keep_channels: bool,
    target_sr: int,
    src_info: Dict,
    target: LoudnormTarget,
) -> Tuple[bool, str]:
    """執行單段式 loudnorm 後備方案；回傳 (ok, detail_message)。"""
    fallback_cmd = build_singlepass_cmd(
        in_path=in_path,
        out_path=out_path,
        keep_channels=keep_channels,
        target_sr=target_sr,
        src_info=src_info,
        target=target,
        force_overwrite=True,  # 後備重試時強制覆寫，避免殘留不完整輸出擋住
    )
    rc, fo, fe = run_cmd(fallback_cmd)
    if rc == 0:
        return True, f"(已使用單段式 loudnorm 後備方案)\n指令：{' '.join(fallback_cmd)}"
    else:
        return False, f"(後備方案失敗)\n指令：{' '.join(fallback_cmd)}\n錯誤：\n{fe.strip()}"


def process_one(
    in_path: Path,
    out_path: Path,
    keep_channels: bool,
    target_sr: int,
    force_overwrite: bool,
    target: LoudnormTarget,
) -> Tuple[str, bool, str]:
    """處理單一檔案。回傳 (相對輸出路徑/檔名, success, message)。"""
    try:
        src = ffprobe_audio_info(in_path)
    except Exception as e:
        return (str(out_path), False, f"ffprobe 失敗：{e}")

    # Pass 1: 測量 loudnorm
    rc1, m_out, m_err = run_cmd(build_measure_cmd(in_path, target))
    if rc1 != 0:
        # 直接嘗試後備方案
        ok, detail = _try_fallback_singlepass(in_path, out_path, keep_channels, target_sr, src, target)
        return (str(out_path), ok, f"兩段式 loudnorm 量測失敗\n{m_err.strip()}\n{detail}")

    try:
        m = parse_measurement(m_err)
    except Exception as e:
        ok, detail = _try_fallback_singlepass(in_path, out_path, keep_channels, target_sr, src, target)
        return (str(out_path), ok, f"解析 loudnorm 量測輸出失敗：{e}\n原始輸出：\n{m_err.strip()}\n{detail}")

    # Pass 2: 套用 loudnorm（帶入量測值）
    apply_cmd = build_apply_cmd(
        in_path=in_path,
        out_path=out_path,
        keep_channels=keep_channels,
        target_sr=target_sr,
        src_info=src,
        target=target,
        force_overwrite=force_overwrite,
    )
    for i, token in enumerate(apply_cmd):
        if isinstance(token, str) and token.startswith("loudnorm="):
            apply_cmd[i] = token.format(
                mI=m["input_i"], mTP=m["input_tp"], mLRA=m["input_lra"],
                mTh=m["input_thresh"], off=m["target_offset"],
            )
            break

    rc2, a_out, a_err = run_cmd(apply_cmd)
    if rc2 != 0:
        ok, detail = _try_fallback_singlepass(in_path, out_path, keep_channels, target_sr, src, target)
        return (str(out_path), ok, f"兩段式 loudnorm 套用/轉檔失敗\n指令：{' '.join(apply_cmd)}\n錯誤：\n{a_err.strip()}\n{detail}")

    return (str(out_path), True, "OK")


def should_process_file(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in SUPPORTED_EXTS


def collect_inputs(input_dir: Path, output_dir: Path) -> Tuple[list, int]:
    """收集需處理的檔案清單 (in_path, out_path) ，並建立對應資料夾。"""
    pairs = []
    for root, dirs, files in os.walk(input_dir):
        dirs[:] = [
            d for d in dirs
            if d != DEFAULT_OUT_DIR_NAME and (Path(root) / d).resolve() != output_dir.resolve()
        ]
        root_path = Path(root)
        for name in files:
            in_path = root_path / name
            if not should_process_file(in_path):
                continue
            rel_parent = in_path.parent.relative_to(input_dir)
            out_parent = output_dir / rel_parent
            out_parent.mkdir(parents=True, exist_ok=True)
            out_path = out_parent / (in_path.stem + ".mp3")
            pairs.append((in_path, out_path))
    return pairs, len(pairs)


def main():
    if not have_ffmpeg() or not have_ffprobe():
        if not have_ffmpeg():
            print("錯誤：找不到 ffmpeg，請先安裝並確認在 PATH 中。", file=sys.stderr)
        if not have_ffprobe():
            print("錯誤：找不到 ffprobe，請先安裝並確認在 PATH 中。", file=sys.stderr)
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        prog="轉音檔_v2_fallback.py",
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "將資料夾內 mp4/mp3/m4a/wav/flac 批次轉為 MP3，先試兩段式 loudnorm，若失敗則自動改用單段式 loudnorm。\n"
            "MP3 取樣率若已符合目標，則不更改取樣率與平均位元率（仍會做標準化）。"
        ),
        epilog=(
            "範例：\n"
            "  # 1) 預設：處理腳本所在資料夾，輸出到 ./已轉換/\n"
            "  python 轉檔v2_fallback.py\n\n"
            "  # 2) 指定輸入與輸出資料夾\n"
            "  python 轉檔v2_fallback.py /path/to/in -o /path/to/out\n\n"
            "  # 3) 保留原聲道（預設會 downmix 單聲道）\n"
            "  python 轉檔v2_fallback.py --stereo\n\n"
            "  # 4) 自訂目標取樣率（預設 32000 Hz）\n"
            "  python 轉檔v2_fallback.py --sample-rate 44100\n\n"
            "  # 5) 指定並行工作數（預設為 CPU 核心數）\n"
            "  python 轉檔v2_fallback.py --workers 8\n\n"
            "  # 6) 乾跑（僅列出分析與轉檔指令）\n"
            "  python 轉檔v2_fallback.py --dry-run\n"
        ),
    )

    parser.add_argument("input_dir", nargs="?", default=str(script_dir), help="輸入資料夾（預設：腳本所在資料夾）")
    parser.add_argument("-o", "--output", default=None, help=f"輸出資料夾（預設：<input_dir>/{DEFAULT_OUT_DIR_NAME}）")
    parser.add_argument("--stereo", "--keep-channels", dest="keep_channels", action="store_true", help="保留原有聲道（預設：單聲道 downmix）")
    parser.add_argument("--force", action="store_true", help="若輸出檔已存在，強制覆寫（預設：略過已存在檔案）")
    parser.add_argument("--dry-run", action="store_true", help="僅顯示將執行的指令，不實際進行轉檔")
    parser.add_argument("--sample-rate", type=int, default=32000, help="目標取樣率（Hz），預設 32000")
    parser.add_argument("--workers", type=int, default=0, help="並行處理的工作數（0=自動）")
    parser.add_argument("--I", type=float, default=-14.0, help="loudnorm 目標整體響度 (LUFS)；預設 -14")
    parser.add_argument("--TP", type=float, default=-1.5, help="loudnorm 目標真峰值 (dBTP)；預設 -1.5")
    parser.add_argument("--LRA", type=float, default=11.0, help="loudnorm 目標動態範圍 (LRA)；預設 11")

    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"錯誤：輸入路徑不存在或不是資料夾：{input_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output).resolve() if args.output else (input_dir / DEFAULT_OUT_DIR_NAME).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    target = LoudnormTarget(I=args.I, TP=args.TP, LRA=args.LRA)

    pairs, total = collect_inputs(input_dir, output_dir)
    if total == 0:
        print("沒有可處理的檔案。支援：.mp4 .mp3 .m4a .wav .flac")
        return

    print("=== 設定 ===")
    print(f"輸入資料夾：{input_dir}")
    print(f"輸出資料夾：{output_dir}")
    print(f"聲道處理：{'保留原聲道' if args.keep_channels else '單聲道 (mono)'}")
    print(f"loudnorm 目標：I={target.I} LUFS, TP={target.TP} dB, LRA={target.LRA}")
    print(f"目標取樣率：{args.sample_rate} Hz（僅在需要時更改 MP3 的取樣率）")
    print(f"覆寫策略：{'強制覆寫' if args.force else '已存在則略過'}")
    print(f"並行工作數：{args.workers if args.workers>0 else os.cpu_count() or 1}")
    print(f"模式：{'乾跑' if args.dry_run else '實際轉檔'}\n")

    if args.dry_run:
        # 僅展示將會跑的指令（以第一個檔案示意）
        sample = pairs[0]
        try:
            info = ffprobe_audio_info(sample[0])
        except Exception as e:
            print(f"[DRY-RUN] ffprobe 失敗：{e}")
            return
        print("[DRY-RUN] 兩段式量測指令：", " ".join(build_measure_cmd(sample[0], target)))
        dummy_apply = build_apply_cmd(sample[0], sample[1], args.keep_channels, args.sample_rate, info, target, True)
        print("[DRY-RUN] 兩段式套用指令（值將以量測結果替換）：", " ".join(dummy_apply))
        dummy_fallback = build_singlepass_cmd(sample[0], sample[1], args.keep_channels, args.sample_rate, info, target, True)
        print("[DRY-RUN] 後備（單段式 loudnorm）指令：", " ".join(dummy_fallback))
        return

    # 去除已存在且不覆寫的項目
    todo = []
    skipped = 0
    for in_path, out_path in pairs:
        if out_path.exists() and not args.force:
            skipped += 1
            continue
        todo.append((in_path, out_path))

    succeeded = 0
    failed = 0
    error_logs = []

    workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                process_one,
                in_path,
                out_path,
                args.keep_channels,
                args.sample_rate,
                args.force,
                target,
            ): (in_path, out_path)
            for (in_path, out_path) in todo
        }
        for fut in tqdm(as_completed(futures), total=len(futures), desc="轉檔中", unit="檔"):
            try:
                out_rel, ok, msg = fut.result()
                if ok:
                    succeeded += 1
                else:
                    failed += 1
                    error_logs.append(f"[FAIL] {out_rel}\n{msg}\n")
            except Exception as e:
                failed += 1
                pair = futures[fut]
                error_logs.append(f"[EXC] {pair[0]} -> {pair[1]}\n{e}\n")

    print("\n=== 結果 ===")
    print(f"總計檔案：{total}")
    print(f"待處理：{len(todo)} ；略過（已存在且未 --force）：{skipped}")
    print(f"成功轉檔：{succeeded}")
    print(f"失敗檔案：{failed}")

    if error_logs:
        print("\n=== 失敗/錯誤詳細 ===")
        for log in error_logs:
            print(log)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中斷。", file=sys.stderr)
        sys.exit(130)

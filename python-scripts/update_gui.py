#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音效處理一條龍 GUI
========================================
整合並升級「流程1_clean_convert_json.py」與「流程2_生成uuid.py」。

流程（皆可單獨執行，也可一鍵全跑）：
  1. 檔名清理   ── 就地整理輸入資料夾的檔名（_ → -、合併方括弧、去空白…）
  2. 轉檔        ── 用 ffmpeg loudnorm 把音檔批次轉成標準化 MP3 到輸出資料夾
  3. 生成 JSON   ── 解析輸出資料夾的 MP3 檔名為 title / tags
  4. 產生 UUID   ── 用 ufid64 為每筆資料計算決定性 id
  5. 更新 JSON   ── 把 config/sounds.json 備份成 sounds-old.json，
                    再把新音效資料併入 sounds.json

特色：
  - 可即時檢視「檔名變更（原→新）」、「解析結果（file / title / tags / id）」
  - 更新前可預覽哪些是「新增」、哪些是「重複」
  - 直接重用既有腳本的核心函式（檔名清理 / JSON生成 / ufid64），轉檔則以子行程呼叫 轉檔v3.py

依賴：標準函式庫 + tkinter；轉檔步驟需要系統的 ffmpeg/ffprobe 與 轉檔v3.py 所需的 tqdm。
"""

import os
import sys
import copy
import json
import queue
import shutil
import threading
import importlib.util
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "update_gui.json"
DEFAULT_SOUNDS = (SCRIPT_DIR.parent / "config" / "sounds.json")
DEFAULT_SOUNDS_DIR = (SCRIPT_DIR.parent / "sounds")  # 既有音檔實體所在
SOUNDS_INDENT = 4  # 與現有 config/sounds.json 一致


# --------------------------------------------------------------------------- #
#  動態載入既有腳本（檔名含中文，用 importlib 依路徑載入）
# --------------------------------------------------------------------------- #
def _load_module(filename: str, alias: str):
    path = SCRIPT_DIR / filename
    if not path.exists():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _try_load(filename: str, alias: str):
    try:
        return _load_module(filename, alias)
    except Exception as e:  # noqa: BLE001
        print(f"[警告] 無法載入 {filename}：{e}")
        return None


mod_clean = _try_load("檔名清理.py", "mod_clean")     # transform_filename()
mod_json = _try_load("JSON生成v3.py", "mod_json")      # build_index()
mod_uuid = _try_load("ufid64.py", "mod_uuid")          # ufid(), assign_ids_strict()


# --------------------------------------------------------------------------- #
#  設定檔
# --------------------------------------------------------------------------- #
def load_settings() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def save_settings(data: dict) -> None:
    try:
        CONFIG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        print(f"[警告] 無法寫入設定：{e}")


# --------------------------------------------------------------------------- #
#  核心邏輯（與 GUI 解耦，皆接受 log 回呼）
# --------------------------------------------------------------------------- #
def clean_filenames(input_dir: Path, log) -> list:
    """就地清理 input_dir 第一層的檔名。回傳 [(old, new), ...]。"""
    if mod_clean is None:
        raise RuntimeError("檔名清理.py 未載入，無法執行清理。")
    changes = []
    for p in sorted(input_dir.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        new_name = mod_clean.transform_filename(p.name)
        if new_name == p.name:
            continue
        dst = p.with_name(new_name)
        if dst.exists() and dst.resolve() != p.resolve():
            log(f"[跳過] 目標已存在：{dst.name}")
            continue
        try:
            p.rename(dst)
            log(f"[更名] {p.name}  →  {dst.name}")
            changes.append((p.name, dst.name))
        except Exception as e:  # noqa: BLE001
            log(f"[失敗] {p.name} → {dst.name}：{e}")
    if not changes:
        log("沒有需要更名的檔案。")
    return changes


def build_convert_cmd(input_dir: Path, output_dir: Path, opts: dict) -> list:
    cmd = [sys.executable, str(SCRIPT_DIR / "轉檔v3.py"),
           "-i", str(input_dir), "-o", str(output_dir)]
    if opts.get("recursive"):
        cmd.append("--recursive")
    if opts.get("keep_channels"):
        cmd.append("--stereo")
    if opts.get("force"):
        cmd.append("--force")
    cmd += ["--sample-rate", str(opts.get("sample_rate", 32000))]
    if opts.get("workers", 0):
        cmd += ["--workers", str(opts["workers"])]
    cmd += ["--I", str(opts.get("I", -14.0)),
            "--TP", str(opts.get("TP", -1.5)),
            "--LRA", str(opts.get("LRA", 11.0))]
    return cmd


def run_convert(input_dir: Path, output_dir: Path, opts: dict, log,
                cancel_event: threading.Event) -> int:
    """以子行程呼叫 轉檔v3.py，串流輸出到 log。回傳結束碼。"""
    script = SCRIPT_DIR / "轉檔v3.py"
    if not script.exists():
        raise RuntimeError(f"找不到 轉檔v3.py：{script}")
    cmd = build_convert_cmd(input_dir, output_dir, opts)
    log("執行：" + " ".join(f'"{c}"' if " " in c else c for c in cmd))

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "UTF-8"

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    try:
        for line in proc.stdout:
            if cancel_event.is_set():
                proc.terminate()
                log("[中斷] 已要求停止轉檔。")
                break
            log(line.rstrip("\n"))
    finally:
        proc.stdout.close()
        proc.wait()
    return proc.returncode


def generate_index(output_dir: Path, log) -> list:
    """解析輸出資料夾的 MP3 檔名 → [{file, title, tags}]。"""
    if mod_json is None:
        raise RuntimeError("JSON生成v3.py 未載入，無法生成索引。")
    data = mod_json.build_index(str(output_dir))
    log(f"解析完成：共 {len(data)} 筆 MP3。")
    return data


def assign_uuids(entries: list, opts: dict, log) -> list:
    """為 entries 計算 id（k=0，與 ufid64 預設一致）。回傳新 list。"""
    if mod_uuid is None:
        raise RuntimeError("ufid64.py 未載入，無法產生 UUID。")
    nbytes = int(opts.get("nbytes", 4))
    namespace = opts.get("namespace") or None
    out = []
    for e in entries:
        e = dict(e)
        f = e.get("file")
        if isinstance(f, str) and f:
            e["id"] = mod_uuid.ufid(f, namespace, 0, "nfkc", True, True, nbytes)
        out.append(e)
    log(f"已產生 {len(out)} 筆 id（bytes={nbytes}, namespace={namespace or '(無)'}）。")
    return out


# --------------------------------------------------------------------------- #
#  音效試聽（優先用 ffplay，沒有則退回系統預設播放器）
# --------------------------------------------------------------------------- #
class AudioPlayer:
    def __init__(self):
        self.ffplay = shutil.which("ffplay")
        self.proc: subprocess.Popen | None = None

    def play(self, path: Path):
        path = Path(path)
        if not path.exists():
            raise RuntimeError(f"找不到音檔：{path}")
        self.stop()
        if self.ffplay:
            self.proc = subprocess.Popen(
                [self.ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # 後備：交給作業系統預設播放器（無法由本程式停止）
            try:
                os.startfile(str(path))  # type: ignore[attr-defined]  # Windows
            except AttributeError:
                subprocess.Popen(["xdg-open", str(path)])

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        self.proc = None


ACTION_LABEL = {"skip": "略過", "overwrite": "覆寫", "rename": "重新命名"}


def suggest_rename(file: str, taken: set) -> str:
    """為衝突檔名建議一個未被占用的新名（stem-2.mp3、-3…）。"""
    stem, ext = os.path.splitext(file)
    n = 2
    while True:
        cand = f"{stem}-{n}{ext or '.mp3'}"
        if cand not in taken:
            return cand
        n += 1


# --------------------------------------------------------------------------- #
#  重複衝突處理對話框（可試聽、逐筆選擇處理方式）
# --------------------------------------------------------------------------- #
class ConflictDialog(tk.Toplevel):
    def __init__(self, parent, conflicts, existing_by_file, player,
                 sounds_dir: Path, output_dir: Path):
        super().__init__(parent)
        self.title("處理重複衝突")
        self.geometry("860x520")
        self.transient(parent)
        self.conflicts = conflicts                # list of new entries (dict)
        self.existing_by_file = existing_by_file  # file -> existing entry
        self.player = player
        self.sounds_dir = sounds_dir
        self.output_dir = output_dir
        self.result = None                        # file -> {action,new_file}

        taken = set(existing_by_file.keys())
        self.resolutions = {}
        for c in conflicts:
            f = c.get("file")
            self.resolutions[f] = {"action": "skip", "new_file": suggest_rename(f, taken)}

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        if conflicts:
            self.tv.selection_set(self.tv.get_children()[0])
        self.wait_window()

    # ---- UI ---- #
    def _build(self):
        hint = ttk.Label(
            self, foreground="#555",
            text="逐筆選擇處理方式：略過＝不加入；覆寫＝以新資料取代既有；"
                 "重新命名＝改新檔名後當作新音效加入（會實際更名輸出資料夾的檔案）。")
        hint.pack(fill="x", padx=10, pady=(8, 0))

        pan = ttk.Panedwindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True, padx=10, pady=8)

        left = ttk.Frame(pan)
        pan.add(left, weight=1)
        cols = ("file", "action")
        tv = ttk.Treeview(left, columns=cols, show="headings")
        tv.heading("file", text="衝突檔名")
        tv.heading("action", text="處理方式")
        tv.column("file", width=300)
        tv.column("action", width=120)
        ys = ttk.Scrollbar(left, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        tv.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        tv.bind("<<TreeviewSelect>>", self._on_select)
        self.tv = tv
        for c in self.conflicts:
            f = c.get("file")
            tv.insert("", "end", iid=f, values=(f, ACTION_LABEL["skip"]))

        right = ttk.Frame(pan)
        pan.add(right, weight=2)

        self.lbl_file = ttk.Label(right, text="", font=("", 10, "bold"))
        self.lbl_file.pack(fill="x", padx=6, pady=(2, 6))

        ex = ttk.LabelFrame(right, text="既有（sounds.json）")
        ex.pack(fill="x", padx=6, pady=4)
        self.lbl_ex = ttk.Label(ex, text="", justify="left")
        self.lbl_ex.pack(side="left", fill="x", expand=True, padx=6, pady=4)
        ttk.Button(ex, text="▶ 試聽舊", command=self._play_old).pack(side="right", padx=6)

        nw = ttk.LabelFrame(right, text="新檔（本次解析）")
        nw.pack(fill="x", padx=6, pady=4)
        self.lbl_nw = ttk.Label(nw, text="", justify="left")
        self.lbl_nw.pack(side="left", fill="x", expand=True, padx=6, pady=4)
        ttk.Button(nw, text="▶ 試聽新", command=self._play_new).pack(side="right", padx=6)

        ttk.Button(right, text="■ 停止試聽", command=self.player.stop).pack(anchor="w", padx=6, pady=(0, 6))

        act = ttk.LabelFrame(right, text="處理方式")
        act.pack(fill="x", padx=6, pady=4)
        self.var_action = tk.StringVar(value="skip")
        for val in ("skip", "overwrite", "rename"):
            ttk.Radiobutton(act, text=ACTION_LABEL[val], value=val,
                            variable=self.var_action,
                            command=self._on_action_change).pack(anchor="w", padx=8, pady=1)
        rn = ttk.Frame(act)
        rn.pack(fill="x", padx=8, pady=(2, 6))
        ttk.Label(rn, text="新檔名：").pack(side="left")
        self.var_newname = tk.StringVar()
        self.ent_newname = ttk.Entry(rn, textvariable=self.var_newname)
        self.ent_newname.pack(side="left", fill="x", expand=True)
        self.var_newname.trace_add("write", lambda *_: self._save_current())

        btm = ttk.Frame(self)
        btm.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btm, text="全部略過", command=lambda: self._apply_all("skip")).pack(side="left")
        ttk.Button(btm, text="全部覆寫", command=lambda: self._apply_all("overwrite")).pack(side="left", padx=4)
        ttk.Button(btm, text="取消", command=self._cancel).pack(side="right")
        ttk.Button(btm, text="確定", command=self._ok).pack(side="right", padx=4)

    # ---- 狀態 ---- #
    def _current_file(self):
        sel = self.tv.selection()
        return sel[0] if sel else None

    def _on_select(self, _=None):
        f = self._current_file()
        if f is None:
            return
        new = next((c for c in self.conflicts if c.get("file") == f), {})
        old = self.existing_by_file.get(f, {})
        self.lbl_file.configure(text=f"衝突檔名：{f}")
        self.lbl_ex.configure(text=self._fmt(old))
        self.lbl_nw.configure(text=self._fmt(new))
        res = self.resolutions[f]
        self.var_action.set(res["action"])
        self.var_newname.set(res["new_file"])
        self._sync_rename_state()

    @staticmethod
    def _fmt(entry: dict) -> str:
        if not entry:
            return "(無)"
        return (f"title：{entry.get('title', '')}\n"
                f"tags：{', '.join(entry.get('tags', []))}\n"
                f"id：{entry.get('id', '')}")

    def _sync_rename_state(self):
        self.ent_newname.configure(
            state="normal" if self.var_action.get() == "rename" else "disabled")

    def _on_action_change(self):
        self._sync_rename_state()
        self._save_current()

    def _save_current(self):
        f = self._current_file()
        if f is None:
            return
        self.resolutions[f]["action"] = self.var_action.get()
        self.resolutions[f]["new_file"] = self.var_newname.get().strip()
        label = ACTION_LABEL[self.var_action.get()]
        if self.var_action.get() == "rename":
            label += f" → {self.var_newname.get().strip()}"
        self.tv.set(f, "action", label)

    def _apply_all(self, action: str):
        for f in self.resolutions:
            self.resolutions[f]["action"] = action
            label = ACTION_LABEL[action]
            if action == "rename":
                label += f" → {self.resolutions[f]['new_file']}"
            self.tv.set(f, "action", label)
        cur = self._current_file()
        if cur:
            self.var_action.set(action)
            self._sync_rename_state()

    def _play_old(self):
        f = self._current_file()
        if f:
            self._safe_play(self.sounds_dir / f)

    def _play_new(self):
        f = self._current_file()
        if f:
            self._safe_play(self.output_dir / f)

    def _safe_play(self, path: Path):
        try:
            self.player.play(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showwarning("無法試聽", str(e), parent=self)

    def _ok(self):
        self._save_current()
        # 驗證重新命名目標
        taken = set(self.existing_by_file.keys())
        rename_targets = set()
        for f, res in self.resolutions.items():
            if res["action"] != "rename":
                continue
            nf = res["new_file"]
            if not nf:
                messagebox.showwarning("檢查", f"{f}：新檔名不可為空。", parent=self)
                return
            if not nf.lower().endswith(".mp3"):
                messagebox.showwarning("檢查", f"{f}：新檔名需以 .mp3 結尾。", parent=self)
                return
            if nf in taken or nf in rename_targets:
                messagebox.showwarning("檢查", f"新檔名重複：{nf}", parent=self)
                return
            rename_targets.add(nf)
        self.result = self.resolutions
        self.player.stop()
        self.destroy()

    def _cancel(self):
        self.player.stop()
        self.result = None
        self.destroy()


# --------------------------------------------------------------------------- #
#  GUI
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None

        self.entries: list = []        # 解析 + uuid 後的資料
        self.rename_changes: list = []  # (old, new)
        self.player = AudioPlayer()

        root.title("音效處理工具 — 清理 ▸ 轉檔 ▸ JSON ▸ UUID ▸ 更新")
        root.geometry("980x720")
        root.minsize(820, 600)

        self._build_vars()
        self._build_paths()
        self._build_notebook()
        self._build_statusbar()

        self.root.after(120, self._drain_log)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- 變數 -------------------------------------------------------------- #
    def _build_vars(self):
        s = self.settings
        self.var_in = tk.StringVar(value=s.get("input", ""))
        self.var_out = tk.StringVar(value=s.get("output", ""))
        self.var_sounds = tk.StringVar(value=s.get("sounds", str(DEFAULT_SOUNDS)))
        self.var_sounds_dir = tk.StringVar(value=s.get("sounds_dir", str(DEFAULT_SOUNDS_DIR)))

        self.var_recursive = tk.BooleanVar(value=s.get("recursive", False))
        self.var_keep_channels = tk.BooleanVar(value=s.get("keep_channels", False))
        self.var_force = tk.BooleanVar(value=s.get("force", False))
        self.var_sr = tk.StringVar(value=str(s.get("sample_rate", 32000)))
        self.var_workers = tk.StringVar(value=str(s.get("workers", 0)))
        self.var_I = tk.StringVar(value=str(s.get("I", -14.0)))
        self.var_TP = tk.StringVar(value=str(s.get("TP", -1.5)))
        self.var_LRA = tk.StringVar(value=str(s.get("LRA", 11.0)))

        self.var_nbytes = tk.StringVar(value=str(s.get("nbytes", 4)))
        self.var_namespace = tk.StringVar(value=s.get("namespace", ""))
        self.var_overwrite_dup = tk.BooleanVar(value=s.get("overwrite_dup", False))

    # ---- 路徑列 ------------------------------------------------------------ #
    def _build_paths(self):
        frm = ttk.LabelFrame(self.root, text="路徑")
        frm.pack(fill="x", padx=10, pady=(10, 4))
        frm.columnconfigure(1, weight=1)

        def row(r, label, var, browse):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=4)
            ttk.Entry(frm, textvariable=var).grid(row=r, column=1, sticky="ew", padx=4, pady=4)
            ttk.Button(frm, text="瀏覽…", command=browse).grid(row=r, column=2, padx=6, pady=4)

        row(0, "輸入資料夾（原始音檔）", self.var_in, self._pick_in)
        row(1, "輸出資料夾（轉檔結果）", self.var_out, self._pick_out)
        row(2, "sounds.json", self.var_sounds, self._pick_sounds)
        row(3, "音檔資料夾（既有 sounds，供試聽）", self.var_sounds_dir, self._pick_sounds_dir)

    def _pick_sounds_dir(self):
        d = filedialog.askdirectory(title="選擇既有音檔資料夾",
                                    initialdir=self.var_sounds_dir.get() or ".")
        if d:
            self.var_sounds_dir.set(d)

    def _pick_in(self):
        d = filedialog.askdirectory(title="選擇輸入資料夾", initialdir=self.var_in.get() or ".")
        if d:
            self.var_in.set(d)

    def _pick_out(self):
        d = filedialog.askdirectory(title="選擇輸出資料夾", initialdir=self.var_out.get() or ".")
        if d:
            self.var_out.set(d)

    def _pick_sounds(self):
        f = filedialog.askopenfilename(
            title="選擇 sounds.json", initialdir=str(Path(self.var_sounds.get() or ".").parent),
            filetypes=[("JSON", "*.json"), ("所有檔案", "*.*")])
        if f:
            self.var_sounds.set(f)

    # ---- Notebook ---------------------------------------------------------- #
    def _build_notebook(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=4)
        self.nb = nb
        self._tab_run(nb)
        self._tab_renames(nb)
        self._tab_results(nb)
        self._tab_update(nb)

    # --- Tab 1：執行流程 --- #
    def _tab_run(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="執行流程")

        # 選項
        opt = ttk.LabelFrame(tab, text="轉檔選項")
        opt.pack(fill="x", padx=6, pady=6)
        ttk.Checkbutton(opt, text="遞迴子資料夾", variable=self.var_recursive).grid(row=0, column=0, sticky="w", padx=6, pady=3)
        ttk.Checkbutton(opt, text="保留原聲道（預設轉單聲道）", variable=self.var_keep_channels).grid(row=0, column=1, sticky="w", padx=6, pady=3)
        ttk.Checkbutton(opt, text="覆寫已存在輸出", variable=self.var_force).grid(row=0, column=2, sticky="w", padx=6, pady=3)

        def num(parent, label, var, r, c, width=7):
            ttk.Label(parent, text=label).grid(row=r, column=c, sticky="e", padx=(12, 2), pady=3)
            ttk.Entry(parent, textvariable=var, width=width).grid(row=r, column=c + 1, sticky="w", pady=3)

        num(opt, "取樣率", self.var_sr, 1, 0)
        num(opt, "並行數(0=自動)", self.var_workers, 1, 2)
        num(opt, "I(LUFS)", self.var_I, 2, 0)
        num(opt, "TP(dB)", self.var_TP, 2, 2)
        num(opt, "LRA", self.var_LRA, 2, 4)

        idopt = ttk.LabelFrame(tab, text="UUID 選項")
        idopt.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(idopt, text="id 長度(bytes)").grid(row=0, column=0, sticky="e", padx=6, pady=3)
        ttk.Combobox(idopt, textvariable=self.var_nbytes, values=["4", "8", "16"],
                     width=5, state="readonly").grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(idopt, text="namespace(選填)").grid(row=0, column=2, sticky="e", padx=12, pady=3)
        ttk.Entry(idopt, textvariable=self.var_namespace, width=24).grid(row=0, column=3, sticky="w", pady=3)

        # 按鈕
        btns = ttk.Frame(tab)
        btns.pack(fill="x", padx=6, pady=4)
        self.buttons = {}
        specs = [
            ("clean", "1. 檔名清理", self.do_clean),
            ("convert", "2. 轉檔", self.do_convert),
            ("json", "3. 生成 JSON", self.do_json),
            ("uuid", "4. 產生 UUID", self.do_uuid),
            ("all", "▶ 一鍵全部執行", self.do_all),
        ]
        for i, (key, text, cmd) in enumerate(specs):
            b = ttk.Button(btns, text=text, command=cmd)
            b.grid(row=0, column=i, padx=4, pady=2, sticky="ew")
            btns.columnconfigure(i, weight=1)
            self.buttons[key] = b
        self.btn_cancel = ttk.Button(btns, text="■ 停止", command=self._cancel, state="disabled")
        self.btn_cancel.grid(row=0, column=len(specs), padx=4)

        # log
        logf = ttk.LabelFrame(tab, text="執行紀錄")
        logf.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text = tk.Text(logf, wrap="word", height=12, state="disabled",
                                font=("Consolas", 9))
        ys = ttk.Scrollbar(logf, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=ys.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")

    # --- Tab 2：檔名變更 --- #
    def _tab_renames(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="檔名變更")
        cols = ("old", "new")
        tv = ttk.Treeview(tab, columns=cols, show="headings")
        tv.heading("old", text="原檔名")
        tv.heading("new", text="新檔名")
        tv.column("old", width=420)
        tv.column("new", width=420)
        ys = ttk.Scrollbar(tab, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        tv.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        ys.pack(side="right", fill="y", pady=6)
        self.tv_renames = tv

    # --- Tab 3：解析結果 --- #
    def _tab_results(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="解析結果")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(bar, text="▶ 試聽選取", command=self._play_selected_result).pack(side="left")
        ttk.Button(bar, text="■ 停止", command=self.player.stop).pack(side="left", padx=(4, 12))
        ttk.Button(bar, text="匯出此結果為 JSON…", command=self._export_results).pack(side="left")
        self.lbl_results = ttk.Label(bar, text="尚無資料")
        self.lbl_results.pack(side="left", padx=12)
        ttk.Label(bar, text="（雙擊 title / tags 編輯；tags 以逗號分隔）",
                  foreground="#666").pack(side="right")

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("id", "file", "title", "tags")
        tv = ttk.Treeview(body, columns=cols, show="headings")
        for c, t, w in [("id", "id", 90), ("file", "file", 320),
                        ("title", "title", 260), ("tags", "tags", 200)]:
            tv.heading(c, text=t)
            tv.column(c, width=w)
        ys = ttk.Scrollbar(body, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        tv.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tv_results = tv
        self._results_editor = None
        tv.bind("<Double-1>", self._edit_results_cell)

    # --- 解析結果：行內編輯 title / tags --- #
    EDITABLE_COLS = ("title", "tags")

    def _edit_results_cell(self, event):
        tv = self.tv_results
        self._destroy_results_editor()
        if tv.identify_region(event.x, event.y) != "cell":
            return
        row = tv.identify_row(event.y)
        col = tv.identify_column(event.x)  # e.g. '#3'
        if not row or not col:
            return
        col_idx = int(col[1:]) - 1
        col_name = tv["columns"][col_idx]
        if col_name not in self.EDITABLE_COLS:
            return
        try:
            entry_idx = int(row)
        except ValueError:
            return
        if not (0 <= entry_idx < len(self.entries)):
            return

        x, y, w, h = tv.bbox(row, col)
        cur = tv.set(row, col_name)
        ed = tk.Entry(tv)
        ed.insert(0, cur)
        ed.select_range(0, "end")
        ed.focus_set()
        ed.place(x=x, y=y, width=w, height=h)
        self._results_editor = ed

        def commit(_=None):
            if self._results_editor is None:
                return
            new_val = ed.get()
            self._apply_results_edit(entry_idx, col_name, new_val)
            self._destroy_results_editor()

        ed.bind("<Return>", commit)
        ed.bind("<FocusOut>", commit)
        ed.bind("<Escape>", lambda _e: self._destroy_results_editor())

    def _destroy_results_editor(self):
        if self._results_editor is not None:
            self._results_editor.destroy()
            self._results_editor = None

    def _apply_results_edit(self, entry_idx, col_name, new_val):
        """把編輯結果寫回 self.entries[entry_idx]，並刷新該列顯示。"""
        entry = self.entries[entry_idx]
        if col_name == "title":
            entry["title"] = new_val.strip()
        elif col_name == "tags":
            entry["tags"] = [t.strip() for t in new_val.split(",") if t.strip()]
        # 更新顯示（tags 以正規化後的逗號分隔重新呈現）
        tv = self.tv_results
        row = str(entry_idx)
        tv.set(row, "title", entry.get("title", ""))
        tv.set(row, "tags", ", ".join(entry.get("tags", [])))
        self.log(f"[編輯] {entry.get('file', '')} 的 {col_name} → "
                 f"{entry.get(col_name) if col_name == 'title' else ', '.join(entry.get('tags', []))}")

    # --- Tab 4：更新 sounds.json --- #
    def _tab_update(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="更新 sounds.json")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Button(top, text="預覽差異", command=self.preview_merge).pack(side="left")
        ttk.Checkbutton(top, text="覆寫重複項（以新資料取代）",
                        variable=self.var_overwrite_dup).pack(side="left", padx=12)
        ttk.Button(top, text="✔ 更新 JSON（備份後寫入）",
                   command=self.do_update_json).pack(side="left", padx=4)
        self.lbl_merge = ttk.Label(tab, text="按「預覽差異」檢視將新增 / 重複的項目。")
        self.lbl_merge.pack(fill="x", padx=8)

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("status", "id", "file", "title", "tags")
        tv = ttk.Treeview(body, columns=cols, show="headings")
        for c, t, w in [("status", "狀態", 70), ("id", "id", 90),
                        ("file", "file", 300), ("title", "title", 240),
                        ("tags", "tags", 160)]:
            tv.heading(c, text=t)
            tv.column(c, width=w)
        ys = ttk.Scrollbar(body, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        tv.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        tv.tag_configure("new", background="#e6ffe6")
        tv.tag_configure("dup", background="#fff2e6")
        self.tv_merge = tv

    # ---- 狀態列 ------------------------------------------------------------ #
    def _build_statusbar(self):
        self.status = tk.StringVar(value="就緒")
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", side="bottom")
        ttk.Separator(bar, orient="horizontal").pack(fill="x")
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(fill="x", padx=10, pady=3)

    # ------------------------------------------------------------------ #
    #  log / 執行緒工具
    # ------------------------------------------------------------------ #
    def log(self, msg: str):
        self.log_queue.put(str(msg))

    def _drain_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_log)

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        for b in self.buttons.values():
            b.configure(state=state)
        self.btn_cancel.configure(state="normal" if busy else "disabled")
        self.status.set("執行中…" if busy else "就緒")

    def _run_async(self, target):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("忙碌中", "有工作正在執行，請稍候。")
            return
        self.cancel_event.clear()
        self._set_busy(True)

        def wrapped():
            try:
                target()
            except Exception as e:  # noqa: BLE001
                self.log(f"[錯誤] {e}")
                self.root.after(0, lambda: messagebox.showerror("錯誤", str(e)))
            finally:
                self.root.after(0, lambda: self._set_busy(False))

        self.worker = threading.Thread(target=wrapped, daemon=True)
        self.worker.start()

    def _cancel(self):
        self.cancel_event.set()
        self.log("[中斷] 已要求停止…")

    # ------------------------------------------------------------------ #
    #  驗證 / 設定
    # ------------------------------------------------------------------ #
    def _collect_opts(self) -> dict:
        def f(var, default):
            try:
                return float(var.get())
            except ValueError:
                return default

        def i(var, default):
            try:
                return int(float(var.get()))
            except ValueError:
                return default

        return {
            "recursive": self.var_recursive.get(),
            "keep_channels": self.var_keep_channels.get(),
            "force": self.var_force.get(),
            "sample_rate": i(self.var_sr, 32000),
            "workers": i(self.var_workers, 0),
            "I": f(self.var_I, -14.0),
            "TP": f(self.var_TP, -1.5),
            "LRA": f(self.var_LRA, 11.0),
            "nbytes": i(self.var_nbytes, 4),
            "namespace": self.var_namespace.get().strip(),
        }

    def _persist(self):
        o = self._collect_opts()
        o.update({
            "input": self.var_in.get(),
            "output": self.var_out.get(),
            "sounds": self.var_sounds.get(),
            "sounds_dir": self.var_sounds_dir.get(),
            "overwrite_dup": self.var_overwrite_dup.get(),
        })
        save_settings(o)

    def _need_dir(self, var, label) -> Path:
        p = var.get().strip()
        if not p:
            raise RuntimeError(f"請先指定{label}。")
        path = Path(p)
        if not path.exists() or not path.is_dir():
            raise RuntimeError(f"{label}不存在或不是資料夾：{path}")
        return path

    # ------------------------------------------------------------------ #
    #  動作
    # ------------------------------------------------------------------ #
    def do_clean(self):
        self._persist()

        def task():
            in_dir = self._need_dir(self.var_in, "輸入資料夾")
            self.log("\n=== 1. 檔名清理 ===")
            changes = clean_filenames(in_dir, self.log)
            self.rename_changes = changes
            self.root.after(0, self._refresh_renames)

        self._run_async(task)

    def do_convert(self):
        self._persist()

        def task():
            in_dir = self._need_dir(self.var_in, "輸入資料夾")
            out = self.var_out.get().strip()
            if not out:
                raise RuntimeError("請先指定輸出資料夾。")
            out_dir = Path(out)
            out_dir.mkdir(parents=True, exist_ok=True)
            self.log("\n=== 2. 轉檔 ===")
            rc = run_convert(in_dir, out_dir, self._collect_opts(), self.log, self.cancel_event)
            if rc != 0:
                raise RuntimeError(f"轉檔結束碼非 0：{rc}")
            self.log("[完成] 轉檔。")

        self._run_async(task)

    def do_json(self):
        self._persist()

        def task():
            out_dir = self._need_dir(self.var_out, "輸出資料夾")
            self.log("\n=== 3. 生成 JSON ===")
            data = generate_index(out_dir, self.log)
            self.entries = data
            self.root.after(0, self._refresh_results)

        self._run_async(task)

    def do_uuid(self):
        self._persist()

        def task():
            if not self.entries:
                out_dir = self._need_dir(self.var_out, "輸出資料夾")
                self.log("（尚未生成索引，先自動執行生成 JSON）")
                self.entries = generate_index(out_dir, self.log)
            self.log("\n=== 4. 產生 UUID ===")
            self.entries = assign_uuids(self.entries, self._collect_opts(), self.log)
            self.root.after(0, self._refresh_results)

        self._run_async(task)

    def do_all(self):
        self._persist()

        def task():
            in_dir = self._need_dir(self.var_in, "輸入資料夾")
            out = self.var_out.get().strip()
            if not out:
                raise RuntimeError("請先指定輸出資料夾。")
            out_dir = Path(out)
            out_dir.mkdir(parents=True, exist_ok=True)
            opts = self._collect_opts()

            self.log("\n=== 1. 檔名清理 ===")
            self.rename_changes = clean_filenames(in_dir, self.log)
            self.root.after(0, self._refresh_renames)
            if self.cancel_event.is_set():
                return

            self.log("\n=== 2. 轉檔 ===")
            rc = run_convert(in_dir, out_dir, opts, self.log, self.cancel_event)
            if rc != 0:
                raise RuntimeError(f"轉檔結束碼非 0：{rc}")
            if self.cancel_event.is_set():
                return

            self.log("\n=== 3. 生成 JSON ===")
            data = generate_index(out_dir, self.log)

            self.log("\n=== 4. 產生 UUID ===")
            self.entries = assign_uuids(data, opts, self.log)
            self.root.after(0, self._refresh_results)
            self.log("\n[完成] 1~4 步驟。請至「更新 sounds.json」分頁預覽並寫入。")

        self._run_async(task)

    # ------------------------------------------------------------------ #
    #  更新 sounds.json
    # ------------------------------------------------------------------ #
    def _load_sounds(self) -> tuple[Path, list]:
        p = Path(self.var_sounds.get().strip())
        if not p.exists():
            raise RuntimeError(f"找不到 sounds.json：{p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise RuntimeError("sounds.json 最外層必須是陣列。")
        return p, data

    def _compute_merge(self):
        """回傳 (existing, new_entries, dup_entries)。"""
        if not self.entries:
            raise RuntimeError("尚無解析結果，請先執行步驟 1~4。")
        _, existing = self._load_sounds()
        existing_files = {e.get("file") for e in existing if isinstance(e, dict)}
        new_entries, dup_entries = [], []
        for e in self.entries:
            if e.get("file") in existing_files:
                dup_entries.append(e)
            else:
                new_entries.append(e)
        return existing, new_entries, dup_entries

    def preview_merge(self):
        try:
            existing, new_entries, dup_entries = self._compute_merge()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("錯誤", str(e))
            return
        tv = self.tv_merge
        tv.delete(*tv.get_children())
        for e in new_entries:
            tv.insert("", "end", tags=("new",), values=(
                "新增", e.get("id", ""), e.get("file", ""),
                e.get("title", ""), ", ".join(e.get("tags", []))))
        for e in dup_entries:
            tv.insert("", "end", tags=("dup",), values=(
                "重複", e.get("id", ""), e.get("file", ""),
                e.get("title", ""), ", ".join(e.get("tags", []))))
        self.lbl_merge.configure(
            text=(f"現有 {len(existing)} 筆；本次解析 {len(self.entries)} 筆 → "
                  f"新增 {len(new_entries)} 筆、重複 {len(dup_entries)} 筆。"))
        self.nb.select(self.nb.index("end") - 1)

    def do_update_json(self):
        try:
            existing, new_entries, dup_entries = self._compute_merge()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("錯誤", str(e))
            return

        # 決定每筆重複的處理方式
        resolutions = {}  # file -> {action, new_file}
        if dup_entries:
            if self.var_overwrite_dup.get():
                resolutions = {e.get("file"): {"action": "overwrite", "new_file": ""}
                               for e in dup_entries}
            else:
                existing_by_file = {e.get("file"): e for e in existing
                                    if isinstance(e, dict)}
                dlg = ConflictDialog(
                    self.root, dup_entries, existing_by_file, self.player,
                    Path(self.var_sounds_dir.get().strip() or "."),
                    Path(self.var_out.get().strip() or "."))
                if dlg.result is None:
                    self.log("[取消] 未處理重複衝突，更新中止。")
                    return
                resolutions = dlg.result

        n_skip = sum(1 for r in resolutions.values() if r["action"] == "skip")
        n_over = sum(1 for r in resolutions.values() if r["action"] == "overwrite")
        n_ren = sum(1 for r in resolutions.values() if r["action"] == "rename")
        msg = (f"將更新 sounds.json：\n\n"
               f"  現有：{len(existing)} 筆\n"
               f"  新增：{len(new_entries)} 筆\n"
               f"  重複：{len(dup_entries)} 筆"
               + (f"（略過 {n_skip}、覆寫 {n_over}、重新命名 {n_ren}）" if dup_entries else "")
               + f"\n\n舊檔會先備份為 sounds-old.json。確定要寫入嗎？")
        if not messagebox.askyesno("確認更新", msg):
            return

        self._persist()

        def task():
            self.log("\n=== 5. 更新 sounds.json ===")
            sounds_path = Path(self.var_sounds.get().strip())
            old_path = sounds_path.with_name("sounds-old.json")
            output_dir = Path(self.var_out.get().strip() or ".")
            opts = self._collect_opts()
            nbytes = int(opts.get("nbytes", 4))
            namespace = opts.get("namespace") or None

            shutil.copy2(sounds_path, old_path)
            self.log(f"[備份] {sounds_path.name} → {old_path.name}")

            merged = copy.deepcopy(existing)
            by_file = {e.get("file"): i for i, e in enumerate(merged)
                       if isinstance(e, dict)}
            dup_by_file = {e.get("file"): e for e in dup_entries}

            n_skip = n_over = n_ren = 0
            extra_new = []  # 重新命名後當作新增
            for f, res in resolutions.items():
                src = dup_by_file.get(f)
                if src is None:
                    continue
                action = res["action"]
                if action == "skip":
                    n_skip += 1
                elif action == "overwrite":
                    idx = by_file.get(f)
                    if idx is not None:
                        merged[idx] = dict(src)
                    n_over += 1
                elif action == "rename":
                    new_file = res["new_file"]
                    old_fp = output_dir / f
                    new_fp = output_dir / new_file
                    if old_fp.exists():
                        if new_fp.exists():
                            raise RuntimeError(f"重新命名目標已存在：{new_fp}")
                        old_fp.rename(new_fp)
                        self.log(f"[更名] {f} → {new_file}")
                    else:
                        self.log(f"[警告] 找不到輸出檔，僅更新資料：{old_fp}")
                    # 更新原解析資料（self.entries 共用同一物件）
                    src["file"] = new_file
                    if mod_uuid is not None:
                        src["id"] = mod_uuid.ufid(new_file, namespace, 0,
                                                  "nfkc", True, True, nbytes)
                    extra_new.append(dict(src))
                    n_ren += 1

            new_all = [dict(e) for e in new_entries] + extra_new
            merged.extend(new_all)
            self.log(f"[新增] 加入 {len(new_all)} 筆"
                     + (f"（含 {n_ren} 筆重新命名）" if n_ren else "") + "。")
            if dup_entries:
                self.log(f"[重複] 略過 {n_skip}、覆寫 {n_over}、重新命名 {n_ren}。")

            # 以 ufid 補/驗證 id（保留既有、補缺、偵測碰撞）
            if mod_uuid is not None:
                opts = self._collect_opts()
                try:
                    changed = mod_uuid.assign_ids_strict(
                        merged, opts.get("namespace") or None, False,
                        "nfkc", True, True, "warn", int(opts.get("nbytes", 4)))
                    self.log(f"[UUID] 補/更新 {changed} 筆 id。")
                except SystemExit as se:
                    raise RuntimeError(f"id 碰撞或驗證失敗：{se}")

            text = json.dumps(merged, ensure_ascii=False, indent=SOUNDS_INDENT)
            sounds_path.write_text(text + "\n", encoding="utf-8")
            self.log(f"[完成] 已寫入 {sounds_path}（共 {len(merged)} 筆）。")
            if n_ren:
                self.root.after(0, self._refresh_results)  # 反映重新命名後的 file/id
            self.root.after(0, lambda: messagebox.showinfo(
                "完成", f"已更新 sounds.json，共 {len(merged)} 筆。\n備份：{old_path.name}"))

        self._run_async(task)

    # ------------------------------------------------------------------ #
    #  Treeview 重整
    # ------------------------------------------------------------------ #
    def _play(self, path: Path):
        """試聽指定音檔，錯誤以對話框提示。"""
        try:
            self.player.play(path)
            self.status.set(f"試聽：{Path(path).name}")
        except Exception as e:  # noqa: BLE001
            messagebox.showwarning("無法試聽", str(e))

    def _play_selected_result(self):
        sel = self.tv_results.selection()
        if not sel:
            messagebox.showinfo("試聽", "請先在清單中選取一筆。")
            return
        idx = int(sel[0])
        if not (0 <= idx < len(self.entries)):
            return
        out = self.var_out.get().strip()
        if not out:
            messagebox.showwarning("無法試聽", "尚未指定輸出資料夾。")
            return
        self._play(Path(out) / self.entries[idx].get("file", ""))

    def _refresh_renames(self):
        tv = self.tv_renames
        tv.delete(*tv.get_children())
        for old, new in self.rename_changes:
            tv.insert("", "end", values=(old, new))

    def _refresh_results(self):
        tv = self.tv_results
        self._destroy_results_editor()
        tv.delete(*tv.get_children())
        for i, e in enumerate(self.entries):
            tv.insert("", "end", iid=str(i), values=(
                e.get("id", ""), e.get("file", ""),
                e.get("title", ""), ", ".join(e.get("tags", []))))
        self.lbl_results.configure(text=f"共 {len(self.entries)} 筆")

    def _export_results(self):
        if not self.entries:
            messagebox.showinfo("無資料", "尚無解析結果可匯出。")
            return
        f = filedialog.asksaveasfilename(
            title="匯出解析結果", defaultextension=".json",
            initialfile="mp3_index.json", filetypes=[("JSON", "*.json")])
        if not f:
            return
        Path(f).write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"[匯出] {f}")
        messagebox.showinfo("完成", f"已匯出：{f}")

    # ------------------------------------------------------------------ #
    def _on_close(self):
        try:
            self.player.stop()
            self._persist()
        finally:
            self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")  # Windows 預設較美觀
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

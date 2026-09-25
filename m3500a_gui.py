#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PICOTEST M3500A GUI (SCPI over USB)  —  covers Appendix C remote commands.

适用 / applies to: M3500A firmware 1.x (vendor USB, plain SCPI over bulk)
前置 / prereq:
  1) Zadig install WinUSB for VID_164E/PID_0DAC
  2) pip install pyusb libusb-package

运行 / run:  python m3500a_gui.py

Features:
  - tabs: Measure / SENSe / Temperature / Math / Trigger / System / Status / Console
  - EN <-> 中文 language toggle
  - commands unsupported by 1.x are marked "(n/a)" and disabled
  - continuous read, stats, live chart, CSV logging/export
"""
import os
import time
import threading
import queue
import csv
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------
try:
    import libusb_package
    _BACKEND = libusb_package.get_libusb1_backend()
except Exception:
    _BACKEND = None

import usb.core
import usb.util

VID, PID = 0x164E, 0x0DAC
EP_OUT, EP_IN = 0x02, 0x82


class DMMError(Exception):
    pass


class M3500A:
    def __init__(self):
        kw = dict(idVendor=VID, idProduct=PID)
        if _BACKEND is not None:
            kw["backend"] = _BACKEND
        dev = usb.core.find(**kw)
        if dev is None:
            raise DMMError("M3500A not found (install WinUSB via Zadig?)")
        self.dev = dev
        try:
            dev.set_configuration()
        except Exception:
            pass
        try:
            usb.util.claim_interface(dev, 0)
        except Exception:
            pass

    def write(self, cmd):
        if isinstance(cmd, str):
            cmd = cmd.encode()
        if not cmd.endswith(b"\n"):
            cmd += b"\n"
        self.dev.write(EP_OUT, cmd, timeout=2000)

    def read(self, maxlen=512):
        chunks = []
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                data = self.dev.read(EP_IN, maxlen, timeout=300)
                chunks.append(bytes(data))
                if len(data) < maxlen:
                    break
            except usb.core.USBTimeoutError:
                if chunks:
                    break
            except Exception as e:
                raise DMMError("USB read error: %s" % e)
        return b"".join(chunks)

    def query(self, cmd):
        self.write(cmd)
        return self.read().decode(errors="replace").strip()

    def close(self):
        try:
            usb.util.release_interface(self.dev, 0)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
FUNCS = ["DCV", "ACV", "DCI", "ACI", "2W-Ohm", "4W-Ohm",
         "FREQ", "PERIOD", "CONT", "DIODE", "TEMP", "TCOUPLE", "DCV RATIO"]
MEAS = {"DCV": "VOLT:DC", "ACV": "VOLT:AC", "DCI": "CURR:DC", "ACI": "CURR:AC",
        "2W-Ohm": "RES", "4W-Ohm": "FRES", "FREQ": "FREQ", "PERIOD": "PER",
        "CONT": "CONT", "DIODE": "DIOD", "TEMP": "TEMP", "TCOUPLE": "TCOU",
        "DCV RATIO": "VOLT:DC:RAT"}
NODE = {"DCV": "VOLT:DC", "ACV": "VOLT:AC", "DCI": "CURR:DC", "ACI": "CURR:AC",
        "2W-Ohm": "RES", "4W-Ohm": "FRES", "FREQ": "FREQ:VOLT", "PERIOD": "PER:VOLT"}
RANGES = {
    "DCV": ["AUTO", "0.1", "1", "10", "100", "1000"],
    "ACV": ["AUTO", "0.1", "1", "10", "100", "750"],
    "DCI": ["AUTO", "0.01", "0.1", "1", "3"],
    "ACI": ["AUTO", "1", "3"],
    "2W-Ohm": ["AUTO", "100", "1000", "10000", "100000", "1000000", "10000000", "100000000"],
    "4W-Ohm": ["AUTO", "100", "1000", "10000", "100000", "1000000", "10000000", "100000000"],
    "FREQ": ["AUTO", "0.1", "1", "10", "100", "750"],
    "PERIOD": ["AUTO", "0.1", "1", "10", "100", "750"],
}
NPLC_FUNCS = {"DCV", "DCI", "2W-Ohm", "4W-Ohm"}
BW_FUNCS = {"ACV", "ACI"}
AP_FUNCS = {"FREQ", "PERIOD"}

# 测量模式(位数/速度) -> (NPLC, 闸门时间s)
MODE_NAMES = ["Fast 4.5", "Slow 4.5", "Fast 5.5", "Slow 5.5", "Fast 6.5", "Slow 6.5"]
# Table 4-1: name -> (NPLC, auto-zero(auto-gain), gate-time s, suggested interval s)
MODE_MAP = {
    "Fast 4.5": ("0.02", False, "0.01", "0.02"),
    "Slow 4.5": ("0.1", True, "0.01", "0.05"),
    "Fast 5.5": ("0.1", False, "0.1", "0.05"),
    "Slow 5.5": ("1", True, "0.1", "0.1"),
    "Fast 6.5": ("1", True, "1", "0.1"),
    "Slow 6.5": ("10", True, "1", "0.5"),
}
UNITS = {"DCV": "V", "ACV": "V", "DCI": "A", "ACI": "A", "2W-Ohm": "Ohm",
         "4W-Ohm": "Ohm", "FREQ": "Hz", "PERIOD": "s", "TEMP": "C", "TCOUPLE": "C"}

# 1.x does not implement the TCOUPLE subsystem
UNSUPPORTED = {"TC type", "Ref junction", "Sim ref temp", "Real ref offset"}

# dropdown shows words, but the "Get" reads a number/short form -> mapping
VMAP_BY_LABEL = {
    "Autorange": {"1": "ON", "0": "OFF"},
    "Auto zero": {"1": "ON", "0": "OFF/ONCE"},
    "Auto gain": {"1": "ON", "0": "OFF/ONCE"},
    "Input impedance auto": {"1": "ON", "0": "OFF"},
    "State": {"1": "ON", "0": "OFF"},
    "Delay auto": {"1": "ON", "0": "OFF"},
    "Display": {"1": "ON", "0": "OFF"},
    "Beeper": {"1": "ON", "0": "OFF"},
    "Unit": {"C": "Celsius", "F": "Fahrenheit", "K": "Kelvin"},
    "Source": {"IMM": "Immediate", "BUS": "software trigger", "EXT": "external"},
    "RTD wiring": {"RTD": "2-wire", "FRTD": "4-wire"},
}

# explanation shown to the right of each row (abbrev. + meaning of the returned value)
HINT_BY_LABEL = {
    "Mode": {"en": "Table 4-1: Fast/Slow 4.5/5.5/6.5 -> NPLC .02/.1/1/10 + AZ/AG",
             "zh": "Table 4-1: 快/慢 4½/5½/6½ -> NPLC .02/.1/1/10 + 自动调零/增益"},
    "NPLC": {"en": "power-line cycles; returns a number",
             "zh": "工频周期数(积分时间); 读回数值"},
    "Function": {"en": "FUNC?; returns short form, e.g. VOLT",
                 "zh": "FUNC?; 读回短格式, 如 VOLT"},
    "Range": {"en": "returns numeric range",
              "zh": "读回数值量程"},
    "Resolution": {"en": "returns numeric resolution",
                   "zh": "读回数值分辨率"},
    "FREQ aperture": {"en": "gate time; returns seconds",
                      "zh": "闸门时间; 读回秒"},
    "PER aperture": {"en": "gate time; returns seconds",
                     "zh": "闸门时间; 读回秒"},
    "AC bandwidth": {"en": "returns 3 / 20 / 200",
                     "zh": "读回 3 / 20 / 200"},
    "Input impedance auto": {"en": ">10GOhm on DCV 0.1/1/10V",
                             "zh": "DCV 0.1/1/10V 时 >10GΩ"},
    "State": {"en": "returns 1=ON / 0=OFF; CALCulate:STATe",
              "zh": "读回 1=ON / 0=OFF; CALCulate:STATe"},
    "Math fn": {"en": "CALC:FUNC; returns PERC/AVER/NULL/LIM/MXB/DB/DBM",
                "zh": "CALC:FUNC; 读回 PERC/AVER/NULL/LIM/MXB/DB/DBM"},
    "Standard Event En": {"en": "*ESE bit-weighted mask",
                          "zh": "*ESE 按位加权掩码"},
    "Status Byte En": {"en": "*SRE mask",
                       "zh": "*SRE 掩码"},
    "Questionable En": {"en": "questionable enable mask",
                        "zh": "可疑数据使能掩码"},
    "Questionable Ev": {"en": "questionable event register",
                        "zh": "可疑数据事件寄存器"},
    "Trigger count": {"en": "INF returns 9.9E37",
                      "zh": "INF 读回 9.9E37"},
    "DATA:FEED": {"en": 'returns "CALC" or ""',
                  "zh": '读回 "CALC" 或 ""'},
    "PERC target": {"en": "percent target value", "zh": "百分比目标值"},
    "NULL offset": {"en": "null offset value", "zh": "NULL 偏置值"},
    "MXB M": {"en": "y = M*x + B", "zh": "y = M*x + B"},
    "MXB B": {"en": "y = M*x + B", "zh": "y = M*x + B"},
    "DB reference": {"en": "dB relative register", "zh": "dB 相对寄存器"},
    "DBM reference(Ohm)": {"en": "dBm reference, 50 .. 8000 Ohm",
                           "zh": "dBm 参考, 50 .. 8000 欧"},
    "RTD type": {"en": "returns e.g. PT100", "zh": "读回如 PT100"},
    "RTD wiring": {"en": "RTD(2-wire) / FRTD(4-wire)",
                   "zh": "RTD(2线) / FRTD(4线)"},
    "Display text": {"en": "up to 16 chars on front panel", "zh": "面板最多 16 字符"},
}

ZH = {
    "PICOTEST M3500A GUI  (SCPI over USB)": "PICOTEST M3500A 上位机 (SCPI over USB)",
    "Connect": "连接", "Disconnect": "断开", "not connected": "未连接", "ready": "就绪",
    "connected": "已连接", "connecting...": "连接中...", "connect failed": "连接失败",
    "disconnected": "已断开", "continuous...": "连续读取中...",
    "Not connected": "未连接", "Click Connect first": "请先点击“连接”",
    "Export": "导出", "no data": "没有数据", "exported ": "已导出 ",
    "logging to ": "记录到 ", "logging stopped": "停止记录",
    "Stop": "停止", "Continuous": "连续读取",
    # tabs
    "Measure": "测量", "Temperature": "温度", "Math": "数学", "Trigger": "触发",
    "System": "系统", "Status": "状态", "Console": "命令台",
    # measure
    "Settings": "测量设置", "Function": "功能", "Mode": "测量模式",
    "Range": "量程", "Resolution": "分辨率",
    "AC bandwidth": "AC 带宽", "Gate time(s)": "闸门时间(s)",
    "Auto zero (ZERO:AUTO)": "自动调零 (ZERO:AUTO)",
    "Temp unit": "温度单位", "Apply": "应用设置", "Read once": "读取一次",
    "interval(s)": "间隔(s)", "Log to CSV": "记录到 CSV",
    "Reading": "读数", "Clear": "清空", "Export CSV": "导出 CSV",
    "Chart (last %d)": "曲线 (最近 %d 点)",
    # sense
    "Commands with (*) follow the current function on the Measure tab.":
        "带 (*) 的命令跟随“测量”页当前功能。",
    "Integration / filter / zero / input": "积分 / 滤波 / 调零 / 输入",
    "Speed": "速度",
    "Avg filter": "平均滤波",
    "Avg type": "滤波方式",
    "Avg points": "滤波点数",
    "NPLC (*)": "NPLC (*)", "FREQ aperture": "FREQ 闸门时间", "PER aperture": "PER 闸门时间",
    "Auto gain": "自动增益", "Input impedance auto": "输入阻抗自动",
    "Range / resolution (*)": "量程 / 分辨率 (*)", "Autorange": "自动量程",
    # temperature
    "General / thermocouple": "通用 / 热电偶", "Unit": "单位", "TC type": "热电偶类型",
    "Ref junction": "参考端选择", "Sim ref temp": "模拟参考端温度",
    "Real ref offset": "实参考端偏置", "RTD wiring": "RTD 线制",
    "RTD type": "RTD 类型", "R-Zero": "R-Zero", "Alpha": "Alpha", "Beta": "Beta", "Delta": "Delta",
    # math
    "Math function": "数学功能", "Math fn": "数学功能", "State": "状态", "PERC target": "PERC 目标值",
    "NULL offset": "NULL 偏置", "LIM lower": "LIM 下限", "LIM upper": "LIM 上限",
    "DB reference": "DB 参考", "DBM reference(Ohm)": "DBM 参考(欧)",
    "Min/Max results (read-only)": "Min/Max 结果 (只读)", "Minimum": "最小值",
    "Maximum": "最大值", "Average": "平均值", "Count": "计数",
    # trigger
    "Trigger / sample": "触发 / 采样", "Source": "触发源", "Delay(s)": "触发延时(s)",
    "Delay auto": "延时自动", "Sample count": "采样数", "Trigger count": "触发数",
    "Action / read": "动作 / 读取",
    # system
    "Display / beeper / ID": "显示 / 蜂鸣 / 标识", "Display": "显示开关",
    "Display text": "显示文本", "Beeper": "蜂鸣开关", "IDN string": "IDN 字符串",
    "ID form:": "标识模式:", "Interface / reset / version": "接口 / 复位 / 版本",
    "TEXT:CLE": "清除文本", "BEEP now": "响一声",
    # status
    "IEEE-488.2 / status registers": "IEEE-488.2 / 状态寄存器",
    "Value display": "数值显示",
    "Fast preset": "高速模式",
    "Fast preset applied (NPLC 0.02, ZERO:AUTO OFF)": "已应用高速模式 (NPLC 0.02, 关闭自动调零)",
    "Tip: for small intervals set NPLC 0.05-0.1 and ZERO:AUTO OFF.":
        "小间隔采集建议把 NPLC 设为 0.05~0.1 并关闭自动调零。",
    "Standard Event En": "标准事件使能", "Status Byte En": "状态字节使能",
    "Questionable En": "可疑数据使能", "Power-on status": "上电状态清零",
    "Questionable Ev": "可疑数据事件",
    # buttons
    "Set": "设置", "Get": "读取", "Send": "发送",
}
LANG_NAMES = {"EN": "en", "中文": "zh"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.lang = "zh"
        self._i18n = []            # (widget, key) or ('tab', nb, frame, key)
        self.dmm = None
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.continuous = False
        self.null_active = False
        self.interval = 0.5
        self.readings = []
        self.csv_fp = None
        self.csv_writer = None
        self.max_points = 300
        self._alive = True

        self._plot_dirty = False
        self._csv_rows = 0
        self._build_ui()
        self._apply_lang()
        self.after(30, self._poll_results)
        self.after(120, self._tick_plot)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- i18n helpers ----------
    def t(self, key):
        return ZH.get(key, key) if self.lang == "zh" else key

    def _reg(self, widget, key):
        self._i18n.append((widget, key))
        return widget

    def _lab(self, parent, key, **kw):
        return self._reg(ttk.Label(parent, text=self.t(key), **kw), key)

    def _btn(self, parent, key, cmd, **kw):
        return self._reg(ttk.Button(parent, text=self.t(key), command=cmd, **kw), key)

    def _lf(self, parent, key, **kw):
        return self._reg(ttk.LabelFrame(parent, text=self.t(key), **kw), key)

    def _chk(self, parent, key, var, **kw):
        return self._reg(ttk.Checkbutton(parent, text=self.t(key), variable=var, **kw), key)

    def _apply_lang(self):
        self.title(self.t("PICOTEST M3500A GUI  (SCPI over USB)"))
        for item in self._i18n:
            try:
                if item[0] == "tab":
                    _, nb, frame, key = item
                    nb.tab(frame, text=self.t(key))
                elif item[0] == "hint":
                    _, w, key = item
                    h = HINT_BY_LABEL.get(key)
                    if h:
                        w.configure(text=h[self.lang])
                else:
                    w, key = item
                    w.configure(text=self.t(key))
            except Exception:
                pass
        try:
            self.lf_chart.configure(text=self.t("Chart (last %d)") % self.max_points)
        except Exception:
            pass

    def set_lang(self, name):
        self.lang = LANG_NAMES.get(name, "en")
        self._apply_lang()

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        self.btn_conn = self._btn(top, "Connect", self.connect)
        self.btn_conn.pack(side="left")
        self.btn_disc = ttk.Button(top, text="Disconnect", command=self.disconnect, state="disabled")
        self._reg(self.btn_disc, "Disconnect")
        self.btn_disc.pack(side="left", padx=4)
        self.lbl_idn = self._reg(ttk.Label(top, text="not connected", foreground="#888"), "not connected")
        self.lbl_idn.pack(side="left", padx=12)

        langbox = ttk.Frame(top)
        langbox.pack(side="right")
        ttk.Label(langbox, text="Lang").pack(side="left")
        self.cmb_lang = ttk.Combobox(langbox, values=["EN", "中文"], width=5, state="readonly")
        self.cmb_lang.set("中文")
        self.cmb_lang.bind("<<ComboboxSelected>>", lambda e: self.set_lang(self.cmb_lang.get()))
        self.cmb_lang.pack(side="left", padx=4)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=4)
        self.nb = nb
        self._tab_measure(nb)
        self._tab_sense(nb)
        self._tab_temp(nb)
        self._tab_math(nb)
        self._tab_trigger(nb)
        self._tab_system(nb)
        self._tab_status(nb)
        self._tab_command(nb)

        self.status = tk.StringVar(value="ready")
        self.lbl_status = ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w")
        self.lbl_status.pack(fill="x")

    def _add_tab(self, nb, key):
        frame = ttk.Frame(nb, padding=8)
        nb.add(frame, text=self.t(key))
        self._i18n.append(("tab", nb, frame, key))
        return frame

    def _param_row(self, parent, r, label, set_tmpl, query_tmpl,
                   values=None, width=16, func_dep=False, only_query=False):
        unsupported = label in UNSUPPORTED
        lab = self.t(label) + ("  (n/a)" if unsupported else "")
        _lbl = ttk.Label(parent, text=lab)
        if not unsupported:
            self._reg(_lbl, label)
        _lbl.grid(row=r, column=0, sticky="w", pady=2)
        var = tk.StringVar()
        if values:
            w = ttk.Combobox(parent, textvariable=var, values=values, width=width)
        else:
            w = ttk.Entry(parent, textvariable=var, width=width)
        w.grid(row=r, column=1, sticky="w", padx=4)
        res = ttk.Label(parent, text="", foreground="#060", width=22)
        state = ("disabled",) if unsupported else ()

        hint = HINT_BY_LABEL.get(label)
        if hint:
            hl = ttk.Label(parent, text=hint[self.lang], foreground="#999",
                           font=("Segoe UI", 8))
            self._i18n.append(("hint", hl, label))
            hl.grid(row=r, column=5, sticky="w", padx=6)

        def build(tmpl):
            if tmpl is None:
                return None
            cmd = tmpl
            if func_dep:
                node = self.cur_node()
                if not node:
                    return None
                cmd = cmd.replace("{node}", node)
            return cmd.format(v=var.get()) if "{v}" in cmd else cmd

        if not only_query:
            b1 = ttk.Button(parent, text=self.t("Set"), width=4, state=state or "normal",
                            command=lambda: (self.set_cmd(build(set_tmpl))))
            self._reg(b1, "Set")
            b1.grid(row=r, column=2, padx=2)
        b2 = ttk.Button(parent, text=self.t("Get"), width=4, state=state or "normal",
                        command=lambda: (self.query_to(build(query_tmpl), res,
                                                       VMAP_BY_LABEL.get(label))))
        self._reg(b2, "Get")
        b2.grid(row=r, column=3, padx=2)
        res.grid(row=r, column=4, sticky="w", padx=4)
        return var

    # ---- Measure ----
    def _tab_measure(self, nb):
        tab = self._add_tab(nb, "Measure")
        left = self._lf(tab, "Settings", padding=8)
        left.grid(row=0, column=0, sticky="nw")

        def row(r, key, widget):
            self._lab(left, key).grid(row=r, column=0, sticky="w", pady=3)
            widget.grid(row=r, column=1, sticky="ew", pady=3)

        self.var_func = tk.StringVar(value="DCV")
        w = ttk.Combobox(left, textvariable=self.var_func, values=FUNCS, width=14, state="readonly")
        w.bind("<<ComboboxSelected>>", lambda e: self._on_func_change())
        row(0, "Function", w)
        self.var_mode = tk.StringVar(value="Slow 5.5")
        mb = ttk.Combobox(left, textvariable=self.var_mode, values=MODE_NAMES, width=18, state="readonly")
        mb.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())
        row(1, "Mode", mb)
        # NPLC / gate-time 由 Mode 设置, 供 apply_config 使用 (无独立控件, 在 SENSe 页可手动改)
        self.var_nplc = tk.StringVar(value="1")
        self.var_aper = tk.StringVar(value="0.1")
        self.var_range = tk.StringVar(value="AUTO")
        self.cmb_range = ttk.Combobox(left, textvariable=self.var_range, values=RANGES["DCV"], width=14)
        row(2, "Range", self.cmb_range)
        self.var_avg_on = tk.BooleanVar(value=False)
        self._chk(left, "Avg filter", self.var_avg_on).grid(row=3, column=0, columnspan=2, sticky="w", pady=3)
        self.var_avg_type = tk.StringVar(value="MOVing")
        row(4, "Avg type", ttk.Combobox(left, textvariable=self.var_avg_type,
                                        values=["MOVing", "REPeat"], width=14))
        self.var_avg_count = tk.StringVar(value="10")
        row(5, "Avg points", ttk.Combobox(left, textvariable=self.var_avg_count,
                                          values=["2", "5", "10", "20", "50", "100"], width=14))
        self.var_zauto = tk.BooleanVar(value=True)
        self._chk(left, "Auto zero (ZERO:AUTO)", self.var_zauto).grid(row=6, column=0, columnspan=2, sticky="w", pady=3)

        btns = ttk.Frame(left)
        btns.grid(row=7, column=0, columnspan=2, pady=(8, 0), sticky="ew")
        self._btn(btns, "Apply", self.apply_config).pack(fill="x", pady=2)
        self._btn(btns, "Read once", self.read_once).pack(fill="x", pady=2)
        self.btn_cont = self._btn(btns, "Continuous", self.toggle_continuous)
        self.btn_cont.pack(fill="x", pady=2)
        self.btn_null = ttk.Button(btns, text="NULL", command=self.null_toggle)
        self.btn_null.pack(fill="x", pady=2)
        iv = ttk.Frame(left)
        iv.grid(row=8, column=0, columnspan=2, sticky="ew", pady=3)
        self._lab(iv, "interval(s)").pack(side="left")
        self.var_interval = tk.StringVar(value="0.1")
        ttk.Entry(iv, textvariable=self.var_interval, width=6).pack(side="left", padx=4)
        lf = ttk.Frame(left)
        lf.grid(row=9, column=0, columnspan=2, sticky="ew", pady=3)
        self.var_autocsv = tk.BooleanVar(value=False)
        self._chk(lf, "Log to CSV", self.var_autocsv, command=self._toggle_csv).pack(side="left")
        df = ttk.Frame(left)
        df.grid(row=10, column=0, columnspan=2, sticky="ew", pady=3)
        self._lab(df, "Value display").pack(side="left")
        self.var_dispfmt = tk.StringVar(value="Auto")
        ttk.Combobox(df, textvariable=self.var_dispfmt, values=["Auto", "Raw", "Sci"],
                     width=8, state="readonly").pack(side="left", padx=4)

        right = ttk.Frame(tab)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)
        box = self._lf(right, "Reading", padding=8)
        box.pack(fill="x")
        self.lbl_value = tk.Label(box, text="----", font=("Consolas", 34, "bold"), fg="#036")
        self.lbl_value.pack()
        self.lbl_unit = tk.Label(box, text="", font=("Consolas", 12))
        self.lbl_unit.pack()
        self.lbl_stats = tk.Label(box, text="n=0", font=("Consolas", 10), fg="#555")
        self.lbl_stats.pack(pady=4)
        self.lf_chart = ttk.LabelFrame(right, text="Chart (last %d)" % self.max_points, padding=4)
        self.lf_chart.pack(fill="both", expand=True, pady=6)
        self.canvas = tk.Canvas(self.lf_chart, background="white", height=250,
                                highlightthickness=1, highlightbackground="#ccc")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw_plot())
        sf = ttk.Frame(right)
        sf.pack(fill="x")
        self._btn(sf, "Clear", self.clear_data).pack(side="left")
        self._btn(sf, "Export CSV", self.export_csv).pack(side="left", padx=4)
        ttk.Button(sf, text="SYST:ERR?", command=lambda: self.query_to("SYST:ERR?", self.lbl_misc)).pack(side="left")
        ttk.Button(sf, text="ROUT:TERM?", command=lambda: self.query_to("ROUT:TERM?", self.lbl_misc)).pack(side="left", padx=4)
        self.lbl_misc = ttk.Label(sf, text="", foreground="#060")
        self.lbl_misc.pack(side="left", padx=6)
        legend = ("Mode  ->  NPLC / AZ(AG) / interval(s):\n"
                  "  Fast 4.5  ->  0.02 / off,off / 0.02\n"
                  "  Slow 4.5  ->  0.1  / on,on   / 0.05\n"
                  "  Fast 5.5  ->  0.1  / off,off / 0.05\n"
                  "  Slow 5.5  ->  1    / on,on   / 0.1\n"
                  "  Fast 6.5  ->  1    / on,on   / 0.1\n"
                  "  Slow 6.5  ->  10   / on,on   / 0.5")
        ttk.Label(tab, text=legend, foreground="#999",
                  font=("Consolas", 8), justify="left").grid(row=1, column=0, sticky="nw", pady=(6, 0))

    def _tab_sense(self, nb):
        tab = self._add_tab(nb, "SENSe")
        self._lab(tab, "Commands with (*) follow the current function on the Measure tab.",
                  foreground="#888").grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 6))
        g = self._lf(tab, "Integration / filter / zero / input", padding=8)
        g.grid(row=1, column=0, sticky="nw")
        self._param_row(g, 0, "NPLC (*)", "SENS:{node}:NPLC {v}", "SENS:{node}:NPLC?",
                        ["0.02", "0.1", "1", "10"], func_dep=True)
        self._param_row(g, 1, "FREQ aperture", "SENS:FREQ:APER {v}", "SENS:FREQ:APER?", ["0.01", "0.1", "1"])
        self._param_row(g, 2, "PER aperture", "SENS:PER:APER {v}", "SENS:PER:APER?", ["0.01", "0.1", "1"])
        self._param_row(g, 3, "AC bandwidth", "SENS:DET:BAND {v}", "SENS:DET:BAND?", ["3", "20", "200"])
        self._param_row(g, 4, "Auto zero", "SENS:ZERO:AUTO {v}", "SENS:ZERO:AUTO?", ["OFF", "ONCE", "ON"])
        self._param_row(g, 5, "Auto gain", "SENS:GAIN:AUTO {v}", "SENS:GAIN:AUTO?", ["OFF", "ONCE", "ON"])
        self._param_row(g, 6, "Input impedance auto", "INP:IMP:AUTO {v}", "INP:IMP:AUTO?", ["OFF", "ON"])
        g2 = self._lf(tab, "Range / resolution (*)", padding=8)
        g2.grid(row=1, column=1, sticky="nw", padx=10)
        self._param_row(g2, 0, "Range", "SENS:{node}:RANG {v}", "SENS:{node}:RANG?", func_dep=True, width=12)
        self._param_row(g2, 1, "Autorange", "SENS:{node}:RANG:AUTO {v}", "SENS:{node}:RANG:AUTO?",
                        ["OFF", "ON"], func_dep=True)
        self._param_row(g2, 2, "Resolution", "SENS:{node}:RES {v}", "SENS:{node}:RES?",
                        ["MIN", "MAX", "DEF"], func_dep=True)
        self._param_row(g2, 3, "Function", 'FUNC "{v}"', "FUNC?",
                        ['VOLT:DC', 'VOLT:AC', 'CURR:DC', 'CURR:AC', 'RES', 'FRES',
                         'FREQ', 'PER', 'CONT', 'DIOD', 'TEMP', 'TCOU', 'VOLT:DC:RAT'], width=18)
        g3 = self._lf(tab, "Speed", padding=8)
        g3.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self._btn(g3, "Fast preset", self.fast_preset).pack(side="left")
        self._reg(ttk.Label(g3, text=self.t("Tip: for small intervals set NPLC 0.05-0.1 and ZERO:AUTO OFF."),
                            foreground="#999", font=("Segoe UI", 8), justify="left"),
                  "Tip: for small intervals set NPLC 0.05-0.1 and ZERO:AUTO OFF.").pack(side="left", padx=10)

    def _tab_temp(self, nb):
        tab = self._add_tab(nb, "Temperature")
        g = self._lf(tab, "General / thermocouple", padding=8)
        g.grid(row=0, column=0, sticky="nw")
        self._param_row(g, 0, "Unit", "UNIT {v}", "UNIT?", ["Cel", "Far", "K"])
        self._param_row(g, 1, "TC type", "TCOU:TYPE {v}", "TCOU:TYPE?", ["E", "J", "K", "N", "R", "S", "T"])
        self._param_row(g, 2, "Ref junction", "TCOU:RJUN:RSEL {v}", "TCOU:RJUN:RSEL?", ["REAL", "SIM"])
        self._param_row(g, 3, "Sim ref temp", "TCOU:RJUN:SIM {v}", "TCOU:RJUN:SIM?")
        self._param_row(g, 4, "Real ref offset", "TCOU:RJUN:REAL:OFFS {v}", "TCOU:RJUN:REAL:OFFS?")
        self._param_row(g, 5, "RTD wiring", "TEMP:TRAN {v}", "TEMP:TRAN?", ["RTD", "FRTD"])
        r = self._lf(tab, "RTD", padding=8)
        r.grid(row=0, column=1, sticky="nw", padx=10)
        self._param_row(r, 0, "RTD type", "TEMP:RTD:TYPE {v}", "TEMP:RTD:TYPE?",
                        ["PT100", "D100", "F100", "PT385", "PT3916", "USER", "SPRTD", "NTCT"], width=12)
        self._param_row(r, 1, "R-Zero", "TEMP:RTD:RZER {v}", "TEMP:RTD:RZER?")
        self._param_row(r, 2, "Alpha", "TEMP:RTD:ALPH {v}", "TEMP:RTD:ALPH?")
        self._param_row(r, 3, "Beta", "TEMP:RTD:BETA {v}", "TEMP:RTD:BETA?")
        self._param_row(r, 4, "Delta", "TEMP:RTD:DELT {v}", "TEMP:RTD:DELT?")
        s = self._lf(tab, "SPRTD", padding=8)
        s.grid(row=0, column=2, sticky="nw", padx=10)
        for i, (lab, sfx) in enumerate([("R-Zero", "RZER"), ("A4", "A4"), ("B4", "B4"),
                                        ("A", "AX"), ("B", "BX"), ("C", "CX"), ("D", "DX")]):
            self._param_row(s, i, lab, "TEMP:SPRTD:%s {v}" % sfx, "TEMP:SPRTD:%s?" % sfx)

    def _tab_math(self, nb):
        tab = self._add_tab(nb, "Math")
        g = self._lf(tab, "Math function", padding=8)
        g.grid(row=0, column=0, sticky="nw")
        self._param_row(g, 0, "Math fn", "CALC:FUNC {v}", "CALC:FUNC?",
                        ["PERC", "AVER", "NULL", "LIM", "MXB", "DB", "DBM"])
        self._param_row(g, 1, "State", "CALC:STAT {v}", "CALC:STAT?", ["OFF", "ON"])
        self._param_row(g, 2, "PERC target", "CALC:PERC:TARG {v}", "CALC:PERC:TARG?")
        self._param_row(g, 3, "NULL offset", "CALC:NULL:OFFS {v}", "CALC:NULL:OFFS?")
        self._param_row(g, 4, "LIM lower", "CALC:LIM:LOW {v}", "CALC:LIM:LOW?")
        self._param_row(g, 5, "LIM upper", "CALC:LIM:UPP {v}", "CALC:LIM:UPP?")
        self._param_row(g, 6, "MXB M", "CALC:MXB:MMF {v}", "CALC:MXB:MMF?")
        self._param_row(g, 7, "MXB B", "CALC:MXB:MBF {v}", "CALC:MXB:MBF?")
        self._param_row(g, 8, "DB reference", "CALC:DB:REF {v}", "CALC:DB:REF?")
        self._param_row(g, 9, "DBM reference(Ohm)", "CALC:DBM:REF {v}", "CALC:DBM:REF?")
        g2 = self._lf(tab, "Min/Max results (read-only)", padding=8)
        g2.grid(row=0, column=1, sticky="nw", padx=10)
        self._param_row(g2, 0, "Minimum", None, "CALC:AVER:MIN?", only_query=True)
        self._param_row(g2, 1, "Maximum", None, "CALC:AVER:MAX?", only_query=True)
        self._param_row(g2, 2, "Average", None, "CALC:AVER:AVER?", only_query=True)
        self._param_row(g2, 3, "Count", None, "CALC:AVER:COUN?", only_query=True)

    def _tab_trigger(self, nb):
        tab = self._add_tab(nb, "Trigger")
        g = self._lf(tab, "Trigger / sample", padding=8)
        g.grid(row=0, column=0, sticky="nw")
        self._param_row(g, 0, "Source", "TRIG:SOUR {v}", "TRIG:SOUR?", ["BUS", "IMM", "EXT"])
        self._param_row(g, 1, "Delay(s)", "TRIG:DEL {v}", "TRIG:DEL?")
        self._param_row(g, 2, "Delay auto", "TRIG:DEL:AUTO {v}", "TRIG:DEL:AUTO?", ["OFF", "ON"])
        self._param_row(g, 3, "Sample count", "SAMP:COUN {v}", "SAMP:COUN?")
        self._param_row(g, 4, "Trigger count", "TRIG:COUN {v}", "TRIG:COUN?", ["1", "10", "100", "1000", "INF"])
        g2 = self._lf(tab, "Action / read", padding=8)
        g2.grid(row=0, column=1, sticky="nw", padx=10)
        ttk.Button(g2, text="INIT", command=lambda: self.set_cmd("INIT")).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Button(g2, text="READ?", command=lambda: self.jobs.put(("read",))).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Button(g2, text="FETCh?", command=lambda: self.query_to("FETC?", self.lbl_fetch)).grid(row=2, column=0, sticky="w", pady=2)
        ttk.Button(g2, text="DATA:POIN?", command=lambda: self.query_to("DATA:POIN?", self.lbl_fetch)).grid(row=3, column=0, sticky="w", pady=2)
        self._param_row(g2, 4, "DATA:FEED", 'DATA:FEED RDG_STORE,"{v}"', "DATA:FEED?", ['CALC', ''])
        self.lbl_fetch = ttk.Label(g2, text="", foreground="#060", wraplength=420, justify="left")
        self.lbl_fetch.grid(row=5, column=0, columnspan=5, sticky="w", pady=4)

    def _tab_system(self, nb):
        tab = self._add_tab(nb, "System")
        g = self._lf(tab, "Display / beeper / ID", padding=8)
        g.grid(row=0, column=0, sticky="nw")
        self._param_row(g, 0, "Display", "DISP {v}", "DISP?", ["OFF", "ON"])
        self._param_row(g, 1, "Display text", 'DISP:TEXT "{v}"', "DISP:TEXT?")
        self._btn(g, "TEXT:CLE", lambda: self.set_cmd("DISP:TEXT:CLE")).grid(row=1, column=5, padx=2)
        self._param_row(g, 2, "Beeper", "SYST:BEEP:STAT {v}", "SYST:BEEP:STAT?", ["OFF", "ON"])
        self._btn(g, "BEEP now", lambda: self.set_cmd("SYST:BEEP")).grid(row=2, column=5, padx=2)
        self._param_row(g, 3, "IDN string", 'SYST:IDNSTR "{v}"', None, width=28)
        ttk.Button(g, text="*IDN?", command=lambda: self.query_to("*IDN?", self.lbl_sys)).grid(row=3, column=5, padx=2)
        self._lab(g, "ID form:").grid(row=4, column=0, sticky="w")
        ttk.Button(g, text="L0", command=lambda: self.set_cmd("L0")).grid(row=4, column=1, padx=2)
        ttk.Button(g, text="L1", command=lambda: self.set_cmd("L1")).grid(row=4, column=2, padx=2)
        g2 = self._lf(tab, "Interface / reset / version", padding=8)
        g2.grid(row=0, column=1, sticky="nw", padx=10)
        ttk.Button(g2, text="LOCAL", command=lambda: self.set_cmd("SYST:LOC")).grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        ttk.Button(g2, text="REMOTE", command=lambda: self.set_cmd("SYST:REM")).grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        ttk.Button(g2, text="*RST", command=lambda: self.set_cmd("*RST")).grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        ttk.Button(g2, text="*CLS", command=lambda: self.set_cmd("*CLS")).grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        ttk.Button(g2, text="SYST:VERS?", command=lambda: self.query_to("SYST:VERS?", self.lbl_sys)).grid(row=2, column=0, padx=2, pady=2, sticky="ew")
        ttk.Button(g2, text="SYST:ERR?", command=lambda: self.query_to("SYST:ERR?", self.lbl_sys)).grid(row=2, column=1, padx=2, pady=2, sticky="ew")
        self.lbl_sys = ttk.Label(g2, text="", foreground="#060", wraplength=420, justify="left")
        self.lbl_sys.grid(row=3, column=0, columnspan=2, sticky="w", pady=4)

    def _tab_status(self, nb):
        tab = self._add_tab(nb, "Status")
        g = self._lf(tab, "IEEE-488.2 / status registers", padding=8)
        g.grid(row=0, column=0, sticky="nw")
        self._param_row(g, 0, "Standard Event En", "*ESE {v}", "*ESE?")
        self._param_row(g, 1, "Status Byte En", "*SRE {v}", "*SRE?")
        self._param_row(g, 2, "Questionable En", "STAT:QUES:ENAB {v}", "STAT:QUES:ENAB?")
        self._param_row(g, 3, "Power-on status", "*PSC {v}", "*PSC?", ["0", "1"])
        self._param_row(g, 4, "*ESR?", None, "*ESR?", only_query=True)
        self._param_row(g, 5, "*STB?", None, "*STB?", only_query=True)
        self._param_row(g, 6, "Questionable Ev", None, "STAT:QUES:EVEN?", only_query=True)
        ttk.Button(g, text="STAT:PRES", command=lambda: self.set_cmd("STAT:PRES")).grid(row=7, column=2, pady=2)
        ttk.Button(g, text="*OPC", command=lambda: self.set_cmd("*OPC")).grid(row=7, column=3, pady=2)
        ttk.Button(g, text="*OPC?", command=lambda: self.query_to("*OPC?", self.lbl_st)).grid(row=7, column=4, pady=2)
        self.lbl_st = ttk.Label(g, text="", foreground="#060")
        self.lbl_st.grid(row=8, column=0, columnspan=5, sticky="w")

    def _tab_command(self, nb):
        tab = self._add_tab(nb, "Console")
        self.txt_log = tk.Text(tab, height=22, wrap="word", font=("Consolas", 10))
        self.txt_log.pack(fill="both", expand=True)
        e = ttk.Frame(tab)
        e.pack(fill="x", pady=4)
        self.var_scpi = tk.StringVar()
        ent = ttk.Entry(e, textvariable=self.var_scpi, font=("Consolas", 10))
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda ev: self.send_scpi())
        self._btn(e, "Send", lambda: self.send_scpi()).pack(side="left", padx=4)
        self._btn(e, "Clear", lambda: self.txt_log.delete("1.0", "end")).pack(side="left")

    # ---------- logic ----------
    def cur_node(self):
        return NODE.get(self.var_func.get())

    def _on_func_change(self):
        f = self.var_func.get()
        self.cmb_range["values"] = RANGES.get(f, ["AUTO"])
        self.var_range.set("AUTO")

    def _on_mode_change(self):
        nplc, az, aper, iv = MODE_MAP.get(self.var_mode.get(), ("1", True, "0.1", "0.5"))
        self.var_nplc.set(nplc)
        self.var_zauto.set(bool(az))
        self.var_aper.set(aper)
        self.var_interval.set("%g" % float(iv))          # 推荐间隔(仍可手动改)
        if self.continuous:
            try:
                self.interval = max(0.05, float(self.var_interval.get()))
            except Exception:
                pass
        if self.dmm is not None:
            self.apply_config()

    def _log(self, s):
        self.txt_log.insert("end", s + "\n")
        self.txt_log.see("end")

    def connect(self):
        self.status.set(self.t("connecting..."))
        try:
            if self.dmm:
                self.dmm.close()
            self.dmm = M3500A()
            idn = self.dmm.query("*IDN?")
            self.lbl_idn.config(text=idn, foreground="#080")
            self.status.set(self.t("connected"))
            self.btn_conn.config(state="disabled")
            self.btn_disc.config(state="normal")
            threading.Thread(target=self._worker_loop, daemon=True).start()
            self._log("Connected: " + idn)
            self.apply_config()
        except Exception as e:
            self.dmm = None
            self.lbl_idn.config(text=self.t("not connected"), foreground="#888")
            self.status.set(self.t("connect failed"))
            messagebox.showerror(self.t("connect failed"), str(e))

    def disconnect(self):
        self.continuous = False
        self._stop_csv()
        if self.dmm:
            try:
                self.dmm.close()
            except Exception:
                pass
            self.dmm = None
        self.lbl_idn.config(text=self.t("not connected"), foreground="#888")
        self.btn_conn.config(state="normal")
        self.btn_disc.config(state="disabled")
        self.status.set(self.t("disconnected"))

    def _worker_loop(self):
        while self._alive and self.dmm is not None:
            try:
                while True:
                    self._handle_job(self.jobs.get_nowait())
            except queue.Empty:
                pass
            if self.continuous and self.dmm:
                t0 = time.perf_counter()
                self._do_read()
                try:
                    period = max(0.0, float(self.interval))
                except Exception:
                    period = 0.5
                dt = time.perf_counter() - t0
                time.sleep(max(0.0, period - dt))
            else:
                time.sleep(0.05)

    def _handle_job(self, job):
        try:
            if job[0] == "config":
                for c in job[1]:
                    self.dmm.write(c)
                err = self.dmm.query("SYST:ERR?")
                self.results.put(("info", "config: " + err, None, None))
            elif job[0] == "scpi":
                _, cmd, want_read, cb = job
                if want_read:
                    self.results.put(("resp", cmd, self.dmm.query(cmd), cb))
                else:
                    self.dmm.write(cmd)
                    self.results.put(("info", "sent: " + cmd, None, None))
            elif job[0] == "read":
                self._do_read()
            elif job[0] == "null_on":
                v = float(self.dmm.query("READ?"))
                self.dmm.write("CALC:NULL:OFFS %.9E" % v)
                self.dmm.write("CALC:FUNC NULL")
                self.dmm.write("CALC:STAT ON")
                self.results.put(("info", "NULL set to %.9E" % v, None, None))
                self.results.put(("null_state", True, None, None))
            elif job[0] == "null_off":
                self.dmm.write("CALC:STAT OFF")
                self.results.put(("info", "NULL off", None, None))
                self.results.put(("null_state", False, None, None))
        except Exception as e:
            self.results.put(("error", str(e), None, None))

    def _do_read(self):
        try:
            self.results.put(("reading", self.dmm.query("READ?"), None, None))
        except Exception as e:
            self.results.put(("error", str(e), None, None))
            self.continuous = False

    def _poll_results(self):
        readings = []
        try:
            while True:
                kind, a, b, cb = self.results.get_nowait()
                if kind == "reading":
                    readings.append(a)
                elif kind == "resp":
                    self._log(">> %s\n<< %s" % (a, b))
                    if callable(cb):
                        cb(b)
                elif kind == "info":
                    self._log(a)
                    self.status.set(a)
                elif kind == "null_state":
                    self.null_active = bool(a)
                    self.btn_null.configure(text=("NULL ON" if a else "NULL"))
                elif kind == "error":
                    self.status.set("error: " + a)
                    self._log("!! " + a)
        except queue.Empty:
            pass
        if readings:
            self._apply_readings(readings)
        self.after(30, self._poll_results)

    def _tick_plot(self):
        # throttled redraw (max ~8 fps) so the UI stays smooth
        if self._plot_dirty:
            self._plot_dirty = False
            try:
                self._draw_plot()
            except Exception:
                pass
        self.after(120, self._tick_plot)

    def _on_reading(self, raw):
        self._apply_readings([raw])

    def _apply_readings(self, raws):
        new_vals = []
        for raw in raws:
            for tok in raw.strip().split(","):
                tok = tok.strip()
                if not tok:
                    continue
                try:
                    new_vals.append(float(tok))
                except Exception:
                    pass
        if not new_vals:
            if raws:
                self.lbl_value.config(text=raws[-1].strip()[:14], fg="#a00")
            return
        OL = 9.0e37        # 过载/超大值(欧姆开路 = +9.9E37)不进曲线, 免得把量程拉爆
        now = time.time()
        for v in new_vals:
            if abs(v) < OL:
                self.readings.append((now, v))
        if len(self.readings) > self.max_points:
            self.readings = self.readings[-self.max_points:]
        last = new_vals[-1]
        if abs(last) >= OL:
            txt, fg = "OL", "#a00"
        else:
            mode = self.var_dispfmt.get() if getattr(self, "var_dispfmt", None) else "Auto"
            if mode == "Raw" and raws:
                txt = raws[-1].strip()
            elif mode == "Sci":
                txt = "%.6E" % last
            else:
                txt = self._fmt(last)
            fg = "#036"
        self.lbl_value.config(text=txt[:22], fg=fg)
        self.lbl_unit.config(text=UNITS.get(self.var_func.get(), ""))
        self._update_stats()
        self._plot_dirty = True
        if self.csv_writer:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            for v in new_vals:
                self.csv_writer.writerow([ts, "%.9g" % v])
            self._csv_rows += len(new_vals)
            if self._csv_rows >= 20:          # batch flush, not on every reading
                self.csv_fp.flush()
                self._csv_rows = 0

    def _fmt(self, v):
        if v == 0:
            return "0"
        if abs(v) >= 1e6 or abs(v) < 1e-3:
            return "%.6E" % v
        return "%.7f" % v

    def _update_stats(self):
        vals = [v for _, v in self.readings]
        n = len(vals)
        if n == 0:
            self.lbl_stats.config(text="n=0")
            return
        mn, mx = min(vals), max(vals)
        avg = sum(vals) / n
        sd = math.sqrt(sum((x - avg) ** 2 for x in vals) / n) if n > 1 else 0.0
        self.lbl_stats.config(text="n=%d  min=%s  max=%s  avg=%s  sd=%.3E"
                              % (n, self._fmt(mn), self._fmt(mx), self._fmt(avg), sd))

    def _draw_plot(self):
        c = self.canvas
        c.delete("all")
        w, h = int(c.winfo_width()), int(c.winfo_height())
        if w < 10 or h < 10:
            return
        vals = [v for _, v in self.readings]
        if not vals:
            return
        mn, mx = min(vals), max(vals)
        if mx == mn:
            span = abs(mx) * 0.01 if mx != 0 else 1.0   # 常数序列也要有可绘制的跨度
            mn -= span
            mx += span
        pad = 34
        x0, y0, x1, y1 = pad, pad, w - 10, h - 10
        c.create_line(x0, y0, x0, y1, fill="#aaa")
        c.create_line(x0, y1, x1, y1, fill="#aaa")
        c.create_text(4, y0 + 2, anchor="nw", text="%.4g" % mx, font=("Consolas", 8), fill="#666")
        c.create_text(4, y1 - 2, anchor="sw", text="%.4g" % mn, font=("Consolas", 8), fill="#666")
        n = len(vals)
        pts = []
        for i, v in enumerate(vals):
            x = x0 + (x1 - x0) * (i / max(1, n - 1))
            y = y1 - (y1 - y0) * (v - mn) / (mx - mn)
            pts.extend([x, y])
        if n >= 2:
            c.create_line(*pts, fill="#036", width=2)
        else:
            c.create_oval(pts[0] - 3, pts[1] - 3, pts[0] + 3, pts[1] + 3, fill="#036")

    def read_once(self):
        if self._need_conn():
            self.jobs.put(("read",))

    def null_toggle(self):
        # NULL: 取当前读数为相对零点, 启用 NULL 数学 (测电阻消引线电阻常用)
        if not self._need_conn():
            return
        self.jobs.put(("null_off" if self.null_active else "null_on",))

    def toggle_continuous(self):
        if not self._need_conn():
            return
        self.continuous = not self.continuous
        self.btn_cont.configure(text=self.t("Stop") if self.continuous else self.t("Continuous"))
        try:
            self.interval = max(0.05, float(self.var_interval.get()))
        except Exception:
            self.interval = 0.5
        self.status.set(self.t("continuous...") if self.continuous else self.t("ready"))

    def apply_config(self):
        if not self._need_conn():
            return
        f = self.var_func.get()
        node = NODE.get(f)
        cmds = []
        if f not in ("CONT", "DIODE", "TEMP", "TCOUPLE"):
            rng = self.var_range.get()
            if rng == "AUTO":
                cmds.append("CONF:%s" % MEAS[f])
                if node:
                    cmds.append("SENS:%s:RANG:AUTO ON" % node)
            else:
                cmds.append("CONF:%s %s" % (MEAS[f], rng))
                if node:
                    cmds.append("SENS:%s:RANG:AUTO OFF" % node)
        else:
            cmds.append("CONF:%s" % MEAS[f])
        if f in NPLC_FUNCS and node:
            cmds.append("SENS:%s:NPLC %s" % (node, self.var_nplc.get()))
        if f in AP_FUNCS and node:
            cmds.append("%s:APER %s" % (node, self.var_aper.get()))
        cmds.append("SENS:ZERO:AUTO %s" % ("ON" if self.var_zauto.get() else "OFF"))
        cmds.append("SENS:GAIN:AUTO %s" % ("ON" if self.var_zauto.get() else "OFF"))
        cmds.append("AVER:STAT %s" % ("ON" if self.var_avg_on.get() else "OFF"))
        cmds.append("AVER:TCON %s" % self.var_avg_type.get())
        cmds.append("AVER:COUN %s" % self.var_avg_count.get())
        self.jobs.put(("config", cmds))

    def fast_preset(self):
        # 高速采集预设 = Fast 4.5 (NPLC 0.02, 自动调零/增益 OFF)
        self.var_mode.set("Fast 4.5")
        self._on_mode_change()
        self.status.set(self.t("Fast preset applied (Fast 4.5)"))

    def set_cmd(self, cmd):
        if cmd and self._need_conn():
            self.jobs.put(("scpi", cmd, False, None))

    def query_to(self, cmd, label, vmap=None):
        if not cmd or not self._need_conn():
            return
        cb = None
        if label is not None:
            def cb(resp, lb=label, m=vmap):
                s = resp
                if m and s in m:
                    s = "%s (%s)" % (s, m[s])
                try:
                    lb.config(text=s[:70])
                except Exception:
                    pass
        self.jobs.put(("scpi", cmd, True, cb))

    def send_scpi(self, cmd=None, read=None):
        if not self._need_conn():
            return
        if cmd is None:
            cmd = self.var_scpi.get().strip()
            self.var_scpi.set("")
        if not cmd:
            return
        if read is None:
            read = "?" in cmd
        self._log(">> " + cmd)
        self.jobs.put(("scpi", cmd, bool(read), None))

    def _toggle_csv(self):
        if self.var_autocsv.get():
            path = filedialog.asksaveasfilename(defaultextension=".csv",
                                                filetypes=[("CSV", "*.csv")],
                                                initialfile="m3500a_log.csv")
            if not path:
                self.var_autocsv.set(False)
                return
            self.csv_fp = open(path, "w", newline="", encoding="utf-8-sig")
            self.csv_writer = csv.writer(self.csv_fp)
            self.csv_writer.writerow(["timestamp", "value"])
            self.status.set(self.t("logging to ") + os.path.basename(path))
        else:
            self._stop_csv()
            self.status.set(self.t("logging stopped"))

    def _stop_csv(self):
        if self.csv_fp:
            try:
                self.csv_fp.close()
            except Exception:
                pass
        self.csv_fp = None
        self.csv_writer = None

    def export_csv(self):
        if not self.readings:
            messagebox.showinfo(self.t("Export"), self.t("no data"))
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")],
                                            initialfile="m3500a_data.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            w.writerow(["timestamp", "value"])
            for t, v in self.readings:
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)), "%.9g" % v])
        self.status.set(self.t("exported ") + os.path.basename(path))

    def clear_data(self):
        self.readings = []
        self._update_stats()
        self._draw_plot()

    def _need_conn(self):
        if self.dmm is None:
            messagebox.showwarning(self.t("Not connected"), self.t("Click Connect first"))
            return False
        return True

    def _on_close(self):
        self._alive = False
        self.continuous = False
        self._stop_csv()
        try:
            if self.dmm:
                self.dmm.close()
        except Exception:
            pass
        self.destroy()


def _selftest():
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    out = ["backend=" + ("libusb_package" if _BACKEND is not None else "auto")]
    try:
        d = M3500A()
        out.append("IDN=" + d.query("*IDN?"))
        out.append("READ=" + d.query("READ?"))
        d.close()
        out.append("RESULT=OK")
    except Exception as e:
        out.append("ERROR=" + str(e))
        out.append("RESULT=FAIL")
    with open(os.path.join(base, "m3500a_selftest.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(out))
    sys.exit(0 if out[-1] == "RESULT=OK" else 1)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    App().mainloop()

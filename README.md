# M3500A-DMM-GUI

**Driving a PICOTEST M3500A 6½-digit DMM over USB on modern Windows — without the vendor driver.**

**在 Windows 11 上，用通用 WinUSB 驱动直接控制 PICOTEST M3500A 万用表（固件 1.x）。**

- Instrument / 仪器：PICOTEST **M3500A**（OEM：Array / Keithley 2100 同平台），firmware **1.0G**
- USB ID：`VID_164E` / `PID_0DAC`（vendor-specific class `FF/A0/B0`，**不是** USBTMC）
- Windows Code 28（无驱动）→ 用 **Zadig 装 WinUSB** → 用 **pyusb** 直接发 SCPI
- 附带 **Tkinter 上位机 GUI**（中英切换、连续采样、实时曲线、CSV、完整 SCPI 面板）
- 可直接运行，也可打包成单文件 exe

> 详细的逆向与调研过程见 **[归档说明.md](归档说明.md)**。
> See **[归档说明.md](归档说明.md)** for the full reverse-engineering write-up (Chinese).

---

## 结论（TL;DR）

原来那个"厂商私有 USB 协议"其实一点都不私有：**接口就是一个"裸 SCPI 字节管道"**。
只要给设备绑一个通用驱动（WinUSB），用 pyusb 直接把 SCPI 字符串写到批量端点即可：

```python
dev.write(0x02, b"*IDN?\n")      # -> b"PICOTEST,M3500A,1,01.0G-01-04"
dev.read(0x82, 512)
```

**不需要原厂驱动，也不建议刷固件**（固件与校准数据在同一片 flash，跨版本刷新有风险）。

---

## 快速开始 / Quick start

### 1) 给设备装通用驱动（Windows）
1. 安装并运行 **Zadig**（装了 [sigrok/PulseView](https://sigrok.org/wiki/Downloads) 的话自带：`C:\Program Files\sigrok\PulseView\zadig.exe`）
2. `Options → List All Devices`
3. 选择 **M3500A Multimeter**（VID `164E` / PID `0DAC`）
4. 目标驱动选 **WinUSB** → `Install Driver` / `Replace Driver`
5. 设备管理器里的 Code 28 消失

### 2) 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 3) 运行
```bash
python m3500a_gui.py        # 图形上位机
python m3500a.py            # 命令行 demo（读 IDN / DCV）
python planB_usb_probe.py   # 端点/分帧探测脚本
```

或直接运行打包好的 exe：`dist/M3500A_GUI.exe`（见下方"打包"）。

---

## GUI 功能 / Features

- **Measure**：功能（DCV/ACV/DCI/ACI/2W/4W/FREQ/PERIOD/CONT/DIODE/TEMP/TCOUPLE/DCV RATIO）、量程、分辨率、NPLC/带宽/闸门时间、自动调零；单次/连续读取、间隔、文本读数、统计(n/min/max/avg/σ)、实时曲线、CSV 记录/导出
- **SENSe**：NPLC、闸门时间、DET:BAND、ZERO:AUTO、GAIN:AUTO、INP:IMP:AUTO、RANGE/RANG:AUTO/RES、FUNC
- **Temperature**：UNIT、TCOUPLE、RTD、SPRTD 全套系数
- **Math**：CALC 的 PERC/AVER/NULL/LIM/MXB/DB/DBM 全套参数 + Min/Max 只读
- **Trigger**：TRIG/SAMP/COUN、INIT/READ?/FETCh?/DATA:POIN?/DATA:FEED
- **System** / **Status**：显示与面板文字(DISP:TEXT)、蜂鸣、IDN、L0/L1、LOCAL/REMOTE、*RST/*CLS、IEEE-488.2 状态寄存器
- **Console**：任意 SCPI 收发日志
- **中英文切换**（右上角 EN / 中文）
- 1.0G 不支持的命令标注 **`(n/a)`** 并禁用（仅热电偶 `TCOU:*`）
- 每个参数行有灰色提示：解释缩写 + **读回值对应的下拉文字**（如 `1 (ON)`、`C (Celsius)`）

---

## 打包单文件 exe

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name M3500A_GUI --collect-all libusb_package --hidden-import usb.backend.libusb1 m3500a_gui.py
```
产物 `dist/M3500A_GUI.exe`。自检：`M3500A_GUI.exe --selftest` 会把结果写到 exe 同目录的 `m3500a_selftest.txt`。

---

## 仓库结构

```
.
├── m3500a.py            # 低层 SCPI-over-USB 驱动 (+ CLI demo)
├── m3500a_gui.py        # Tkinter 上位机
├── planB_usb_probe.py   # 端点/分帧探测脚本
├── requirements.txt
├── README.md            # 本文件
└── 归档说明.md           # 完整的逆向/调研过程记录
```

---

## 命令支持矩阵（固件 1.0G 实测）

- ✅ 全部支持：`MEAS`/`CONF`、`SENS:*`（NPLC/RANG*、RES、DET:BAND、ZERO/GAIN:AUTO、INP:IMP:AUTO）、`UNIT`、`TEMP:TRAN`、`TEMP:RTD:*`、`TEMP:SPRTD:*`、`CALC:*`、`TRIG:*`、`SAMP:COUN`、`DATA:*`、`DISP*`、`SYST:*`、`*ESE/*SRE/*PSC/*ESR/*STB`、`STAT:QUES:*`、`ROUT:TERM?`、`CONF?`、`FUNC?`
- ❌ 不支持：**热电偶 `TCOU:*`**（`TCOU:TYPE`、`TCOU:RJUN:RSEL/SIM/REAL:OFFS`）→ `-113 Undefined header`

---

## 免责声明 / Disclaimer

- 本项目**不包含**任何厂商固件、手册或安装包（版权归 PICOTEST / Array / Keithley 所有）。
- **刷写固件有变砖风险**，且固件与校准数据位于同一片 flash（MX29LV400），跨大版本刷新可能影响校准；本项目**不提供**也**不建议**刷写工具。
- 一切操作风险自负。

# 本项目由dpsk4.1f创建

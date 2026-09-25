#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PICOTEST M3500A 6.5-digit DMM - USB SCPI driver (firmware 1.x, vendor-specific USB).

The 1.x firmware exposes a plain "SCPI over bulk/interrupt" byte pipe:
    host -> EP 0x02 (bulk OUT)   : command bytes (e.g. b"*IDN?\\n")
    host <- EP 0x82 (bulk IN)    : response bytes
(EP 0x01/0x81 interrupt also works.)

Requirements:
    - Zadig installed WinUSB for VID_164E / PID_0DAC
    - pip install pyusb libusb-package

Usage demo:  python m3500a.py
"""
import sys
import time

try:
    import libusb_package
    BACKEND = libusb_package.get_libusb1_backend()
except Exception:
    BACKEND = None

import usb.core
import usb.util

VID, PID = 0x164E, 0x0DAC
EP_OUT, EP_IN = 0x02, 0x82          # bulk (use 0x01/0x81 for interrupt if you prefer)


class M3500A:
    def __init__(self, read_timeout_ms=1500):
        kw = dict(idVendor=VID, idProduct=PID)
        if BACKEND is not None:
            kw["backend"] = BACKEND
        self.dev = usb.core.find(**kw)
        if self.dev is None:
            raise RuntimeError("M3500A not found (is WinUSB installed via Zadig?)")
        try:
            self.dev.set_configuration()
        except Exception:
            pass
        try:
            usb.util.claim_interface(self.dev, 0)
        except Exception:
            pass
        self.read_timeout_ms = read_timeout_ms

    def write(self, cmd):
        if isinstance(cmd, str):
            cmd = cmd.encode()
        if not cmd.endswith(b"\n"):
            cmd = cmd + b"\n"
        self.dev.write(EP_OUT, cmd, timeout=2000)

    def read(self, maxlen=256):
        """Read one response; loop until a short timeout means 'no more data'."""
        chunks = []
        deadline = time.time() + self.read_timeout_ms / 1000.0
        while time.time() < deadline:
            try:
                data = self.dev.read(EP_IN, maxlen, timeout=300)
                chunks.append(bytes(data))
                if len(data) < maxlen:      # short packet -> end of response
                    break
            except usb.core.USBTimeoutError:
                if chunks:
                    break
            except Exception as e:
                raise RuntimeError("USB read error: %s" % e)
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

    # convenience
    def idn(self):
        return self.query("*IDN?")

    def read_dcv(self):
        self.write("CONF:VOLT:DC")
        return self.query("READ?")


def main():
    dmm = M3500A()
    try:
        print("IDN        :", dmm.idn())
        print("DCV sample :", dmm.read_dcv(), "V")
        print("\n--- 10 readings ---")
        for i in range(10):
            print("  %2d: %s V" % (i + 1, dmm.read_dcv()))
            time.sleep(0.2)
    finally:
        dmm.close()


if __name__ == "__main__":
    main()

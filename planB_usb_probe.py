#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3500A (VID_164E / PID_0DAC, firmware 1.0G) USB probe - Plan B.

Prereq:
  1) Zadig installed WinUSB for this device.
  2) pip install pyusb libusb-package

Run:  python planB_usb_probe.py
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


def find_dev():
    kw = dict(idVendor=VID, idProduct=PID)
    if BACKEND is not None:
        kw["backend"] = BACKEND
    dev = usb.core.find(**kw)
    if dev is None:
        print("[!] Device not found.")
        print("    - Did Zadig install WinUSB for VID_164E/PID_0DAC ?")
        print("    - Try: python -m pip install libusb-package")
        sys.exit(1)
    return dev


def show(dev):
    print("Device %04X:%04X  bcdUSB=%04X  bcdDevice=%04X" %
          (dev.idVendor, dev.idProduct, dev.bcdUSB, dev.bcdDevice))
    for cfg in dev:
        print("  Config %d  (bmAttributes=0x%02X MaxPower=%d)" %
              (cfg.bConfigurationValue, cfg.bmAttributes, cfg.bMaxPower))
        for intf in cfg:
            print("    Interface %d  class=0x%02X sub=0x%02X prot=0x%02X" %
                  (intf.bInterfaceNumber, intf.bInterfaceClass,
                   intf.bInterfaceSubClass, intf.bInterfaceProtocol))
            for ep in intf:
                print("      EP 0x%02X  attr=0x%02X  maxpkt=%d" %
                      (ep.bEndpointAddress, ep.bmAttributes, ep.wMaxPacketSize))


def one(dev, ep_out, ep_in, payload, wait=0.15, read_len=128):
    try:
        dev.write(ep_out, payload, timeout=1500)
    except Exception as e:
        return "WRITE-ERR: %s" % e
    time.sleep(wait)
    try:
        data = dev.read(ep_in, read_len, timeout=1500)
        return "OK  read %d bytes: %r" % (len(data), bytes(data))
    except Exception as e:
        return "READ-ERR: %s" % e


def variants(cmd):
    out = []
    out.append(("raw", cmd))
    out.append(("crlf", cmd + b"\r\n"))
    out.append(("lf", cmd + b"\n"))
    out.append(("pad16", cmd + b"\x00" * (16 - len(cmd))))
    out.append(("pad64", cmd + b"\x00" * (64 - len(cmd))))
    out.append(("len+raw", bytes([len(cmd)]) + cmd))
    out.append(("raw+len", cmd + bytes([len(cmd)])))
    return out


def main():
    dev = find_dev()
    show(dev)
    try:
        dev.set_configuration()
    except Exception as e:
        print("set_configuration:", e)
    try:
        usb.util.claim_interface(dev, 0)
    except Exception as e:
        print("claim_interface:", e)

    endpoints_out = [0x01, 0x02]
    endpoints_in = [0x81, 0x82]
    cmds = [b"*IDN?", b"*idn?"]

    found = []
    for ep_out in endpoints_out:
        for ep_in in endpoints_in:
            for cmd in cmds:
                for name, p in variants(cmd):
                    r = one(dev, ep_out, ep_in, p)
                    print("OUT %02X IN %02X %-7s len=%2d -> %s" %
                          (ep_out, ep_in, name, len(p), r))
                    if r.startswith("OK"):
                        found.append((ep_out, ep_in, name, p, r))

    print("\n==== SUMMARY ====")
    if not found:
        print("No response on any framing. Next: capture the vendor protocol from")
        print("DmmUpdate.exe / ins003.dll with x86dbg (bp DeviceIoControl).")
    else:
        for f in found:
            print("HIT ep_out=%02X ep_in=%02X %s -> %s" % (f[0], f[1], f[2], f[4]))


if __name__ == "__main__":
    main()

"""
SVC Vegetables — Shop Print Agent
=================================
Runs on the shop's Windows PC (the one the GOBBLER 80mm printer is plugged into).
Watches MongoDB for print jobs queued by the web app and prints them with
auto-cut after every bill.

One-time setup on the shop PC:
  1. Install Python from python.org (tick "Add Python to PATH").
  2. Install the GOBBLER Windows driver normally (so it appears in
     Windows Settings > Printers).
  3. In a command prompt, in this folder:
        pip install -r requirements_agent.txt
  4. Run:
        python print_agent.py
     First run asks for the MongoDB link and which printer to use, then
     remembers both in agent_config.json.
  5. (Optional) Auto-start: press Win+R, type  shell:startup , and place a
     shortcut to print_agent.py there.

Keep this window open while the shop is running — it prints jobs within seconds.
"""
import io
import json
import logging
import os
import sys
import time
from datetime import datetime

logging.getLogger("escpos").setLevel(logging.ERROR)

import pymongo
import pypdfium2 as pdfium

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_config.json")
DRY_RUN = os.environ.get("AGENT_DRY_RUN") == "1"      # test mode: no real printer needed


# ── printing backends ─────────────────────────────────────────────────────────
def list_windows_printers():
    import win32print
    return [p[2] for p in win32print.EnumPrinters(
        win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]


def make_printer(cfg):
    """Return an escpos printer object for this machine."""
    if DRY_RUN:
        from escpos.printer import Dummy
        return Dummy()
    if sys.platform == "win32":
        # Raw bytes through the installed Windows driver queue — most reliable on Windows
        from escpos.printer import Win32Raw
        return Win32Raw(cfg["printer_name"])
    # Non-Windows fallback: direct USB (used for testing the agent on Mac/Linux)
    from escpos.printer import Usb
    usb_args = {}
    try:
        import libusb_package
        usb_args["backend"] = libusb_package.get_libusb1_backend()
    except Exception:
        pass
    return Usb(int(cfg.get("usb_vid", 0)), int(cfg.get("usb_pid", 0)), usb_args=usb_args)


def pdf_to_thermal_images(pdf_bytes):
    """Rasterize PDF pages at 8 dots/mm, crop 4mm margins -> 576-dot 1-bit images."""
    doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    images = []
    try:
        for page in doc:
            pil = page.render(scale=8 / 2.8346).to_pil()
            g = pil.convert("L")
            w, h = g.size
            crop = round(w * 4 / 80)
            g = g.crop((crop, 0, min(crop + 576, w), h))
            images.append(g.point(lambda x: 0 if x < 160 else 255, mode="1"))
    finally:
        doc.close()
    return images


def print_job(cfg, pdf_bytes):
    images = pdf_to_thermal_images(pdf_bytes)
    p = make_printer(cfg)
    try:
        for img in images:
            p.image(img)
            p.cut()
        if DRY_RUN:
            print(f"    [dry-run] would print {len(images)} bill(s), "
                  f"{len(p.output):,} ESC/POS bytes")
    finally:
        try:
            p.close()
        except Exception:
            pass
    return len(images)


# ── config ────────────────────────────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_FILE):
        return json.load(open(CONFIG_FILE))
    print("=== First-time setup ===")
    cfg = {"MONGO_URI": input("Paste your MONGO_URI (same as the app's secrets): ").strip()}
    if sys.platform == "win32" and not DRY_RUN:
        printers = list_windows_printers()
        if not printers:
            print("No Windows printers found — install the GOBBLER driver first.")
            sys.exit(1)
        print("Installed printers:")
        for i, name in enumerate(printers):
            print(f"  {i + 1}. {name}")
        guess = next((i for i, n in enumerate(printers)
                      if any(k in n.upper() for k in ("GOBBLER", "80", "POS", "THERMAL"))), 0)
        sel = input(f"Printer number [{guess + 1}]: ").strip()
        cfg["printer_name"] = printers[int(sel) - 1 if sel else guess]
    json.dump(cfg, open(CONFIG_FILE, "w"), indent=2)
    print(f"Saved to {CONFIG_FILE}\n")
    return cfg


# ── main loop ─────────────────────────────────────────────────────────────────
def main():
    cfg = load_config()
    client = pymongo.MongoClient(cfg["MONGO_URI"], serverSelectionTimeoutMS=10000,
                                 tlsAllowInvalidCertificates=True)
    db = client["svc_vegetables"]
    try:
        db.print_jobs.create_index([("status", 1), ("created_at", 1)])
    except Exception:
        pass
    mode = "DRY-RUN (no printer)" if DRY_RUN else (
        f"printer: {cfg.get('printer_name')}" if sys.platform == "win32" else "USB")
    print(f"✅ Agent running — {mode}. Waiting for print jobs… (close this window to stop)")
    while True:
        try:
            job = db.print_jobs.find_one_and_update(
                {"status": "pending"}, {"$set": {"status": "printing"}},
                sort=[("created_at", 1)])
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] ⚠️ network problem ({str(e)[:80]}) — retrying in 10s…")
            time.sleep(10)
            continue
        if job is None:
            time.sleep(3)
            continue
        label = job.get("label", "?")
        print(f"[{datetime.now():%H:%M:%S}] printing: {label} ({job.get('n_bills', '?')} bills)…")
        try:
            n = print_job(cfg, bytes(job["pdf"]))
            db.print_jobs.update_one({"_id": job["_id"]},
                                     {"$set": {"status": "done", "done_at": datetime.now()}})
            print(f"    ✅ done — {n} bill(s) cut")
        except Exception as e:
            try:
                db.print_jobs.update_one({"_id": job["_id"]},
                                         {"$set": {"status": "error", "error": str(e)[:300]}})
            except Exception:
                pass
            print(f"    ❌ FAILED: {e}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAgent stopped.")
    except Exception as fatal:
        print(f"\n❌ Agent could not start: {fatal}")
        try:
            input("Press Enter to close…")   # keep the window open so the error is readable
        except Exception:
            pass

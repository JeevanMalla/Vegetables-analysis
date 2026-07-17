"""Direct ESC/POS printing (USB/LAN) and the cloud→shop print-job queue."""
from datetime import datetime

from . import database as dbs

try:
    from escpos.printer import Network as EscposNetwork
    from escpos.printer import Usb as EscposUsb
    import pypdfium2 as pdfium
    ESCPOS_AVAILABLE = True
except Exception:
    ESCPOS_AVAILABLE = False


def _usb_backend():
    """libusb backend bundled via pip (no brew needed)."""
    try:
        import libusb_package
        return libusb_package.get_libusb1_backend()
    except Exception:
        return None


def detect_usb_printers():
    """List attached USB devices; printer-class (7) devices marked as likely printers."""
    import usb.core, usb.util
    found = []
    for d in usb.core.find(find_all=True, backend=_usb_backend()):
        try:
            name = usb.util.get_string(d, d.iProduct) if d.iProduct else ""
        except Exception:
            name = ""
        is_printer = d.bDeviceClass == 7
        if not is_printer:
            try:
                for cfg in d:
                    for intf in cfg:
                        if intf.bInterfaceClass == 7:
                            is_printer = True
            except Exception:
                pass
        found.append({"vid": d.idVendor, "pid": d.idProduct,
                      "name": name or "Unknown device", "printer": is_printer})
    return sorted(found, key=lambda x: not x["printer"])


# ══════════════════════════════════════════════════════════════
# DIRECT ESC/POS PRINTING (GOBBLER 80mm over LAN, port 9100)
# ══════════════════════════════════════════════════════════════
def pdf_to_thermal_images(pdf_bytes):
    """
    Rasterize each PDF page at true thermal resolution: 8 dots/mm (203 dpi),
    crop the 4mm page margins → 576-dot-wide 1-bit images, ready for ESC/POS.
    """
    doc = pdfium.PdfDocument(pdf_bytes)
    images = []
    try:
        for page in doc:
            # scale = px per pt; 8 dots/mm ÷ 2.8346 pt/mm
            pil = page.render(scale=8 / 2.8346).to_pil()
            g = pil.convert("L")
            w, h = g.size
            crop = round(w * 4 / 80)          # the 4mm left/right page margins
            g = g.crop((crop, 0, min(crop + 576, w), h))   # exactly 576 dots = 72mm printable
            images.append(g.point(lambda x: 0 if x < 160 else 255, mode='1'))
    finally:
        doc.close()
    return images


def print_images_escpos(images, host, port=9100):
    """Send raster images to the printer over LAN, auto-cutting after each one."""
    p = EscposNetwork(host, port=int(port), timeout=10)
    try:
        for img in images:
            p.image(img)
            p.cut()
    finally:
        try:
            p.close()
        except Exception:
            pass


def queue_print_job(pdf_bytes, n_bills, label):
    """Store a print job in MongoDB for the shop print agent (print_agent.py)."""
    from bson.binary import Binary
    dbs.db.print_jobs.insert_one({
        "created_at": datetime.now(), "label": label, "n_bills": int(n_bills),
        "pdf": Binary(pdf_bytes), "status": "pending", "error": ""})


def print_images_escpos_usb(images, vid, pid):
    """Send raster images to the USB-connected printer, auto-cutting after each one."""
    be = _usb_backend()
    usb_args = {"backend": be} if be else {}
    p = EscposUsb(vid, pid, usb_args=usb_args, timeout=10000)
    try:
        for img in images:
            p.image(img)
            p.cut()
    finally:
        try:
            p.close()
        except Exception:
            pass

"""Bills tab."""
from ..common import *  # noqa: F401,F403


def render(ctx):
    a = ctx.get("a"); sales = ctx.get("sales"); receipts = ctx.get("receipts")
    active_date = ctx.get("active_date"); all_dates = ctx.get("all_dates")
    LATEST_DATE = ctx.get("LATEST_DATE")

    st.markdown('<div class="sec">🖨️ CUSTOMER BILLS — 80mm (3-INCH) THERMAL PRINTER</div>', unsafe_allow_html=True)
    st.caption("One bill per customer, one page each — the printer's auto-cutter separates them. "
               "Print the PDF at **100% scale / actual size** (no fit-to-page) on the GOBBLER 80mm printer.")

    if not FPDF_AVAILABLE:
        st.error("PDF library missing. Run: `pip install fpdf2` and restart the app.")
    else:
        _bill_def = (datetime.strptime(active_date, "%Y-%m-%d").date()
                     if active_date else date.today())
        pb1, pb2, pb3 = st.columns(3)
        with pb1:
            bill_date = st.date_input("Bill Date", value=_bill_def, key="bill_date")
        bill_date_str = bill_date.strftime("%Y-%m-%d")

        bill_sdf, bill_rdf = load_data(bill_date_str)
        if bill_sdf is None or bill_sdf.empty:
            st.info(f"No sales data for {bill_date_str}. Upload/import sales for this date first.")
        else:
            _bnames = sorted(set(bill_sdf['Name'].unique()) - EXCLUDE_CUSTOMERS)
            _bamap = {}
            if dbs.MONGO_AVAILABLE:
                for _doc in dbs.db.customers.find({}, {"_id": 0, "name": 1, "area": 1}):
                    _bamap[_doc.get("name")] = _doc.get("area", "")
            if bill_rdf is not None and not bill_rdf.empty:
                _bamap.update(dict(zip(bill_rdf['Name'], bill_rdf['Schedule'])))
            _bareas = sorted({str(_bamap.get(n, "")) for n in _bnames if _bamap.get(n, "")})

            with pb2:
                bill_area = st.selectbox("Area / Schedule", ["All Areas"] + _bareas, key="bill_area")
            with pb3:
                bill_cust = st.selectbox("Single Customer (optional)",
                                         ["All Customers"] + _bnames, key="bill_cust")

            if bill_cust != "All Customers":
                _n_bills = 1
            elif bill_area != "All Areas":
                _n_bills = sum(1 for n in _bnames if _bamap.get(n, "") == bill_area)
            else:
                _n_bills = len(_bnames)
            st.caption(f"**{_n_bills}** bill(s) will be generated · each bill shows: previous day cash, "
                       f"opening balance, item lines (bags/kgs/rate/amount), today's total, "
                       f"closing balance (opening + today's sales) and running balance "
                       f"(prev running bal + today's sales) — hand to the buyer in the evening "
                       f"when collecting cash.")

            if st.button("🖨️ Generate Bills PDF", type="primary", use_container_width=True):
                with st.spinner("Building bills…"):
                    _pdf_bytes, _n = build_bills_pdf(
                        bill_date_str,
                        area=None if bill_area == "All Areas" else bill_area,
                        customer=None if bill_cust == "All Customers" else bill_cust)
                if _pdf_bytes:
                    _tag = (bill_cust if bill_cust != "All Customers"
                            else bill_area if bill_area != "All Areas" else "ALL")
                    _fname = f"bills_{_tag}_{bill_date_str}.pdf".replace(" ", "_").replace("/", "-")
                    st.session_state["bills_pdf"] = (_fname, _pdf_bytes, _n)
                else:
                    st.session_state.pop("bills_pdf", None)
                    st.warning("No bills matched that selection.")

            if "bills_pdf" in st.session_state:
                _fname, _data, _n = st.session_state["bills_pdf"]
                st.success(f"✅ {_n} bill(s) ready — {_fname}")
                st.download_button("⬇️ Download Bills PDF (backup)", data=_data, file_name=_fname,
                                   mime="application/pdf", use_container_width=True,
                                   key="bills_dl")

            # ── DIRECT ESC/POS PRINTING — no PDF, no driver, auto-cut ──
            st.markdown('<div class="sec">🖨️ DIRECT PRINT — ESC/POS</div>', unsafe_allow_html=True)
            st.caption("Auto-cutter fires after every bill · no PDF scaling, no driver dialogs.")
            conn_kind = st.radio(
                "Where is the printer?",
                ["🏪 Shop printer (app runs on website/cloud)", "USB (this computer)", "LAN (network)"],
                horizontal=True, key="printer_conn")

            if conn_kind.startswith("🏪"):
                st.caption("Jobs go through MongoDB to the **print agent** running on the shop's Windows PC "
                           "(`print_agent.py` — one-time setup). Click Print here, bills come out there.")
                if not dbs.MONGO_AVAILABLE:
                    st.error("Database connection needed for shop printing.")
                elif st.button(f"🖨️ Print {_n_bills} bill(s) on SHOP printer", type="primary",
                               use_container_width=True, key="print_shop"):
                    with st.spinner("Building bills…"):
                        _pb, _pn = build_bills_pdf(
                            bill_date_str,
                            area=None if bill_area == "All Areas" else bill_area,
                            customer=None if bill_cust == "All Customers" else bill_cust)
                    if not _pb:
                        st.warning("No bills matched that selection.")
                    else:
                        _tag2 = (bill_cust if bill_cust != "All Customers"
                                 else bill_area if bill_area != "All Areas" else "ALL")
                        queue_print_job(_pb, _pn, f"Bills {_tag2} {bill_date_str}")
                        st.success(f"✅ {_pn} bill(s) queued — the shop printer will start within a few seconds "
                                   f"(if the agent is running).")
                if dbs.MONGO_AVAILABLE:
                    _jobs = list(dbs.db.print_jobs.find({}, {"pdf": 0}).sort("created_at", -1).limit(5))
                    if _jobs:
                        _jdf = pd.DataFrame([{
                            "Time": j["created_at"].strftime("%d %b %H:%M:%S"),
                            "Job": j.get("label", ""), "Bills": j.get("n_bills", 0),
                            "Status": {"pending": "⏳ waiting for agent", "printing": "🖨️ printing…",
                                       "done": "✅ printed", "error": "❌ " + str(j.get("error", ""))[:60]
                                       }.get(j.get("status"), j.get("status")),
                        } for j in _jobs])
                        st.dataframe(_jdf, use_container_width=True, hide_index=True)
                        _oldest_pending = next((j for j in reversed(_jobs) if j.get("status") == "pending"), None)
                        if _oldest_pending and (datetime.now() - _oldest_pending["created_at"]).total_seconds() > 60:
                            st.warning("A job has been waiting over a minute — is `print_agent.py` running "
                                       "on the shop computer?")
                        if st.button("🔄 Refresh status", key="jobs_refresh"):
                            st.rerun()

            elif not ESCPOS_AVAILABLE:
                st.error("Direct printing needs: `pip install python-escpos pypdfium2 pyusb libusb-package` "
                         "— then restart the app.")
            elif conn_kind == "USB (this computer)":
                    _vid, _pid = get_printer_usb()
                    u1, u2 = st.columns([1, 2])
                    with u1:
                        if st.button("🔍 Detect USB printer", use_container_width=True, key="usb_detect"):
                            try:
                                _devs = detect_usb_printers()
                            except Exception as _de:
                                _devs = []
                                st.error(f"USB scan failed: {_de}")
                            _printers = [d for d in _devs if d["printer"]]
                            if _printers:
                                _d0 = _printers[0]
                                set_printer_usb(_d0["vid"], _d0["pid"])
                                st.success(f"✅ Found: {_d0['name']} "
                                           f"(vid=0x{_d0['vid']:04x}, pid=0x{_d0['pid']:04x}) — saved.")
                                _vid, _pid = _d0["vid"], _d0["pid"]
                            elif _devs:
                                st.warning("No printer-class device found. Devices seen: " +
                                           ", ".join(f"{d['name']} (0x{d['vid']:04x}:0x{d['pid']:04x})"
                                                     for d in _devs[:6]) +
                                           " — plug the printer in and switch it on, then detect again.")
                            else:
                                st.warning("No USB devices visible — plug the printer in, switch it on, "
                                           "and click Detect again.")
                    with u2:
                        if _vid:
                            st.caption(f"Saved printer: vid=0x{_vid:04x} · pid=0x{_pid:04x} — ready to print.")
                        else:
                            st.caption("No USB printer saved yet — plug it in and click Detect (one-time setup).")

                    if st.button(f"🖨️ Print {_n_bills} bill(s) NOW via USB", type="primary",
                                 use_container_width=True, key="print_now_usb",
                                 disabled=not _vid):
                        with st.spinner("Building bills…"):
                            _pb, _pn = build_bills_pdf(
                                bill_date_str,
                                area=None if bill_area == "All Areas" else bill_area,
                                customer=None if bill_cust == "All Customers" else bill_cust)
                        if not _pb:
                            st.warning("No bills matched that selection.")
                        else:
                            try:
                                with st.spinner(f"Printing {_pn} bill(s)…"):
                                    _imgs = pdf_to_thermal_images(_pb)
                                    print_images_escpos_usb(_imgs, _vid, _pid)
                                st.success(f"✅ {_pn} bill(s) printed via USB — each one auto-cut.")
                            except Exception as _pe:
                                st.error(f"USB printing failed: {_pe}. Make sure the printer is on and "
                                         f"NOT added in macOS System Settings → Printers (the system can "
                                         f"lock the USB port); unplug/replug and Detect again. "
                                         f"The PDF download below always works as backup.")

            else:  # LAN
                    dp1, dp2 = st.columns([3, 1])
                    with dp1:
                        printer_ip = st.text_input("Printer IP address", value=get_printer_ip(),
                                                   placeholder="e.g. 192.168.0.100", key="printer_ip_in")
                    with dp2:
                        printer_port = st.number_input("Port", value=9100, min_value=1, max_value=65535,
                                                       key="printer_port")
                    if st.button(f"🖨️ Print {_n_bills} bill(s) NOW via LAN", type="primary",
                                 use_container_width=True, key="print_now"):
                        if not printer_ip.strip():
                            st.error("Enter the printer's IP address first (print the printer self-test page to find it).")
                        else:
                            set_printer_ip(printer_ip.strip())
                            with st.spinner("Building bills…"):
                                _pb, _pn = build_bills_pdf(
                                    bill_date_str,
                                    area=None if bill_area == "All Areas" else bill_area,
                                    customer=None if bill_cust == "All Customers" else bill_cust)
                            if not _pb:
                                st.warning("No bills matched that selection.")
                            else:
                                try:
                                    with st.spinner(f"Printing {_pn} bill(s)…"):
                                        _imgs = pdf_to_thermal_images(_pb)
                                        print_images_escpos(_imgs, printer_ip.strip(), int(printer_port))
                                    st.success(f"✅ {_pn} bill(s) sent to {printer_ip} — each one auto-cut.")
                                except Exception as _pe:
                                    st.error(f"Printing failed: {_pe}. Check the IP / LAN cable "
                                             f"(printer must be on the same network), or use the PDF download.")


# ─────────────────────────────────────────────────────────────
# TAB 2 — RUNNING BALANCE
# ─────────────────────────────────────────────────────────────

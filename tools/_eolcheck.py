import pathlib
for f in ["ocobot/ui/i18n.py","ocobot/ui/monitoring.py","ocobot/ui/btc_slippage_tracker.py","tests/test_g1_50_btc_slippage.py"]:
    d=pathlib.Path(f).read_bytes()
    lines=d.split(b"\n")
    crlf=sum(1 for l in lines if l.endswith(b"\r"))
    print(f, "CRLF" if crlf>0 and crlf>=len(lines)-2 else ("LF" if crlf==0 else "MIXED(%d/%d)"%(crlf,len(lines))))

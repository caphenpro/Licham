"""Lịch Âm Dương + Bát Tự (Skyfield NASA DE421) - Giao diện Web đơn giản, gọn nhẹ.

Cách chạy:
  python newfile.py
  python newfile.py --port 8080 --tz 7
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import battu_cli
from amlich.precise import TIET_KHI, new_moons, solar_terms
from battu_cli import am_lich, can_chi_nam, lap_tu_tru
from skyfield.api import Loader
from skyfield.almanac import moon_phases, find_discrete

THU = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

# ==========================================
# [VẤN ĐỀ 1]: Khởi tạo Skyfield & Ephemeris (NASA DE421)
# ==========================================
load = Loader(os.path.join(os.path.expanduser("~"), ".battu_jpl"))
ts = load.timescale()
eph = load("de421.bsp")
earth, sun, moon = eph["earth"], eph["sun"], eph["moon"]

def skyfield_solar_longitude(dt: datetime) -> float:
    """Tính kinh độ Mặt Trời biểu kiến chính xác bằng Skyfield."""
    t = ts.from_datetime(dt.astimezone(timezone.utc))
    _, lon, _ = earth.at(t).observe(sun).apparent().ecliptic_latlon(epoch="date")
    return lon.degrees % 360

battu_cli.solar_longitude = skyfield_solar_longitude

TEN_TIET = {lon: ten for ten, lon in TIET_KHI}

def _kinh_do_mang(t):
    """Hỗ trợ mảng tính toán kinh độ cho hàm tìm kiếm tiết khí."""
    _, lon, _ = earth.at(t).observe(sun).apparent().ecliptic_latlon(epoch="date")
    return lon.degrees

def _chi_so_tiet(t):
    """Xác định mốc chia 15 độ của các tiết khí."""
    return (_kinh_do_mang(t) // 15).astype(int)

_chi_so_tiet.step_days = 5.0

# ==========================================
# [VẤN ĐỀ 2]: Tính toán Pha Trăng & Độ sáng
# ==========================================
def pha_trang(dt: datetime) -> tuple[str, float]:
    """Tính tên hình thái pha trăng và phần trăm độ chiếu sáng."""
    t = ts.from_datetime(dt.astimezone(timezone.utc))
    e = earth.at(t)
    _, sun_lon, _ = e.observe(sun).apparent().ecliptic_latlon(epoch="date")
    _, moon_lon, _ = e.observe(moon).apparent().ecliptic_latlon(epoch="date")
    deg = (moon_lon.degrees - sun_lon.degrees) % 360
    ten = [
        "Trăng mới", "Trăng lưỡi liềm đầu tháng", "Trăng bán nguyệt đầu tháng", "Trăng khuyết tròn dần",
        "Trăng tròn", "Trăng khuyết nhỏ dần", "Trăng bán nguyệt cuối tháng", "Trăng lưỡi liềm cuối tháng"
    ]
    ten_pha = ten[int(((deg + 22.5) % 360) // 45)]
    try:
        sang = moon.at(t).fraction_illuminated(sun)
    except Exception:
        import math
        sang = (1 - math.cos(math.radians(deg))) / 2.0
    return ten_pha, sang

# ==========================================
# [VẤN ĐỀ 3]: Tính thời điểm Sóc (Trăng mới) trước/sau
# ==========================================
def soc_quanh(dt: datetime, tz_offset: float):
    """Tìm ngày Sóc gần nhất trước và sau thời điểm đang xét."""
    zone = timezone(timedelta(hours=tz_offset))
    t0 = ts.from_datetime((dt - timedelta(days=35)).astimezone(timezone.utc))
    t1 = ts.from_datetime((dt + timedelta(days=35)).astimezone(timezone.utc))
    try:
        times, phases = find_discrete(t0, t1, moon_phases(eph))
        new_moons_dt = [t.astimezone(zone) for t, p in zip(times, phases) if p == 0]
        past = [m for m in new_moons_dt if m <= dt.astimezone(zone)]
        future = [m for m in new_moons_dt if m > dt.astimezone(zone)]
        return (past[-1] if past else dt - timedelta(days=30)), (future[0] if future else dt + timedelta(days=30))
    except Exception:
        ms = new_moons(dt - timedelta(days=35), dt + timedelta(days=35))
        return max(m for m in ms if m <= dt), min(m for m in ms if m > dt)

# ==========================================
# [VẤN ĐỀ 4]: Tính toán 24 Tiết Khí quanh thời điểm chọn
# ==========================================
def tiet_khi_quanh(dt: datetime, tz_offset: float) -> dict:
    """Xác định tiết khí hiện tại, tiến độ và tiết khí kế tiếp."""
    zone = timezone(timedelta(hours=tz_offset))
    dt = dt.astimezone(zone)
    nguon = "NASA/JPL DE421 (Skyfield)"
    try:
        t0 = ts.from_datetime((dt - timedelta(days=50)).astimezone(timezone.utc))
        t1 = ts.from_datetime((dt + timedelta(days=50)).astimezone(timezone.utc))
        times, idx = find_discrete(t0, t1, _chi_so_tiet)
        ds = [((int(k) * 15) % 360, t.astimezone(zone)) for t, k in zip(times, idx)]
        if len(ds) < 4:
            raise RuntimeError()
    except Exception:
        nguon = "astronomy-engine (dự phòng)"
        ds = []
        lon_cua = {ten: lon for ten, lon in TIET_KHI}
        for y in (dt.year - 1, dt.year, dt.year + 1):
            ds += [(lon_cua[n], g) for n, g in solar_terms(y, tz_offset)]
    ds.sort(key=lambda x: x[1])

    def truoc(lst): return max((x for x in lst if x[1] <= dt), key=lambda x: x[1])
    def sau(lst): return min((x for x in lst if x[1] > dt), key=lambda x: x[1])

    thang = [x for x in ds if x[0] % 30 == 15]
    return {"hien_tai": truoc(ds), "ke_tiep": sau(ds), "tiet_truoc": truoc(thang), "tiet_sau": sau(thang), "nguon": nguon}

def fmt_delta(td: timedelta) -> str:
    """Định dạng khoảng thời gian delta thành chuỗi ngày giờ dễ đọc."""
    s = int(td.total_seconds())
    return f"{s // 86400} ngày {s % 86400 // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"

HANH_CAN = {"Giáp": "moc", "Ất": "moc", "Bính": "hoa", "Đinh": "hoa", "Mậu": "tho", "Kỷ": "tho", "Canh": "kim", "Tân": "kim", "Nhâm": "thuy", "Quý": "thuy"}
HANH_CHI = {"Dần": "moc", "Mão": "moc", "Tị": "hoa", "Ngọ": "hoa", "Thìn": "tho", "Tuất": "tho", "Sửu": "tho", "Mùi": "tho", "Thân": "kim", "Dậu": "kim", "Hợi": "thuy", "Tý": "thuy"}

def _tru_json(text: str) -> dict:
    """Chuyển đổi chuỗi Can Chi thành dạng cấu trúc JSON kèm ngũ hành để gán màu sắc."""
    can, chi = text.split()
    return {"can": can, "chi": chi, "hc": HANH_CAN[can], "hz": HANH_CHI[chi]}

# ==========================================
# [VẤN ĐỀ 5]: Tổng hợp dữ liệu trả về cho Web API
# ==========================================
def du_lieu(dt: datetime, tz: float, ty_som: bool) -> dict:
    r = lap_tu_tru(dt, tz, ty_som)
    dt = r["dt"]
    ngay, thang, nhuan, nam = am_lich(dt.date(), tz)
    cn, cc = can_chi_nam(nam)
    ten_trang, sang = pha_trang(dt)
    soc_truoc, soc_sau = soc_quanh(dt, tz)
    tk = tiet_khi_quanh(dt, tz)
    tt, ts_ = tk["tiet_truoc"], tk["tiet_sau"]
    (lon_ht, bd_ht), (lon_kt, bd_kt) = tk["hien_tai"], tk["ke_tiep"]
    tien_do = max(0.0, min(100.0, ((r["kinh_do"] - lon_ht) % 360) / 15 * 100))
    loai = lambda lon: "Trung khí" if lon % 30 == 0 else "Tiết"
    zone = dt.tzinfo
    return {
        "iso": dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "duong": {"thu": THU[dt.weekday()], "ngay": dt.strftime("%d/%m/%Y"), "gio": dt.strftime("%H:%M:%S"), "tz": f"UTC{tz:+g}"},
        "am": {"ngay": ngay, "thang": thang, "nhuan": nhuan, "nam": nam, "nam_cc": {"can": cn, "chi": cc, "hc": HANH_CAN[cn], "hz": HANH_CHI[cc]}},
        "tru": {"gio": _tru_json(r["tru_gio"]), "ngay": _tru_json(r["tru_ngay"]), "thang": _tru_json(r["tru_thang"]), "nam": _tru_json(r["tru_nam"]), "nam_bat_tu": r["nam_bat_tu"]},
        "tiet_khi": {"ten": TEN_TIET[lon_ht], "loai": loai(lon_ht), "kinh_do": lon_ht, "bat_dau": bd_ht.strftime("%d/%m/%Y %H:%M:%S"), "da_qua": fmt_delta(dt - bd_ht), "tien_do": round(tien_do, 1), "ke_tiep": TEN_TIET[lon_kt], "ke_tiep_loai": loai(lon_kt), "ke_tiep_kd": lon_kt, "ke_tiep_gio": bd_kt.strftime("%d/%m/%Y %H:%M:%S"), "con": fmt_delta(bd_kt - dt)},
        "mat_troi": {"kinh_do": round(r["kinh_do"], 4), "tiet_truoc": [TEN_TIET[tt[0]], tt[1].strftime("%d/%m %H:%M:%S")], "tiet_sau": [TEN_TIET[ts_[0]], ts_[1].strftime("%d/%m %H:%M:%S")], "con": fmt_delta(ts_[1] - dt)},
        "trang": {"ten": ten_trang, "sang": round(sang * 100), "soc_truoc": soc_truoc.astimezone(zone).strftime("%d/%m %H:%M:%S"), "tuoi": fmt_delta(dt - soc_truoc), "soc_sau": soc_sau.astimezone(zone).strftime("%d/%m %H:%M:%S")},
        "canh_bao": bool(r["sat_ranh_gioi"]),
        "nguon": "NASA/JPL DE421 (Skyfield). Tiết khí: " + tk["nguon"],
    }

def parse_web_time(s: str, tz: float) -> datetime:
    """Xử lý chuỗi thời gian truyền lên từ giao diện web."""
    zone = timezone(timedelta(hours=tz))
    if not s or not s.strip():
        return datetime.now(zone)
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if len(nums) < 3:
        raise ValueError("Cần nhập ít nhất năm, tháng, ngày")
    nums += [0] * (6 - len(nums))
    return datetime(*nums[:6], tzinfo=zone)

# ==========================================
# [VẤN ĐỀ 6]: Giao diện Web HTML/CSS/JS nhúng
# ==========================================
GIAO_DIEN_HTML = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lịch Âm Dương + Bát Tự</title>
<style>
:root{--bg:#10141a;--card:#1a212b;--line:#2a3441;--txt:#d6dde6;--dim:#7d8b9a;--label:#5fd7ff;--title:#ff7bd5;--moon:#ffd75f;--warn:#ff5f5f;--moc:#5fff87;--hoa:#ff5f5f;--tho:#d7a05f;--kim:#e4e4e4;--thuy:#5f87ff}
body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,sans-serif;line-height:1.45}
.wrap{max-width:720px;margin:0 auto;padding:12px}
h1{font-size:1.2rem;color:var(--title);margin:4px 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:10px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:6px}
label{display:flex;gap:6px;align-items:center;font-size:.85rem}
input,select,button{font-size:.9rem;padding:8px;border-radius:8px;border:1px solid var(--line);background:#0e1218;color:var(--txt)}
button{background:#22405a;cursor:pointer}
.tt{font-weight:700;color:#fff;font-size:1.1rem}
.pillars{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;text-align:center;margin-top:8px}
.p{background:#0e1218;border:1px solid var(--line);border-radius:10px;padding:8px 2px}
.p .n{display:block;color:var(--label);font-size:.7rem}
.p .c{font-size:1.4rem;font-weight:700}
.p .h{display:block;color:var(--dim);font-size:.65rem}
.kv{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px dashed var(--line);font-size:.9rem}
.kv:last-child{border-bottom:0}
.bar{height:8px;background:#0e1218;border-radius:6px;overflow:hidden;margin:6px 0 8px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--label),var(--moon))}
.moon{color:var(--moon);font-weight:700}.dim{color:var(--dim);font-size:.75rem}.warn{color:var(--warn);font-weight:700}
.moc{color:var(--moc)}.hoa{color:var(--hoa)}.tho{color:var(--tho)}.kim{color:var(--kim)}.thuy{color:var(--thuy)}
</style></head><body><div class="wrap">
<h1>Lịch Âm Dương + Bát Tự (NASA Skyfield)</h1>
<div class="card">
 <div class="row">
  <input id="t" type="datetime-local" step="1">
  <button id="tinh">Tính</button><button id="bay">Bây giờ</button>
 </div>
 <div class="row">
  <label><input id="live" type="checkbox" checked> Thời gian thực</label>
  <label><input id="ts" type="checkbox"> 23h tính sang ngày sau</label>
  <label>Múi giờ UTC<select id="tz"></select></label>
 </div>
</div>
<div id="kq"><div class="card">Đang tải...</div></div>
<div class="dim" id="nguon"></div>
</div>
<script>
var H={moc:'Mộc',hoa:'Hỏa',tho:'Thổ',kim:'Kim',thuy:'Thủy'};
function $(i){return document.getElementById(i)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
var sel=$('tz');
for(var z=-12;z<=14;z++){var o=document.createElement('option');o.value=z;o.textContent=(z>=0?'+':'')+z;if(z===7)o.selected=true;sel.appendChild(o)}
function qs(){
 return 'time='+encodeURIComponent($('live'].checked?'':$('t').value)+'&tz='+encodeURIComponent($('tz').value)+'&tysom='+($('ts').checked?1:0);
}
function kv(a,b){return '<div class="kv"><span>'+a+'</span><span>'+b+'</span></div>'}
function tru(nhan,t){
 return '<div class="p"><span class="n">'+nhan+'</span><div class="c '+t.hc+'">'+esc(t.can)+'</div><div class="c '+t.hz+'">'+esc(t.chi)+
  '</div><span class="h">'+H[t.hc]+' · '+H[t.hz]+'</span></div>';
}
function ve(d){
 if(d.loi){$('kq').innerHTML='<div class="card warn">'+esc(d.loi)+'</div>';return}
 var a=d.am,n=a.nam_cc,t=d.tru,m=d.mat_troi,g=d.trang,k=d.tiet_khi;
 if($('live').checked||document.activeElement!==$('t'))$('t').value=d.iso;
 $('kq').innerHTML=
 '<div class="card"><div class="tt">'+esc(d.duong.thu)+', '+d.duong.ngay+' &nbsp;'+d.duong.gio+' <span class="dim">('+d.duong.tz+')</span></div>'+
 '<div class="am">Âm lịch: <b>'+a.ngay+'/'+a.thang+(a.nhuan?' nhuận':'')+'</b> năm <span class="'+n.hc+'">'+esc(n.can)+'</span> <span class="'+n.hz+'">'+esc(n.chi)+'</span></div>'+
 '<div class="pillars">'+tru('Giờ',t.gio)+tru('Ngày',t.ngay)+tru('Tháng',t.thang)+tru('Năm',t.nam)+'</div>'+
 '<div class="dim" style="margin-top:6px">Năm Bát Tự tính từ Lập Xuân: '+t.nam_bat_tu+'</div>'+
 (d.canh_bao?'<div class="warn">Gần ranh giới tiết khí, cần kiểm tra kỹ giờ sinh.</div>':'')+'</div>'+
 '<div class="card"><div class="dim">Tiết khí hiện tại</div>'+
 '<div class="tt">'+esc(k.ten)+' <span class="dim">'+k.loai+' · '+k.kinh_do+'°</span></div>'+
 '<div class="bar"><i style="width:'+k.tien_do+'%"></i></div>'+
 kv('Bắt đầu',k.bat_dau+' <span class="dim">(đã qua '+k.da_qua+')</span>')+
 kv('Kế tiếp','<b>'+esc(k.ke_tiep)+'</b> <span class="dim">'+k.ke_tiep_loai+' · '+k.ke_tiep_kd+'°</span>')+
 kv('Vào lúc',k.ke_tiep_gio)+kv('Còn lại','<span class="moon">'+k.con+'</span>')+'</div>'+
 '<div class="card">'+kv('Kinh độ Mặt Trời','<b>'+m.kinh_do.toFixed(4)+'°</b>')+
 kv('Tiết đổi tháng gần nhất','<b>'+esc(m.tiet_truoc[0])+'</b> '+m.tiet_truoc[1])+
 kv('Tiết đổi tháng tiếp theo','<b>'+esc(m.tiet_sau[0])+'</b> '+m.tiet_sau[1])+'</div>'+
 '<div class="card">'+kv('Mặt Trăng','<span class="moon">'+esc(g.ten)+', sáng '+g.sang+'%</span>')+
 kv('Sóc vừa qua',g.soc_truoc+' <span class="dim">(tuổi trăng '+g.tuoi+')</span>')+kv('Sóc kế tiếp',g.soc_sau)+'</div>';
 $('nguon').textContent='Nguồn: '+d.nguon;
}
function tai(){
 var x=new XMLHttpRequest();
 x.open('GET','/api?'+qs());
 x.onload=function(){try{ve(JSON.parse(x.responseText))}catch(e){}};
 x.send();
}
function chedo(){$('t').disabled=$('live').checked}
$('tinh').onclick=function(){$('live').checked=false;chedo();tai()};
$('bay').onclick=function(){$('live').checked=true;chedo();tai()};
$('live').onchange=function(){chedo();tai()};
$('ts').onchange=tai;$('tz').onchange=tai;
$('t').onchange=function(){$('live').checked=false;chedo();tai()};
chedo();tai();
setInterval(function(){if($('live').checked)tai()},1000);
</script></body></html>
"""

# ==========================================
# [VẤN ĐỀ 7]: Khởi chạy HTTP Server cục bộ
# ==========================================
def chay_web(args):
    khoa = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _gui(self, ma, loai, noi_dung: bytes):
            self.send_response(ma)
            self.send_header("Content-Type", loai)
            self.send_header("Content-Length", str(len(noi_dung)))
            self.end_headers()
            self.wfile.write(noi_dung)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                self._gui(200, "text/html; charset=utf-8", GIAO_DIEN_HTML.encode("utf-8"))
            elif u.path == "/api":
                q = parse_qs(u.query)
                try:
                    tz = float(q.get("tz", [args.tz])[0])
                    dt = parse_web_time(q.get("time", [""])[0], tz)
                    with khoa:
                        kq = du_lieu(dt, tz, q.get("tysom", ["0"])[0] == "1")
                except Exception as exc:
                    kq = {"loi": str(exc)}
                self._gui(200, "application/json; charset=utf-8", json.dumps(kq, ensure_ascii=False).encode("utf-8"))
            else:
                self._gui(404, "text/plain; charset=utf-8", b"Not found")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Giao diện web đang chạy tại: {url}")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng ứng dụng.")
    finally:
        server.server_close()

def main():
    parser = argparse.ArgumentParser(description="Lịch Âm Dương + Bát Tự Webapp")
    parser.add_argument("--port", type=int, default=8765, help="Cổng chạy web")
    parser.add_argument("--host", default="127.0.0.1", help="Địa chỉ host")
    parser.add_argument("--tz", type=float, default=7.0, help="Múi giờ")
    args = parser.parse_args()
    chay_web(args)

if __name__ == "__main__":
    main()
"""battu_cli: lập Tứ Trụ (Bát Tự) và đổi âm lịch từ ngày giờ sinh dương lịch.

Cài đặt:  pip install "battu_tietkhi[precise]"
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone

from battu_tietkhi import CANS, CHI_HOURS, get_battu_hour, get_battu_month

try:
    import astronomy
    from amlich.precise import lunar_months_precise, solar_terms
except ImportError as exc:
    raise SystemExit('Thiếu thư viện thiên văn. Chạy: pip install "battu_tietkhi[precise]"') from exc


# ==========================================
# [VẤN ĐỀ 1]: Kiểm tra cấu hình chia giờ của thư viện
# ==========================================
def _hour_lib_is_fixed() -> bool:
    """Kiểm tra quy tắc chia khoảng giờ Tý, Sửu... để tương thích với các phiên bản battu_tietkhi."""
    return get_battu_hour(datetime(2000, 1, 1, 1, 30), "Giáp").endswith("Sửu")

_LIB_FIXED = _hour_lib_is_fixed()


# ==========================================
# [VẤN ĐỀ 2]: Tính toán thiên văn & Can Chi cơ bản
# ==========================================
def solar_longitude(dt: datetime) -> float:
    """Tính kinh độ Mặt Trời tại thời điểm truyền vào."""
    u = dt.astimezone(timezone.utc)
    t = astronomy.Time.Make(u.year, u.month, u.day, u.hour, u.minute,
                            u.second + u.microsecond / 1e6)
    return astronomy.SunPosition(t).elon % 360

def _jdn(d: date) -> int:
    return d.toordinal() + 1721425

def can_chi_ngay(d: date) -> tuple[str, str]:
    """Tính Can Chi cho ngày theo Julian Date Number."""
    j = _jdn(d)
    return CANS[(j + 9) % 10], CHI_HOURS[(j + 1) % 12]

def can_chi_nam(year: int) -> tuple[str, str]:
    """Tính Can Chi cho năm dương lịch."""
    return CANS[(year - 4) % 10], CHI_HOURS[(year - 4) % 12]


# ==========================================
# [VẤN ĐỀ 3]: Đổi ngày dương sang âm lịch chính xác
# ==========================================
def am_lich(d: date, tz: float):
    """Ánh xạ ngày dương sang tháng/ngày âm lịch dựa vào mốc Sóc chuẩn."""
    for cy in (d.year - 1, d.year):
        for m in lunar_months_precise(cy, tz):
            if m.start <= d < m.end:
                nam = cy if m.number >= 11 else cy + 1
                return (d - m.start).days + 1, m.number, m.leap, nam
    raise RuntimeError("không xác định được ngày âm lịch")


# ==========================================
# [VẤN ĐỀ 4]: Lập lá số Tứ Trụ (Năm, Tháng, Ngày, Giờ)
# ==========================================
def lap_tu_tru(dt: datetime, tz: float = 7.0, ty_som: bool = False) -> dict:
    """Xây dựng 4 trụ Bát Tự hoàn chỉnh từ thời điểm sinh."""
    zone = timezone(timedelta(hours=tz))
    dt = dt.replace(tzinfo=zone) if dt.tzinfo is None else dt.astimezone(zone)

    lon = solar_longitude(dt)

    # Xác định năm Bát Tự dựa theo tiết Lập Xuân (315 độ)
    nam = dt.year - 1 if (dt.month <= 2 and lon < 315) else dt.year
    can_nam, chi_nam = can_chi_nam(nam)

    thang = get_battu_month(lon, can_nam)

    ngay_tinh = dt.date() + timedelta(days=1) if (ty_som and dt.hour >= 23) else dt.date()
    can_ngay, chi_ngay = can_chi_ngay(ngay_tinh)

    dt_gio = dt.replace(tzinfo=None)
    if not _LIB_FIXED:
        dt_gio += timedelta(hours=1)
    gio = get_battu_hour(dt_gio, can_ngay)

    # Tìm ranh giới các tiết đổi tháng Bát Tự
    tiet = []
    for y in (dt.year - 1, dt.year, dt.year + 1):
        tiet += [(n, t) for n, t in solar_terms(y, tz) if n in TIET_THANG]
    tiet.sort(key=lambda x: x[1])
    truoc = max((x for x in tiet if x[1] <= dt), key=lambda x: x[1])
    sau = min((x for x in tiet if x[1] > dt), key=lambda x: x[1])

    return {
        "dt": dt, "kinh_do": lon, "nam_bat_tu": nam,
        "tru_nam": f"{can_nam} {chi_nam}", "tru_thang": thang,
        "tru_ngay": f"{can_ngay} {chi_ngay}", "tru_gio": gio,
        "tiet_truoc": truoc, "tiet_sau": sau,
        "sat_ranh_gioi": min(dt - truoc[1], sau[1] - dt) < timedelta(hours=1),
    }

TIET_THANG = {"Lập xuân", "Kinh trập", "Thanh minh", "Lập hạ", "Mang chủng", "Tiểu thử",
              "Lập thu", "Bạch lộ", "Hàn lộ", "Lập đông", "Đại tuyết", "Tiểu hàn"}

def in_ket_qua(r: dict, tz: float) -> None:
    """In kết quả trực tiếp ra màn hình dòng lệnh CLI."""
    dt = r["dt"]
    ngay, thang, nhuan, nam = am_lich(dt.date(), tz)
    cn, cc = can_chi_nam(nam)
    print(f"Dương lịch : {dt:%d/%m/%Y %H:%M:%S} (UTC{tz:+g})")
    print(f"Âm lịch    : {ngay}/{thang}{' (nhuận)' if nhuan else ''} năm {cn} {cc} ({nam})")
    print(f"Kinh độ MT : {r['kinh_do']:.4f}°")
    t1, t2 = r["tiet_truoc"], r["tiet_sau"]
    print(f"Tiết       : {t1[0]} {t1[1]:%d/%m %H:%M:%S}  ->  {t2[0]} {t2[1]:%d/%m %H:%M:%S}")
    print()
    print("      Giờ          Ngày         Tháng         Năm")
    print(f"  {r['tru_gio']:<12} {r['tru_ngay']:<12} {r['tru_thang']:<12} {r['tru_nam']}")
    print(f"(năm Bát Tự tính từ Lập Xuân: {r['nam_bat_tu']})")
    if r["sat_ranh_gioi"]:
        print("! Giờ sinh cách ranh giới tiết dưới 1 giờ, nên kiểm tra lại giờ sinh.")

def _parse(s: str) -> datetime:
    for f in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), f)
        except ValueError:
            pass
    raise SystemExit(f"Sai định dạng: {s!r}")

def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Lập Tứ Trụ Bát Tự + âm lịch")
    p.add_argument("ngay", nargs="?", help="ngày sinh")
    p.add_argument("gio", nargs="?", help="giờ sinh")
    p.add_argument("--tz", type=float, default=7.0, help="múi giờ")
    p.add_argument("--ty-som", action="store_true", help="tính từ 23h là ngày hôm sau")
    a = p.parse_args(argv)

    if a.ngay:
        dt = _parse(f"{a.ngay} {a.gio or '12:00'}")
    else:
        dt = _parse(input("Ngày giờ sinh dương lịch (vd 2000-01-01 12:00): "))
    in_ket_qua(lap_tu_tru(dt, a.tz, a.ty_som), a.tz)

if __name__ == "__main__":
    main()
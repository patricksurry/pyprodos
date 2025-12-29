from datetime import datetime

from prodos.p8datetime import P8DateTime


def test_roundtrip():
    dt = P8DateTime(year=69, month=12, day=28, hour=3, minute=42)
    dt2 = P8DateTime.unpack(dt.pack())
    assert dt == dt2


def test_repr():
    dt = P8DateTime.from_datetime(datetime(1969, 12, 28, 1, 23, 45))
    assert repr(dt) == '69-12-28T01:23'

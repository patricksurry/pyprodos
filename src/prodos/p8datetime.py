from typing import ClassVar, Self
from dataclasses import dataclass
from datetime import datetime


@dataclass(kw_only=True, repr=False)
class P8DateTime:
    empty: ClassVar['P8DateTime']

    year: int
    month: int
    day: int
    hour: int
    minute: int

    def __repr__(self):
        return f"{self.year:02d}-{self.month:02d}-{self.day:02d}T{self.hour:02d}:{self.minute:02d}"

    def pack(self) -> bytes:
        return bytes([
            ((self.month & 0b111) << 5) | self.day,
            (self.year << 1) | (self.month >> 3),
            self.minute,
            self.hour
        ])

    @classmethod
    def unpack(kls, buf: bytes) -> Self:
        return kls(
            year = buf[1] >> 1,
            month = (buf[0] >> 5) + ((buf[1] & 1) << 3),
            day = buf[0] & 0b11111,
            hour = buf[3],
            minute = buf[2],
        )

    @classmethod
    def from_datetime(kls, dt: datetime):
        return P8DateTime(
            year=dt.year%100, month=dt.month, day=dt.day,
            hour=dt.hour, minute=dt.minute
        )

    @classmethod
    def now(kls):
        return P8DateTime.from_datetime(datetime.now())

P8DateTime.empty = P8DateTime(year=0, month=0, day=0, hour=0, minute=0)

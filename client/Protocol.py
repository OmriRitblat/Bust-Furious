import struct
from dataclasses import dataclass
from typing import Optional, Tuple

# --------------------------
# Protocol constants
# --------------------------
MAGIC_COOKIE = 0xabcddcba

MSG_OFFER   = 0x2
MSG_REQUEST = 0x3
MSG_PAYLOAD = 0x4

DECISION_SIZE = 5  # "Hittt" / "Stand"

# Results (server -> client)
RESULT_NOT_OVER = 0x0
RESULT_TIE      = 0x1
RESULT_LOSS     = 0x2   # client lost
RESULT_WIN      = 0x3   # client won


# --------------------------
# Data objects
# --------------------------
@dataclass
class Offer:
    server_tcp_port: int
    server_name: str

@dataclass
class Request:
    rounds: int
    client_name: str

@dataclass
class Card:
    rank: int  # 1-13
    suit: int  # 0-3

    def game_value(self) -> int:
        # 2-10 -> numeric, J/Q/K -> 10, A -> 11
        if self.rank == 1:
            return 11
        elif 2 <= self.rank <= 10:
            return self.rank
        else:
            return 10


class Protocol:
    """
    Client-side protocol: parse offers, send requests, send decisions, receive server payloads.
    """

    OFFER_FMT   = "!IBH32s"     # cookie(4) type(1) port(2) name(32)
    REQUEST_FMT = "!IBB32s"     # cookie(4) type(1) rounds(1) name(32)

    # Payload (כמו אצלך בשרת): cookie(4) type(1) decision(5) result(1) rank(2) suit(1) = 14 bytes
    # אתה בחרת signed בשרת (h,b), אז ניישר קו כדי שה-unpack תמיד יעבוד.
    PAYLOAD_FMT = "!IB5sBhb"

    @staticmethod
    def _fix_name(name: str) -> bytes:
        b = name.encode("utf-8", errors="ignore")[:32]
        return b + b"\x00" * (32 - len(b))

    @staticmethod
    def _parse_name(b: bytes) -> str:
        return b.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

    # ---------- OFFER ----------
    @staticmethod
    def parse_offer(data: bytes) -> Optional[Offer]:
        if len(data) != struct.calcsize(Protocol.OFFER_FMT):
            return None
        cookie, mtype, port, name = struct.unpack(Protocol.OFFER_FMT, data)
        if cookie != MAGIC_COOKIE or mtype != MSG_OFFER:
            return None
        return Offer(server_tcp_port=int(port), server_name=Protocol._parse_name(name))

    # ---------- REQUEST ----------
    @staticmethod
    def build_request(req: Request) -> bytes:
        rounds = max(1, min(int(req.rounds), 255))
        return struct.pack(
            Protocol.REQUEST_FMT,
            MAGIC_COOKIE,
            MSG_REQUEST,
            rounds,
            Protocol._fix_name(req.client_name),
        )

    # ---------- PAYLOAD ----------
    @staticmethod
    def build_payload_from_client(decision: str) -> bytes:
        # חייב להיות בדיוק 5 bytes: "Hittt" או "Stand"
        if decision not in ("Hittt", "Stand"):
            raise ValueError("decision must be 'Hittt' or 'Stand'")
        decision_bytes = decision.encode("ascii")  # 5 bytes

        # client לא משתמש ב-result/rank/suit -> נשים 0
        return struct.pack(
            Protocol.PAYLOAD_FMT,
            MAGIC_COOKIE,
            MSG_PAYLOAD,
            decision_bytes,
            0,  # result dummy
            0,  # rank dummy
            0   # suit dummy
        )

    @staticmethod
    def parse_payload_from_server(data: bytes) -> Optional[Tuple[int, Card]]:
        if len(data) != struct.calcsize(Protocol.PAYLOAD_FMT):
            return None
        cookie, mtype, _decision, result, rank, suit = struct.unpack(Protocol.PAYLOAD_FMT, data)
        if cookie != MAGIC_COOKIE or mtype != MSG_PAYLOAD:
            return None
        return int(result), Card(rank=int(rank), suit=int(suit))

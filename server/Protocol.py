import struct
from dataclasses import dataclass
from typing import Optional

# --------------------------
# Protocol
# --------------------------
MAGIC_COOKIE = 0xabcddcba

# Message types
MSG_OFFER = 0x2
MSG_REQUEST = 0x3
MSG_PAYLOAD = 0x4

DECISION_SIZE = 5  # "Hittt" / "Stand"


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
    rank: int  # 1-10
    suit: int  # 0-3

    def game_value(self) -> int:
        if self.rank == 1:
            return 11
        if 2 <= self.rank <= 10:
            return self.rank
        return 10


class Protocol:
    """
    Server-side protocol (with different payload structures):

    client->server decision payload:
      cookie(4) type(1) decision(5)                     => 10 bytes

    server->client payload:
      cookie(4) type(1) result(1) rank(2) suit(1)       => 8 bytes
    """

    OFFER_FMT = "!IBH32s"      # cookie(4) type(1) port(2) name(32)
    REQUEST_FMT = "!IBB32s"    # cookie(4) type(1) rounds(1) name(32)

    PAYLOAD_CLIENT_FMT = "!IB5s"   # 10 bytes: decision only
    PAYLOAD_SERVER_FMT = "!IBBhb"  # 8 bytes: result + rank + suit (signed like you used)

    @staticmethod
    def offer_size() -> int:
        return struct.calcsize(Protocol.OFFER_FMT)

    @staticmethod
    def request_size() -> int:
        return struct.calcsize(Protocol.REQUEST_FMT)

    @staticmethod
    def client_payload_size() -> int:
        return struct.calcsize(Protocol.PAYLOAD_CLIENT_FMT)

    @staticmethod
    def server_payload_size() -> int:
        return struct.calcsize(Protocol.PAYLOAD_SERVER_FMT)

    @staticmethod
    def _fix_name(name: str) -> bytes:
        b = name.encode("utf-8", errors="ignore")[:32]
        return b + b"\x00" * (32 - len(b))

    @staticmethod
    def _parse_name(b: bytes) -> str:
        return b.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

    # ---------- OFFER ----------
    @staticmethod
    def build_offer(offer: Offer) -> bytes:
        return struct.pack(
            Protocol.OFFER_FMT,
            MAGIC_COOKIE,
            MSG_OFFER,
            offer.server_tcp_port,
            Protocol._fix_name(offer.server_name),
        )

    # ---------- REQUEST ----------
    @staticmethod
    def parse_request(data: bytes) -> Optional[Request]:
        if len(data) != struct.calcsize(Protocol.REQUEST_FMT):
            return None
        cookie, mtype, rounds, name = struct.unpack(Protocol.REQUEST_FMT, data)
        if cookie != MAGIC_COOKIE or mtype != MSG_REQUEST:
            return None
        return Request(rounds=int(rounds), client_name=Protocol._parse_name(name))

    # ---------- PAYLOAD: server -> client ----------
    @staticmethod
    def build_payload_from_server(result: int, card: Card) -> bytes:
        # 8 bytes only
        return struct.pack(
            Protocol.PAYLOAD_SERVER_FMT,
            MAGIC_COOKIE,
            MSG_PAYLOAD,
            int(result) & 0xFF,
            int(card.rank),
            int(card.suit)
        )

    # ---------- PAYLOAD: client -> server ----------
    @staticmethod
    def parse_payload_from_client(data: bytes) -> Optional[str]:
        # Expect exactly 10 bytes
        if len(data) != struct.calcsize(Protocol.PAYLOAD_CLIENT_FMT):
            return None
        cookie, mtype, decision_raw = struct.unpack(Protocol.PAYLOAD_CLIENT_FMT, data)
        if cookie != MAGIC_COOKIE or mtype != MSG_PAYLOAD:
            return None

        decision = decision_raw.decode("utf-8", errors="ignore")
        if decision not in ("Hittt", "Stand"):
            return None
        return decision

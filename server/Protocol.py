from ServerMain import Offer
import socket
import struct
import threading
import time
import random
from dataclasses import dataclass
from typing import Optional, Tuple, List
# --------------------------
# Protocol
# --------------------------
MAGIC_COOKIE = 0xabcddcba

# Message types
MSG_OFFER = 0x2
MSG_REQUEST = 0x3
MSG_PAYLOAD = 0x4


# Payload decision sizes: "Hittt" or "Stand" = 5 bytes
DECISION_SIZE = 5

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
    Encodes/decodes Offer/Request/Payload messages according to the hackathon spec. :contentReference[oaicite:1]{index=1}
    """

    OFFER_FMT = "!IBH32s"      # cookie(4) type(1) port(2) name(32)
    REQUEST_FMT = "!IBB32s"    # cookie(4) type(1) rounds(1) name(32)
    # payload:
    # cookie(4) type(1) decision(5) result(1) card_rank(2) card_suit(1)
    PAYLOAD_FMT = "!IB5sBHb"   # We'll build manually to avoid signed issues on suit

    @staticmethod
    def _fix_name(name: str) -> bytes:
        b = name.encode("utf-8", errors="ignore")[:32]
        return b + b"\x00" * (32 - len(b))

    @staticmethod
    def _parse_name(b: bytes) -> str:
        return b.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")

    @staticmethod
    def build_offer(offer: Offer) -> bytes:
        return struct.pack(
            Protocol.OFFER_FMT,
            MAGIC_COOKIE,
            MSG_OFFER,
            offer.server_tcp_port,
            Protocol._fix_name(offer.server_name),
        )

    @staticmethod
    def parse_request(data: bytes) -> Optional[Request]:
        if len(data) != struct.calcsize(Protocol.REQUEST_FMT):
            return None
        cookie, mtype, rounds, name = struct.unpack(Protocol.REQUEST_FMT, data)
        if cookie != MAGIC_COOKIE or mtype != MSG_REQUEST:
            return None
        return Request(rounds=rounds, client_name=Protocol._parse_name(name))

    @staticmethod
    def build_payload_from_server(result: int, card: Card) -> bytes:
        decision = b"\x00" * DECISION_SIZE

        return struct.pack(
            "!IB5sBhb",
            MAGIC_COOKIE,
            MSG_PAYLOAD,
            decision,
            result,
            card.rank,   # signed short (2 bytes) - need to check that ok without unsigned
            card.suit    # signed char  (1 byte)  - need to check that ok without unsigned
        )


    @staticmethod
    def parse_payload_from_client(data: bytes) -> Optional[str]:
        # Expect: cookie(4) type(1) decision(5) ... (client may still send full payload, but spec says decision is relevant)
        if len(data) < 4 + 1 + 5:
            return None
        cookie, mtype = struct.unpack("!IB", data[:5])
        if cookie != MAGIC_COOKIE or mtype != MSG_PAYLOAD:
            return None
        decision_raw = data[5:10]
        decision = decision_raw.decode("utf-8", errors="ignore")
        # Must be exactly "Hittt" or "Stand"
        if decision not in ("Hittt", "Stand"):
            return None
        return decision
import socket
import struct
from typing import Optional, Tuple
from enum import Enum, auto

from Protocol import (
    Protocol, Offer, Request, Card,
    RESULT_NOT_OVER, RESULT_WIN, RESULT_LOSS, RESULT_TIE
)

class RoundResult(Enum):
    WIN = auto()
    LOSS = auto()
    TIE = auto()
    ERROR = auto()

def map_protocol_result(result: int) -> RoundResult:
    if result == RESULT_WIN:
        return RoundResult.WIN
    if result == RESULT_LOSS:
        return RoundResult.LOSS
    if result == RESULT_TIE:
        return RoundResult.TIE
    return RoundResult.ERROR

UDP_OFFER_PORT = 13122
SUITS = ['H', 'D', 'C', 'S']


def recv_exact(conn: socket.socket, n: int) -> Optional[bytes]:
    conn.settimeout(None)
    got = 0
    chunks = []
    try:
        while got < n:
            chunk = conn.recv(n - got)
            if not chunk:
                return None
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks)
    except (socket.timeout, OSError):
        return None


def listen_for_offer() -> Optional[Tuple[str, Offer]]:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", UDP_OFFER_PORT))
    print(f"[UDP] Listening for offers on port {UDP_OFFER_PORT}...")

    while True:
        data, (src_ip, _src_port) = s.recvfrom(4096)
        offer = Protocol.parse_offer(data)
        if offer:
            print(f"[UDP] Offer from {src_ip}: team='{offer.server_name}', tcp_port={offer.server_tcp_port}")
            s.close()
            return src_ip, offer


def cards_str(cards):
    return " ".join(f"{c.rank}{SUITS[c.suit]}" for c in cards)


def play_round(conn: socket.socket, round_idx: int) -> RoundResult:
    payload_size = struct.calcsize(Protocol.PAYLOAD_FMT)
    print(f"\n=== ROUND {round_idx} ===")

    init = []
    for _ in range(3):
        raw = recv_exact(conn, payload_size)
        if not raw:
            print("[TCP] Disconnected while receiving initial cards.")
            return RoundResult.ERROR
        parsed = Protocol.parse_payload_from_server(raw)
        if not parsed:
            print("[TCP] Bad payload from server.")
            return RoundResult.ERROR
        result, card = parsed
        init.append((result, card))

    player_cards = [init[0][1], init[1][1]]
    dealer_up = init[2][1]

    print(f"Your cards: {cards_str(player_cards)} (total={sum(c.game_value() for c in player_cards)})")
    print(f"Dealer up:  {dealer_up.rank}{SUITS[dealer_up.suit]}")

    # תור שחקן: בכל Hit/Stand שולחים payload עם decision
    while True:
        total = sum(c.game_value() for c in player_cards)

        cmd = input("Hit or Stand? (h/s): ").strip().lower()
        decision = "Stand" if cmd in ("s", "stand") else "Hittt"

        try:
            conn.sendall(Protocol.build_payload_from_client(decision))
        except OSError:
            print("[TCP] Failed to send decision.")
            return RoundResult.ERROR

        if decision == "Stand":
            break

        # Hit -> השרת ישלח קלף נוסף לשחקן (NOT_OVER)
        raw = recv_exact(conn, payload_size)
        if not raw:
            print("[TCP] Disconnected while receiving hit card.")
            return RoundResult.ERROR
        parsed = Protocol.parse_payload_from_server(raw)
        if not parsed:
            print("[TCP] Bad payload from server.")
            return RoundResult.ERROR

        result, card = parsed
        if result != RESULT_NOT_OVER:
            # אם השרת החליט לסיים מיד
            print(f"[SERVER] Round ended early (result={result}).")
            return RoundResult.ERROR

        player_cards.append(card)
        total = sum(c.game_value() for c in player_cards)
        print(f"You got: {card.rank}{SUITS[card.suit]} (total={total})")

        if total > 21:
            break

    # אחרי Stand (או אחרי hitים): השרת שולח reveal/hits של דילר ואז תוצאה סופית
    while True:
        raw = recv_exact(conn, payload_size)
        if not raw:
            print("[TCP] Disconnected while waiting for dealer/result.")
            return RoundResult.ERROR
        parsed = Protocol.parse_payload_from_server(raw)
        if not parsed:
            print("[TCP] Bad payload from server.")
            return RoundResult.ERROR

        result, card = parsed
        if result == RESULT_NOT_OVER:
            print(f"[Dealer] {card.rank}{SUITS[card.suit]}")
            continue

        rr = map_protocol_result(result)

        if rr == RoundResult.WIN:
            print("✅ You WIN!")
        elif rr == RoundResult.LOSS:
            print("❌ You LOSE!")
        elif rr == RoundResult.TIE:
            print("🤝 TIE!")

        return rr


def main():
    stats = {
    RoundResult.WIN: 0,
    RoundResult.LOSS: 0,
    RoundResult.TIE: 0,
    RoundResult.ERROR: 0,
    }
    server_ip, offer = listen_for_offer()
    if not server_ip:
        return

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    print(f"[TCP] Connecting to {server_ip}:{offer.server_tcp_port} ...")
    conn.connect((server_ip, offer.server_tcp_port))
    print("[TCP] Connected.")

    rounds_str = input("How many rounds? (1-255): ").strip() or "1"
    try:
        rounds = int(rounds_str)
    except ValueError:
        rounds = 1
    rounds = max(1, min(rounds, 255))

    name = input("Your client name: ").strip() or "ClientTeam"
    req = Request(rounds=rounds, client_name=name)

    conn.sendall(Protocol.build_request(req))
    # אם אצלכם באמת שולחים '\n' אחרי request – אפשר להוסיף:
    # conn.sendall(b"\n")

    for i in range(1, rounds + 1):
        res = play_round(conn, i)
        stats[res] += 1

        if res == RoundResult.ERROR:
            print("[CLIENT] Error occurred, stopping game.")
            break

    conn.close()
    print("[TCP] Done.")
    print("\n===== GAME SUMMARY =====")
    print(f"Wins:   {stats[RoundResult.WIN]}")
    print(f"Losses: {stats[RoundResult.LOSS]}")
    print(f"Ties:   {stats[RoundResult.TIE]}")
    print(f"Errors: {stats[RoundResult.ERROR]}")


if __name__ == "__main__":
    main()

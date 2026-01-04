import Protocol, GameLogic
import socket
import struct
import threading
import time
import random
from dataclasses import dataclass
from typing import Optional, Tuple, List
from ServerMain import Offer
from Protocol import Protocol, Card, Request
import GameLogic

# Round results (server -> client)
RESULT_NOT_OVER = 0x0
RESULT_TIE = 0x1
RESULT_LOSS = 0x2   # client lost (dealer won)
RESULT_WIN = 0x3    # client won (dealer lost)

SUITS = ['H', 'D', 'C', 'S']  # encoded 0-3
RANKS = list(range(1, 14))    # 1-13

# --------------------------
# Single game session
# --------------------------

class GameSession:
    def __init__(self, conn: socket.socket, addr: Tuple[str, int], team_name: str):
        self.conn = conn
        self.addr = addr
        self.team_name = team_name

    def _recv_exact(self, n: int) -> Optional[bytes]:
        self.conn.settimeout(None)
        chunks = []
        got = 0
        try:
            while got < n:
                chunk = self.conn.recv(n - got)
                if not chunk:
                    return None
                chunks.append(chunk)
                got += len(chunk)
            return b"".join(chunks)
        except socket.timeout:
            return None
        except OSError:
            return None

    def _recv_until_newline(self, max_len: int = 128) -> Optional[bytes]:
        self.conn.settimeout(None)
        data = b""
        try:
            while b"\n" not in data and len(data) < max_len:
                chunk = self.conn.recv(1)
                if not chunk:
                    return None
                data += chunk
            return data
        except socket.timeout:
            return None
        except OSError:
            return None

    def _send(self, data: bytes) -> bool:
        try:
            self.conn.sendall(data)
            return True
        except OSError:
            return False

    def _new_shuffled_deck(self) -> List[Card]:
        deck = [Card(rank=r, suit=s) for s in range(4) for r in range(1, 14)]
        random.shuffle(deck)
        return deck

    def _draw(self, deck: List[Card]) -> Card:
        return deck.pop()

    def _sum_cards(self, cards: List[Card]) -> int:
        return sum(c.game_value() for c in cards)

    def play(self) -> None:
        print(f"[TCP] Client connected from {self.addr}")

        # Request message: client sends request over TCP followed by '\n' (spec says newline after rounds)
        # We'll read fixed request size, then consume newline if present.
        req_size = struct.calcsize(Protocol.REQUEST_FMT)
        req_bytes = self._recv_exact(req_size)
        if not req_bytes:
            print("[TCP] Failed to read request (timeout/disconnect)")
            return

        req = Protocol.parse_request(req_bytes)
        if not req:
            print("[TCP] Invalid request format")
            return

        rounds = max(1, min(req.rounds, 255))
        print(f"[GAME] Client='{req.client_name}' requested {rounds} rounds")

        wins_dealer = 0
        wins_client = 0
        ties = 0

        for r in range(1, rounds + 1):
            res = self._play_single_round(r,req.client_name)
            if res == RESULT_WIN:
                wins_dealer += 1
            elif res == RESULT_LOSS:
                wins_client += 1
            else:
                ties += 1

        print(f"[DONE] {req.client_name}: rounds={rounds}, dealer_wins={wins_dealer}, client_wins={wins_client}, ties={ties}")

    def _play_single_round(self, round_idx: int, client_name: str) -> int:
        deck = self._new_shuffled_deck()

        player = [self._draw(deck), self._draw(deck)]
        dealer = [self._draw(deck), self._draw(deck)]

        player_total = self._sum_cards(player)
        dealer_up = dealer[0]
        # Send initial state (simplify by sending cards one by one)
        player_cards_str = " ".join(f"{c.rank}{SUITS[c.suit]}" for c in player)
        
        print(
        f"[ROUND {round_idx} client='{client_name}]': "
        f"player={player_cards_str} (total={player_total}), "
        f"dealer_up={dealer_up.rank}{SUITS[dealer_up.suit]}")

        # Send player's two cards + dealer upcard to client (as payload messages)
        for c in player:
            if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, c)):
                return RESULT_TIE
        if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, dealer_up)):
            return RESULT_TIE

        # Player turn
        while True:
            if player_total > 21:
                print(f"[ROUND {round_idx} client='{client_name}] Player bust ({player_total}).")
                # Send result (round over) - include dummy card
                dummy = Card(rank=2, suit=0)
                self._send(Protocol.build_payload_from_server(RESULT_LOSS, dummy))
                return RESULT_WIN

            # wait for client decision payload
            data = self._recv_exact(Protocol.client_payload_size())
            if not data:
                print(f"[ROUND {round_idx} client='{client_name}] Client disconnected during decision.")
                return RESULT_TIE

            decision = Protocol.parse_payload_from_client(data)
            if not decision:
                print(f"[ROUND {round_idx} client='{client_name}] Invalid decision payload.")
                return RESULT_TIE

            if decision == "Stand":
                print(f"[ROUND {round_idx} client='{client_name}] Player stands at {player_total}")
                break

            # Hit
            newc = self._draw(deck)
            player.append(newc)
            player_total = self._sum_cards(player)
            print(f"[ROUND {round_idx} client='{client_name}] Player hit: +{newc.rank}{SUITS[newc.suit]} => {player_total}")
            if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, newc)):
                return RESULT_TIE

        # Dealer turn (reveal hidden + hit till >=17)
        hidden = dealer[1]
        dealer_total = self._sum_cards(dealer)
        print(f"[ROUND {round_idx} client='{client_name}] Dealer reveals: {hidden.rank}{SUITS[hidden.suit]} => {dealer_total}")
        if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, hidden)):
            return RESULT_TIE

        while dealer_total <= 21 and GameLogic.dealer_should_hit(dealer_total, player_total):
            newc = self._draw(deck)
            dealer.append(newc)
            dealer_total = self._sum_cards(dealer)
            print(f"[ROUND {round_idx} client='{client_name}] Dealer hit: +{newc.rank}{SUITS[newc.suit]} => {dealer_total}")
            if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, newc)):
                return RESULT_TIE

        # Decide winner
        if dealer_total > 21:
            print(f"[ROUND {round_idx} client='{client_name}] Dealer bust ({dealer_total}). Client wins.")
            dummy = Card(rank=2, suit=0)
            self._send(Protocol.build_payload_from_server(RESULT_WIN, dummy))
            return RESULT_WIN

        if player_total > dealer_total:
            result = RESULT_WIN
        elif dealer_total > player_total:
            result = RESULT_LOSS
        else:
            result = RESULT_TIE

        print(f"[ROUND {round_idx} client='{client_name}] Final: player={player_total}, dealer={dealer_total}, result={result}")
        dummy = Card(rank=2, suit=0)
        self._send(Protocol.build_payload_from_server(result, dummy))
        return result

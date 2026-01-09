import socket
import struct
import threading
import random
from dataclasses import dataclass
from typing import Optional, Dict, List

from Protocol import Protocol, Card
import GameLogic

RESULT_NOT_OVER = 0x0
RESULT_TIE = 0x1
RESULT_LOSS = 0x2   # client lost (dealer won)
RESULT_WIN = 0x3    # client won (dealer lost)

SUITS = ['H', 'D', 'C', 'S']


@dataclass
class RoundResults:
    dealer_wins: int = 0
    client_wins: int = 0
    ties: int = 0


class OneBoard:
    def __init__(self, team_name: str):
        self.team_name = team_name

        self.deck: List[Card] = self._new_shuffled_deck()

        # conn -> remaining rounds
        self.remaining_rounds: Dict[socket.socket, int] = {}

        # conn -> stats
        self.stats: Dict[socket.socket, RoundResults] = {}

        # conn -> client_name
        self.player_name: Dict[socket.socket, str] = {}

        self.cond = threading.Condition()

    # ---------- network helpers ----------
    def _recv_exact(self, n: int, conn: socket.socket) -> Optional[bytes]:
        conn.settimeout(None)  # interactive
        chunks = []
        got = 0
        try:
            while got < n:
                chunk = conn.recv(n - got)
                if not chunk:
                    return None
                chunks.append(chunk)
                got += len(chunk)
            return b"".join(chunks)
        except OSError:
            return None

    def _send(self, data: bytes, conn: socket.socket) -> bool:
        try:
            conn.sendall(data)
            return True
        except OSError:
            return False

    # ---------- cards ----------
    def _new_shuffled_deck(self) -> List[Card]:
        deck = [Card(rank=r, suit=s) for s in range(4) for r in range(1, 14)]
        random.shuffle(deck)
        return deck

    def _ensure_deck(self, needed: int) -> None:
        # אם אין מספיק קלפים, מתחילים חפיסה חדשה
        if len(self.deck) < needed:
            self.deck = self._new_shuffled_deck()

    def _draw(self) -> Card:
        self._ensure_deck(1)
        return self.deck.pop()

    def _sum_cards(self, cards: List[Card]) -> int:
        return sum(c.game_value() for c in cards)

    # ---------- player management ----------
    def add_player(self, conn: socket.socket) -> None:
        req_size = struct.calcsize(Protocol.REQUEST_FMT)
        req_bytes = self._recv_exact(req_size, conn)
        if not req_bytes:
            print("[TCP] Failed to read request (disconnect)")
            return

        req = Protocol.parse_request(req_bytes)
        if not req:
            print("[TCP] Invalid request format")
            return

        rounds = max(1, min(req.rounds, 255))
        name = req.client_name or "client"

        with self.cond:
            self.remaining_rounds[conn] = rounds
            self.stats[conn] = RoundResults()
            self.player_name[conn] = name
            print(f"[TCP] Client '{name}' joined from {conn.getpeername()} for {rounds} rounds")
            self.cond.notify_all()

    def _drop_player(self, conn: socket.socket, reason: str) -> None:
        name = self.player_name.get(conn, "client")
        print(f"[TCP] Dropping client '{name}' ({reason})")
        try:
            conn.close()
        except OSError:
            pass
        self.remaining_rounds.pop(conn, None)
        self.stats.pop(conn, None)
        self.player_name.pop(conn, None)

    # ---------- protocol actions ----------
    def _get_decision(self, conn: socket.socket) -> Optional[str]:
        data = self._recv_exact(Protocol.client_payload_size(), conn)
        if not data:
            return None
        return Protocol.parse_payload_from_client(data)

    def _send_initial_hands(self, players_hands: Dict[socket.socket, List[Card]], dealer_up: Card) -> None:
        for conn, hand in players_hands.items():
            # 2 קלפים לשחקן + קלף גלוי של דילר
            for c in hand:
                if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, c), conn):
                    self._drop_player(conn, "send failed (player card)")
                    continue
            if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, dealer_up), conn):
                self._drop_player(conn, "send failed (dealer upcard)")

    # ---------- main game loop ----------
    def play_forever(self) -> None:
        print("[GAME] OneBoard starting...")

        while True:
            # wait for at least one player
            with self.cond:
                while len(self.remaining_rounds) == 0:
                    print("[GAME] Waiting for players...")
                    self.cond.wait()

                # snapshot players for this round (so add_player can run concurrently)
                conns = [c for c, r in self.remaining_rounds.items() if r > 0]

            if not conns:
                continue

            # need: 2 per player + 2 dealer + (dealer hits up to ~10 worst case) + some player hits
            self._ensure_deck(2 * len(conns) + 2 + 20)

            # deal initial hands
            players_hands: Dict[socket.socket, List[Card]] = {c: [self._draw(), self._draw()] for c in conns}
            dealer_hand: List[Card] = [self._draw(), self._draw()]
            dealer_up = dealer_hand[0]
            dealer_hidden = dealer_hand[1]

            print(f"\n[GAME] New round with {len(conns)} players. Dealer up={dealer_up.rank}{SUITS[dealer_up.suit]}")

            # decrement rounds for participants of this round
            with self.cond:
                for c in conns:
                    if c in self.remaining_rounds:
                        self.remaining_rounds[c] -= 1

            # send initial hands
            self._send_initial_hands(players_hands, dealer_up)

            # active players still in the round (not busted / not disconnected)
            active = list(conns)

            # ----- each player turn -----
            for conn in list(active):
                name = self.player_name.get(conn, "client")

                while True:
                    total = self._sum_cards(players_hands[conn])

                    decision = self._get_decision(conn)
                    if decision is None:
                        self._drop_player(conn, "disconnect during decision")
                        if conn in active:
                            active.remove(conn)
                        break

                    if decision == "Stand":
                        print(f"[client='{name}'] stand ({total})")
                        break

                    # Hittt
                    newc = self._draw()
                    total += newc.game_value()
                    players_hands[conn].append(newc)
                    print(f"[client='{name}'] hit +{newc.rank}{SUITS[newc.suit]} => {self._sum_cards(players_hands[conn])}")

                    if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, newc), conn):
                        self._drop_player(conn, "send failed (hit card)")
                        if conn in active:
                            active.remove(conn)
                        break
                    
                    if total > 21:
                        # player bust -> immediate LOSS
                        print(f"[client='{name}'] bust ({total})")
                        dummy = Card(rank=2, suit=0)
                        self._send(Protocol.build_payload_from_server(RESULT_LOSS, dummy), conn)
                        with self.cond:
                            if conn in self.stats:
                                self.stats[conn].dealer_wins += 1
                        active.remove(conn)
                        break
            # ----- dealer turn -----
            # reveal hidden card to everyone still active
            for conn in list(active):
                if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, dealer_hidden), conn):
                    self._drop_player(conn, "send failed (dealer reveal)")
                    active.remove(conn)

            dealer_total = self._sum_cards(dealer_hand)
            print(f"[DEALER] reveal {dealer_hidden.rank}{SUITS[dealer_hidden.suit]} => {dealer_total}")

            while GameLogic.GameLogic.dealer_should_hit(dealer_total, players_hands):
                newc = self._draw()
                dealer_hand.append(newc)
                dealer_total = self._sum_cards(dealer_hand)
                print(f"[DEALER] hit +{newc.rank}{SUITS[newc.suit]} => {dealer_total}")

                for conn in list(active):
                    if not self._send(Protocol.build_payload_from_server(RESULT_NOT_OVER, newc), conn):
                        self._drop_player(conn, "send failed (dealer hit)")
                        active.remove(conn)

            # ----- decide winners for active players -----
            for conn in list(active):
                name = self.player_name.get(conn, "client")
                player_total = self._sum_cards(players_hands[conn])

                if dealer_total > 21:
                    result = RESULT_WIN
                elif player_total > dealer_total:
                    result = RESULT_WIN
                elif dealer_total > player_total:
                    result = RESULT_LOSS
                else:
                    result = RESULT_TIE

                dummy = Card(rank=2, suit=0)
                self._send(Protocol.build_payload_from_server(result, dummy), conn)

                with self.cond:
                    if conn in self.stats:
                        if result == RESULT_WIN:
                            self.stats[conn].client_wins += 1
                        elif result == RESULT_LOSS:
                            self.stats[conn].dealer_wins += 1
                        else:
                            self.stats[conn].ties += 1

                print(f"[client='{name}'] final player={player_total} dealer={dealer_total} => {result}")

            # ----- clean up finished players -----
            with self.cond:
                finished = [c for c, r in self.remaining_rounds.items() if r <= 0]
            for c in finished:
                name = self.player_name.get(c, "client")
                st = self.stats.get(c, RoundResults())
                print(f"[DONE] client='{name}' stats: W={st.client_wins} L={st.dealer_wins} T={st.ties}")
                self._drop_player(c, "finished rounds")

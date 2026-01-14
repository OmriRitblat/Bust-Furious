import socket
import threading
from dataclasses import dataclass
from typing import Tuple

import Protocol
import GameSession
import OneBoard

UDP_OFFER_PORT = 13122
OFFER_INTERVAL_SEC = 1.0


@dataclass
class Offer:
    server_tcp_port: int
    server_name: str


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


class OfferBroadcaster(threading.Thread):
    def __init__(self, server_tcp_port: int, server_name: str, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.server_tcp_port = server_tcp_port
        self.server_name = server_name
        self.stop_event = stop_event

    def run(self) -> None:
        msg = Protocol.Protocol.build_offer(Offer(self.server_tcp_port, self.server_name))

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            while not self.stop_event.is_set():
                try:
                    s.sendto(msg, ("<broadcast>", UDP_OFFER_PORT))
                except OSError:
                    pass
                self.stop_event.wait(OFFER_INTERVAL_SEC)
        finally:
            s.close()


class ServerMain:
    def __init__(self, team_name: str):
        self.team_name = team_name
        self.stop_event = threading.Event()

    def run(self) -> None:
        mode = self._choose_mode()

        # TCP listen
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp.bind(("", 0))
        tcp.listen()
        tcp.settimeout(1.0)
        tcp_port = tcp.getsockname()[1]

        ip = get_local_ip()
        print(f"Server started, listening on IP address {ip} TCP port {tcp_port}")
        print(f"Mode: {mode}")

        # UDP offers
        offer_thread = OfferBroadcaster(tcp_port, self.team_name, self.stop_event)
        offer_thread.start()

        board = None
        if mode == "ONEBOARD":
            board = OneBoard.OneBoard(self.team_name)
            threading.Thread(target=board.play_forever, daemon=True).start()

        try:
            while not self.stop_event.is_set():
                try:
                    conn, addr = tcp.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                if mode == "ONEBOARD":
                    t = threading.Thread(target=self._handle_oneboard_join, args=(board, conn, addr), daemon=True)
                    t.start()
                else:
                    session = GameSession.GameSession(conn, addr, self.team_name)
                    t = threading.Thread(target=self._handle_session, args=(session,), daemon=True)
                    t.start()

        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.stop_event.set()
            try:
                tcp.close()
            except OSError:
                pass

    @staticmethod
    def _choose_mode() -> str:
        while True:
            ans = input("Choose mode: [1] One shared board  [2] Session per client : ").strip()
            if ans == "1":
                return "ONEBOARD"
            if ans == "2":
                return "SESSION"
            print("Invalid choice. Enter 1 or 2.")

    @staticmethod
    def _handle_session(session: "GameSession.GameSession") -> None:
        try:
            with session.conn:
                session.play()
        except Exception as e:
            print(f"[ERROR] Session crashed: {e}")

    @staticmethod
    def _handle_oneboard_join(board: "OneBoard.OneBoard", conn: socket.socket, addr: Tuple[str, int]) -> None:
        try:
            board.add_player(conn)
        except Exception as e:
            print(f"[ERROR] OneBoard add_player crashed from {addr}: {e}")
            try:
                conn.close()
            except OSError:
                pass


if __name__ == "__main__":
    try:
        ServerMain(team_name="AlphaTeam").run()
    except KeyboardInterrupt:
        print("\nShutting down...")

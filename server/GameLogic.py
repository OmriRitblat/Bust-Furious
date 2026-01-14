class GameLogic:
    """
    Dealer rule for multi-player board:
    Dealer hits while his total is <= max(player totals) and <= 21
    """

    @staticmethod
    def dealer_should_hit(dealer_total: int, players_hands: dict) -> bool:
        """
        :param dealer_total: current sum of dealer cards
        :param players_hands: dict[conn -> List[Card]]
        :return: True if dealer should take another card
        """

        if dealer_total > 17:
            return False

        best_player = 0
        for hand in players_hands.values():
            total = sum(c.game_value() for c in hand)
            if total <= 21:
                best_player = max(best_player, total)

        if best_player == 0:
            return False

        return dealer_total <= best_player

def dealer_should_hit(dealer_total: int, player_total: int) -> bool:
    """
    Module-level helper for single-player GameSession usage.
    Return True when dealer should hit: dealer hasn't busted, the
    player hasn't busted, and dealer total is <= player total.
    """
    if dealer_total > 17:
        return False
    return dealer_total <= player_total
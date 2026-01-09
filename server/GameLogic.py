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

        # אם הדילר כבר עבר 21 – לא מושך
        if dealer_total > 21:
            return False

        # חישוב הסכום המקסימלי של שחקן שלא עבר 21
        best_player = 0
        for hand in players_hands.values():
            total = sum(c.game_value() for c in hand)
            if total <= 21:
                best_player = max(best_player, total)

        # אם אין אף שחקן פעיל (כולם bust)
        if best_player == 0:
            return False

        # הדילר מושך כל עוד הוא לא גדול מכולם
        return dealer_total <= best_player

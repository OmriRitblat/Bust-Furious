# --------------------------
# Game logic (dealer)
# --------------------------
def dealer_should_hit(total: int,client_total: int) -> bool:
    if(total>client_total):
        return False
    return total < 17


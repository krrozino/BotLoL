def calcular_elo(pdl):
    if pdl < 1000: return "Ferro"
    if pdl < 1200: return "Bronze"
    if pdl < 1400: return "Prata"
    if pdl < 1600: return "Ouro"
    if pdl < 1800: return "Platina"
    if pdl < 2000: return "Esmeralda"
    return "Diamante+"

def calcular_winrate(vitorias, derrotas):
    total = vitorias + derrotas
    if total == 0:
        return "0%"
    wr = (vitorias / total) * 100
    return f"{int(wr)}%"    
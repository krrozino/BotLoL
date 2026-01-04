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

def get_icone_modo(modo):
    """
    Retorna o emoji personalizado do modo de jogo.
    IMPORTANTE: Substitua os exemplos abaixo pelo código que você pegar no Discord
    usando \:nome_do_emoji:
    """
    icones = {
        # Exemplo: "<:nome:ID>"
        "sr": "<:summoners_rift_icon:1457516794183946333>   ",
        "aram": "<:aram_icon:1457516650130706577>",
        "arena": "<:arena_icon:1457516699535278204>"
    }
    # Retorna o emoji ou um controle de videogame genérico se der erro
    return icones.get(modo, "🎮")

def get_icone_elo(pdl):
    """
    Retorna o emoji personalizado do Elo.
    Você também pode criar emojis para cada elo (Ferro, Ouro, etc).
    """
    elo = calcular_elo(pdl)
    icones = {
        # Configure seus emojis de elo aqui também se quiser!
        "Ferro": "<:ferro:1457521262225002536>",       
        "Bronze": "<:bronze:1457521218671607848>",      
        "Prata": "<:prata:1457521313013829842>",       
        "Ouro": "<:ouro:1457521377245663253>",        
        "Platina": "<:platina:1457521475882975375>",     
        "Esmeralda": "<:esmeralda:1457521515372351644>",   
        "Diamante+": "<:diamante:1457521834386915389>"    
    }
    return icones.get(elo, "🏅")
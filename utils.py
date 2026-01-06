import discord

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
    icones = {
        # Exemplo: "<:nome:ID>"
        "sr": "<:summoners_rift_icon:1457516794183946333>   ",
        "aram": "<:aram_icon:1457516650130706577>",
        "arena": "<:arena_icon:1457516699535278204>"
    }
    return icones.get(modo, "🎮")

def get_icone_elo(pdl):
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
    return "🏅"

async def gerenciar_cargos_elo(member: discord.Member, pdl: int, modo: str = "sr"):
    """Atualiza o cargo do jogador baseado no PDL e Modo."""
    guild = member.guild
    elos_base = ["Ferro", "Bronze", "Prata", "Ouro", "Platina", "Esmeralda", "Diamante+"]
    elo_atual_base = calcular_elo(pdl)
    
    suffix = ""
    if modo == "aram": suffix = " ARAM"
    if modo == "arena": suffix = " Arena"
    
    elo_atual_nome = f"{elo_atual_base}{suffix}"
    cargos_modo = [f"{e}{suffix}" for e in elos_base]
    
    # Remove cargos antigos do mesmo modo
    cargos_remover = [r for r in member.roles if r.name in cargos_modo and r.name != elo_atual_nome]
    if cargos_remover:
        try: await member.remove_roles(*cargos_remover)
        except: pass

    # Adiciona o novo
    role_nova = discord.utils.get(guild.roles, name=elo_atual_nome)
    if role_nova and role_nova not in member.roles:
        try: await member.add_roles(role_nova)
        except: pass
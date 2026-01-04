import discord
from discord.ext import commands
import random
import os
from pymongo import MongoClient
from server import keep_alive # Importa o site falso

# --- CONFIGURAÇÃO ---
# O Token e o Link do Banco virão das variáveis do Render
TOKEN = os.environ.get('TOKEN')
MONGO_URL = os.environ.get('MONGO_URL')

# Configuração do Banco de Dados
cluster = MongoClient(MONGO_URL)
db = cluster["InhouseBot"]
collection = db["Jogadores"]

# Configurações do Bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

fila = []
partida_atual = None

# --- FUNÇÕES DE BANCO DE DADOS ---
def get_jogador(user_id):
    return collection.find_one({"_id": str(user_id)})

def criar_jogador(user_id, nick, opgg):
    collection.insert_one({
        "_id": str(user_id),
        "nick": nick,
        "opgg": opgg,
        "pdl": 1000,
        "vitorias": 0,
        "derrotas": 0
    })

def atualizar_pdl(user_id, pdl_mudanca, vitoria):
    # $inc aumenta ou diminui o valor. $set atualiza valores fixos
    update_query = {
        "$inc": {"pdl": pdl_mudanca, "vitorias": 1 if vitoria else 0, "derrotas": 0 if vitoria else 1}
    }
    collection.update_one({"_id": str(user_id)}, update_query)
    
    # Garante que não fique negativo
    jogador = get_jogador(user_id)
    if jogador["pdl"] < 0:
        collection.update_one({"_id": str(user_id)}, {"$set": {"pdl": 0}})

def calcular_elo(pdl):
    if pdl < 1000: return "Ferro"
    if pdl < 1200: return "Bronze"
    if pdl < 1400: return "Prata"
    if pdl < 1600: return "Ouro"
    if pdl < 1800: return "Platina"
    if pdl < 2000: return "Esmeralda"
    return "Diamante+"

# --- COMANDOS ---

@bot.event
async def on_ready():
    print(f'✅ Bot Online e Conectado ao Banco!')

@bot.command()
async def registrar(ctx, nick: str, opgg: str = "Não informado"):
    if get_jogador(ctx.author.id):
        await ctx.send(f"{ctx.author.mention}, você já está registrado!")
    else:
        criar_jogador(ctx.author.id, nick, opgg)
        await ctx.send(f"✅ Conta criada para **{nick}** com 1000 PDL!")

@bot.command()
async def perfil(ctx, membro: discord.Member = None):
    alvo = membro or ctx.author
    dados = get_jogador(alvo.id)

    if not dados:
        await ctx.send("Jogador não registrado. Use !registrar")
        return

    elo = calcular_elo(dados['pdl'])
    msg = f"**Perfil de {dados['nick']}**\n"
    msg += f"🏅 Elo: **{elo}** ({dados['pdl']} PDL)\n"
    msg += f"⚔️ V/D: {dados['vitorias']}/{dados['derrotas']}\n"
    if dados['opgg'] != "Não informado":
        msg += f"🔗 OP.GG: <{dados['opgg']}>"
    
    await ctx.send(msg)

@bot.command()
async def join(ctx):
    if not get_jogador(ctx.author.id):
        await ctx.send("Registre-se primeiro com !registrar Nick")
        return
    
    if ctx.author in fila:
        await ctx.send("Você já está na fila.")
    else:
        fila.append(ctx.author)
        await ctx.send(f"{ctx.author.mention} entrou! ({len(fila)}/10)")
        if len(fila) == 10: # Mude para 2 para testar
            await iniciar_partida(ctx)

@bot.command()
async def start(ctx):
    if len(fila) < 10: # Mude aqui para testes
        await ctx.send(f"Faltam {10 - len(fila)} jogadores.")
    else:
        await iniciar_partida(ctx)

async def iniciar_partida(ctx):
    global partida_atual
    random.shuffle(fila)
    time_azul = fila[:5]
    time_vermelho = fila[5:]
    partida_atual = {'azul': time_azul, 'vermelho': time_vermelho}
    
    msg = "**🟦 TIME AZUL:**\n"
    for p in time_azul:
        d = get_jogador(p.id)
        msg += f"- {d['nick']} ({d['pdl']} PDL)\n"
        
    msg += "\n**🟥 TIME VERMELHO:**\n"
    for p in time_vermelho:
        d = get_jogador(p.id)
        msg += f"- {d['nick']} ({d['pdl']} PDL)\n"
        
    await ctx.send(msg)
    fila.clear()

@bot.command()
@commands.has_permissions(administrator=True)
async def vitoria(ctx, time_vencedor: str):
    global partida_atual
    if not partida_atual:
        await ctx.send("Sem partida rolando.")
        return

    time_vencedor = time_vencedor.lower()
    if time_vencedor not in ['azul', 'vermelho']:
        await ctx.send("Use azul ou vermelho.")
        return

    ganhadores = partida_atual[time_vencedor]
    perdedores = partida_atual['vermelho'] if time_vencedor == 'azul' else partida_atual['azul']
    
    msg = f"🏆 **VITÓRIA DO {time_vencedor.upper()}**\n"
    
    for p in ganhadores:
        atualizar_pdl(p.id, 20, True)
        d = get_jogador(p.id)
        msg += f"📈 {d['nick']}: +20 ({d['pdl']})\n"
        
    for p in perdedores:
        atualizar_pdl(p.id, -20, False)
        d = get_jogador(p.id)
        msg += f"📉 {d['nick']}: -20 ({d['pdl']})\n"

    partida_atual = None
    await ctx.send(msg)

# Liga o servidor web e o bot
keep_alive()
bot.run(TOKEN)
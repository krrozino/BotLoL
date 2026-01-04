import discord
from discord.ext import commands
import random
import os
from server import keep_alive

# Importando nossas funções dos outros arquivos
from database import get_jogador, criar_jogador, atualizar_pdl
from utils import calcular_elo

# --- CONFIGURAÇÃO ---
TOKEN = os.environ.get('TOKEN')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

# Variáveis globais (Memória RAM)
fila = []
partida_atual = None

# --- EVENTOS E COMANDOS ---

@bot.event
async def on_ready():
    print(f'✅ Bot Online: {bot.user}')

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
        if len(fila) == 10: 
            await iniciar_partida(ctx)

@bot.command()
async def leave(ctx):
    if ctx.author in fila:
        fila.remove(ctx.author)
        await ctx.send(f"🏃 {ctx.author.mention} saiu da fila. ({len(fila)}/10)")
    else:
        await ctx.send("Você não está na fila.")

@bot.command()
async def fila(ctx):
    if not fila:
        await ctx.send("A fila está vazia.")
    else:
        nomes = [p.display_name for p in fila]
        await ctx.send(f"📋 **Fila Atual ({len(fila)}/10):**\n" + "\n".join(nomes))

@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx):
    fila.clear()
    await ctx.send("🧹 Fila limpa por um administrador!")

@bot.command()
async def start(ctx):
    if len(fila) < 10: 
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

# Help e Error Handler
@bot.command()
async def help(ctx):
    embed = discord.Embed(title="📜 Central de Ajuda", color=0x00ff00)
    embed.add_field(name="Jogadores", value="`!registrar`, `!perfil`, `!join`, `!leave`, `!fila`", inline=False)
    embed.add_field(name="Admins", value="`!start`, `!vitoria`, `!reset`", inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Use: `{ctx.prefix}{ctx.command.name} <argumento>`")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"Erro: {error}")

keep_alive()
bot.run(TOKEN)
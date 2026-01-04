import discord
from discord import app_commands
from discord.ext import commands
import os
from server import keep_alive

# Importando database
from database import (
    get_jogador, criar_jogador, atualizar_pdl, atualizar_rota, 
    get_ranking, editar_perfil, set_pdl_manual, get_dados_varios, 
    adicionar_mvp, resgatar_diario, salvar_historico, get_ultimas_partidas
)
from utils import calcular_elo, calcular_winrate

TOKEN = os.environ.get('TOKEN')
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

fila = []
# partida_atual agora guarda: {'azul': [], 'vermelho': [], 'modo': 'sr', 'valendo_pdl': True}
partida_atual = None 

# --- GRUPO DE COMANDOS DE ADMINISTRAÇÃO ---
class AdminGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="admin", description="Comandos de Admin")

    @app_commands.command(name="kick", description="Remove jogador da fila.")
    @app_commands.default_permissions(administrator=True)
    async def kick(self, interaction: discord.Interaction, membro: discord.Member):
        if membro in fila:
            fila.remove(membro)
            await interaction.response.send_message(f"👢 **{membro.display_name}** removido da fila.")
        else:
            await interaction.response.send_message("❌ Não está na fila.", ephemeral=True)

    @app_commands.command(name="reset", description="Limpa fila.")
    @app_commands.default_permissions(administrator=True)
    async def reset(self, interaction: discord.Interaction):
        fila.clear()
        await interaction.response.send_message("🧹 Fila limpa.")

    @app_commands.command(name="setpdl", description="Define PDL manual (Sempre SR).")
    @app_commands.default_permissions(administrator=True)
    async def setpdl(self, interaction: discord.Interaction, membro: discord.Member, quantidade: int):
        set_pdl_manual(membro.id, quantidade)
        await interaction.response.send_message(f"👮 PDL de **{membro.display_name}** definido para **{quantidade}**.")

    @app_commands.command(name="cancelar", description="Cancela partida atual.")
    @app_commands.default_permissions(administrator=True)
    async def cancelar(self, interaction: discord.Interaction):
        global partida_atual
        if not partida_atual:
            await interaction.response.send_message("❌ Sem partida rolando.", ephemeral=True)
            return
        partida_atual = None
        await interaction.response.send_message("🚫 Partida cancelada.")

    @app_commands.command(name="shuffle", description="Re-balancea os times (Respeita o Modo).")
    @app_commands.default_permissions(administrator=True)
    async def shuffle(self, interaction: discord.Interaction):
        global partida_atual
        if not partida_atual:
            await interaction.response.send_message("❌ Nenhuma partida para misturar.", ephemeral=True)
            return
        
        modo_jogo = partida_atual.get('modo', 'sr')
        todos = partida_atual['azul'] + partida_atual['vermelho']
        
        # Busca dados
        ids = [p.id for p in todos]
        dados = get_dados_varios(ids)
        mapa = {d['_id']: d for d in dados}

        campo_pdl = "pdl"
        if modo_jogo == "aram": campo_pdl = "pdl_aram"
        if modo_jogo == "arena": campo_pdl = "pdl_arena"

        # Ordena por PDL
        ordenados = sorted(todos, key=lambda p: mapa.get(str(p.id), {}).get(campo_pdl, 1000), reverse=True)
        
        # Algoritmo Genérico de Balanceamento (Snake Draft Adaptável: A, B, B, A...)
        azul, verm = [], []
        for i, p in enumerate(ordenados):
            # Lógica: 0->Azul, 1->Verm, 2->Verm, 3->Azul, 4->Azul, 5->Verm...
            if i % 4 == 0 or i % 4 == 3:
                azul.append(p)
            else:
                verm.append(p)
        
        partida_atual['azul'] = azul
        partida_atual['vermelho'] = verm
        
        # Embed Visual
        soma_azul = sum([mapa[str(p.id)].get(campo_pdl, 1000) for p in azul])
        soma_verm = sum([mapa[str(p.id)].get(campo_pdl, 1000) for p in verm])
        qtd = len(azul) if len(azul) > 0 else 1 # Evita divisão por zero
        
        def fmt(p):
            d = mapa.get(str(p.id))
            r = d.get('rota', '❔') if modo_jogo == "sr" else "🎲"
            return f"{r} **{d['nick']}** ({d.get(campo_pdl, 1000)})"

        embed = discord.Embed(title=f"🔄 Times Misturados ({modo_jogo.upper()})!", color=0xe67e22)
        embed.add_field(name=f"🟦 AZUL (Méd: {int(soma_azul/qtd)})", value="\n".join([fmt(p) for p in azul]), inline=False)
        embed.add_field(name=f"🟥 VERMELHO (Méd: {int(soma_verm/qtd)})", value="\n".join([fmt(p) for p in verm]), inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="vitoria", description="Finaliza a partida.")
    @app_commands.choices(time=[
        app_commands.Choice(name="🟦 Time Azul", value="azul"),
        app_commands.Choice(name="🟥 Time Vermelho", value="vermelho")
    ])
    @app_commands.default_permissions(administrator=True)
    async def vitoria(self, interaction: discord.Interaction, time: app_commands.Choice[str]):
        global partida_atual
        if not partida_atual:
            await interaction.response.send_message("❌ Sem partida.", ephemeral=True)
            return

        await interaction.response.defer()
        
        modo_jogo = partida_atual.get('modo', 'sr')
        valendo_pdl = partida_atual.get('valendo_pdl', True)
        vencedor = time.value
        ganhadores = partida_atual[vencedor]
        perdedores = partida_atual['vermelho'] if vencedor == 'azul' else partida_atual['azul']
        
        # Salva histórico (Mesmo sem valer PDL, fica no histórico)
        nomes_azul = [get_jogador(p.id)['nick'] for p in partida_atual['azul']]
        nomes_vermelho = [get_jogador(p.id)['nick'] for p in partida_atual['vermelho']]
        salvar_historico(vencedor, nomes_azul, nomes_vermelho, modo_jogo)

        # Monta a mensagem
        tipo_partida = "RANKED" if valendo_pdl else "PERSONALIZADA (Sem PDL)"
        msg = f"🏆 **VITÓRIA {vencedor.upper()}** - {tipo_partida}\n\n"
        
        if valendo_pdl:
            # Lógica Normal de Ranked
            for p in ganhadores:
                bonus = atualizar_pdl(p.id, 20, True, modo=modo_jogo) 
                d = get_jogador(p.id)
                campo_pdl = "pdl" if modo_jogo == "sr" else f"pdl_{modo_jogo}"
                aviso = "🔥" if bonus > 0 else ""
                msg += f"📈 {d['nick']}: +{20+bonus} ({d.get(campo_pdl, 0)}) {aviso}\n"
            msg += "\n"
            for p in perdedores:
                atualizar_pdl(p.id, -20, False, modo=modo_jogo)
                d = get_jogador(p.id)
                campo_pdl = "pdl" if modo_jogo == "sr" else f"pdl_{modo_jogo}"
                msg += f"📉 {d['nick']}: -20 ({d.get(campo_pdl, 0)})\n"
        else:
            # Lógica Unranked (Apenas lista os jogadores)
            msg += "**Jogadores Vitoriosos:**\n"
            for p in ganhadores:
                msg += f"✨ {p.display_name}\n"

        partida_atual = None
        await interaction.followup.send(msg)

# --- COMANDOS PÚBLICOS ---

@bot.event
async def on_ready():
    print(f'✅ Bot Online: {bot.user}')
    try:
        bot.tree.add_command(AdminGroup())
        await bot.tree.sync()
    except Exception as e:
        print(e)

@bot.hybrid_command(name="registrar", description="Cria conta.")
async def registrar(ctx, nick: str, opgg: str = "Não informado"):
    if get_jogador(ctx.author.id):
        await ctx.send("Já registrado!", ephemeral=True)
    else:
        criar_jogador(ctx.author.id, nick, opgg)
        await ctx.send(f"✅ Conta criada para **{nick}**!")

@bot.hybrid_command(name="join", description="Entrar na fila.")
async def join(ctx):
    if not get_jogador(ctx.author.id): return await ctx.send("Use /registrar", ephemeral=True)
    if ctx.author in fila: return await ctx.send("Já na fila.", ephemeral=True)
    
    fila.append(ctx.author)
    await ctx.send(f"⚔️ {ctx.author.mention} entrou! ({len(fila)} Jogadores)")
    
    if len(fila) == 10:
        await ctx.send("🔥 **Fila Cheia (10)!** Admin, use `/start`.")

@bot.hybrid_command(name="leave", description="Sair da fila.")
async def leave(ctx):
    if ctx.author in fila:
        fila.remove(ctx.author)
        await ctx.send(f"🏃 {ctx.author.mention} saiu.")
    else:
        await ctx.send("Não está na fila.", ephemeral=True)

@bot.hybrid_command(name="fila", description="Ver fila.")
async def ver_fila(ctx):
    if not fila: return await ctx.send("Fila vazia.")
    nomes = [p.display_name for p in fila]
    await ctx.send(f"📋 **Fila ({len(fila)}):**\n" + "\n".join(nomes))

@bot.hybrid_command(name="rota", description="Define posição (Apenas SR).")
@app_commands.choices(lane=[
    app_commands.Choice(name="Top", value="top"),
    app_commands.Choice(name="Jungle", value="jungle"),
    app_commands.Choice(name="Mid", value="mid"),
    app_commands.Choice(name="ADC", value="adc"),
    app_commands.Choice(name="Support", value="sup"),
    app_commands.Choice(name="Fill", value="fill")
])
async def rota(ctx, lane: app_commands.Choice[str]):
    lanes = {"top": "🛡️ Top", "jungle": "🌲 Jungle", "mid": "🧙‍♂️ Mid", "adc": "🏹 ADC", "sup": "❤️ Sup", "fill": "🔄 Fill"}
    atualizar_rota(ctx.author.id, lanes[lane.value])
    await ctx.send(f"✅ Rota: **{lanes[lane.value]}**", ephemeral=True)

# --- START ATUALIZADO ---
@bot.hybrid_command(name="start", description="Inicia partida personalizada.")
@app_commands.choices(modo=[
    app_commands.Choice(name="🗺️ Summoner's Rift", value="sr"),
    app_commands.Choice(name="❄️ ARAM", value="aram"),
    app_commands.Choice(name="⚔️ Arena", value="arena")
])
@app_commands.describe(
    valendo_pdl="Se 'False', a partida não altera os pontos (Scrim/Custom). Padrão: True.",
    ignorar_tamanho="Se 'True', força o início com qualquer número par de jogadores (1v1, 2v2...)."
)
async def start(ctx, modo: app_commands.Choice[str], valendo_pdl: bool = True, ignorar_tamanho: bool = False):
    modo_valor = modo.value if modo else "sr"
    
    # Validações de tamanho
    qtd = len(fila)
    if qtd < 2:
        await ctx.send("❌ Mínimo de 2 jogadores para iniciar.")
        return
    
    # Se não forçar, exige 10 players
    if not ignorar_tamanho and qtd < 10:
        await ctx.send(f"⚠️ A fila tem apenas {qtd} jogadores. Para iniciar assim mesmo (1v1, 2v2, etc), use o parâmetro `ignorar_tamanho: True`.")
        return
    
    if qtd % 2 != 0:
        await ctx.send(f"⚠️ A fila tem {qtd} jogadores (ímpar). Alguém precisa sair ou entrar para balancear os times.")
        return

    await iniciar_partida(ctx, modo_valor, valendo_pdl)

async def iniciar_partida(ctx, modo_jogo, valendo_pdl):
    global partida_atual
    
    if isinstance(ctx, discord.Interaction): responder = ctx.response.send_message
    else: responder = ctx.send

    tipo_txt = "🚫 Unranked" if not valendo_pdl else "🏆 Ranked"
    await responder(f"⚖️ **Iniciando {modo_jogo.upper()} ({len(fila)} players) - {tipo_txt}**")

    ids = [p.id for p in fila]
    dados = get_dados_varios(ids)
    mapa = {d['_id']: d for d in dados}
    
    campo_pdl = "pdl"
    if modo_jogo == "aram": campo_pdl = "pdl_aram"
    if modo_jogo == "arena": campo_pdl = "pdl_arena"

    # Ordena pelo PDL
    ordenados = sorted(fila, key=lambda p: mapa.get(str(p.id), {}).get(campo_pdl, 1000), reverse=True)
    
    # Algoritmo de Balanceamento Genérico (Funciona pra 2, 4, 6, 8, 10...)
    azul, verm = [], []
    for i, p in enumerate(ordenados):
        if i % 4 == 0 or i % 4 == 3: # Padrão A, B, B, A
            azul.append(p)
        else:
            verm.append(p)

    partida_atual = {'azul': azul, 'vermelho': verm, 'modo': modo_jogo, 'valendo_pdl': valendo_pdl}
    
    soma_azul = sum([mapa[str(p.id)].get(campo_pdl, 1000) for p in azul])
    soma_verm = sum([mapa[str(p.id)].get(campo_pdl, 1000) for p in verm])
    qtd_time = len(azul)
    
    def fmt(p):
        d = mapa.get(str(p.id))
        r = d.get('rota', '❔') if modo_jogo == "sr" else "🎲"
        return f"{r} **{d['nick']}** ({d.get(campo_pdl, 1000)})"

    embed = discord.Embed(title=f"⚔️ Partida {modo_jogo.upper()} Iniciada!", color=0x0099ff)
    if not valendo_pdl:
        embed.set_author(name="Modo Treino / Amistoso (Sem PDL)")
        
    embed.add_field(name=f"🟦 AZUL (Méd: {int(soma_azul/qtd_time)})", value="\n".join([fmt(p) for p in azul]), inline=False)
    embed.add_field(name=f"🟥 VERMELHO (Méd: {int(soma_verm/qtd_time)})", value="\n".join([fmt(p) for p in verm]), inline=False)
    
    channel = ctx.channel if hasattr(ctx, 'channel') else ctx.user
    if isinstance(ctx, discord.Interaction): await ctx.followup.send(embed=embed)
    else: await ctx.send(embed=embed)
    
    # DM Notificação
    for jogador in fila:
        try:
            await jogador.send(f"🎮 **Partida Iniciada!**\nCanal: {channel.mention}")
        except: pass

    fila.clear()

@bot.hybrid_command(name="perfil", description="Ver stats.")
async def perfil(ctx, membro: discord.Member = None):
    alvo = membro or ctx.author
    d = get_jogador(alvo.id)
    if not d: return await ctx.send("Não registrado.", ephemeral=True)

    embed = discord.Embed(title=f"📊 {d['nick']}", color=0x9b59b6)
    
    sr = d.get('pdl', 1000)
    aram = d.get('pdl_aram', 1000)
    arena = d.get('pdl_arena', 1000)

    embed.add_field(name="🗺️ Rift", value=f"**{calcular_elo(sr)}**\n{sr} PDL", inline=True)
    embed.add_field(name="❄️ ARAM", value=f"**{calcular_elo(aram)}**\n{aram} PDL", inline=True)
    embed.add_field(name="⚔️ Arena", value=f"**{calcular_elo(arena)}**\n{arena} PDL", inline=True)
    
    wr = calcular_winrate(d['vitorias'], d['derrotas'])
    embed.set_footer(text=f"Winrate Geral: {wr} | MVPs: {d.get('mvps', 0)}")
    
    await ctx.send(embed=embed)

@bot.hybrid_command(name="ranking", description="Top Jogadores por Modo.")
@app_commands.choices(modo=[
    app_commands.Choice(name="🗺️ Summoner's Rift", value="sr"),
    app_commands.Choice(name="❄️ ARAM", value="aram"),
    app_commands.Choice(name="⚔️ Arena", value="arena")
])
async def ranking(ctx, modo: app_commands.Choice[str] = None):
    sel_modo = modo.value if modo else "sr"
    top = get_ranking(sel_modo)
    
    embed = discord.Embed(title=f"🏆 Ranking - {sel_modo.upper()}", color=0xffd700)
    txt = ""
    for i, p in enumerate(top):
        if sel_modo == "sr": val = p.get('pdl', 1000)
        elif sel_modo == "aram": val = p.get('pdl_aram', 1000)
        else: val = p.get('pdl_arena', 1000)
        txt += f"**{i+1}º {p['nick']}** — {val} PDL\n"
    
    embed.description = txt if txt else "Ninguém jogou ainda."
    await ctx.send(embed=embed)

@bot.command()
async def diario(ctx):
    sucesso, msg = resgatar_diario(ctx.author.id)
    await ctx.send(f"💰 {ctx.author.mention}, {msg}")

@bot.command()
async def mvp(ctx, membro: discord.Member):
    if ctx.author.id == membro.id: return await ctx.send("❌ Não vote em si mesmo!")
    adicionar_mvp(membro.id)
    await ctx.send(f"🌟 MVP para **{membro.display_name}**!")

@bot.command()
async def historico(ctx):
    partidas = get_ultimas_partidas()
    if not partidas: return await ctx.send("Sem histórico.")
    embed = discord.Embed(title="📜 Últimas Partidas", color=0xbdc3c7)
    for p in partidas:
        v = p['vencedor']
        m = p.get('modo', 'sr').upper()
        embed.add_field(name=f"🏆 {v.upper()} ({m})", value=f"**Azul:** {', '.join(p['azul'])}\n**Verm:** {', '.join(p['vermelho'])}", inline=False)
    await ctx.send(embed=embed)

keep_alive()
bot.run(TOKEN)
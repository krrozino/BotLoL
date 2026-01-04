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
partida_atual = None 

# --- FUNÇÃO AUXILIAR DE CARGOS ---
async def gerenciar_cargos_elo(member: discord.Member, pdl: int):
    """
    Remove cargos de elo antigos e adiciona o novo baseado no PDL.
    """
    guild = member.guild
    elos_nomes = ["Ferro", "Bronze", "Prata", "Ouro", "Platina", "Esmeralda", "Diamante+"]
    elo_atual = calcular_elo(pdl) # Vem do utils.py
    
    # 1. Identifica cargos antigos para remover
    cargos_para_remover = []
    for role in member.roles:
        if role.name in elos_nomes and role.name != elo_atual:
            cargos_para_remover.append(role)
    
    # Remove antigos
    if cargos_para_remover:
        try:
            await member.remove_roles(*cargos_para_remover)
        except Exception as e:
            print(f"Erro ao remover cargos de {member.display_name}: {e}")

    # 2. Adiciona o novo
    role_nova = discord.utils.get(guild.roles, name=elo_atual)
    if role_nova and role_nova not in member.roles:
        try:
            await member.add_roles(role_nova)
        except Exception as e:
            print(f"Erro ao dar cargo {elo_atual} para {member.display_name}: {e}")

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

    @app_commands.command(name="setpdl", description="Define PDL manual (Atualiza cargo).")
    @app_commands.default_permissions(administrator=True)
    async def setpdl(self, interaction: discord.Interaction, membro: discord.Member, quantidade: int):
        set_pdl_manual(membro.id, quantidade)
        await gerenciar_cargos_elo(membro, quantidade)
        await interaction.response.send_message(f"👮 PDL de **{membro.display_name}** definido para **{quantidade}**. Cargos atualizados.")

    @app_commands.command(name="cancelar", description="Cancela partida atual.")
    @app_commands.default_permissions(administrator=True)
    async def cancelar(self, interaction: discord.Interaction):
        global partida_atual
        if not partida_atual:
            await interaction.response.send_message("❌ Sem partida rolando.", ephemeral=True)
            return
        partida_atual = None
        await interaction.response.send_message("🚫 Partida cancelada.")

    @app_commands.command(name="shuffle", description="Re-balancea os times.")
    @app_commands.default_permissions(administrator=True)
    async def shuffle(self, interaction: discord.Interaction):
        global partida_atual
        if not partida_atual:
            await interaction.response.send_message("❌ Nenhuma partida para misturar.", ephemeral=True)
            return
        
        modo_jogo = partida_atual.get('modo', 'sr')
        todos = partida_atual['azul'] + partida_atual['vermelho']
        
        ids = [p.id for p in todos]
        dados = get_dados_varios(ids)
        mapa = {d['_id']: d for d in dados}

        campo_pdl = "pdl"
        if modo_jogo == "aram": campo_pdl = "pdl_aram"
        if modo_jogo == "arena": campo_pdl = "pdl_arena"

        ordenados = sorted(todos, key=lambda p: mapa.get(str(p.id), {}).get(campo_pdl, 1000), reverse=True)
        
        azul, verm = [], []
        for i, p in enumerate(ordenados):
            if i % 4 == 0 or i % 4 == 3: azul.append(p)
            else: verm.append(p)
        
        partida_atual['azul'] = azul
        partida_atual['vermelho'] = verm
        
        qtd = len(azul) if len(azul) > 0 else 1
        soma_azul = sum([mapa[str(p.id)].get(campo_pdl, 1000) for p in azul])
        soma_verm = sum([mapa[str(p.id)].get(campo_pdl, 1000) for p in verm])
        
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
        
        nomes_azul = [get_jogador(p.id)['nick'] for p in partida_atual['azul']]
        nomes_vermelho = [get_jogador(p.id)['nick'] for p in partida_atual['vermelho']]
        salvar_historico(vencedor, nomes_azul, nomes_vermelho, modo_jogo)

        tipo_partida = "RANKED" if valendo_pdl else "PERSONALIZADA"
        msg = f"🏆 **VITÓRIA {vencedor.upper()}** - {tipo_partida}\n\n"
        
        if valendo_pdl:
            for p in ganhadores:
                bonus = atualizar_pdl(p.id, 20, True, modo=modo_jogo) 
                d = get_jogador(p.id)
                pdl_novo = d.get("pdl", 1000) if modo_jogo == "sr" else d.get(f"pdl_{modo_jogo}", 1000)
                if modo_jogo == "sr": await gerenciar_cargos_elo(p, pdl_novo)
                aviso = "🔥" if bonus > 0 else ""
                msg += f"📈 {d['nick']}: +{20+bonus} ({pdl_novo}) {aviso}\n"
            
            msg += "\n"
            for p in perdedores:
                atualizar_pdl(p.id, -20, False, modo=modo_jogo)
                d = get_jogador(p.id)
                pdl_novo = d.get("pdl", 1000) if modo_jogo == "sr" else d.get(f"pdl_{modo_jogo}", 1000)
                if modo_jogo == "sr": await gerenciar_cargos_elo(p, pdl_novo)
                msg += f"📉 {d['nick']}: -20 ({pdl_novo})\n"
        else:
            msg += "**Jogadores:**\n"
            for p in ganhadores: msg += f"✨ {p.display_name}\n"

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
        print(f"Erro sync: {e}")

@bot.hybrid_command(name="registrar", description="Cria sua conta.")
@app_commands.describe(nick="Nick do LoL", opgg="Link do OP.GG")
async def registrar(ctx, nick: str, opgg: str = "Não informado"):
    if get_jogador(ctx.author.id):
        await ctx.send("Você já está registrado!", ephemeral=True)
        return

    try:
        criar_jogador(ctx.author.id, nick, opgg)
        msg = f"✅ Conta criada para **{nick}**!"
        
        cargo_reg = discord.utils.get(ctx.guild.roles, name="Registrado")
        cargo_nreg = discord.utils.get(ctx.guild.roles, name="Não Registrado")

        if cargo_reg:
            try: await ctx.author.add_roles(cargo_reg)
            except: pass
        if cargo_nreg:
            try: await ctx.author.remove_roles(cargo_nreg)
            except: pass
        
        await gerenciar_cargos_elo(ctx.author, 1000)
        msg += " Cargos aplicados!"
        await ctx.send(msg)
    except Exception as e:
        await ctx.send(f"❌ Erro: {e}", ephemeral=True)

@bot.hybrid_command(name="join", description="Entrar na fila.")
async def join(ctx):
    if not get_jogador(ctx.author.id): return await ctx.send("Use /registrar", ephemeral=True)
    if ctx.author in fila: return await ctx.send("Já na fila.", ephemeral=True)
    
    fila.append(ctx.author)
    await ctx.send(f"⚔️ {ctx.author.mention} entrou! ({len(fila)} Jogadores)")
    if len(fila) == 10: await ctx.send("🔥 **Fila Cheia (10)!** Admin, use `/start`.")

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

@bot.hybrid_command(name="rota", description="Define posição (SR).")
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

@bot.hybrid_command(name="start", description="Inicia partida.")
@app_commands.choices(modo=[
    app_commands.Choice(name="🗺️ Summoner's Rift", value="sr"),
    app_commands.Choice(name="❄️ ARAM", value="aram"),
    app_commands.Choice(name="⚔️ Arena", value="arena")
])
@app_commands.describe(valendo_pdl="Conta pontos? (Padrão: True)", ignorar_tamanho="Forçar início com <10?")
async def start(ctx, modo: app_commands.Choice[str], valendo_pdl: bool = True, ignorar_tamanho: bool = False):
    modo_valor = modo.value if modo else "sr"
    qtd = len(fila)
    if qtd < 2: return await ctx.send("❌ Mínimo 2 jogadores.")
    if not ignorar_tamanho and qtd < 10: return await ctx.send(f"⚠️ Faltam players. Use `ignorar_tamanho: True` se quiser forçar.")
    if qtd % 2 != 0: return await ctx.send("⚠️ Número ímpar de jogadores.")
    await iniciar_partida(ctx, modo_valor, valendo_pdl)

async def iniciar_partida(ctx, modo_jogo, valendo_pdl):
    global partida_atual
    if isinstance(ctx, discord.Interaction): responder = ctx.response.send_message
    else: responder = ctx.send

    txt = "🏆 Ranked" if valendo_pdl else "🚫 Unranked"
    await responder(f"⚖️ **Iniciando {modo_jogo.upper()} ({len(fila)}) - {txt}**")

    ids = [p.id for p in fila]
    dados = get_dados_varios(ids)
    mapa = {d['_id']: d for d in dados}
    
    campo_pdl = "pdl"
    if modo_jogo == "aram": campo_pdl = "pdl_aram"
    if modo_jogo == "arena": campo_pdl = "pdl_arena"

    ordenados = sorted(fila, key=lambda p: mapa.get(str(p.id), {}).get(campo_pdl, 1000), reverse=True)
    
    azul, verm = [], []
    for i, p in enumerate(ordenados):
        if i % 4 == 0 or i % 4 == 3: azul.append(p)
        else: verm.append(p)

    partida_atual = {'azul': azul, 'vermelho': verm, 'modo': modo_jogo, 'valendo_pdl': valendo_pdl}
    
    soma_azul = sum([mapa[str(p.id)].get(campo_pdl, 1000) for p in azul])
    soma_verm = sum([mapa[str(p.id)].get(campo_pdl, 1000) for p in verm])
    qtd_time = len(azul) if azul else 1
    
    def fmt(p):
        d = mapa.get(str(p.id))
        r = d.get('rota', '❔') if modo_jogo == "sr" else "🎲"
        return f"{r} **{d['nick']}** ({d.get(campo_pdl, 1000)})"

    embed = discord.Embed(title=f"⚔️ Partida {modo_jogo.upper()}!", color=0x0099ff)
    embed.add_field(name=f"🟦 AZUL (Méd: {int(soma_azul/qtd_time)})", value="\n".join([fmt(p) for p in azul]), inline=False)
    embed.add_field(name=f"🟥 VERMELHO (Méd: {int(soma_verm/qtd_time)})", value="\n".join([fmt(p) for p in verm]), inline=False)
    
    if isinstance(ctx, discord.Interaction): await ctx.followup.send(embed=embed)
    else: await ctx.send(embed=embed)
    
    channel = ctx.channel if hasattr(ctx, 'channel') else ctx.user
    for p in fila:
        try: await p.send(f"🎮 **Partida Iniciada!**\nCanal: {channel.mention}")
        except: pass
    fila.clear()

@bot.hybrid_command(name="perfil", description="Ver stats.")
async def perfil(ctx, membro: discord.Member = None):
    alvo = membro or ctx.author
    d = get_jogador(alvo.id)
    if not d: return await ctx.send("Não registrado.", ephemeral=True)

    embed = discord.Embed(title=f"📊 {d['nick']}", color=0x9b59b6)
    sr, aram, arena = d.get('pdl', 1000), d.get('pdl_aram', 1000), d.get('pdl_arena', 1000)

    embed.add_field(name="🗺️ Rift", value=f"**{calcular_elo(sr)}**\n{sr} PDL", inline=True)
    embed.add_field(name="❄️ ARAM", value=f"**{calcular_elo(aram)}**\n{aram} PDL", inline=True)
    embed.add_field(name="⚔️ Arena", value=f"**{calcular_elo(arena)}**\n{arena} PDL", inline=True)
    
    wr = calcular_winrate(d['vitorias'], d['derrotas'])
    embed.set_footer(text=f"Winrate Geral: {wr} | MVPs: {d.get('mvps', 0)}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="ranking", description="Top Jogadores.")
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
        val = p.get('pdl', 1000) if sel_modo == "sr" else p.get(f'pdl_{sel_modo}', 1000)
        txt += f"**{i+1}º {p['nick']}** — {val} PDL\n"
    embed.description = txt if txt else "Vazio."
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

@bot.hybrid_command(name="help", description="Mostra a lista de todos os comandos.")
async def help(ctx):
    embed = discord.Embed(title="📘 Manual do Bot - Inhouse", description="Lista de comandos disponíveis.", color=0x3498db)
    
    # Comandos para todos
    txt_jogadores = """
    `/registrar` - Cria sua conta (obrigatório).
    `/join` - Entra na fila para jogar.
    `/leave` - Sai da fila.
    `/fila` - Mostra a lista de espera.
    `/rota` - Escolhe sua posição (Top, Jungle, etc).
    `/perfil` - Vê seu Elo, Vitórias e Winrate.
    `/ranking` - Mostra o Top 10 do servidor.
    `!diario` - Resgata pontos grátis todo dia.
    `!mvp @jogador` - Vota no destaque da partida.
    `!historico` - Vê resultados recentes.
    """
    embed.add_field(name="🎮 Jogadores", value=txt_jogadores, inline=False)

    # Comandos para Admins (Só mostra se tiver permissão, visualmente ajuda saber que existem)
    txt_admin = """
    `/start` - Inicia a partida (SR, ARAM, Arena).
    `/admin vitoria` - Finaliza o jogo e distribui PDL.
    `/admin shuffle` - Mistura os times novamente.
    `/admin kick` - Remove alguém da fila.
    `/admin setpdl` - Edita pontos manualmente.
    `/admin cancelar` - Cancela partida em andamento.
    `/admin reset` - Limpa a fila inteira.
    """
    embed.add_field(name="👮 Administração", value=txt_admin, inline=False)
    
    embed.set_footer(text="Dica: Comandos com '/' são mais fáceis de usar!")
    
    await ctx.send(embed=embed)     

keep_alive()
bot.run(TOKEN)
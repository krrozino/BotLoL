import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import datetime
from server import keep_alive

# Importando database
from database import (
    get_jogador, criar_jogador, atualizar_pdl, atualizar_rota, 
    get_ranking, editar_perfil, set_pdl_manual, get_dados_varios, 
    adicionar_mvp, resgatar_diario, salvar_historico, get_ultimas_partidas,
    aplicar_punicao, checar_banimento
)
from utils import calcular_elo, calcular_winrate, get_icone_modo, get_icone_elo

TOKEN = os.environ.get('TOKEN')
CANAL_LOGS_NOME = "logs-inhouse" 
CATEGORIA_INHOUSE_NOME = "🏆 Partidas Inhouse"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

fila = []
partida_atual = None 
ultimo_movimento_fila = datetime.datetime.now()

# --- SISTEMA DE BOTÕES (VIEW) ---
class FilaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def atualizar_mensagem(self, interaction: discord.Interaction):
        delta = datetime.datetime.now() - ultimo_movimento_fila
        minutos = int(delta.total_seconds() / 60)
        
        embed = discord.Embed(title=f"Lobby Inhouse - {len(fila)} Jogadores", color=0x2ecc71)
        if not fila:
            embed.description = "A fila está vazia. Seja o primeiro!"
        else:
            lista_txt = ""
            for i, p in enumerate(fila):
                num = i + 1
                status = "**(Jogando)**" if i < 10 else "(Próxima)"
                lista_txt += f"{num}. {p.display_name} {status}\n"
            embed.description = lista_txt
        embed.set_footer(text=f"Última atividade: {minutos} min atrás")
        try: await interaction.message.edit(embed=embed, view=self)
        except: pass

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, custom_id="btn_entrar", emoji="⚔️")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        global ultimo_movimento_fila
        if not get_jogador(interaction.user.id):
            return await interaction.response.send_message("❌ Registre-se primeiro: `/registrar`", ephemeral=True)
        
        banido, tempo = checar_banimento(interaction.user.id)
        if banido:
            return await interaction.response.send_message(f"🚫 **Você está suspenso da fila.**\nTempo restante: {tempo}", ephemeral=True)

        if interaction.user in fila:
            return await interaction.response.send_message("Já na fila!", ephemeral=True)
            
        fila.append(interaction.user)
        ultimo_movimento_fila = datetime.datetime.now()
        await interaction.response.defer()
        await self.atualizar_mensagem(interaction)
        
        if len(fila) == 10:
            await interaction.channel.send("🔥 **Fila Cheia (10)!** Admin, use `/start`.")

    @discord.ui.button(label="Sair", style=discord.ButtonStyle.danger, custom_id="btn_sair", emoji="🏃")
    async def sair(self, interaction: discord.Interaction, button: discord.ui.Button):
        global ultimo_movimento_fila
        if interaction.user not in fila:
            return await interaction.response.send_message("Não está na fila.", ephemeral=True)
        fila.remove(interaction.user)
        ultimo_movimento_fila = datetime.datetime.now()
        await interaction.response.defer()
        await self.atualizar_mensagem(interaction)

    @discord.ui.button(label="Perfil", style=discord.ButtonStyle.secondary, custom_id="btn_perfil", emoji="📊")
    async def ver_meu_perfil(self, interaction: discord.Interaction, button: discord.ui.Button):
        d = get_jogador(interaction.user.id)
        if not d: return await interaction.response.send_message("Não registrado.", ephemeral=True)
        elo = calcular_elo(d['pdl'])
        wr = calcular_winrate(d['vitorias'], d['derrotas'])
        icone = get_icone_elo(d['pdl'])
        await interaction.response.send_message(f"📊 **{d['nick']}**: {icone} {elo} ({d['pdl']} PDL) - WR: {wr}", ephemeral=True)

# --- FUNÇÕES AUXILIARES ---

async def enviar_log(guild, texto):
    canal = discord.utils.get(guild.text_channels, name=CANAL_LOGS_NOME)
    if canal:
        embed = discord.Embed(description=texto, color=0xff0000, timestamp=datetime.datetime.now())
        embed.set_footer(text="Log Inhouse")
        await canal.send(embed=embed)

async def gerenciar_cargos_elo(member: discord.Member, pdl: int):
    guild = member.guild
    elos_nomes = ["Ferro", "Bronze", "Prata", "Ouro", "Platina", "Esmeralda", "Diamante+"]
    elo_atual = calcular_elo(pdl)
    
    cargos_remover = [r for r in member.roles if r.name in elos_nomes and r.name != elo_atual]
    if cargos_remover:
        try: await member.remove_roles(*cargos_remover)
        except: pass

    role_nova = discord.utils.get(guild.roles, name=elo_atual)
    if role_nova and role_nova not in member.roles:
        try: await member.add_roles(role_nova)
        except: pass

async def criar_canais_voz(guild, azul_members, verm_members):
    categoria = discord.utils.get(guild.categories, name=CATEGORIA_INHOUSE_NOME)
    if not categoria:
        categoria = await guild.create_category(CATEGORIA_INHOUSE_NOME)

    overwrites_azul = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True)
    }
    for m in azul_members: overwrites_azul[m] = discord.PermissionOverwrite(view_channel=True, connect=True)

    overwrites_verm = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True)
    }
    for m in verm_members: overwrites_verm[m] = discord.PermissionOverwrite(view_channel=True, connect=True)

    c_azul = await guild.create_voice_channel(f"🟦 Time Azul", category=categoria, overwrites=overwrites_azul)
    c_verm = await guild.create_voice_channel(f"🟥 Time Vermelho", category=categoria, overwrites=overwrites_verm)

    for m in azul_members:
        if m.voice: 
            try: await m.move_to(c_azul)
            except: pass
    for m in verm_members:
        if m.voice: 
            try: await m.move_to(c_verm)
            except: pass
            
    return c_azul, c_verm

async def deletar_canais_voz(canais):
    for c in canais:
        if c:
            try: await c.delete()
            except: pass

@tasks.loop(minutes=5)
async def checar_afk():
    global fila, ultimo_movimento_fila
    if not fila or partida_atual: return
    if datetime.datetime.now() - ultimo_movimento_fila > datetime.timedelta(minutes=60):
        qtd = len(fila)
        fila.clear()
        print(f"🧹 Fila limpa por inatividade ({qtd} players).")

# --- GRUPO DE ADMIN ---
class AdminGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="admin", description="Comandos de Admin")

    @app_commands.command(name="painel", description="Envia o painel de botões.")
    @app_commands.default_permissions(administrator=True)
    async def painel(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Lobby Inhouse", description="Clique abaixo para entrar na fila.", color=0x2ecc71)
        await interaction.response.send_message("Painel criado!", ephemeral=True)
        await interaction.channel.send(embed=embed, view=FilaView())

    @app_commands.command(name="registrar_player", description="Registra outro jogador manualmente.")
    @app_commands.default_permissions(administrator=True)
    async def registrar_player(self, interaction: discord.Interaction, membro: discord.Member, nick: str, opgg: str = "Admin"):
        if get_jogador(membro.id):
            return await interaction.response.send_message("❌ Jogador já registrado.", ephemeral=True)
        
        criar_jogador(membro.id, nick, opgg)
        await gerenciar_cargos_elo(membro, 1000)
        
        try:
            role = discord.utils.get(interaction.guild.roles, name="Registrado")
            if role: await membro.add_roles(role)
        except: pass

        await interaction.response.send_message(f"✅ **{membro.display_name}** registrado com sucesso!")
        await enviar_log(interaction.guild, f"✏️ **FORCE REGISTER:** Admin {interaction.user.mention} registrou {membro.mention}.")

    @app_commands.command(name="sub", description="Substitui um jogador e aplica punição opcional.")
    @app_commands.describe(punir="Se True, tira 20 PDL e bane da fila por 30min.")
    @app_commands.default_permissions(administrator=True)
    async def sub(self, interaction: discord.Interaction, saiu: discord.Member, entrou: discord.Member, punir: bool = True):
        global partida_atual
        if not partida_atual: return await interaction.response.send_message("❌ Sem partida rolando.", ephemeral=True)
        
        if not get_jogador(entrou.id):
             return await interaction.response.send_message(f"❌ {entrou.mention} não está registrado.", ephemeral=True)

        time_encontrado = None
        if saiu in partida_atual['azul']:
            partida_atual['azul'].remove(saiu)
            partida_atual['azul'].append(entrou)
            time_encontrado = "azul"
        elif saiu in partida_atual['vermelho']:
            partida_atual['vermelho'].remove(saiu)
            partida_atual['vermelho'].append(entrou)
            time_encontrado = "vermelho"
        
        if not time_encontrado:
             return await interaction.response.send_message(f"❌ {saiu.mention} não está jogando.", ephemeral=True)

        texto_punicao = ""
        if punir:
            aplicar_punicao(saiu.id, 20, 60)
            await gerenciar_cargos_elo(saiu, get_jogador(saiu.id)['pdl'])
            texto_punicao = f"\n🚫 **PUNIÇÃO:** {saiu.mention} perdeu **20 PDL** e está suspenso por **60 min**."

        canais = partida_atual.get('canais_voz')
        if canais:
            c_alvo = canais[0] if time_encontrado == "azul" else canais[1]
            try:
                await c_alvo.set_permissions(saiu, view_channel=False)
                await c_alvo.set_permissions(entrou, view_channel=True, connect=True)
                if entrou.voice: await entrou.move_to(c_alvo)
                if saiu.voice: await saiu.move_to(None)
            except Exception as e:
                print(f"Erro ao mover sub: {e}")

        embed = discord.Embed(title="🔄 SUBSTITUIÇÃO - REMAKE NECESSÁRIO", color=0xe74c3c)
        embed.description = f"**Saiu:** {saiu.mention}\n**Entrou:** {entrou.mention}{texto_punicao}\n\n⚠️ **Atenção:** A sala no LoL deve ser refeita com o novo jogador!"
        
        await interaction.response.send_message(embed=embed)
        await enviar_log(interaction.guild, f"🔄 **SUB:** {saiu.mention} trocado por {entrou.mention}. Punição: {punir}.")

    @app_commands.command(name="kick", description="Remove jogador da fila.")
    @app_commands.default_permissions(administrator=True)
    async def kick(self, interaction: discord.Interaction, membro: discord.Member):
        global ultimo_movimento_fila
        if membro in fila:
            fila.remove(membro)
            ultimo_movimento_fila = datetime.datetime.now()
            await interaction.response.send_message(f"👢 **{membro.display_name}** removido.")
            await enviar_log(interaction.guild, f"👢 **KICK:** {interaction.user.mention} removeu {membro.mention}.")
        else:
            await interaction.response.send_message("❌ Não está na fila.", ephemeral=True)

    @app_commands.command(name="reset", description="Limpa fila.")
    @app_commands.default_permissions(administrator=True)
    async def reset(self, interaction: discord.Interaction):
        global ultimo_movimento_fila
        fila.clear()
        ultimo_movimento_fila = datetime.datetime.now()
        await interaction.response.send_message("🧹 Fila limpa.")
        await enviar_log(interaction.guild, f"🧹 **RESET:** {interaction.user.mention} limpou a fila.")

    @app_commands.command(name="setpdl", description="Define PDL manual.")
    @app_commands.default_permissions(administrator=True)
    async def setpdl(self, interaction: discord.Interaction, membro: discord.Member, quantidade: int):
        set_pdl_manual(membro.id, quantidade)
        await gerenciar_cargos_elo(membro, quantidade)
        await interaction.response.send_message(f"👮 PDL de **{membro.display_name}** definido para **{quantidade}**.")
        await enviar_log(interaction.guild, f"👮 **SETPDL:** {interaction.user.mention} definiu PDL de {membro.mention} para {quantidade}.")

    @app_commands.command(name="cancelar", description="Cancela partida atual.")
    @app_commands.default_permissions(administrator=True)
    async def cancelar(self, interaction: discord.Interaction):
        global partida_atual
        if not partida_atual: return await interaction.response.send_message("❌ Sem partida.", ephemeral=True)
        
        if 'canais_voz' in partida_atual:
            await deletar_canais_voz(partida_atual['canais_voz'])

        partida_atual = None
        await interaction.response.send_message("🚫 Partida cancelada e canais deletados.")
        await enviar_log(interaction.guild, f"🚫 **CANCEL:** {interaction.user.mention} cancelou a partida.")

    @app_commands.command(name="shuffle", description="Re-balancea os times.")
    @app_commands.default_permissions(administrator=True)
    async def shuffle(self, interaction: discord.Interaction):
        global partida_atual
        if not partida_atual: return await interaction.response.send_message("❌ Sem partida.", ephemeral=True)
        
        modo = partida_atual.get('modo', 'sr')
        todos = partida_atual['azul'] + partida_atual['vermelho']
        ids = [p.id for p in todos]
        dados = get_dados_varios(ids)
        mapa = {d['_id']: d for d in dados}
        campo = "pdl" if modo == "sr" else f"pdl_{modo}"

        ordenados = sorted(todos, key=lambda p: mapa.get(str(p.id), {}).get(campo, 1000), reverse=True)
        azul, verm = [], []
        for i, p in enumerate(ordenados):
            if i % 4 == 0 or i % 4 == 3: azul.append(p)
            else: verm.append(p)
        
        partida_atual['azul'] = azul
        partida_atual['vermelho'] = verm
        
        icone = get_icone_modo(modo)
        embed = discord.Embed(title=f"{icone} Times Misturados ({modo.upper()})", color=0xe67e22)
        def fmt(p):
            d = mapa.get(str(p.id))
            r = d.get('rota', '❔') if modo == "sr" else "🎲"
            return f"{r} **{d['nick']}** ({d.get(campo, 1000)})"
        embed.add_field(name="🟦 AZUL", value="\n".join([fmt(p) for p in azul]), inline=False)
        embed.add_field(name="🟥 VERMELHO", value="\n".join([fmt(p) for p in verm]), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="vitoria", description="Finaliza a partida.")
    @app_commands.choices(time=[app_commands.Choice(name="Time Azul", value="azul"), app_commands.Choice(name="Time Vermelho", value="vermelho")])
    @app_commands.default_permissions(administrator=True)
    async def vitoria(self, interaction: discord.Interaction, time: app_commands.Choice[str]):
        global partida_atual
        if not partida_atual: return await interaction.response.send_message("❌ Sem partida.", ephemeral=True)

        await interaction.response.defer()
        
        modo = partida_atual.get('modo', 'sr')
        valendo = partida_atual.get('valendo_pdl', True)
        venc = time.value
        ganhadores = partida_atual[venc]
        perdedores = partida_atual['vermelho'] if venc == 'azul' else partida_atual['azul']
        
        nomes_azul = [get_jogador(p.id)['nick'] for p in partida_atual['azul']]
        nomes_verm = [get_jogador(p.id)['nick'] for p in partida_atual['vermelho']]
        salvar_historico(venc, nomes_azul, nomes_verm, modo)

        msg = f"🏆 **VITÓRIA {venc.upper()}**\n\n"
        
        if valendo:
            for p in ganhadores:
                bonus = atualizar_pdl(p.id, 20, True, modo=modo) 
                d = get_jogador(p.id)
                novo = d.get("pdl", 1000) if modo == "sr" else d.get(f"pdl_{modo}", 1000)
                if modo == "sr": await gerenciar_cargos_elo(p, novo)
                msg += f"📈 {d['nick']}: +{20+bonus} ({novo}) {'🔥' if bonus else ''}\n"
            msg += "\n"
            for p in perdedores:
                atualizar_pdl(p.id, -20, False, modo=modo)
                d = get_jogador(p.id)
                novo = d.get("pdl", 1000) if modo == "sr" else d.get(f"pdl_{modo}", 1000)
                if modo == "sr": await gerenciar_cargos_elo(p, novo)
                msg += f"📉 {d['nick']}: -20 ({novo})\n"
        else:
            msg += "**Partida Amistosa finalizada!**"

        if 'canais_voz' in partida_atual:
            await deletar_canais_voz(partida_atual['canais_voz'])

        partida_atual = None
        await interaction.followup.send(msg)
        await enviar_log(interaction.guild, f"🏆 **FIM:** Admin {interaction.user.mention} declarou vitória do {venc}.")

# --- EVENTOS E COMANDOS PÚBLICOS ---

@bot.event
async def on_ready():
    print(f'✅ Bot Online: {bot.user}')
    try:
        bot.tree.add_command(AdminGroup())
        bot.add_view(FilaView()) 
        await bot.tree.sync()
        if not checar_afk.is_running(): checar_afk.start() 
    except Exception as e: print(f"Erro: {e}")

@bot.hybrid_command(name="registrar", description="Cria sua conta.")
async def registrar(ctx, nick: str, opgg: str = "Não informado"):
    if get_jogador(ctx.author.id): return await ctx.send("Já registrado!", ephemeral=True)
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
        await ctx.send(msg + " Cargos aplicados!")
    except Exception as e: await ctx.send(f"Erro: {e}", ephemeral=True)

@bot.hybrid_command(name="rota", description="Define posição.")
@app_commands.choices(lane=[app_commands.Choice(name=n, value=v) for n, v in [("Top","top"),("Jungle","jungle"),("Mid","mid"),("ADC","adc"),("Support","sup"),("Fill","fill")]])
async def rota(ctx, lane: app_commands.Choice[str]):
    mapa = {"top":"🛡️ Top", "jungle":"🌲 Jungle", "mid":"🧙‍♂️ Mid", "adc":"🏹 ADC", "sup":"❤️ Sup", "fill":"🔄 Fill"}
    atualizar_rota(ctx.author.id, mapa[lane.value])
    await ctx.send(f"✅ Rota: **{mapa[lane.value]}**", ephemeral=True)

# --- START ATUALIZADO ---
@bot.hybrid_command(name="start", description="Inicia partida com configurações.")
@app_commands.choices(
    modo=[
        app_commands.Choice(name="Summoner's Rift", value="sr"),
        app_commands.Choice(name="ARAM", value="aram"),
        app_commands.Choice(name="Arena", value="arena")
    ],
    tipo=[
        app_commands.Choice(name="Escolha às Cegas (Blind)", value="Escolha às Cegas"),
        app_commands.Choice(name="Modo Alternado (Draft)", value="Modo Alternado"),
        app_commands.Choice(name="Todos Aleatórios (All Random)", value="Todos Aleatórios"),
        app_commands.Choice(name="Alternada Torneio (Tournament)", value="Alternada Torneio")
    ]
)
@app_commands.describe(
    nome_sala="Nome da sala no LoL",
    tipo="Tipo de seleção (Draft, Blind...)",
    senha="Senha da sala (Opcional)",
    regras="Regras adicionais (Opcional)",
    valendo_pdl="Conta pontos? (Padrão: True)",
    ignorar_tamanho="Forçar início com <10?"
)
async def start(
    ctx, 
    modo: app_commands.Choice[str], 
    tipo: app_commands.Choice[str],
    nome_sala: str,
    senha: str = "Sem senha",
    regras: str = "Nenhuma",
    valendo_pdl: bool = True, 
    ignorar_tamanho: bool = False
):
    global fila
    modo_val = modo.value if modo else "sr"
    tipo_val = tipo.value if tipo else "Modo Alternado"
    
    qtd = len(fila)
    if qtd < 2: return await ctx.send("❌ Mínimo 2 players.")
    if not ignorar_tamanho and qtd < 10: return await ctx.send("⚠️ Faltam players. Use `ignorar_tamanho: True`.")
    if qtd % 2 != 0: return await ctx.send("⚠️ Ímpar.")
    
    corte = 10 if qtd >= 10 else qtd
    jogadores_da_partida = fila[:corte] 
    fila = fila[corte:] 
    
    # Passando os novos argumentos para a função
    await iniciar_partida(ctx, modo_val, valendo_pdl, jogadores_da_partida, tipo_val, nome_sala, senha, regras)

async def iniciar_partida(ctx, modo, valendo, players, tipo, nome_sala, senha, regras):
    global partida_atual
    responder = ctx.response.send_message if isinstance(ctx, discord.Interaction) else ctx.send
    
    txt = "🏆 Ranked" if valendo else "🚫 Unranked"
    await responder(f"⚖️ **Iniciando {modo.upper()} ({len(players)} players) - {txt}**\n*Criando canais de voz...*")

    ids = [p.id for p in players]
    dados = get_dados_varios(ids)
    mapa = {d['_id']: d for d in dados}
    campo = "pdl" if modo == "sr" else f"pdl_{modo}"

    ordenados = sorted(players, key=lambda p: mapa.get(str(p.id), {}).get(campo, 1000), reverse=True)
    azul, verm = [], []
    for i, p in enumerate(ordenados):
        if i % 4 == 0 or i % 4 == 3: azul.append(p)
        else: verm.append(p)

    try:
        canais = await criar_canais_voz(ctx.guild, azul, verm)
    except Exception as e:
        print(f"Erro ao criar voz: {e}")
        canais = None
        await ctx.channel.send("⚠️ Não consegui criar os canais de voz (Verifique permissões).")

    partida_atual = {
        'azul': azul, 
        'vermelho': verm, 
        'modo': modo, 
        'valendo_pdl': valendo,
        'canais_voz': canais,
        'info_sala': {'nome': nome_sala, 'senha': senha, 'tipo': tipo} # Guardando info
    }
    
    icone = get_icone_modo(modo)
    titulo = f"{icone} Partida Iniciada - {modo.upper()}"
    
    embed = discord.Embed(title=titulo, color=0x0099ff)
    if not valendo: embed.set_author(name="🚫 Treino / Amistoso")
    
    # --- CAMPO DE INFORMAÇÕES DA SALA ---
    info_texto = (
        f"**Nome da Sala:** `{nome_sala}`\n"
        f"**Senha:** `{senha}`\n"
        f"**Tipo de Jogo:** {tipo}\n"
        f"**Tamanho:** {len(azul)} vs {len(verm)}\n"
        f"**Regras:** {regras}"
    )
    embed.add_field(name="🏠 Configuração da Sala", value=info_texto, inline=False)
    # ------------------------------------

    def fmt(p):
        d = mapa.get(str(p.id))
        r = d.get('rota', '❔') if modo == "sr" else "🎲"
        return f"{r} **{d['nick']}** ({d.get(campo, 1000)})"

    embed.add_field(name="🟦 TIME AZUL", value="\n".join([fmt(p) for p in azul]), inline=False)
    embed.add_field(name="🟥 TIME VERMELHO", value="\n".join([fmt(p) for p in verm]), inline=False)
    
    if canais:
        embed.add_field(name="🔊 Voz", value=f"{canais[0].mention} | {canais[1].mention}", inline=False)

    if isinstance(ctx, discord.Interaction): await ctx.followup.send(embed=embed)
    else: await ctx.send(embed=embed)
    
    channel = ctx.channel if hasattr(ctx, 'channel') else ctx.user
    for p in players:
        try: await p.send(f"🎮 **Partida Iniciada!**\nSala: `{nome_sala}`\nSenha: `{senha}`")
        except: pass

@bot.hybrid_command(name="perfil", description="Ver stats.")
async def perfil(ctx, membro: discord.Member = None):
    alvo = membro or ctx.author
    d = get_jogador(alvo.id)
    if not d: return await ctx.send("Não registrado.", ephemeral=True)
    embed = discord.Embed(title=f"📊 Perfil de {d['nick']}", color=0x9b59b6)
    sr, aram, arena = d.get('pdl', 1000), d.get('pdl_aram', 1000), d.get('pdl_arena', 1000)
    embed.add_field(name=f"{get_icone_modo('sr')} Rift", value=f"{get_icone_elo(sr)} **{calcular_elo(sr)}**\n{sr} PDL", inline=True)
    embed.add_field(name=f"{get_icone_modo('aram')} ARAM", value=f"{get_icone_elo(aram)} **{calcular_elo(aram)}**\n{aram} PDL", inline=True)
    embed.add_field(name=f"{get_icone_modo('arena')} Arena", value=f"{get_icone_elo(arena)} **{calcular_elo(arena)}**\n{arena} PDL", inline=True)
    wr = calcular_winrate(d['vitorias'], d['derrotas'])
    streak = d.get('streak', 0)
    fogo = "🔥" * streak if streak > 0 else ""
    embed.set_footer(text=f"WR: {wr} | MVPs: {d.get('mvps', 0)} | Streak: {streak} {fogo}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="ranking", description="Top Jogadores.")
@app_commands.choices(modo=[app_commands.Choice(name="Summoner's Rift", value="sr"), app_commands.Choice(name="ARAM", value="aram"), app_commands.Choice(name="Arena", value="arena")])
async def ranking(ctx, modo: app_commands.Choice[str] = None):
    sel_modo = modo.value if modo else "sr"
    top = get_ranking(sel_modo)
    icone = get_icone_modo(sel_modo)
    embed = discord.Embed(title=f"{icone} Top 10 - {sel_modo.upper()}", color=0xffd700)
    txt = ""
    for i, p in enumerate(top):
        val = p.get('pdl', 1000) if sel_modo == "sr" else p.get(f'pdl_{sel_modo}', 1000)
        medalha = ["🥇","🥈","🥉"][i] if i < 3 else f"{i+1}º"
        txt += f"{medalha} **{p['nick']}** — {val} PDL\n"
    embed.description = txt if txt else "Vazio."
    await ctx.send(embed=embed)

@bot.hybrid_command(name="help", description="Ajuda.")
async def help(ctx):
    embed = discord.Embed(title="📘 Manual Inhouse", color=0x3498db)
    embed.add_field(name="Jogadores", value="`/registrar`\nUse o **Painel** para entrar na fila!\n`/rota`, `/perfil`, `/ranking`")
    embed.add_field(name="Admin", value="`/admin painel`\n`/start` (Configura a sala)\n`/admin sub` (Troca e Punição)\n`/admin vitoria`, `/admin cancelar`")
    await ctx.send(embed=embed)

@bot.command()
async def diario(ctx):
    sucesso, msg = resgatar_diario(ctx.author.id)
    await ctx.send(f"💰 {ctx.author.mention}, {msg}")

@bot.command()
async def mvp(ctx, membro: discord.Member):
    if ctx.author.id == membro.id: return await ctx.send("❌ Auto-voto proibido!")
    adicionar_mvp(membro.id)
    await ctx.send(f"🌟 MVP para **{membro.display_name}**!")

@bot.command()
async def historico(ctx):
    partidas = get_ultimas_partidas()
    if not partidas: return await ctx.send("Sem histórico.")
    embed = discord.Embed(title="📜 Últimas Partidas", color=0xbdc3c7)
    for p in partidas:
        v = p['vencedor']
        m = p.get('modo', 'sr')
        icone = get_icone_modo(m)
        embed.add_field(name=f"{icone} {v.upper()}", value=f"**Azul:** {', '.join(p['azul'])}\n**Verm:** {', '.join(p['vermelho'])}", inline=False)
    await ctx.send(embed=embed)

keep_alive()
bot.run(TOKEN)
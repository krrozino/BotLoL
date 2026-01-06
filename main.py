import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import datetime
from server import keep_alive

# Importando database (CORRIGIDO: Incluindo get_todos_jogadores_paginado)
from database import (
    get_jogador, criar_jogador, atualizar_pdl, atualizar_rota, 
    editar_perfil, set_pdl_manual, get_dados_varios, 
    adicionar_mvp, resgatar_diario, salvar_historico,
    aplicar_punicao, checar_banimento,
    get_ranking_paginado, contar_jogadores, get_historico_pessoal, get_todos_jogadores_paginado
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

# --- VIEWS (BOTÕES INTERATIVOS) ---

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
            try: await interaction.channel.send("🔥 **Fila Cheia (10)!** Admin, use `/start`.")
            except: pass

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

class RankingView(discord.ui.View):
    def __init__(self, modo):
        super().__init__(timeout=60)
        self.pagina = 0
        self.modo = modo
        self.total_jogadores = contar_jogadores()

    async def atualizar_embed(self, interaction):
        top = get_ranking_paginado(self.modo, skip=self.pagina*10, limit=10)
        icone = get_icone_modo(self.modo)
        embed = discord.Embed(title=f"{icone} Ranking - {self.modo.upper()}", color=0xffd700)
        
        txt = ""
        for i, p in enumerate(top):
            val = p.get('pdl', 1000) if self.modo == "sr" else p.get(f'pdl_{self.modo}', 1000)
            posicao = (self.pagina * 10) + i + 1
            medalha = "👑" if posicao == 1 else f"{posicao}º"
            txt += f"**{medalha} {p['nick']}** — {val} PDL\n"
        
        embed.description = txt if txt else "Ninguém nessa página."
        embed.set_footer(text=f"Página {self.pagina + 1} • Total: {self.total_jogadores}")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.primary, disabled=True)
    async def anterior(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.pagina > 0:
            self.pagina -= 1
            self.proximo.disabled = False
            if self.pagina == 0: button.disabled = True
            await self.atualizar_embed(interaction)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.primary)
    async def proximo(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.pagina + 1) * 10 < self.total_jogadores:
            self.pagina += 1
            self.anterior.disabled = False
            if (self.pagina + 1) * 10 >= self.total_jogadores:
                button.disabled = True
            await self.atualizar_embed(interaction)

class ListaJogadoresView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.pagina = 0
        self.total_jogadores = contar_jogadores()

    async def atualizar_embed(self, interaction):
        lista = get_todos_jogadores_paginado(skip=self.pagina*10, limit=10)
        embed = discord.Embed(title=f"📋 Lista de Jogadores Registrados", color=0x95a5a6)
        txt = ""
        for p in lista:
            txt += f"• **{p['nick']}** (ID: {p['_id']}) | PDL: {p.get('pdl', 1000)}\n"
        embed.description = txt if txt else "Vazio."
        embed.set_footer(text=f"Página {self.pagina + 1} • Total: {self.total_jogadores}")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.primary, disabled=True)
    async def anterior(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.pagina > 0:
            self.pagina -= 1
            self.proximo.disabled = False
            if self.pagina == 0: button.disabled = True
            await self.atualizar_embed(interaction)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.primary)
    async def proximo(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.pagina + 1) * 10 < self.total_jogadores:
            self.pagina += 1
            self.anterior.disabled = False
            if (self.pagina + 1) * 10 >= self.total_jogadores:
                button.disabled = True
            await self.atualizar_embed(interaction)

# --- FUNÇÕES AUXILIARES ---

async def enviar_log(guild, texto):
    canal = discord.utils.get(guild.text_channels, name=CANAL_LOGS_NOME)
    if canal:
        embed = discord.Embed(description=texto, color=0xff0000, timestamp=datetime.datetime.now())
        embed.set_footer(text="Log Inhouse")
        await canal.send(embed=embed)

async def gerenciar_cargos_elo(member: discord.Member, pdl: int, modo: str = "sr"):
    """
    Atualiza cargos de elo. 
    Se modo="sr", busca "Ouro". 
    Se modo="aram", busca "Ouro ARAM".
    """
    guild = member.guild
    elos_base = ["Ferro", "Bronze", "Prata", "Ouro", "Platina", "Esmeralda", "Diamante+"]
    elo_atual_base = calcular_elo(pdl)
    
    # Define o sufixo baseado no modo
    suffix = ""
    if modo == "aram": suffix = " ARAM"
    if modo == "arena": suffix = " Arena"
    
    elo_atual_nome = f"{elo_atual_base}{suffix}"
    
    # Lista de todos os cargos possíveis para este modo (para remover os antigos)
    cargos_modo = [f"{e}{suffix}" for e in elos_base]
    
    cargos_remover = [r for r in member.roles if r.name in cargos_modo and r.name != elo_atual_nome]
    if cargos_remover:
        try: await member.remove_roles(*cargos_remover)
        except: pass

    role_nova = discord.utils.get(guild.roles, name=elo_atual_nome)
    if role_nova and role_nova not in member.roles:
        try: await member.add_roles(role_nova)
        except: pass

async def criar_canais_voz(guild, azul_members, verm_members):
    categoria = discord.utils.get(guild.categories, name=CATEGORIA_INHOUSE_NOME)
    if not categoria:
        categoria = await guild.create_category(CATEGORIA_INHOUSE_NOME)

    overwrites_azul = {guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True)}
    for m in azul_members: overwrites_azul[m] = discord.PermissionOverwrite(view_channel=True, connect=True)

    overwrites_verm = {guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True)}
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
        fila.clear()
        print("🧹 Fila limpa por inatividade.")

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

    # --- LISTA COMPLETA DE JOGADORES (PAGINADA) ---
    @app_commands.command(name="jogadores", description="Lista todos os jogadores registrados.")
    @app_commands.default_permissions(administrator=True)
    async def jogadores(self, interaction: discord.Interaction):
        view = ListaJogadoresView()
        lista = get_todos_jogadores_paginado(skip=0, limit=10)
        embed = discord.Embed(title="📋 Lista de Jogadores Registrados", color=0x95a5a6)
        txt = ""
        for p in lista:
            txt += f"• **{p['nick']}** (ID: {p['_id']}) | PDL: {p.get('pdl', 1000)}\n"
        embed.description = txt if txt else "Nenhum jogador encontrado."
        embed.set_footer(text=f"Página 1 • Total: {view.total_jogadores}")
        await interaction.response.send_message(embed=embed, view=view)

    # --- INFO DETALHADA DO JOGADOR ---
    @app_commands.command(name="info_jogador", description="Ver detalhes completos de um jogador.")
    @app_commands.default_permissions(administrator=True)
    async def info_jogador(self, interaction: discord.Interaction, membro: discord.Member):
        d = get_jogador(membro.id)
        if not d: return await interaction.response.send_message("❌ Jogador não registrado.", ephemeral=True)
        
        embed = discord.Embed(title=f"📁 Ficha Técnica: {d['nick']}", color=0x3498db)
        embed.add_field(name="🆔 Discord ID", value=d['_id'], inline=True)
        embed.add_field(name="🔗 OP.GG", value=d['opgg'], inline=True)
        
        embed.add_field(name="🗺️ SR PDL", value=f"{d.get('pdl', 1000)}", inline=True)
        embed.add_field(name="❄️ ARAM PDL", value=f"{d.get('pdl_aram', 1000)}", inline=True)
        embed.add_field(name="⚔️ Arena PDL", value=f"{d.get('pdl_arena', 1000)}", inline=True)
        
        embed.add_field(name="📈 Stats", value=f"{d['vitorias']}V / {d['derrotas']}D (MVPs: {d.get('mvps', 0)})", inline=False)
        embed.add_field(name="🔥 Streak", value=d.get('streak', 0), inline=True)
        embed.add_field(name="🚫 Banido Até", value=d.get('banido_ate', 'Livre'), inline=True)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="registrar_player", description="Registra outro jogador manualmente.")
    @app_commands.default_permissions(administrator=True)
    async def registrar_player(self, interaction: discord.Interaction, membro: discord.Member, nick: str, opgg: str = "Admin"):
        if get_jogador(membro.id):
            return await interaction.response.send_message("❌ Jogador já registrado.", ephemeral=True)
        
        criar_jogador(membro.id, nick, opgg)
        await gerenciar_cargos_elo(membro, 1000, "sr")
        
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
        if not get_jogador(entrou.id): return await interaction.response.send_message("❌ Sub não registrado.", ephemeral=True)

        time_encontrado = None
        if saiu in partida_atual['azul']:
            partida_atual['azul'].remove(saiu)
            partida_atual['azul'].append(entrou)
            time_encontrado = "azul"
        elif saiu in partida_atual['vermelho']:
            partida_atual['vermelho'].remove(saiu)
            partida_atual['vermelho'].append(entrou)
            time_encontrado = "vermelho"
        
        if not time_encontrado: return await interaction.response.send_message("❌ Jogador não está na partida.", ephemeral=True)

        txt_punicao = ""
        if punir:
            aplicar_punicao(saiu.id, 20, 60)
            await gerenciar_cargos_elo(saiu, get_jogador(saiu.id)['pdl'], "sr")
            txt_punicao = f"\n🚫 **PUNIÇÃO:** -20 PDL e 60min Ban."

        canais = partida_atual.get('canais_voz')
        if canais:
            c_alvo = canais[0] if time_encontrado == "azul" else canais[1]
            try:
                await c_alvo.set_permissions(saiu, view_channel=False)
                await c_alvo.set_permissions(entrou, view_channel=True, connect=True)
                if entrou.voice: await entrou.move_to(c_alvo)
                if saiu.voice: await saiu.move_to(None)
            except: pass

        embed = discord.Embed(title="🔄 SUBSTITUIÇÃO - REMAKE", color=0xe74c3c)
        embed.description = f"**Saiu:** {saiu.mention}\n**Entrou:** {entrou.mention}{txt_punicao}\n\n⚠️ **Refaçam a sala no LoL!**"
        await interaction.response.send_message(embed=embed)
        await enviar_log(interaction.guild, f"🔄 **SUB:** {saiu} -> {entrou}. Punido: {punir}")

    @app_commands.command(name="kick", description="Kicka da fila.")
    @app_commands.default_permissions(administrator=True)
    async def kick(self, interaction: discord.Interaction, membro: discord.Member):
        global ultimo_movimento_fila
        if membro in fila:
            fila.remove(membro)
            ultimo_movimento_fila = datetime.datetime.now()
            await interaction.response.send_message(f"👢 {membro.mention} removido.")
            await enviar_log(interaction.guild, f"👢 **KICK:** {membro.mention} removido.")
        else: await interaction.response.send_message("Não está na fila.", ephemeral=True)

    @app_commands.command(name="reset", description="Limpa fila.")
    @app_commands.default_permissions(administrator=True)
    async def reset(self, interaction: discord.Interaction):
        global ultimo_movimento_fila
        fila.clear()
        ultimo_movimento_fila = datetime.datetime.now()
        await interaction.response.send_message("🧹 Fila limpa.")
        await enviar_log(interaction.guild, f"🧹 **RESET:** Fila limpa por {interaction.user.mention}")

    @app_commands.command(name="setpdl", description="Edita PDL.")
    @app_commands.choices(modo=[app_commands.Choice(name="SR", value="sr"), app_commands.Choice(name="ARAM", value="aram"), app_commands.Choice(name="Arena", value="arena")])
    @app_commands.default_permissions(administrator=True)
    async def setpdl(self, interaction: discord.Interaction, membro: discord.Member, quantidade: int, modo: app_commands.Choice[str] = None):
        modo_val = modo.value if modo else "sr"
        set_pdl_manual(membro.id, quantidade, modo_val)
        # Atualiza o cargo correspondente ao modo
        await gerenciar_cargos_elo(membro, quantidade, modo_val)
        await interaction.response.send_message(f"👮 PDL ({modo_val.upper()}) de {membro.mention} = {quantidade}.")
        await enviar_log(interaction.guild, f"👮 **SETPDL:** {membro.mention} -> {quantidade} ({modo_val})")

    @app_commands.command(name="cancelar", description="Cancela partida.")
    @app_commands.default_permissions(administrator=True)
    async def cancelar(self, interaction: discord.Interaction):
        global partida_atual
        if not partida_atual: return await interaction.response.send_message("❌ Sem partida.", ephemeral=True)
        if 'canais_voz' in partida_atual: await deletar_canais_voz(partida_atual['canais_voz'])
        partida_atual = None
        await interaction.response.send_message("🚫 Cancelada.")
        await enviar_log(interaction.guild, f"🚫 **CANCEL:** Partida cancelada.")

    @app_commands.command(name="vitoria", description="Finaliza partida.")
    @app_commands.choices(time=[app_commands.Choice(name="Azul", value="azul"), app_commands.Choice(name="Vermelho", value="vermelho")])
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
        
        salvar_historico(venc, [get_jogador(p.id)['nick'] for p in partida_atual['azul']], [get_jogador(p.id)['nick'] for p in partida_atual['vermelho']], modo)
        msg = f"🏆 **VITÓRIA {venc.upper()}**\n\n"
        
        if valendo:
            for p in ganhadores:
                bonus = atualizar_pdl(p.id, 20, True, modo) 
                d = get_jogador(p.id)
                novo = d.get("pdl", 1000) if modo == "sr" else d.get(f"pdl_{modo}", 1000)
                await gerenciar_cargos_elo(p, novo, modo) # Atualiza cargo do modo específico
                msg += f"📈 {d['nick']}: +{20+bonus} ({novo}) {'🔥' if bonus else ''}\n"
            msg += "\n"
            for p in perdedores:
                atualizar_pdl(p.id, -20, False, modo)
                d = get_jogador(p.id)
                novo = d.get("pdl", 1000) if modo == "sr" else d.get(f"pdl_{modo}", 1000)
                await gerenciar_cargos_elo(p, novo, modo)
                msg += f"📉 {d['nick']}: -20 ({novo})\n"
        
        if 'canais_voz' in partida_atual: await deletar_canais_voz(partida_atual['canais_voz'])
        partida_atual = None
        await interaction.followup.send(msg)
        await enviar_log(interaction.guild, f"🏆 **FIM:** Vitória {venc} declarada.")

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

# --- COMANDOS PÚBLICOS ---

@bot.event
async def on_ready():
    print(f'✅ Bot Online: {bot.user}')
    try:
        bot.tree.add_command(AdminGroup())
        bot.add_view(FilaView())
        await bot.tree.sync()
        if not checar_afk.is_running(): checar_afk.start()
    except Exception as e: print(f"Erro: {e}")

# --- NOVO: PING ---
@bot.hybrid_command(name="ping", description="Verifica a latência do bot.")
async def ping(ctx):
    latencia = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! **{latencia}ms**")

# --- NOVO: EDITAR ---
@bot.hybrid_command(name="editar", description="Edita seu Nick ou Link do OP.GG.")
@app_commands.describe(nick="Novo Nick", opgg="Novo Link OP.GG")
async def editar(ctx, nick: str = None, opgg: str = None):
    if not get_jogador(ctx.author.id):
        await ctx.send("❌ Você não está registrado.", ephemeral=True)
        return
    
    if not nick and not opgg:
        await ctx.send("⚠️ Preencha pelo menos um campo.", ephemeral=True)
        return
        
    msg = ""
    if nick:
        editar_perfil(ctx.author.id, "nick", nick)
        msg += f"✅ Nick atualizado para **{nick}**.\n"
    if opgg:
        editar_perfil(ctx.author.id, "opgg", opgg)
        msg += f"✅ OP.GG atualizado.\n"
        
    await ctx.send(msg, ephemeral=True)

@bot.hybrid_command(name="registrar", description="Cria conta.")
async def registrar(ctx, nick: str, opgg: str = "Não informado"):
    if get_jogador(ctx.author.id): return await ctx.send("Já registrado!", ephemeral=True)
    try:
        criar_jogador(ctx.author.id, nick, opgg)
        cargo = discord.utils.get(ctx.guild.roles, name="Registrado")
        if cargo: await ctx.author.add_roles(cargo)
        await gerenciar_cargos_elo(ctx.author, 1000, "sr")
        await ctx.send(f"✅ Conta criada para **{nick}**!")
    except Exception as e: await ctx.send(f"Erro: {e}", ephemeral=True)

@bot.hybrid_command(name="rota", description="Define posição.")
@app_commands.choices(lane=[app_commands.Choice(name=n, value=v) for n, v in [("Top","top"),("Jungle","jungle"),("Mid","mid"),("ADC","adc"),("Support","sup"),("Fill","fill")]])
async def rota(ctx, lane: app_commands.Choice[str]):
    atualizar_rota(ctx.author.id, {"top":"🛡️ Top", "jungle":"🌲 Jungle", "mid":"🧙‍♂️ Mid", "adc":"🏹 ADC", "sup":"❤️ Sup", "fill":"🔄 Fill"}[lane.value])
    await ctx.send("✅ Rota atualizada!", ephemeral=True)

@bot.hybrid_command(name="ranking", description="Top Jogadores.")
@app_commands.choices(modo=[app_commands.Choice(name="Summoner's Rift", value="sr"), app_commands.Choice(name="ARAM", value="aram"), app_commands.Choice(name="Arena", value="arena")])
async def ranking(ctx, modo: app_commands.Choice[str] = None):
    sel_modo = modo.value if modo else "sr"
    view = RankingView(sel_modo)
    top = get_ranking_paginado(sel_modo, 0, 10)
    icone = get_icone_modo(sel_modo)
    embed = discord.Embed(title=f"{icone} Ranking - {sel_modo.upper()}", color=0xffd700)
    txt = ""
    for i, p in enumerate(top):
        val = p.get('pdl', 1000) if sel_modo == "sr" else p.get(f'pdl_{sel_modo}', 1000)
        medalha = ["🥇","🥈","🥉"][i] if i < 3 else f"{i+1}º"
        txt += f"**{medalha} {p['nick']}** — {val} PDL\n"
    embed.description = txt if txt else "Vazio."
    embed.set_footer(text=f"Página 1 • Total: {view.total_jogadores}")
    await ctx.send(embed=embed, view=view)

@bot.hybrid_command(name="historico_player", description="Vê histórico de um jogador.")
async def historico_player(ctx, membro: discord.Member = None):
    alvo = membro or ctx.author
    d = get_jogador(alvo.id)
    if not d: return await ctx.send("Jogador não registrado.", ephemeral=True)
    partidas = get_historico_pessoal(d['nick'])
    if not partidas: return await ctx.send(f"**{d['nick']}** ainda não jogou.", ephemeral=True)
    embed = discord.Embed(title=f"📜 Histórico de {d['nick']}", color=0x9b59b6)
    for p in partidas:
        venceu = False
        time_jog = "Indefinido"
        if d['nick'] in p['azul']: 
            time_jog = "Azul"
            if p['vencedor'] == 'azul': venceu = True
        elif d['nick'] in p['vermelho']: 
            time_jog = "Vermelho"
            if p['vencedor'] == 'vermelho': venceu = True
        resultado = "✅ Vitória" if venceu else "❌ Derrota"
        data_fmt = p['data'].strftime("%d/%m %H:%M")
        embed.add_field(name=f"{resultado} ({p.get('modo','sr').upper()})", value=f"📅 {data_fmt}\n🛡️ Time: {time_jog}", inline=False)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="start", description="Inicia partida.")
@app_commands.choices(modo=[app_commands.Choice(name="Summoner's Rift", value="sr"), app_commands.Choice(name="ARAM", value="aram"), app_commands.Choice(name="Arena", value="arena")], tipo=[app_commands.Choice(name="Blind", value="Blind"), app_commands.Choice(name="Draft", value="Draft"), app_commands.Choice(name="Tournament", value="Tournament")])
@app_commands.describe(nome_sala="Nome da sala", senha="Senha", valendo_pdl="Valendo?", ignorar_tamanho="Forçar?")
async def start(ctx, modo: app_commands.Choice[str], tipo: app_commands.Choice[str], nome_sala: str, senha: str = "Sem senha", regras: str = "Nenhuma", valendo_pdl: bool = True, ignorar_tamanho: bool = False):
    global fila
    modo_val = modo.value if modo else "sr"
    tipo_val = tipo.value if tipo else "Draft"
    qtd = len(fila)
    if qtd < 2: return await ctx.send("❌ Mínimo 2.")
    if not ignorar_tamanho and qtd < 10: return await ctx.send("⚠️ Faltam players.")
    if qtd % 2 != 0: return await ctx.send("⚠️ Ímpar.")
    
    corte = 10 if qtd >= 10 else qtd
    players = fila[:corte]
    fila = fila[corte:]
    await iniciar_partida(ctx, modo_val, valendo_pdl, players, tipo_val, nome_sala, senha, regras)

async def iniciar_partida(ctx, modo, valendo, players, tipo, nome_sala, senha, regras):
    global partida_atual
    responder = ctx.response.send_message if isinstance(ctx, discord.Interaction) else ctx.send
    await responder(f"⚖️ **Iniciando {modo.upper()}...**")
    ids = [p.id for p in players]
    dados = get_dados_varios(ids)
    mapa = {d['_id']: d for d in dados}
    campo = "pdl" if modo == "sr" else f"pdl_{modo}"
    ordenados = sorted(players, key=lambda p: mapa.get(str(p.id), {}).get(campo, 1000), reverse=True)
    azul, verm = [], []
    for i, p in enumerate(ordenados):
        if i % 4 == 0 or i % 4 == 3: azul.append(p)
        else: verm.append(p)
        
    try: canais = await criar_canais_voz(ctx.guild, azul, verm)
    except: canais = None
    
    partida_atual = {'azul': azul, 'vermelho': verm, 'modo': modo, 'valendo_pdl': valendo, 'canais_voz': canais, 'info_sala': {'nome': nome_sala, 'senha': senha, 'tipo': tipo}}
    icone = get_icone_modo(modo)
    embed = discord.Embed(title=f"{icone} Partida {modo.upper()}", color=0x0099ff)
    embed.add_field(name="🏠 Sala", value=f"Nome: `{nome_sala}`\nSenha: `{senha}`\nTipo: {tipo}\nRegras: {regras}", inline=False)
    def fmt(p):
        d = mapa.get(str(p.id))
        r = d.get('rota', '❔') if modo == "sr" else "🎲"
        return f"{r} **{d['nick']}** ({d.get(campo, 1000)})"
    embed.add_field(name="🟦 AZUL", value="\n".join([fmt(p) for p in azul]), inline=False)
    embed.add_field(name="🟥 VERMELHO", value="\n".join([fmt(p) for p in verm]), inline=False)
    if canais: embed.add_field(name="🔊 Voz", value=f"{canais[0].mention} | {canais[1].mention}", inline=False)
    if isinstance(ctx, discord.Interaction): await ctx.followup.send(embed=embed)
    else: await ctx.send(embed=embed)
    for p in players:
        try: await p.send(f"🎮 **Partida!** Sala: `{nome_sala}` Senha: `{senha}`")
        except: pass

@bot.command()
async def mvp(ctx, membro: discord.Member):
    if ctx.author.id == membro.id: return await ctx.send("❌ Auto-voto proibido!")
    adicionar_mvp(membro.id)
    await ctx.send(f"🌟 MVP para **{membro.display_name}**!")

@bot.hybrid_command(name="perfil", description="Ver stats.")
async def perfil(ctx, membro: discord.Member = None):
    alvo = membro or ctx.author
    d = get_jogador(alvo.id)
    if not d: return await ctx.send("Não registrado.", ephemeral=True)
    embed = discord.Embed(title=f"📊 {d['nick']}", color=0x9b59b6)
    sr, aram, arena = d.get('pdl', 1000), d.get('pdl_aram', 1000), d.get('pdl_arena', 1000)
    embed.add_field(name=f"Rift", value=f"{get_icone_elo(sr)} {sr}", inline=True)
    embed.add_field(name=f"ARAM", value=f"{get_icone_elo(aram)} {aram}", inline=True)
    embed.add_field(name=f"Arena", value=f"{get_icone_elo(arena)} {arena}", inline=True)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="help", description="Ajuda.")
async def help(ctx):
    embed = discord.Embed(title="📘 Ajuda", color=0x3498db)
    embed.description = "`/painel`, `/registrar`, `/editar`\n`/historico_player`, `/ranking`"
    await ctx.send(embed=embed)

keep_alive()
bot.run(TOKEN)
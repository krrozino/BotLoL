import discord
import datetime
from database import get_jogador, checar_banimento, get_ranking_paginado, contar_jogadores, get_todos_jogadores_paginado, adicionar_mvp
from utils import calcular_elo, calcular_winrate, get_icone_elo, get_icone_modo

# --- VIEW DA FILA (MANTIDA IGUAL) ---
class FilaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def atualizar_mensagem(self, interaction: discord.Interaction):
        fila = interaction.client.fila
        ultimo_movimento = interaction.client.ultimo_movimento_fila
        delta = datetime.datetime.now() - ultimo_movimento
        minutos = int(delta.total_seconds() / 60)
        
        embed = discord.Embed(title=f"Lobby Inhouse - {len(fila)} Jogadores", color=0x2ecc71)
        if not fila:
            embed.description = "A fila está vazia. Seja o primeiro a entrar!"
        else:
            lista_txt = ""
            for i, p in enumerate(fila):
                status = "**(Jogando)**" if i < 10 else "(Próxima)"
                lista_txt += f"`{i+1}.` {p.display_name} {status}\n"
            embed.description = lista_txt
        embed.set_footer(text=f"Última atividade: {minutos} min atrás")
        try: await interaction.message.edit(embed=embed, view=self)
        except: pass

    @discord.ui.button(label="Entrar", style=discord.ButtonStyle.success, custom_id="btn_entrar", emoji="⚔️")
    async def entrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        if not get_jogador(interaction.user.id):
            return await interaction.response.send_message("❌ **Registro Necessário:** Use `/registrar` primeiro.", ephemeral=True)
        
        banido, tempo = checar_banimento(interaction.user.id)
        if banido:
            return await interaction.response.send_message(f"🚫 **Você está suspenso.**\nTempo restante: {tempo}", ephemeral=True)

        if interaction.user in bot.fila:
            return await interaction.response.send_message("Você já está na fila!", ephemeral=True)
            
        bot.fila.append(interaction.user)
        bot.ultimo_movimento_fila = datetime.datetime.now()
        await interaction.response.defer()
        await self.atualizar_mensagem(interaction)
        
        if len(bot.fila) == 10:
            try: await interaction.channel.send("🔥 **Fila Cheia (10)!** Admin, use `/start` para iniciar.")
            except: pass

    @discord.ui.button(label="Sair", style=discord.ButtonStyle.danger, custom_id="btn_sair", emoji="🏃")
    async def sair(self, interaction: discord.Interaction, button: discord.ui.Button):
        bot = interaction.client
        if interaction.user not in bot.fila:
            return await interaction.response.send_message("Você não está na fila.", ephemeral=True)
        bot.fila.remove(interaction.user)
        bot.ultimo_movimento_fila = datetime.datetime.now()
        await interaction.response.defer()
        await self.atualizar_mensagem(interaction)

    @discord.ui.button(label="Perfil", style=discord.ButtonStyle.secondary, custom_id="btn_perfil", emoji="📊")
    async def ver_meu_perfil(self, interaction: discord.Interaction, button: discord.ui.Button):
        d = get_jogador(interaction.user.id)
        if not d: return await interaction.response.send_message("Registre-se para ver seu perfil.", ephemeral=True)
        elo_sr = calcular_elo(d.get('pdl', 1000))
        wr = calcular_winrate(d['vitorias'], d['derrotas'])
        icone = get_icone_elo(d.get('pdl', 1000))
        msg = f"📊 **{d['nick']}**\n{icone} SR: {d.get('pdl', 1000)} ({elo_sr})\n❄️ ARAM: {d.get('pdl_aram', 1000)}\n📈 WR: {wr} | MVPs: {d.get('mvps', 0)}"
        await interaction.response.send_message(msg, ephemeral=True)

# --- NOVO: SISTEMA DE VOTAÇÃO DE MVP ---
class MVPView(discord.ui.View):
    def __init__(self, ganhadores_list):
        super().__init__(timeout=300) # 5 minutos para votar
        self.votos = {} # {user_id_voto: count}
        self.votaram = [] # lista de ids que já votaram
        
        # Cria as opções do menu com os ganhadores
        opcoes = []
        for player in ganhadores_list:
            opcoes.append(discord.SelectOption(label=player.display_name, value=str(player.id), emoji="🌟"))
        
        # Adiciona o Select Menu dinamicamente
        select = discord.ui.Select(placeholder="Vote no MVP da partida!", options=opcoes, custom_id="select_mvp")
        select.callback = self.callback_voto
        self.add_item(select)

    async def callback_voto(self, interaction: discord.Interaction):
        # Verifica se já votou
        if interaction.user.id in self.votaram:
            return await interaction.response.send_message("❌ Você já votou!", ephemeral=True)
        
        escolhido_id = interaction.data['values'][0]
        
        # Computa voto
        self.votos[escolhido_id] = self.votos.get(escolhido_id, 0) + 1
        self.votaram.append(interaction.user.id)
        
        await interaction.response.send_message(f"✅ Voto computado!", ephemeral=True)

    @discord.ui.button(label="Encerrar Votação", style=discord.ButtonStyle.danger, emoji="🛑")
    async def encerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Apenas admins podem encerrar manualmente antes do tempo
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Apenas admins podem encerrar.", ephemeral=True)
        
        self.stop()
        await self.calcular_resultado(interaction)

    async def on_timeout(self):
        # Se o tempo acabar, não temos interaction, então não dá pra editar mensagem facilmente sem guardar referência.
        # Idealmente o admin encerra.
        pass

    async def calcular_resultado(self, interaction):
        if not self.votos:
            return await interaction.response.edit_message(content="❌ Votação encerrada. Nenhum voto computado.", view=None, embed=None)
        
        # Acha quem teve mais votos
        vencedor_id = max(self.votos, key=self.votos.get)
        total_votos = self.votos[vencedor_id]
        
        # Atualiza no banco
        adicionar_mvp(vencedor_id)
        
        embed = discord.Embed(title="🌟 MVP DA PARTIDA", color=0xf1c40f)
        embed.description = f"O jogador <@{vencedor_id}> foi eleito com **{total_votos}** votos!"
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/1021/1021201.png") # Imagem genérica de troféu
        
        await interaction.response.edit_message(content=None, embed=embed, view=None)

# --- RANKING MELHORADO ---
class RankingView(discord.ui.View):
    def __init__(self, modo_inicial="sr"):
        super().__init__(timeout=120)
        self.pagina = 0
        self.modo = modo_inicial
        self.total_jogadores = contar_jogadores()

    async def update_view(self, interaction):
        top = get_ranking_paginado(self.modo, skip=self.pagina*10, limit=10)
        icone = get_icone_modo(self.modo)
        embed = discord.Embed(title=f"{icone} Ranking - {self.modo.upper()}", color=0xffd700)
        
        txt = ""
        for i, p in enumerate(top):
            if self.modo == "sr": val = p.get('pdl', 1000)
            elif self.modo == "aram": val = p.get('pdl_aram', 1000)
            else: val = p.get('pdl_arena', 1000)
            
            # Formatação Melhorada
            posicao = (self.pagina * 10) + i + 1
            medalha = "👑" if posicao == 1 else f"`{posicao}º`"
            wr = calcular_winrate(p.get('vitorias',0), p.get('derrotas',0))
            mvps = p.get('mvps', 0)
            
            txt += f"{medalha} **{p['nick']}** — {val} PDL\n"
            txt += f"└─ 📊 {p.get('vitorias',0)}V/{p.get('derrotas',0)}D ({wr}) | 🌟 {mvps} MVPs\n"
        
        embed.description = txt if txt else "Nenhum jogador encontrado."
        embed.set_footer(text=f"Página {self.pagina + 1} • Total Jogadores: {self.total_jogadores}")
        
        self.btn_ant.disabled = (self.pagina == 0)
        self.btn_prox.disabled = ((self.pagina + 1) * 10 >= self.total_jogadores)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.select(placeholder="Modo de Jogo", options=[
        discord.SelectOption(label="Summoner's Rift", value="sr", emoji="🗺️"),
        discord.SelectOption(label="ARAM", value="aram", emoji="❄️"),
        discord.SelectOption(label="Arena", value="arena", emoji="⚔️")
    ])
    async def select_modo(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.modo = select.values[0]
        self.pagina = 0
        await self.update_view(interaction)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.primary, disabled=True)
    async def btn_ant(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.pagina > 0:
            self.pagina -= 1
            await self.update_view(interaction)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.primary)
    async def btn_prox(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.pagina + 1) * 10 < self.total_jogadores:
            self.pagina += 1
            await self.update_view(interaction)

# --- LISTA MANTIDA ---
class ListaJogadoresView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.pagina = 0
        self.total_jogadores = contar_jogadores()

    async def atualizar_embed(self, interaction):
        lista = get_todos_jogadores_paginado(skip=self.pagina*10, limit=10)
        embed = discord.Embed(title=f"📋 Lista Completa (Admin)", color=0x95a5a6)
        txt = ""
        for p in lista:
            txt += f"• **{p['nick']}** | ID: `{p['_id']}` | SR: {p.get('pdl', 1000)}\n"
        embed.description = txt if txt else "Vazio."
        embed.set_footer(text=f"Página {self.pagina + 1} • Total: {self.total_jogadores}")
        self.btn_ant.disabled = (self.pagina == 0)
        self.btn_prox.disabled = ((self.pagina + 1) * 10 >= self.total_jogadores)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.primary, disabled=True)
    async def btn_ant(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.pagina > 0:
            self.pagina -= 1
            await self.atualizar_embed(interaction)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.primary)
    async def btn_prox(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.pagina + 1) * 10 < self.total_jogadores:
            self.pagina += 1
            await self.atualizar_embed(interaction)
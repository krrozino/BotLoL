import discord
from discord import app_commands
from discord.ext import commands
from views import FilaView, ListaJogadoresView, MVPView
from database import (
    get_jogador, criar_jogador, aplicar_punicao, set_pdl_manual, 
    salvar_historico_db, atualizar_pdl, get_dados_varios, atualizar_rota
)
from utils import gerenciar_cargos_elo, get_icone_modo
import datetime

class Admin(commands.GroupCog, name="admin"):
    def __init__(self, bot):
        self.bot = bot
        self.canal_historico_nome = "historico-partidas" # NOME DO CANAL PARA LOGS

    async def cog_check(self, ctx):
        if ctx.interaction:
            return ctx.interaction.user.guild_permissions.administrator
        return ctx.author.guild_permissions.administrator

    async def enviar_log(self, guild, texto):
        canal = discord.utils.get(guild.text_channels, name="logs-inhouse")
        if canal:
            embed = discord.Embed(description=texto, color=0xe74c3c, timestamp=datetime.datetime.now())
            try: await canal.send(embed=embed)
            except: pass

    # ... COMANDOS ANTERIORES (painel, jogadores, etc.) ...
    
    @app_commands.command(name="painel", description="Cria o painel de fila.")
    async def painel(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏆 Lobby Inhouse", description="Clique abaixo para entrar na fila.", color=0x2ecc71)
        await interaction.response.send_message("Painel criado!", ephemeral=True)
        await interaction.channel.send(embed=embed, view=FilaView())

    @app_commands.command(name="jogadores", description="Lista paginada.")
    async def jogadores(self, interaction: discord.Interaction):
        view = ListaJogadoresView()
        await view.atualizar_embed(interaction)

    @app_commands.command(name="info_jogador", description="Ficha técnica.")
    async def info_jogador(self, interaction: discord.Interaction, membro: discord.Member):
        d = get_jogador(membro.id)
        if not d: return await interaction.response.send_message("❌ Jogador não registrado.", ephemeral=True)
        embed = discord.Embed(title=f"📁 Ficha: {d['nick']}", color=0x3498db)
        embed.add_field(name="ID", value=d['_id'])
        embed.add_field(name="PDL", value=f"{d.get('pdl', 1000)} SR / {d.get('pdl_aram', 1000)} ARAM")
        embed.add_field(name="MVPs", value=d.get('mvps', 0))
        embed.add_field(name="Streak", value=d.get('streak', 0)) # Adicionado Streak na ficha
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="registrar_player", description="Registro manual.")
    async def registrar_player(self, interaction: discord.Interaction, membro: discord.Member, nick: str):
        if get_jogador(membro.id): return await interaction.response.send_message("Já existe.", ephemeral=True)
        criar_jogador(membro.id, nick, "Admin")
        await gerenciar_cargos_elo(membro, 1000, "sr")
        await interaction.response.send_message(f"✅ {membro.mention} registrado.")
        await self.enviar_log(interaction.guild, f"✏️ **Admin Register:** {membro.mention}")

    @app_commands.command(name="kick", description="Kick da fila.")
    async def kick(self, interaction: discord.Interaction, membro: discord.Member):
        if membro in self.bot.fila:
            self.bot.fila.remove(membro)
            self.bot.ultimo_movimento_fila = datetime.datetime.now()
            await interaction.response.send_message(f"👢 {membro.mention} removido.")
        else: await interaction.response.send_message("Não está na fila.", ephemeral=True)

    @app_commands.command(name="reset", description="Limpa fila.")
    async def reset(self, interaction: discord.Interaction):
        self.bot.fila.clear()
        self.bot.ultimo_movimento_fila = datetime.datetime.now()
        await interaction.response.send_message("🧹 Fila limpa.")

    @app_commands.command(name="setpdl", description="Define PDL.")
    @app_commands.choices(modo=[app_commands.Choice(name="SR", value="sr"), app_commands.Choice(name="ARAM", value="aram"), app_commands.Choice(name="Arena", value="arena")])
    async def setpdl(self, interaction: discord.Interaction, membro: discord.Member, quantidade: int, modo: app_commands.Choice[str] = None):
        modo_val = modo.value if modo else "sr"
        set_pdl_manual(membro.id, quantidade, modo_val)
        await gerenciar_cargos_elo(membro, quantidade, modo_val)
        await interaction.response.send_message(f"👮 PDL atualizado: {quantidade}")

    @app_commands.command(name="sub", description="Substituição.")
    async def sub(self, interaction: discord.Interaction, saiu: discord.Member, entrou: discord.Member, punir: bool = True):
        p = self.bot.partida_atual
        if not p: return await interaction.response.send_message("❌ Sem partida.", ephemeral=True)
        if not get_jogador(entrou.id): return await interaction.response.send_message("❌ Sub não registrado.", ephemeral=True)

        time_nome = "azul" if saiu in p['azul'] else "vermelho" if saiu in p['vermelho'] else None
        if not time_nome: return await interaction.response.send_message("Jogador não está na partida.", ephemeral=True)

        p[time_nome].remove(saiu)
        p[time_nome].append(entrou)
        
        if punir:
            aplicar_punicao(saiu.id, 20, 60)
            d = get_jogador(saiu.id)
            await gerenciar_cargos_elo(saiu, d.get('pdl', 1000), "sr")

        if p.get('canais'):
            c = p['canais'][0] if time_nome == "azul" else p['canais'][1]
            try:
                await c.set_permissions(saiu, view_channel=False)
                await c.set_permissions(entrou, view_channel=True, connect=True)
            except: pass
        
        await interaction.response.send_message(f"🔄 Sub: {saiu.mention} -> {entrou.mention}")

    @app_commands.command(name="shuffle", description="Misturar times.")
    async def shuffle(self, interaction: discord.Interaction):
        p = self.bot.partida_atual
        if not p: return await interaction.response.send_message("❌ Sem partida.", ephemeral=True)
        todos = p['azul'] + p['vermelho']
        ids = [x.id for x in todos]
        dados = get_dados_varios(ids)
        mapa = {str(d['_id']): d for d in dados}
        campo = 'pdl' if p['modo'] == 'sr' else f"pdl_{p['modo']}"
        ordenados = sorted(todos, key=lambda x: mapa.get(str(x.id), {}).get(campo, 1000), reverse=True)
        
        p['azul'], p['vermelho'] = [], []
        for i, pl in enumerate(ordenados):
            if i % 4 == 0 or i % 4 == 3: p['azul'].append(pl)
            else: p['vermelho'].append(pl)
            
        embed = discord.Embed(title="🔀 Times Misturados", color=0xe67e22)
        embed.add_field(name="Azul", value="\n".join([x.display_name for x in p['azul']]))
        embed.add_field(name="Vermelho", value="\n".join([x.display_name for x in p['vermelho']]))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="cancelar", description="Cancela partida.")
    async def cancelar(self, interaction: discord.Interaction):
        if not self.bot.partida_atual: return await interaction.response.send_message("Sem partida.", ephemeral=True)
        if self.bot.partida_atual.get('canais'):
            for c in self.bot.partida_atual['canais']: 
                try: await c.delete()
                except: pass
        self.bot.partida_atual = None
        await interaction.response.send_message("🚫 Partida cancelada.")

    # --- COMANDO VITORIA ATUALIZADO ---
    @app_commands.command(name="vitoria", description="Declara vencedor e gera histórico.")
    @app_commands.choices(time=[app_commands.Choice(name="Azul", value="azul"), app_commands.Choice(name="Vermelho", value="vermelho")])
    async def vitoria(self, interaction: discord.Interaction, time: app_commands.Choice[str]):
        p = self.bot.partida_atual
        if not p: return await interaction.response.send_message("Sem partida.", ephemeral=True)
        
        await interaction.response.defer()
        venc = time.value
        modo = p['modo']
        
        # 1. Calcula Duração
        inicio = p.get('inicio', datetime.datetime.now())
        fim = datetime.datetime.now()
        duracao = fim - inicio
        minutos = int(duracao.total_seconds() // 60)
        segundos = int(duracao.total_seconds() % 60)
        duracao_str = f"{minutos}m {segundos}s"

        msg_result = f"🏆 **VITÓRIA {venc.upper()}**\n"
        ganhadores = p[venc]
        perdedores = p['vermelho'] if venc == 'azul' else p['azul']
        
        # Listas para o Relatório do Canal
        relatorio_ganhadores = [] 
        relatorio_perdedores = []

        if p['valendo']:
            for m in ganhadores:
                # atualizar_pdl agora retorna o valor exato ganho (ex: 32)
                qtd_ganha = atualizar_pdl(m.id, True, modo) 
                d = get_jogador(m.id)
                novo = d.get('pdl', 1000) if modo == 'sr' else d.get(f'pdl_{modo}', 1000)
                await gerenciar_cargos_elo(m, novo, modo)
                
                relatorio_ganhadores.append(f"**{m.display_name}**: +{qtd_ganha} ({novo})")
                msg_result += f"📈 {m.display_name}: +{qtd_ganha} ({novo})\n"

            for m in perdedores:
                qtd_perdida = atualizar_pdl(m.id, False, modo)
                d = get_jogador(m.id)
                novo = d.get('pdl', 1000) if modo == 'sr' else d.get(f'pdl_{modo}', 1000)
                await gerenciar_cargos_elo(m, novo, modo)
                
                relatorio_perdedores.append(f"**{m.display_name}**: -{qtd_perdida} ({novo})")
                msg_result += f"📉 {m.display_name}: -{qtd_perdida} ({novo})\n"
        else:
            msg_result += "*(Partida não valeu PDL)*"

        # 2. Salva no Banco (Auditoria Técnica Completa)
        salvar_historico_db({
            "data": fim,
            "duracao_segundos": duracao.total_seconds(),
            "vencedor": venc,
            "azul": [x.display_name for x in p['azul']],
            "vermelho": [x.display_name for x in p['vermelho']],
            "modo": modo
        })

        # 3. Envia o Relatório Bonito no Canal de Histórico
        canal_hist = discord.utils.get(interaction.guild.text_channels, name=self.canal_historico_nome)
        if canal_hist:
            embed_log = discord.Embed(title=f"📜 Relatório de Partida", color=0xf1c40f if venc == "amarelo" else 0x3498db)
            embed_log.add_field(name="Informações", value=f"**Modo:** {modo.upper()}\n**Vencedor:** {venc.upper()}\n**Duração:** {duracao_str}\n**Data:** {fim.strftime('%d/%m/%Y %H:%M')}", inline=False)
            
            lista_win = "\n".join(relatorio_ganhadores) if relatorio_ganhadores else "N/A"
            lista_lose = "\n".join(relatorio_perdedores) if relatorio_perdedores else "N/A"
            
            embed_log.add_field(name=f"🏆 Vencedores ({venc.upper()})", value=lista_win, inline=False)
            embed_log.add_field(name=f"💀 Perdedores", value=lista_lose, inline=False)
            embed_log.set_footer(text=f"Partida finalizada por {interaction.user.display_name}")
            
            await canal_hist.send(embed=embed_log)

        # Limpeza
        if p.get('canais'):
            for c in p['canais']:
                try: await c.delete()
                except: pass
        
        self.bot.partida_atual = None
        
        await interaction.followup.send(msg_result)
        
        # Chama MVP
        view_mvp = MVPView(ganhadores)
        await interaction.channel.send("🌟 **Votação de MVP Aberta!**", view=view_mvp)

async def setup(bot):
    await bot.add_cog(Admin(bot))
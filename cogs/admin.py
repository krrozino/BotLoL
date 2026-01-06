import discord
from discord import app_commands
from discord.ext import commands
from views import FilaView, ListaJogadoresView
from database import (
    get_jogador, criar_jogador, aplicar_punicao, set_pdl_manual, 
    salvar_historico, atualizar_pdl, get_dados_varios, atualizar_rota
)
from utils import gerenciar_cargos_elo, get_icone_modo
import datetime

class Admin(commands.GroupCog, name="admin"):
    def __init__(self, bot):
        self.bot = bot

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

    @app_commands.command(name="painel", description="Cria o painel de fila.")
    async def painel(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏆 Lobby Inhouse", description="Clique abaixo para entrar na fila.", color=0x2ecc71)
        await interaction.response.send_message("Painel criado!", ephemeral=True)
        await interaction.channel.send(embed=embed, view=FilaView())

    @app_commands.command(name="jogadores", description="Lista paginada de todos os registros.")
    async def jogadores(self, interaction: discord.Interaction):
        view = ListaJogadoresView()
        await view.atualizar_embed(interaction)

    @app_commands.command(name="info_jogador", description="Ficha técnica completa.")
    async def info_jogador(self, interaction: discord.Interaction, membro: discord.Member):
        d = get_jogador(membro.id)
        if not d: return await interaction.response.send_message("❌ Jogador não registrado.", ephemeral=True)
        embed = discord.Embed(title=f"📁 Ficha: {d['nick']}", color=0x3498db)
        embed.add_field(name="ID", value=d['_id'])
        embed.add_field(name="PDL (SR/ARAM/Arena)", value=f"{d.get('pdl', 1000)} / {d.get('pdl_aram', 1000)} / {d.get('pdl_arena', 1000)}")
        embed.add_field(name="Banido Até", value=d.get('banido_ate', 'Livre'))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="registrar_player", description="Registro manual.")
    async def registrar_player(self, interaction: discord.Interaction, membro: discord.Member, nick: str):
        if get_jogador(membro.id): return await interaction.response.send_message("Já existe.", ephemeral=True)
        criar_jogador(membro.id, nick, "Admin")
        await gerenciar_cargos_elo(membro, 1000, "sr")
        await interaction.response.send_message(f"✅ {membro.mention} registrado.")
        await self.enviar_log(interaction.guild, f"✏️ **Admin Register:** {membro.mention} por {interaction.user.mention}")

    @app_commands.command(name="kick", description="Remove alguém da fila.")
    async def kick(self, interaction: discord.Interaction, membro: discord.Member):
        if membro in self.bot.fila:
            self.bot.fila.remove(membro)
            self.bot.ultimo_movimento_fila = datetime.datetime.now()
            await interaction.response.send_message(f"👢 {membro.mention} removido da fila.")
            await self.enviar_log(interaction.guild, f"👢 **KICK:** {membro.mention} kickado da fila.")
        else:
            await interaction.response.send_message("Este jogador não está na fila.", ephemeral=True)

    @app_commands.command(name="reset", description="Reseta fila.")
    async def reset(self, interaction: discord.Interaction):
        self.bot.fila.clear()
        self.bot.ultimo_movimento_fila = datetime.datetime.now()
        await interaction.response.send_message("🧹 Fila limpa.")
        await self.enviar_log(interaction.guild, "🧹 **RESET:** Fila resetada.")

    @app_commands.command(name="setpdl", description="Define PDL manualmente.")
    @app_commands.choices(modo=[app_commands.Choice(name="SR", value="sr"), app_commands.Choice(name="ARAM", value="aram"), app_commands.Choice(name="Arena", value="arena")])
    async def setpdl(self, interaction: discord.Interaction, membro: discord.Member, quantidade: int, modo: app_commands.Choice[str] = None):
        modo_val = modo.value if modo else "sr"
        set_pdl_manual(membro.id, quantidade, modo_val)
        await gerenciar_cargos_elo(membro, quantidade, modo_val)
        await interaction.response.send_message(f"👮 PDL de {membro.mention} definido para {quantidade} ({modo_val.upper()}).")
        await self.enviar_log(interaction.guild, f"👮 **SETPDL:** {membro.mention} -> {quantidade} ({modo_val})")

    @app_commands.command(name="sub", description="Substituição em partida ativa.")
    async def sub(self, interaction: discord.Interaction, saiu: discord.Member, entrou: discord.Member, punir: bool = True):
        p = self.bot.partida_atual
        if not p: return await interaction.response.send_message("❌ Nenhuma partida ativa.", ephemeral=True)
        if not get_jogador(entrou.id): return await interaction.response.send_message("❌ O substituto precisa se registrar.", ephemeral=True)

        time_nome = None
        if saiu in p['azul']:
            p['azul'].remove(saiu)
            p['azul'].append(entrou)
            time_nome = "azul"
        elif saiu in p['vermelho']:
            p['vermelho'].remove(saiu)
            p['vermelho'].append(entrou)
            time_nome = "vermelho"
        else:
            return await interaction.response.send_message("❌ Jogador que saiu não está na partida.", ephemeral=True)

        txt_punicao = ""
        if punir:
            aplicar_punicao(saiu.id, 20, 60)
            d = get_jogador(saiu.id)
            await gerenciar_cargos_elo(saiu, d.get('pdl', 1000), "sr")
            txt_punicao = "\n🚫 **Punição:** -20 PDL e 60min Ban."

        # Permissões de Voz
        canais = p.get('canais')
        if canais:
            c_alvo = canais[0] if time_nome == "azul" else canais[1]
            try:
                await c_alvo.set_permissions(saiu, view_channel=False)
                await c_alvo.set_permissions(entrou, view_channel=True, connect=True)
                if entrou.voice: await entrou.move_to(c_alvo)
                if saiu.voice: await saiu.move_to(None)
            except: pass

        await interaction.response.send_message(f"🔄 **SUB:** Saiu {saiu.mention} -> Entrou {entrou.mention}{txt_punicao}")
        await self.enviar_log(interaction.guild, f"🔄 **SUB:** {saiu} por {entrou}.")

    @app_commands.command(name="shuffle", description="Re-mistura os times da partida atual.")
    async def shuffle(self, interaction: discord.Interaction):
        p = self.bot.partida_atual
        if not p: return await interaction.response.send_message("❌ Sem partida.", ephemeral=True)
        
        todos = p['azul'] + p['vermelho']
        modo = p['modo']
        ids = [x.id for x in todos]
        dados = get_dados_varios(ids)
        mapa = {str(d['_id']): d for d in dados}
        
        campo_pdl = 'pdl' if modo == 'sr' else f'pdl_{modo}'
        ordenados = sorted(todos, key=lambda x: mapa.get(str(x.id), {}).get(campo_pdl, 1000), reverse=True)
        
        # Novo balanço
        azul, verm = [], []
        for i, player in enumerate(ordenados):
            if i % 4 == 0 or i % 4 == 3: azul.append(player)
            else: verm.append(player)
            
        # Atualiza a referência global
        self.bot.partida_atual['azul'] = azul
        self.bot.partida_atual['vermelho'] = verm
        
        embed = discord.Embed(title="🔀 Times Misturados", color=0xe67e22)
        embed.add_field(name="Azul", value="\n".join([x.display_name for x in azul]), inline=True)
        embed.add_field(name="Vermelho", value="\n".join([x.display_name for x in verm]), inline=True)
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
        await self.enviar_log(interaction.guild, "🚫 **CANCEL:** Admin cancelou.")

    @app_commands.command(name="vitoria", description="Declara vencedor.")
    @app_commands.choices(time=[app_commands.Choice(name="Azul", value="azul"), app_commands.Choice(name="Vermelho", value="vermelho")])
    async def vitoria(self, interaction: discord.Interaction, time: app_commands.Choice[str]):
        p = self.bot.partida_atual
        if not p: return await interaction.response.send_message("Sem partida.", ephemeral=True)
        
        await interaction.response.defer()
        venc = time.value
        modo = p['modo']
        
        salvar_historico(venc, [x.display_name for x in p['azul']], [x.display_name for x in p['vermelho']], modo)
        
        msg_result = f"🏆 **VITÓRIA {venc.upper()}**\n"

        if p['valendo']:
            ganhadores = p[venc]
            perdedores = p['vermelho'] if venc == 'azul' else p['azul']
            
            for m in ganhadores:
                bonus = atualizar_pdl(m.id, 20, True, modo)
                d = get_jogador(m.id)
                novo = d.get('pdl', 1000) if modo == 'sr' else d.get(f'pdl_{modo}', 1000)
                await gerenciar_cargos_elo(m, novo, modo)
                msg_result += f"📈 {m.display_name}: +{20+bonus} ({novo})\n"

            for m in perdedores:
                atualizar_pdl(m.id, -20, False, modo)
                d = get_jogador(m.id)
                novo = d.get('pdl', 1000) if modo == 'sr' else d.get(f'pdl_{modo}', 1000)
                await gerenciar_cargos_elo(m, novo, modo)
                msg_result += f"📉 {m.display_name}: -20 ({novo})\n"

        if p.get('canais'):
            for c in p['canais']:
                try: await c.delete()
                except: pass
        
        self.bot.partida_atual = None
        await interaction.followup.send(msg_result)
        await self.enviar_log(interaction.guild, f"🏆 **FIM:** Vitória {venc}.")

async def setup(bot):
    await bot.add_cog(Admin(bot))
import discord
from discord import app_commands
from discord.ext import commands
from database import (
    get_jogador, criar_jogador, editar_perfil, atualizar_rota, 
    resgatar_diario, get_ranking_paginado, get_historico_pessoal, adicionar_mvp
)
from utils import get_icone_elo, gerenciar_cargos_elo
from views import RankingView

class Geral(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Comando de prefixo (!mvp @player)
    @commands.command(name="mvp")
    async def mvp(self, ctx, membro: discord.Member):
        if ctx.author.id == membro.id:
            return await ctx.send("❌ Você não pode votar em si mesmo!")
        adicionar_mvp(membro.id)
        await ctx.send(f"🌟 **MVP!** Voto computado para **{membro.display_name}**.")

    @commands.hybrid_command(name="ping", description="Latência do bot.")
    async def ping(self, ctx):
        await ctx.send(f"🏓 Pong! **{round(self.bot.latency * 1000)}ms**")

    @commands.hybrid_command(name="help", description="Guia completo de comandos.")
    async def help(self, ctx):
        embed = discord.Embed(title="📘 Central de Ajuda", color=0x3498db)
        embed.add_field(name="🙋‍♂️ Jogador", value="`/registrar`, `/editar`, `/rota`, `/diario`, `/perfil`\n`!mvp @player`", inline=False)
        embed.add_field(name="⚔️ Fila", value="`/ranking`, `/historico_player`\nUse o `/painel` para jogar.", inline=False)
        embed.add_field(name="👮‍♂️ Admin", value="`/start`, `/admin painel`, `/admin sub`, `/admin kick`, `/admin setpdl`", inline=False)
        await ctx.send(embed=embed)

    @app_commands.command(name="registrar", description="Crie sua conta.")
    async def registrar(self, interaction: discord.Interaction, nick: str, opgg: str = "N/A"):
        if get_jogador(interaction.user.id): 
            return await interaction.response.send_message("Já registrado!", ephemeral=True)
        criar_jogador(interaction.user.id, nick, opgg)
        try:
            cargo = discord.utils.get(interaction.guild.roles, name="Registrado")
            if cargo: await interaction.user.add_roles(cargo)
        except: pass
        await gerenciar_cargos_elo(interaction.user, 1000, "sr")
        await interaction.response.send_message(f"✅ Conta criada para **{nick}**!")

    @app_commands.command(name="editar", description="Edite seu Nick ou OP.GG.")
    async def editar(self, interaction: discord.Interaction, nick: str = None, opgg: str = None):
        if not get_jogador(interaction.user.id):
            return await interaction.response.send_message("❌ Não registrado.", ephemeral=True)
        msg = ""
        if nick:
            editar_perfil(interaction.user.id, "nick", nick)
            msg += f"✅ Nick alterado para **{nick}**.\n"
        if opgg:
            editar_perfil(interaction.user.id, "opgg", opgg)
            msg += f"✅ Link OP.GG atualizado.\n"
        await interaction.response.send_message(msg or "Nada alterado.", ephemeral=True)

    @app_commands.command(name="rota", description="Escolha sua main lane.")
    @app_commands.choices(lane=[
        app_commands.Choice(name="Top", value="top"), app_commands.Choice(name="Jungle", value="jungle"),
        app_commands.Choice(name="Mid", value="mid"), app_commands.Choice(name="ADC", value="adc"),
        app_commands.Choice(name="Support", value="sup"), app_commands.Choice(name="Fill", value="fill")
    ])
    async def rota(self, interaction: discord.Interaction, lane: app_commands.Choice[str]):
        mapa = {"top":"🛡️ Top", "jungle":"🌲 Jungle", "mid":"🧙‍♂️ Mid", "adc":"🏹 ADC", "sup":"❤️ Sup", "fill":"🔄 Fill"}
        atualizar_rota(interaction.user.id, mapa[lane.value])
        await interaction.response.send_message(f"✅ Rota definida: **{mapa[lane.value]}**", ephemeral=True)

    @app_commands.command(name="diario", description="Resgatar bônus diário.")
    async def diario(self, interaction: discord.Interaction):
        sucesso, msg = resgatar_diario(interaction.user.id)
        await interaction.response.send_message(msg, ephemeral=not sucesso)

    @app_commands.command(name="ranking", description="Veja o Top Jogadores.")
    async def ranking(self, interaction: discord.Interaction):
        view = RankingView(modo_inicial="sr")
        embed = discord.Embed(title="🗺️ Ranking - SUMMONER'S RIFT", color=0xffd700)
        top = get_ranking_paginado("sr", 0, 10)
        txt = ""
        for i, p in enumerate(top):
            medalha = "👑" if i == 0 else f"`{i+1}º`"
            txt += f"{medalha} **{p['nick']}** — {p.get('pdl', 1000)} PDL\n"
        embed.description = txt if txt else "Vazio."
        embed.set_footer(text=f"Página 1 • Total: {view.total_jogadores}")
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="perfil", description="Ver perfil completo.")
    async def perfil(self, interaction: discord.Interaction, membro: discord.Member = None):
        alvo = membro or interaction.user
        d = get_jogador(alvo.id)
        if not d: return await interaction.response.send_message("Não registrado.", ephemeral=True)
        embed = discord.Embed(title=f"📊 Perfil de {d['nick']}", color=0x2ecc71)
        sr, aram, arena = d.get('pdl', 1000), d.get('pdl_aram', 1000), d.get('pdl_arena', 1000)
        embed.add_field(name="Summoner's Rift", value=f"{get_icone_elo(sr)} **{sr}** PDL", inline=True)
        embed.add_field(name="ARAM", value=f"{get_icone_elo(aram)} **{aram}** PDL", inline=True)
        embed.add_field(name="Arena", value=f"{get_icone_elo(arena)} **{arena}** PDL", inline=True)
        embed.add_field(name="Rota", value=d.get('rota', 'Fill'), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="historico_player", description="Histórico pessoal.")
    async def historico_player(self, interaction: discord.Interaction, membro: discord.Member = None):
        alvo = membro or interaction.user
        d = get_jogador(alvo.id)
        if not d: return await interaction.response.send_message("Não registrado.", ephemeral=True)
        partidas = get_historico_pessoal(d['nick'])
        if not partidas: return await interaction.response.send_message(f"Sem histórico.", ephemeral=True)
        embed = discord.Embed(title=f"📜 Histórico de {d['nick']}", color=0x9b59b6)
        for p in partidas:
            time = "Azul" if d['nick'] in p['azul'] else "Vermelho"
            vitoria = (time.lower() == p['vencedor'])
            emoji = "✅" if vitoria else "❌"
            data = p['data'].strftime("%d/%m")
            embed.add_field(name=f"{emoji} {p.get('modo','sr').upper()} ({data})", value=f"Time: {time}", inline=False)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Geral(bot))
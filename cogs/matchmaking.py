import discord
from discord import app_commands
from discord.ext import commands
from database import get_dados_varios
from utils import get_icone_modo
import datetime

class Matchmaking(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log_channel_name = "logs-inhouse"
        self.category_name = "🏆 Partidas Inhouse"

    async def criar_canais_voz(self, guild, azul, verm):
        cat = discord.utils.get(guild.categories, name=self.category_name)
        if not cat: cat = await guild.create_category(self.category_name)
        
        perms_base = {guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True, connect=True)}
        
        ov_azul = perms_base.copy()
        for m in azul: ov_azul[m] = discord.PermissionOverwrite(view_channel=True, connect=True)
        
        ov_verm = perms_base.copy()
        for m in verm: ov_verm[m] = discord.PermissionOverwrite(view_channel=True, connect=True)
        
        c1 = await guild.create_voice_channel("🟦 Time Azul", category=cat, overwrites=ov_azul)
        c2 = await guild.create_voice_channel("🟥 Time Vermelho", category=cat, overwrites=ov_verm)
        
        for m in azul: 
            if m.voice: await m.move_to(c1)
        for m in verm:
            if m.voice: await m.move_to(c2)
        return [c1, c2]

    @app_commands.command(name="start", description="Inicia partida (Requer Fila cheia ou Admin).")
    @app_commands.choices(
        modo=[app_commands.Choice(name="Summoner's Rift", value="sr"), app_commands.Choice(name="ARAM", value="aram"), app_commands.Choice(name="Arena", value="arena")], 
        tipo=[app_commands.Choice(name="Blind", value="Blind"), app_commands.Choice(name="Draft", value="Draft"), app_commands.Choice(name="Tournament", value="Tournament")]
    )
    async def start(self, interaction: discord.Interaction, modo: app_commands.Choice[str], tipo: app_commands.Choice[str], nome_sala: str, senha: str = "123", valendo_pdl: bool = True):
        fila = self.bot.fila
        is_admin = interaction.user.guild_permissions.administrator
        
        if len(fila) < 2 and not is_admin:
            return await interaction.response.send_message("❌ Mínimo 2 jogadores.", ephemeral=True)
        if len(fila) % 2 != 0:
            return await interaction.response.send_message(f"❌ Número ímpar ({len(fila)}).", ephemeral=True)

        await interaction.response.defer()
        
        corte = 10 if len(fila) >= 10 else len(fila)
        players = fila[:corte]
        self.bot.fila = fila[corte:] 
        self.bot.ultimo_movimento_fila = datetime.datetime.now()

        ids = [p.id for p in players]
        dados = get_dados_varios(ids)
        mapa = {str(d['_id']): d for d in dados}
        campo_pdl = 'pdl' if modo.value == 'sr' else f'pdl_{modo.value}'
        
        ordenados = sorted(players, key=lambda p: mapa.get(str(p.id), {}).get(campo_pdl, 1000), reverse=True)
        azul, verm = [], []
        for i, p in enumerate(ordenados):
            if i % 4 == 0 or i % 4 == 3: azul.append(p)
            else: verm.append(p)

        canais = await self.criar_canais_voz(interaction.guild, azul, verm)

        # SALVANDO INICIO PARA CALCULAR DURAÇÃO
        self.bot.partida_atual = {
            'azul': azul, 'vermelho': verm, 
            'modo': modo.value, 'valendo': valendo_pdl, 
            'canais': canais,
            'inicio': datetime.datetime.now()
        }

        embed = discord.Embed(title=f"{get_icone_modo(modo.value)} Partida Iniciada: {modo.value.upper()}", color=0x0099ff)
        embed.add_field(name="🏠 Sala", value=f"Nome: `{nome_sala}`\nSenha: `{senha}`", inline=False)
        
        def fmt(lista):
            t = ""
            for p in lista:
                d = mapa.get(str(p.id), {})
                t += f"**{d.get('nick', p.display_name)}** ({d.get(campo_pdl, 1000)})\n"
            return t
            
        embed.add_field(name="🟦 AZUL", value=fmt(azul), inline=True)
        embed.add_field(name="🟥 VERMELHO", value=fmt(verm), inline=True)
        if canais: embed.add_field(name="🔊 Voz", value=f"{canais[0].mention} | {canais[1].mention}", inline=False)
        
        await interaction.followup.send(embed=embed)
        for p in players:
            try: await p.send(f"🎮 **Partida Iniciada!**\nSala: `{nome_sala}`\nSenha: `{senha}`")
            except: pass

async def setup(bot):
    await bot.add_cog(Matchmaking(bot))
import discord
from discord.ext import commands, tasks
import os
import datetime
from server import keep_alive
from views import FilaView

TOKEN = os.environ.get('TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

# Classe personalizada do Bot para guardar variáveis globais
class InhouseBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.remove_command('help')
        
        # Variáveis Globais acessíveis em todos os Cogs via self.bot.fila ou interaction.client.fila
        self.fila = []
        self.partida_atual = None
        self.ultimo_movimento_fila = datetime.datetime.now()

    async def setup_hook(self):
        # Carrega os Cogs (arquivos da pasta cogs)
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.geral")
        await self.load_extension("cogs.matchmaking")
        
        # Persiste a view da Fila
        self.add_view(FilaView())
        
        # Sincroniza comandos Slash
        await self.tree.sync()

bot = InhouseBot()

@tasks.loop(minutes=5)
async def checar_afk():
    if not bot.fila or bot.partida_atual: return
    if datetime.datetime.now() - bot.ultimo_movimento_fila > datetime.timedelta(minutes=60):
        bot.fila.clear()
        print("🧹 Fila limpa por inatividade.")

@bot.event
async def on_ready():
    print(f'✅ {bot.user} está online!')
    if not checar_afk.is_running():
        checar_afk.start()

keep_alive()
bot.run(TOKEN)
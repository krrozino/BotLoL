import os
from pymongo import MongoClient
from datetime import datetime, date

MONGO_URL = os.environ.get('MONGO_URL')

if MONGO_URL:
    cluster = MongoClient(MONGO_URL)
    db = cluster["InhouseBot"]
    collection = db["Jogadores"]
else:
    print("⚠️ AVISO: MONGO_URL não encontrada.")
    collection = None

col_partidas = db["Partidas"]

# --- FUNÇÕES ---

def get_jogador(user_id):
    if collection is None: return None
    return collection.find_one({"_id": str(user_id)})

def criar_jogador(user_id, nick, opgg):
    if collection is None: return
    # Inicializa com PDL base para TODOS os modos
    collection.insert_one({
        "_id": str(user_id),
        "nick": nick,
        "opgg": opgg,
        "pdl": 1000,        # Summoner's Rift
        "pdl_aram": 1000,   # ARAM
        "pdl_arena": 1000,  # Arena
        "vitorias": 0, "derrotas": 0, # Stats Gerais (ou pode separar se quiser)
        "mvps": 0
    })

# Agora aceita o argumento 'modo'
def atualizar_pdl(user_id, pdl_base, vitoria, modo="sr"):
    if collection is None: return
    
    # Define qual campo do banco vamos mexer
    campo_pdl = "pdl" # Default SR
    if modo == "aram": campo_pdl = "pdl_aram"
    if modo == "arena": campo_pdl = "pdl_arena"

    jogador = get_jogador(user_id)
    # Se o jogador for antigo e não tiver o campo novo, assume 1000
    pdl_atual = jogador.get(campo_pdl, 1000)
    
    # Lógica de Streak (Simplificada para o exemplo)
    streak_atual = jogador.get("streak", 0)
    bonus = 0
    
    if vitoria:
        novo_streak = streak_atual + 1
        if novo_streak >= 3: bonus = 5
    else:
        novo_streak = 0
    
    pdl_final = pdl_base + bonus

    # Atualiza o campo dinamicamente
    update_query = {
        "$inc": {campo_pdl: pdl_final, "vitorias": 1 if vitoria else 0, "derrotas": 0 if vitoria else 1},
        "$set": {"streak": novo_streak}
    }
    
    # Se o campo não existia antes, o $inc cria ele automaticamente? 
    # No Mongo sim, mas se basear no get anterior é mais seguro garantir.
    collection.update_one({"_id": str(user_id)}, update_query)
    
    # Verifica se ficou negativo
    novo_dado = get_jogador(user_id)
    if novo_dado.get(campo_pdl, 1000) < 0:
        collection.update_one({"_id": str(user_id)}, {"$set": {campo_pdl: 0}})
    
    return bonus

def get_ranking(modo="sr", rota_filtro=None):
    if collection is None: return []
    
    # Define qual PDL usar para ordenar
    campo_sort = "pdl"
    if modo == "aram": campo_sort = "pdl_aram"
    if modo == "arena": campo_sort = "pdl_arena"

    query = {}
    if rota_filtro and modo == "sr": # Rota só faz sentido no SR
        query["rota"] = rota_filtro

    # Retorna ordenado pelo PDL do modo escolhido
    return list(collection.find(query).sort(campo_sort, -1).limit(10))

# --- Mantenha as outras funções (editar_perfil, set_pdl_manual, etc) iguais ---
# Apenas certifique-se de importar tudo no main.py
def atualizar_rota(user_id, rota):
    if collection is None: return
    collection.update_one({"_id": str(user_id)}, {"$set": {"rota": rota}})

def editar_perfil(user_id, campo, valor):
    if collection is None: return
    collection.update_one({"_id": str(user_id)}, {"$set": {campo: valor}})

def set_pdl_manual(user_id, valor):
    if collection is None: return
    # Por padrão edita o SR, se quiser editar outros precisa adaptar o comando admin
    collection.update_one({"_id": str(user_id)}, {"$set": {"pdl": int(valor)}})

def get_dados_varios(lista_ids):
    if collection is None: return []
    lista_str = [str(i) for i in lista_ids]
    return list(collection.find({"_id": {"$in": lista_str}}))

def adicionar_mvp(user_id):
    if collection is None: return
    collection.update_one({"_id": str(user_id)}, {"$inc": {"mvps": 1}})

def resgatar_diario(user_id):
    if collection is None: return False, "Erro no Banco"
    hoje = str(date.today())
    jogador = collection.find_one({"_id": str(user_id)})
    if not jogador: return False, "Registre-se primeiro!"
    if jogador.get("ultimo_diario") == hoje: return False, "Já resgatou hoje!"
    
    # Dá PDL para o SR (padrão) ou distribui um pouco pra cada? Vamos dar pro SR por enquanto
    collection.update_one({"_id": str(user_id)}, {"$inc": {"pdl": 10}, "$set": {"ultimo_diario": hoje}})
    return True, "Resgatado com sucesso!"

def salvar_historico(time_vencedor, azul_nomes, vermelho_nomes, modo="sr"):
    if col_partidas is None: return
    col_partidas.insert_one({
        "data": datetime.now(),
        "vencedor": time_vencedor,
        "azul": azul_nomes,
        "vermelho": vermelho_nomes,
        "modo": modo
    })

def get_ultimas_partidas():
    if col_partidas is None: return []
    return list(col_partidas.find().sort("data", -1).limit(5))
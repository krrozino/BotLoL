import os
from pymongo import MongoClient
from datetime import datetime, date, timedelta

MONGO_URL = os.environ.get('MONGO_URL')

collection = None
col_partidas = None

if MONGO_URL:
    try:
        cluster = MongoClient(MONGO_URL)
        db = cluster["InhouseBot"]
        collection = db["Jogadores"]
        col_partidas = db["Partidas"]
        print("✅ Conectado ao MongoDB com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao conectar no MongoDB: {e}")
else:
    print("⚠️ AVISO: MONGO_URL não encontrada.")

# --- FUNÇÕES BÁSICAS ---

def get_jogador(user_id):
    if collection is None: return None
    return collection.find_one({"_id": str(user_id)})

def criar_jogador(user_id, nick, opgg):
    if collection is None: return
    try:
        collection.insert_one({
            "_id": str(user_id),
            "nick": nick,
            "opgg": opgg,
            "pdl": 1000,        # Summoner's Rift
            "pdl_aram": 1000,   # ARAM
            "pdl_arena": 1000,  # Arena
            "vitorias": 0, "derrotas": 0, 
            "mvps": 0,
            "banido_ate": None,
            "ultimo_diario": None
        })
    except Exception as e:
        print(f"Erro ao criar jogador: {e}")

def atualizar_pdl(user_id, pdl_base, vitoria, modo="sr"):
    """
    Atualiza o PDL baseado no modo de jogo (sr, aram, arena).
    """
    if collection is None: return 0
    
    # Define qual campo editar baseado no modo
    campo_pdl = "pdl" 
    if modo == "aram": campo_pdl = "pdl_aram"
    if modo == "arena": campo_pdl = "pdl_arena"

    jogador = get_jogador(user_id)
    if not jogador: return 0

    # Pega o valor atual, garantindo que exista (fallback para 1000)
    pdl_atual_banco = jogador.get(campo_pdl, 1000)
    streak_atual = jogador.get("streak", 0)
    bonus = 0
    
    if vitoria:
        novo_streak = streak_atual + 1
        if novo_streak >= 3: bonus = 5
    else:
        novo_streak = 0
    
    pdl_final = pdl_base + bonus

    update_query = {
        "$inc": {campo_pdl: pdl_final, "vitorias": 1 if vitoria else 0, "derrotas": 0 if vitoria else 1},
        "$set": {"streak": novo_streak}
    }
    
    collection.update_one({"_id": str(user_id)}, update_query)
    
    # Verifica se ficou negativo
    novo_dado = get_jogador(user_id)
    if novo_dado and novo_dado.get(campo_pdl, 1000) < 0:
        collection.update_one({"_id": str(user_id)}, {"$set": {campo_pdl: 0}})
    
    return bonus

# --- ADMIN E LISTAGEM ---

def get_todos_jogadores_paginado(skip=0, limit=10):
    """Retorna lista de jogadores para o admin (paginada)."""
    if collection is None: return []
    return list(collection.find().sort("nick", 1).skip(skip).limit(limit))

def contar_jogadores():
    if collection is None: return 0
    return collection.count_documents({})

def get_ranking_paginado(modo="sr", skip=0, limit=10):
    if collection is None: return []
    campo_sort = "pdl"
    if modo == "aram": campo_sort = "pdl_aram"
    if modo == "arena": campo_sort = "pdl_arena"
    
    return list(collection.find().sort(campo_sort, -1).skip(skip).limit(limit))

# --- OUTRAS FUNÇÕES (MANTIDAS) ---

def aplicar_punicao(user_id, pdl_multa, minutos_ban):
    if collection is None: return
    desbanir_em = datetime.now() + timedelta(minutes=minutos_ban)
    collection.update_one(
        {"_id": str(user_id)},
        {"$inc": {"pdl": -pdl_multa}, "$set": {"banido_ate": desbanir_em}}
    )

def checar_banimento(user_id):
    if collection is None: return False, None
    user = collection.find_one({"_id": str(user_id)})
    if not user: return False, None
    ban_ate = user.get("banido_ate")
    if ban_ate and ban_ate > datetime.now():
        restante = ban_ate - datetime.now()
        minutos = int(restante.total_seconds() / 60) + 1
        return True, f"{minutos} min"
    return False, None

def get_historico_pessoal(nick):
    if col_partidas is None: return []
    query = {"$or": [{"azul": nick}, {"vermelho": nick}]}
    return list(col_partidas.find(query).sort("data", -1).limit(5))

def atualizar_rota(user_id, rota):
    if collection is None: return
    collection.update_one({"_id": str(user_id)}, {"$set": {"rota": rota}})

def editar_perfil(user_id, campo, valor):
    if collection is None: return
    collection.update_one({"_id": str(user_id)}, {"$set": {campo: valor}})

def set_pdl_manual(user_id, valor, modo="sr"):
    if collection is None: return
    campo = "pdl"
    if modo == "aram": campo = "pdl_aram"
    if modo == "arena": campo = "pdl_arena"
    collection.update_one({"_id": str(user_id)}, {"$set": {campo: int(valor)}})

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
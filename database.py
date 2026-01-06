import os
from pymongo import MongoClient
from datetime import datetime, date, timedelta
import random

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
            "streak": 0,        # Positivo = Win Streak, Negativo = Lose Streak
            "banido_ate": None,
            "ultimo_diario": None
        })
    except Exception as e:
        print(f"Erro ao criar jogador: {e}")

def atualizar_pdl(user_id, vitoria, modo="sr"):
    """
    Calcula PDL entre 26 e 35 influenciado pela Streak.
    Retorna o valor exato da mudança (inteiro positivo).
    """
    if collection is None: return 0
    
    campo_pdl = "pdl" 
    if modo == "aram": campo_pdl = "pdl_aram"
    if modo == "arena": campo_pdl = "pdl_arena"

    jogador = get_jogador(user_id)
    if not jogador: return 0

    streak_atual = jogador.get("streak", 0)
    
    # --- CÁLCULO DINÂMICO DE PDL ---
    min_pdl, max_pdl = 26, 35
    valor_final = 0

    if vitoria:
        # Atualiza Streak: se estava negativo, reseta para 1. Se positivo, soma.
        novo_streak = 1 if streak_atual < 0 else streak_atual + 1
        
        # Win Streak (>= 3): Chance maior de ganhar MAIS (Moda no 35)
        if novo_streak >= 3:
            valor_final = int(random.triangular(min_pdl, max_pdl, max_pdl))
        # Recuperando de Lose Streak (<= -3): Ganha MENOS (Moda no 26)
        elif streak_atual <= -3:
            valor_final = int(random.triangular(min_pdl, max_pdl, min_pdl))
        else:
            valor_final = random.randint(min_pdl, max_pdl)
            
    else: # Derrota
        # Atualiza Streak: se estava positivo, reseta para -1. Se negativo, subtrai.
        novo_streak = -1 if streak_atual > 0 else streak_atual - 1
        
        # Lose Streak (<= -3): Chance maior de perder MAIS (Moda no 35)
        if novo_streak <= -3:
            valor_final = int(random.triangular(min_pdl, max_pdl, max_pdl))
        # Proteção de Win Streak (>= 3): Perde MENOS (Moda no 26)
        elif streak_atual >= 3:
            valor_final = int(random.triangular(min_pdl, max_pdl, min_pdl))
        else:
            valor_final = random.randint(min_pdl, max_pdl)

    # Aplica no banco
    fator = 1 if vitoria else -1
    mudanca_real = valor_final * fator

    update_query = {
        "$inc": {campo_pdl: mudanca_real, "vitorias": 1 if vitoria else 0, "derrotas": 0 if vitoria else 1},
        "$set": {"streak": novo_streak}
    }
    
    collection.update_one({"_id": str(user_id)}, update_query)
    
    # Evita PDL negativo
    novo_dado = get_jogador(user_id)
    if novo_dado and novo_dado.get(campo_pdl, 1000) < 0:
        collection.update_one({"_id": str(user_id)}, {"$set": {campo_pdl: 0}})
    
    return valor_final

# --- ADMIN E LISTAGEM ---

def get_todos_jogadores_paginado(skip=0, limit=10):
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

# --- UTILS DB ---

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
    # Mantendo compatibilidade com código antigo se necessário
    if col_partidas is None: return
    col_partidas.insert_one({
        "data": datetime.now(),
        "vencedor": time_vencedor,
        "azul": azul_nomes,
        "vermelho": vermelho_nomes,
        "modo": modo
    })

def salvar_historico_db(dados_partida):
    """Função nova para salvar o log detalhado (duração, etc)"""
    if col_partidas is None: return
    col_partidas.insert_one(dados_partida)
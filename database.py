import os
from pymongo import MongoClient

# Pega o link das variáveis de ambiente
MONGO_URL = os.environ.get('MONGO_URL')

# Conexão (Se não tiver link, não quebra o código local, mas avisa)
if MONGO_URL:
    cluster = MongoClient(MONGO_URL)
    db = cluster["InhouseBot"]
    collection = db["Jogadores"]
else:
    print("⚠️ AVISO: MONGO_URL não encontrada. O banco não vai funcionar.")
    collection = None

# --- FUNÇÕES ---

def get_jogador(user_id):
    if collection is None: return None
    return collection.find_one({"_id": str(user_id)})

def criar_jogador(user_id, nick, opgg):
    if collection is None: return
    collection.insert_one({
        "_id": str(user_id),
        "nick": nick,
        "opgg": opgg,
        "pdl": 1000,
        "vitorias": 0,
        "derrotas": 0
    })

def atualizar_pdl(user_id, pdl_mudanca, vitoria):
    if collection is None: return
    # $inc aumenta ou diminui o valor
    update_query = {
        "$inc": {"pdl": pdl_mudanca, "vitorias": 1 if vitoria else 0, "derrotas": 0 if vitoria else 1}
    }
    collection.update_one({"_id": str(user_id)}, update_query)
    
    # Garante que não fique negativo
    jogador = get_jogador(user_id)
    if jogador and jogador["pdl"] < 0:
        collection.update_one({"_id": str(user_id)}, {"$set": {"pdl": 0}})
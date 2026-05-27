import json
import sqlite3
import requests
import time
import os
from datetime import datetime, timedelta
import calendar
import unicodedata

# --- CONFIGURAÇÕES ---
BASE_URL = "https://dadosabertos.camara.leg.br/api/v2"
ANOS_MONITORADOS = [2023, 2024, 2025]
ARQUIVO_CACHE = "catalogo_votacoes.json"
ARQUIVO_DB = "tabelao.db"

# --- 1. PREPARAÇÃO DO BANCO DE DADOS ---
def criar_banco():
    print(f"\n[BANCO] Conectando ao banco '{ARQUIVO_DB}'...")
    conn = sqlite3.connect(ARQUIVO_DB)
    cursor = conn.cursor()
    
    # Limpa a tabela para garantir que não haja duplicatas se rodar várias vezes
    cursor.execute("DROP TABLE IF EXISTS votos") 
    
    # Cria a tabela definitiva
    cursor.execute('''
    CREATE TABLE votos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        projeto_nome TEXT,
        deputado_nome TEXT,
        partido TEXT,
        uf TEXT,
        voto TEXT,
        data_votacao TEXT,
        id_votacao_api TEXT,
        descricao_votacao TEXT
    )
    ''')
    conn.commit()
    return conn

def normalizar(texto):
    if not texto: return ""
    return unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('ASCII').upper()

# --- 2. SISTEMA DE CACHE (BAIXA TUDO UMA VEZ SÓ) ---
def baixar_catalogo_votacoes():
    # Verifica se o cache já existe
    if os.path.exists(ARQUIVO_CACHE):
        print(f"[CACHE] Carregando catálogo de '{ARQUIVO_CACHE}'...")
        try:
            with open(ARQUIVO_CACHE, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            print(f"        -> {len(dados)} votações carregadas.")
            return dados
        except:
            print("        -> Cache corrompido. Baixando novamente.")

    print("[API] Baixando catálogo de votações (2021-2025)...")
    todas_votacoes = []
    sessao = requests.Session()
    sessao.headers.update({'User-Agent': 'Mozilla/5.0 (script-monitoramento)'})
    
    for ano in ANOS_MONITORADOS:
        print(f"      -> Ano {ano}...", end=" ")
        for mes in range(1, 13):
            ultimo_dia = calendar.monthrange(ano, mes)[1]
            inicio = f"{ano}-{mes:02d}-01"
            fim = f"{ano}-{mes:02d}-{ultimo_dia}"
            pagina = 1
            while True:
                try:
                    url = f"{BASE_URL}/votacoes?dataInicio={inicio}&dataFim={fim}&ordenarPor=dataHoraRegistro&ordem=DESC&itens=200&pagina={pagina}"
                    r = sessao.get(url, timeout=20)
                    if r.status_code != 200: break
                    dados = r.json().get('dados', [])
                    if not dados: break 
                    todas_votacoes.extend(dados)
                    pagina += 1
                    time.sleep(0.05)
                except:
                    break
            print(".", end="", flush=True)
    
    print(f"\n      -> Salvando cache em '{ARQUIVO_CACHE}'...")
    with open(ARQUIVO_CACHE, 'w', encoding='utf-8') as f:
        json.dump(todas_votacoes, f, ensure_ascii=False, indent=2)
        
    return todas_votacoes

# --- 3. LÓGICA DE MATCH E SALVAMENTO ---
def baixar_votos_detalhados(id_votacao):
    url = f"{BASE_URL}/votacoes/{id_votacao}/votos"
    try:
        r = requests.get(url, timeout=15)
        return r.json().get('dados', [])
    except:
        return []

def encontrar_e_salvar_melhor_match(conn, catalogo, projeto):
    nome = projeto['nome_popular']
    data_str = projeto.get('data_busca')
    keywords = projeto.get('palavras_chave', [])
    
    if not data_str: return

    data_alvo = datetime.strptime(data_str, "%Y-%m-%d")
    janela_inicio = (data_alvo - timedelta(days=2)).strftime("%Y-%m-%d")
    janela_fim = (data_alvo + timedelta(days=2)).strftime("%Y-%m-%d")
    
    # Filtra candidatos
    candidatos = [v for v in catalogo if v['data'] >= janela_inicio and v['data'] <= janela_fim]
    finais = []

    for v in candidatos:
        desc = normalizar(v.get('descricao', '') + " " + v.get('uri', ''))
        match = False
        for k in keywords:
            if normalizar(k) in desc:
                match = True
                break
        if match:
            if "ENCERRAMENTO" in desc or "ADIAMENTO" in desc: continue
            finais.append(v)

    if not finais:
        print(f"    [X] Nenhuma votação encontrada.")
        return

    # Escolhe a votação com MAIS VOTOS (Vence a Simbólica)
    melhor_votacao = None
    melhores_votos = []
    maior_qtd = 0

    print(f"    [?] Analisando {len(finais)} candidatas...")
    for cand in finais:
        votos = baixar_votos_detalhados(cand['id'])
        if len(votos) > maior_qtd:
            maior_qtd = len(votos)
            melhor_votacao = cand
            melhores_votos = votos
            print(f"        -> Lider: ID {cand['id']} ({len(votos)} votos)")

    # SALVA NO TABELAO.DB
    if melhor_votacao and melhores_votos:
        print(f"    [V] VENCEDOR: {melhor_votacao['id']} com {len(melhores_votos)} votos.")
        
        cursor = conn.cursor()
        for v in melhores_votos:
            dep = v.get('deputado_', v)
            cursor.execute('''
                INSERT INTO votos (projeto_nome, deputado_nome, partido, uf, voto, data_votacao, id_votacao_api, descricao_votacao)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                nome, 
                dep.get('nome'), 
                dep.get('siglaPartido'), 
                dep.get('siglaUf'), 
                v.get('tipoVoto') or v.get('voto'), 
                data_str, 
                melhor_votacao['id'], 
                melhor_votacao.get('descricao', '')
            ))
        conn.commit()
        print("        -> Dados gravados no tabelao.db")
    else:
        print("    [!] Apenas votações simbólicas encontradas.")

# --- 4. EXECUÇÃO ---
def processar():
    try:
        with open('lei.json', 'r', encoding='utf-8') as f:
            projetos = json.load(f)
    except:
        print("ERRO: lei.json não encontrado.")
        return

    conn = criar_banco()
    catalogo = baixar_catalogo_votacoes()
    
    if not catalogo: return

    print("\n=== INICIANDO PROCESSAMENTO ===")
    for proj in projetos:
        print(f"\nProjeto: {proj['nome_popular']}")
        encontrar_e_salvar_melhor_match(conn, catalogo, proj)
        time.sleep(0.2)
        
    # VERIFICAÇÃO FINAL
    c = conn.cursor()
    c.execute("SELECT count(*), projeto_nome FROM votos GROUP BY projeto_nome")
    resumo = c.fetchall()
    print("\n=== RESUMO DO BANCO (tabelao.db) ===")
    print(f"{'PROJETO':<40} | {'VOTOS SALVOS'}")
    print("-" * 60)
    for row in resumo:
        print(f"{row[1][:40]:<40} | {row[0]}")
    
    conn.close()

if __name__ == "__main__":
    processar()
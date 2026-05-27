import sqlite3
import requests
import json
import os
import time
import hashlib
import re # Importante para Regex
from datetime import datetime
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from openai import OpenAI
from tqdm import tqdm
import signal # Added for graceful shutdown

# ==============================================================================
# SEGURANÇA E CHECKPOINT SYSTEM
# ==============================================================================

class CheckpointManager:
    def __init__(self, filepath="checkpoint.json"):
        self.filepath = filepath
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    return json.load(f)
            except:
                return {"completed_months": {}}
        return {"completed_months": {}}

    def _save(self):
        with open(self.filepath, 'w') as f:
            json.dump(self.data, f, indent=4)

    def is_month_completed(self, year, month):
        key = f"{year}-{month:02d}"
        last_check = self.data["completed_months"].get(key)
        if not last_check:
            return False
            
        # Opcional: Re-verificar se faz mais de X dias? 
        # Por enquanto, se está marcado como completo, confiamos (para performance)
        # Se quiser forçar, o usuário apaga o json.
        return True

    def mark_month_completed(self, year, month):
        key = f"{year}-{month:02d}"
        self.data["completed_months"][key] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._save()
        # print(f"   🔒 Checkpoint: {key} salvo como completo.")

class GracefulKiller:
    kill_now = False
    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, *args):
        self.kill_now = True
        print("\n\n🛑  SINAL DE PARADA RECEBIDO! Salvando estado e encerrando com segurança...\n")

# ==============================================================================
# CONFIGURAÇÃO E CONSTANTES
# ==============================================================================
load_dotenv()
CAMARA_API_BASE = "https://dadosabertos.camara.leg.br/api/v2"
DB_PATH = "tabelao.db"
DISCURSOS_DB_PATH = "discursos.db" # Added for context search
VAULT_TABLE = "votacoes_raw_vault"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("⚠️  AVISO: OPENAI_API_KEY não encontrada. Funcionalidades de IA serão limitadas.")
    client = None
else:
    client = OpenAI(api_key=OPENAI_API_KEY)

# ==============================================================================
# CAMADA 1: DATA VAULT (SEGURANÇA E INTEGRIDADE)
# ==============================================================================
def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabela de Auditoria (Cofre)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS votacoes_raw_vault (
        id_votacao TEXT,
        tipo_dado TEXT, 
        raw_json TEXT,
        source_url TEXT,
        sha256_hash TEXT,
        fetched_at DATETIME,
        api_status_code INTEGER,
        PRIMARY KEY (id_votacao, tipo_dado)
    )
    """)

    # Tabela de Apresentação (UI)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS votacoes_destaque (
        id_votacao TEXT PRIMARY KEY,
        uri TEXT,
        data TEXT,
        sigla_orgao TEXT,
        proposicao TEXT,
        resumo_camara TEXT,
        cobertura_midia INTEGER,
        resumo_midia TEXT,
        posicao_midia TEXT,
        links_noticias TEXT,
        simbolica INTEGER, -- 0=Nominal, 1=Simbólica, 2=Nominal Agregada
        atualizado_em TEXT,
        url_proposicao TEXT,
        hash_integridade TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS votos_destaque_detalhe (
        id_votacao TEXT,
        nome_deputado TEXT,
        partido TEXT,
        uf TEXT,
        voto TEXT,
        id_deputado INTEGER,
        FOREIGN KEY (id_votacao) REFERENCES votacoes_destaque(id_votacao)
    )
    """)
    conn.commit()
    conn.close()

def compute_hash(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def secure_fetch_and_vault(id_votacao, sub_resource=None):
    """
    1. Tenta ler do Vault (Cache/Offline Mode).
    2. Se não existir, baixa da API e salva no Vault.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    resource_type = 'detalhe' if sub_resource is None else sub_resource
    
    # 1. Check Cache First (Optimzed)
    cursor.execute("SELECT raw_json, sha256_hash, api_status_code FROM votacoes_raw_vault WHERE id_votacao = ? AND tipo_dado = ?", (id_votacao, resource_type))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        raw_json, sha256_hash, status_code = row
        cached_data = json.loads(raw_json)
        
        # Se for um 404 cacheado, não tenta de novo
        if status_code == 404:
            return None, None
            
        # Se o cache tiver dados válidos, retorna
        if cached_data and len(cached_data) > 0: 
            return cached_data, sha256_hash
        
        # Caso contrário (cache vazio mas não 404), tenta baixar novamente
        print(f"   ⚠️ Cache de {id_votacao} ({resource_type}) parece incompleto. Tentando baixar...")

    # 2. Download from Network
    url = f"{CAMARA_API_BASE}/votacoes/{id_votacao}"
    if sub_resource: url += f"/{sub_resource}"
    
    conn = get_db_connection() # Reabre para salvar
    cursor = conn.cursor()
    
    try:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"   🌍 Baixando {url} (Tentativa {attempt+1})...")
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    raw_text = resp.text
                    new_hash = compute_hash(raw_text)
                    
                    cursor.execute("""
                    INSERT OR REPLACE INTO votacoes_raw_vault 
                    (id_votacao, tipo_dado, raw_json, source_url, sha256_hash, fetched_at, api_status_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (id_votacao, resource_type, raw_text, url, new_hash, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), resp.status_code))
                    conn.commit()
                    conn.close()
                    return json.loads(raw_text), new_hash
                elif resp.status_code == 404:
                    # Recurso não existe (ex: não tem lista de votos ou orientações)
                    cursor.execute("""
                    INSERT OR REPLACE INTO votacoes_raw_vault 
                    (id_votacao, tipo_dado, raw_json, source_url, sha256_hash, fetched_at, api_status_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (id_votacao, resource_type, "{}", url, "EMPTY", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 404))
                    conn.commit()
                    conn.close()
                    return None, None
                else:
                    time.sleep(2)
            except:
                time.sleep(2)
    except Exception as e:
        print(f"   ❌ Erro de Rede: {e}")
        
    conn.close()
    return None, None

# ==============================================================================
# CAMADA 2: LÓGICA DE NEGÓCIO E MÍDIA
# ==============================================================================

def check_media_coverage(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(f"{query} votação câmara aprovada notícia", region="br-pt", max_results=3))
            if results:
                links = [r['href'] for r in results]
                snippets = "\n".join([f"- {r['title']}: {r['body']}" for r in results])
                return True, snippets, json.dumps(links)
    except:
        pass
    return False, "", "[]"

def analyze_media_with_ai(snippets, proposicao, contexto_politico=""):
    prompt = f"""
    Analise esta votação legislativa da Câmara dos Deputados: "{proposicao}".
    
    CONTEXTO POLÍTICO (Orientações Partidárias):
    {contexto_politico}
    
    NOTÍCIAS E MÍDIA:
    {snippets}
    
    TAREFA:
    1. Crie um "RESUMO DA VOTAÇÃO" que explique de forma CLARA e DIRETA o CONTEÚDO da matéria.
       - EVITE FRASES GENÉRICAS como "Mantido o texto" ou "Aprovada a emenda".
       - DIGA O QUE O TEXTO FAZ (Ex: "Aprovado o aumento de pena para crimes de...", "Mantido o veto que impedia...").
    2. Mencione se a votação foi POLÊMICA ou CONSENSUAL baseando-se nas orientações (Ex: Governo e Oposição concordaram? Houve racha?).
    3. Extraia o placar exato se houver nas notícias.
    
    JSON ESPERADO: {{ "resumo": "Texto explicativo rico...", "posicao": "Favorável/Contrário/Misto (Mídia)" }}
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        content = json.loads(resp.choices[0].message.content)
        return content.get("resumo", ""), content.get("posicao", "Neutro")
    except:
        return "", "Erro"

def determine_vote_type(votos_list, text_summary):
    """
    Lógica Central de Classificação.
    Retorna: (Inteiro Simbolica, String Explicação)
    0 = Nominal (API tem lista)
    1 = Simbólica (Consenso Real)
    2 = Nominal Agregada (Placar no Texto)
    """
    
    # Regex agressivo para achar contagens
    # Ex: "100 votos", "50 a favor", "Sim: 200", "Não: 20"
    regex_placar = r'(\d{1,4}\s+votos?)|(\d{1,4}\s+a\s+favor)|(\d{1,4}\s+contra)|(placar\s+de\s+\d+)|(Sim:\s*\d{1,4})|(Não:\s*\d{1,4})'
    
    # Se ja temos lista, é nominal com certeza
    if votos_list and len(votos_list) > 0:
        return 0, "Nominal (Lista API)"

    if re.search(regex_placar, text_summary, re.IGNORECASE | re.DOTALL):
        return 2, "Nominal Agregada (Texto)"
        
    # 3. Se não achou nada -> Simbólica
    return 1, "Simbólica"

# ==============================================================================
# CAMADA 3: ORQUESTRADOR
# ==============================================================================

def process_single_vote(id_votacao):
    id_votacao = str(id_votacao).strip()
    # 0. Verificação em Tempo Real (Fail-safe)
    conn = get_db_connection()
    cursor = conn.cursor()
    # Verifica em todas as tabelas possíveis para evitar reprocessamento
    # Incluímos todas as tabelas de destino para garantir 100% de cobertura
    cursor.execute("""
        SELECT 1 FROM votacoes_destaque WHERE id_votacao = ? 
        UNION 
        SELECT 1 FROM votacoes WHERE id_votacao = ?
        UNION
        SELECT 1 FROM votacoes_raw_vault WHERE id_votacao = ?
        UNION
        SELECT 1 FROM votacoes_analise_enrichment WHERE id_votacao = ?
    """, (id_votacao, id_votacao, id_votacao, id_votacao))
    
    res = cursor.fetchone()
    conn.close()
    
    if res:
        # Silenciosamente ignora se já temos dados completos
        return

    print(f"▶️ Processando ID: {id_votacao}")
    
    # 1. Obter Dados Seguros
    data_detalhe, hash_det = secure_fetch_and_vault(id_votacao, None)
    if not data_detalhe:
        print("   ❌ Erro fatal: Sem dados detalhados.")
        return

    dados = data_detalhe.get('dados', {})
    raw_desc = dados.get('descricao', '')
    
    # 2. Buscar Votos (Lista)
    data_votos, _ = secure_fetch_and_vault(id_votacao, 'votos')
    votos_list = data_votos.get('dados', []) if data_votos else []

    # 2.5 EARLY SAVE (Draft) - Para exibir lista imediatamente
    try:
        conn_draft = get_db_connection()
        cursor_draft = conn_draft.cursor()
        
        # Se tem lista, assume Nominal (0) temporariamente para exibir
        # Se não tem, assume Simbólica (1)
        draft_simbolica = 0 if votos_list else 1
        
        cursor_draft.execute("""
        INSERT OR REPLACE INTO votacoes_destaque 
        (id_votacao, uri, data, sigla_orgao, proposicao, resumo_camara, cobertura_midia, resumo_midia, posicao_midia, links_noticias, simbolica, atualizado_em, url_proposicao, hash_integridade)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            id_votacao,
            dados.get('uri', ''),
            dados.get('data', ''),
            dados.get('siglaOrgao', ''),
            raw_desc,
            raw_desc,
            0, # Draft: sem midia ainda
            "", # Draft: sem resumo ainda
            "", # Draft
            "[]", # Draft
            draft_simbolica,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "", 
            hash_det
        ))
        
        if votos_list:
            clean_votos = [(id_votacao, v['deputado_']['nome'], v['deputado_']['siglaPartido'], v['deputado_']['siglaUf'], v.get('tipoVoto','?'), v['deputado_']['id']) for v in votos_list]
            cursor_draft.execute("DELETE FROM votos_destaque_detalhe WHERE id_votacao=?", (id_votacao,))
            cursor_draft.executemany("INSERT INTO votos_destaque_detalhe VALUES (?,?,?,?,?,?)", clean_votos)
            print("   ⚡️ Draft Salvo (Early Save)!")
            
        conn_draft.commit()
        conn_draft.close()
    except Exception as e:
        print(f"   ⚠️ Erro na gravação do Draft: {e}")
    
    # 3. Orientacoes (Novo)
    data_orientacoes, _ = secure_fetch_and_vault(id_votacao, 'orientacoes')
    orientacoes_text = ""
    if data_orientacoes:
        lista_o = data_orientacoes.get('dados', [])
        if lista_o:
            orientacoes_text = ", ".join([f"{o['siglaPartidoBloco']}: {o['orientacaoVoto']}" for o in lista_o])
            print(f"   📢 Orientações: {orientacoes_text[:60]}...")

    # 4. Enriquecimento (Mídia + AI)
    # Importante: Passamos a descrição oficial PARA A BUSCA
    proposicao_final = raw_desc
    
    # NOV: Tentar pegar contexto rico de proposições afetadas
    props_afetadas = dados.get('proposicoesAfetadas', [])
    if props_afetadas and len(props_afetadas) > 0:
        p = props_afetadas[0]
        # Ex: "PL 2162/2023 - Concede anistia..."
        proposicao_final = f"{p.get('siglaTipo')} {p.get('numero')}/{p.get('ano')} - {p.get('ementa')}"
        print(f"   Contexto melhorado: {proposicao_final[:60]}...")
    
    elif proposicao_final == "Votação genérica" or len(proposicao_final) < 20:
        proposicao_final = f"Votação {dados.get('siglaOrgao', '')} {dados.get('data', '')} Câmara"
        
    has_media, snippets, links_json = check_media_coverage(proposicao_final)
    
    resumo_midia = ""
    posicao_midia = ""
    
    if has_media:
        resumo_midia, posicao_midia = analyze_media_with_ai(snippets, proposicao_final, orientacoes_text)
        print("   🧠 AI gerou resumo com sucesso.")
    else:
        # Fallback: Verificar se já existe enriquecimento antigo (votacoes_analise_enrichment)
        try:
            conn_fallback = sqlite3.connect('tabelao.db')
            cursor_fallback = conn_fallback.cursor()
            cursor_fallback.execute("SELECT resumo_leigo FROM votacoes_analise_enrichment WHERE id_votacao = ?", (id_votacao,))
            row_fallback = cursor_fallback.fetchone()
            if row_fallback and row_fallback[0]:
                resumo_midia = row_fallback[0]
                print(f"   ℹ️  Usando resumo legado (Enrichment DB): {resumo_midia[:50]}...")
            conn_fallback.close()
        except:
            pass
    
    # 4. Classificação Híbrida (AQUI ESTÁ A CORREÇÃO VITAL)
    # Juntamos TUDO que temos de texto para procurar números
    full_text_analysis = f"{raw_desc} {resumo_midia} {snippets}" 
    
    tipo_simbolica, explicacao = determine_vote_type(votos_list, full_text_analysis)
    print(f"   ⚖️  Classificação Identificada: {explicacao}")

    # LÓGICA DE INFERÊNCIA SIMBÓLICA (Consenso = Sim)
    if tipo_simbolica == 1 and not votos_list:
        id_evento = dados.get('idEvento')
        if id_evento:
            print(f"   🕵️‍♂️ Votação Simbólica: Buscando presentes no Evento {id_evento} para inferir 'Sim'...")
            try:
                url_presenca = f"{CAMARA_API_BASE}/eventos/{id_evento}/deputados"
                resp_pres = requests.get(url_presenca, timeout=10)
                if resp_pres.status_code == 200:
                    presentes = resp_pres.json().get('dados', [])
                    for dep in presentes:
                        # Cria estrutura compatível com a lista de votos oficial
                        fake_vote = {
                            'deputado_': {
                                'nome': dep.get('nome'),
                                'siglaPartido': dep.get('siglaPartido'),
                                'siglaUf': dep.get('siglaUf'),
                                'id': dep.get('id')
                            },
                            'tipoVoto': 'Sim'
                        }
                        votos_list.append(fake_vote)
                    print(f"   ✅ Consenso Assumido: {len(votos_list)} deputados marcados com 'Sim'.")
                else:
                    print(f"   ⚠️ API de Eventos retornou {resp_pres.status_code}")
            except Exception as e_inf:
                print(f"   ⚠️ Falha na inferência de presença: {e_inf}")

    # 5. Salvar na UI (Tabela Destaque)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 5.1 Salvar na Tabela BASE (votacoes) para compatibilidade com o Frontend
    # Garante que get_votos_lista funcione.
    cursor.execute("""
    INSERT OR REPLACE INTO votacoes (
        id_votacao, data_votacao, sigla_orgao, tipo_votacao, descricao, 
        nome_projeto, numero_pl, objeto_votacao, tema, 
        houve_cobertura, foi_polemico
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        id_votacao,
        dados.get('data', ''),
        dados.get('siglaOrgao', ''),
        explicacao.split('(')[0].strip(), # "Nominal" ou "Simbólica"
        raw_desc,
        proposicao_final, 
        "", 
        raw_desc, 
        "Geral", 
        1 if has_media else 0,
        0
    ))

    # ==========================================================================
    # 6. INTEGRAGACAO IMEDIATA DA IA (Auto-Enrichment)
    # ==========================================================================
    print("   🧠 Executando Análise de IA em tempo real...")
    init_enrichment_table()
    
    ai_result = perform_ai_classification_internal(
        id_votacao, 
        raw_desc, 
        dados.get('siglaOrgao', ''), 
        dados.get('data', ''),
        orientacoes_text,
        proposicao_final
    )
    
    if ai_result:
        tema_macro = ai_result.get('tema_macro', 'Geral')
        pauta_gov = ai_result.get('pauta_governo', 'Indiferente')
        resumo_ai = ai_result.get('resumo_leigo', '')
        
        # 6.1 Salva na tabela de enrichment
        cursor.execute("""
        INSERT OR REPLACE INTO votacoes_analise_enrichment 
        (id_votacao, tema_macro, resumo_leigo, pauta_governo, local_votacao, analise_ia_json, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            id_votacao,
            tema_macro,
            resumo_ai,
            pauta_gov,
            "Câmara dos Deputados",
            json.dumps(ai_result),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))
        
        # 6.2 Atualiza a tabela principal também (para filtros funcionarem já)
        cursor.execute("UPDATE votacoes SET tema = ? WHERE id_votacao = ?", (tema_macro, id_votacao))
        print(f"   ✅ Classificação IA Concluída: {tema_macro} | Gov: {pauta_gov}")
    else:
        print("   ⚠️ Pulei classificação IA (Erro ou sem chave)")
    


    # 5.2 Salvar na Tabela Destaque
    cursor.execute("""
    INSERT OR REPLACE INTO votacoes_destaque 
    (id_votacao, uri, data, sigla_orgao, proposicao, resumo_camara, cobertura_midia, resumo_midia, posicao_midia, links_noticias, simbolica, atualizado_em, url_proposicao, hash_integridade)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        id_votacao,
        dados.get('uri', ''),
        dados.get('data', ''),
        dados.get('siglaOrgao', ''),
        raw_desc,
        raw_desc,
        1 if has_media else 0,
        resumo_midia,
        posicao_midia,
        links_json,
        tipo_simbolica,
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "", # URL Prop (Opcional)
        hash_det
    ))
    
    if votos_list:
        clean_votos = [(id_votacao, v['deputado_']['nome'], v['deputado_']['siglaPartido'], v['deputado_']['siglaUf'], v.get('tipoVoto','?'), v['deputado_']['id']) for v in votos_list]
        cursor.execute("DELETE FROM votos_destaque_detalhe WHERE id_votacao=?", (id_votacao,))
        cursor.executemany("INSERT INTO votos_destaque_detalhe VALUES (?,?,?,?,?,?)", clean_votos)
        
    conn.commit()
    conn.close()
    print("   ✅ Salvo nas tabelas 'votacoes' e 'votacoes_destaque'.")


def main_loop():
    # Loop Principal: Busca índice e processa
    init_db()
    
    killer = GracefulKiller()
    checkpoint_manager = CheckpointManager()
    
    # 1. Identificar Votações Já Processadas (Robusto)
    processed_ids = set()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Lista estendida de tabelas para garantir que nada seja reprocessado
    tables_to_check = [
        "votacoes_destaque", 
        "votacoes", 
        "votacoes_raw_vault", 
        "votacoes_analise_enrichment"
    ]
    
    for table in tables_to_check:
        try:
            cursor.execute(f"SELECT DISTINCT CAST(id_votacao AS TEXT) FROM {table}")
            rows = cursor.fetchall()
            ids = {str(row[0]).strip() for row in rows if row[0]}
            processed_ids.update(ids)
            print(f"   📦 {table}: {len(ids)} registros carregados.")
        except Exception as e:
            # Silencioso para tabelas que podem não existir no primeiro run
            pass
            
    conn.close()
    print(f"📦 Total de votos detectados únicos: {len(processed_ids)}")

    all_new_ids = []

    # 2. Iterar por Mês (Jan 2023 até Hoje)
    # CORREÇÃO: Varre SEMPRE de Hoje até 2023 para garantir atualizações recentes E histórico
    
    current_date = datetime.now()
    start_global = datetime(2023, 1, 1)
    
    # Gerar lista de tuplas (ano, mes) de Hoje até 2023
    months_to_fetch = []
    temp_date = current_date
    while temp_date >= start_global:
        months_to_fetch.append((temp_date.year, temp_date.month))
        # Voltar 1 mês
        if temp_date.month == 1:
            temp_date = temp_date.replace(year=temp_date.year - 1, month=12, day=1)
        else:
            temp_date = temp_date.replace(month=temp_date.month - 1, day=1)
            
    print(f"🗓️  Buscando votações mês a mês ({len(months_to_fetch)} meses de {current_date.strftime('%m/%Y')} a 01/2023)...")

    for year, month in months_to_fetch:
        if killer.kill_now: break
        
        # SKIP LOGIC
        # Nunca pular o mês atual para garantir detecção de novos votos do dia
        is_current_month = (year == current_date.year and month == current_date.month)
        
        if not is_current_month and checkpoint_manager.is_month_completed(year, month):
            print(f"   ⏩ Pulei {month:02d}/{year} (Checkpoint: já validado hoje).")
            continue

        # Calcular início e fim do mês
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        
        date_ini = f"{year}-{month:02d}-01"
        date_fim = f"{year}-{month:02d}-{last_day}"
        
        # Não pegar datas futuras
        if date_fim > datetime.now().strftime('%Y-%m-%d'):
             date_fim = datetime.now().strftime('%Y-%m-%d')
             
        # URL do Mês
        url = f"{CAMARA_API_BASE}/votacoes?dataInicio={date_ini}&dataFim={date_fim}&ordem=DESC&ordenarPor=dataHoraRegistro&itens=200"
        print(f"   📅 Buscando {date_ini} a {date_fim}...")
        
        month_ids = []
        page_count = 1
        print(f"      ↳ Processando páginas: ", end="", flush=True)
        
        api_error_occured = False # Flag para não marcar como completo se der erro
        
        while url:
            if killer.kill_now: break
            try:
                # print(f"Page {page_count}...", end=" ", flush=True) 
                print(".", end="", flush=True) 
                resp = requests.get(url, timeout=30)
                if resp.status_code != 200:
                    print(f"\n      ❌ Erro {resp.status_code} na API ({date_ini}).")
                    api_error_occured = True
                    break
                    
                data = resp.json()
                items = data.get('dados', [])
                
                skipped_count = 0
                page_ids = []
                
                # Conexão para verificação direta (fail-safe)
                conn_fs = get_db_connection()
                cursor_fs = conn_fs.cursor()
                
                for item in items:
                    v_id = str(item['id']).strip()
                    # 1. Verifica no cache em memória
                    if v_id in processed_ids or v_id in all_new_ids:
                        skipped_count += 1
                        continue
                    
                    # 2. Verifica direto no banco (fail-safe contra registros novos ou falha no set inicial)
                    cursor_fs.execute("""
                        SELECT 1 FROM votacoes WHERE id_votacao = ? 
                        UNION 
                        SELECT 1 FROM votacoes_raw_vault WHERE id_votacao = ?
                        UNION
                        SELECT 1 FROM votacoes_destaque WHERE id_votacao = ?
                    """, (v_id, v_id, v_id))
                    
                    if cursor_fs.fetchone():
                        processed_ids.add(v_id) # Atualiza cache para próximas páginas desse mês
                        skipped_count += 1
                        continue
                        
                    all_new_ids.append(v_id)
                    month_ids.append(v_id)
                    page_ids.append(v_id)
                
                conn_fs.close()
                
                if skipped_count > 0:
                     print(f"S{skipped_count}", end="", flush=True)
                else:
                     print(".", end="", flush=True) 
                
                # Próxima página dentro do mês
                url = next((l['href'] for l in data.get('links', []) if l['rel'] == 'next'), None)
                page_count += 1
                
            except Exception as e:
                print(f"\n      ❌ Erro rede/parse: {e}")
                api_error_occured = True
                break
        
        if killer.kill_now: break
        print(f" ({len(month_ids)} novos)")
        
        # 3. Processar Mês Atual IMEDIATAMENTE (Incremental Save)
        if month_ids:
            print(f"      ⚡️ Processando {len(month_ids)} votos de {date_ini}...")
            for vid in tqdm(month_ids, desc=f"   Votos {month}/{year}", leave=False):
                if killer.kill_now: break
                try:
                    process_single_vote(vid)
                except Exception as e:
                    print(f"❌ Erro crítico no ID {vid}: {e}")
        
        # SAFETY CHECKPOINT
        if not api_error_occured and not killer.kill_now:
            checkpoint_manager.mark_month_completed(year, month)
                    
    print("\n✅ Ciclo completo! Tudo atualizado.")



# ==============================================================================
# CAMADA EXTRA: INTEGRAÇÃO DE INTELIGÊNCIA (FUNCIONALIDADE INTEGRADA)
# ==============================================================================

def init_enrichment_table():
    """Garante que a tabela de enrichment existe."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS votacoes_analise_enrichment (
        id_votacao TEXT PRIMARY KEY,
        tema_macro TEXT,
        resumo_leigo TEXT,
        pauta_governo TEXT,
        local_votacao TEXT,
        analise_ia_json TEXT,
        atualizado_em TEXT
    )
    """)
    conn.commit()
    conn.close()

def get_complete_organ_name_internal(sigla_orgao):
    map_siglas = {
        "PLEN": "Plenário",
        "CCJC": "Comissão de Constituição e Justiça e de Cidadania",
        "CFT": "Comissão de Finanças e Tributação",
        "CDEICS": "Comissão de Desenvolvimento Econômico, Indústria, Comércio e Serviços",
        "CMADS": "Comissão de Meio Ambiente e Desenvolvimento Sustentável",
        "MERCOSUL": "Representação Brasileira no Parlamento do Mercosul",
        "MESA": "Mesa Diretora da Câmara dos Deputados"
    }
    return map_siglas.get(sigla_orgao, sigla_orgao)

def generate_search_keywords_quick_internal(text):
    if not client: return []
    try:
        prompt = f"Gere 3 palavras-chave ou frases curtas para buscar discursos sobre este tema: '{text}'. Retorne apenas as palavras separadas por vírgula."
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return resp.choices[0].message.content.split(',')
    except:
        return []

def fetch_context_speeches_internal(date_str, organ_name, proposition_text):
    if not os.path.exists(DISCURSOS_DB_PATH): return []
    try:
        conn = sqlite3.connect(DISCURSOS_DB_PATH)
        cursor = conn.cursor()
        keywords = generate_search_keywords_quick_internal(proposition_text)
        keywords = [k.strip() for k in keywords if k.strip()]
        if not keywords: keywords = [proposition_text.split()[0]]

        conditions, params = [], []
        conditions.append("date(substr(Data, 1, 10)) = ?")
        params.append(date_str.split('T')[0])

        if organ_name and organ_name != "Plenário":
            conditions.append("Comissao LIKE ?")
            params.append(f"%{organ_name}%")
        elif organ_name == "Plenário":
             conditions.append("Comissao = 'Plenário'")
             
        keyword_clauses = []
        for k in keywords:
            keyword_clauses.append("Texto LIKE ?")
            params.append(f"%{k}%")
            
        if keyword_clauses:
             conditions.append(f"({' OR '.join(keyword_clauses)})")
             
        query = f"SELECT Parlamentar, Partido, Texto FROM discursos WHERE {' AND '.join(conditions)} LIMIT 5"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [f"- {r[0]} ({r[1]}): {r[2][:300]}..." for r in rows]
    except Exception as e:
        # Silently fail for context
        return []

def fetch_original_proposition_meta_internal(id_votacao):
    try:
        url_votacao = f"https://dadosabertos.camara.leg.br/api/v2/votacoes/{id_votacao}"
        resp = requests.get(url_votacao, timeout=5)
        if resp.status_code != 200: return None
        
        d = resp.json().get('dados', {})
        
        # 1. Proposicoes Afetadas
        if 'proposicoesAfetadas' in d and d['proposicoesAfetadas']:
            return d['proposicoesAfetadas'][0]
            
        # 2. Objetos Possiveis
        if 'objetosPossiveis' in d:
            for obj in d['objetosPossiveis']:
                if obj.get('siglaTipo') in ['PL', 'PEC', 'PLP', 'MPV']:
                    return obj
                    
        return None
    except:
        return None

def perform_ai_classification_internal(id_votacao, raw_desc, sigla_orgao, data_votacao, orientacoes_text, proposicao_formatted):
    if not client: return None
    
    # 1. Contextos
    nome_orgao = get_complete_organ_name_internal(sigla_orgao)
    speeches = fetch_context_speeches_internal(data_votacao, nome_orgao, proposicao_formatted)
    contexto_discursos = "\n".join(speeches) if speeches else "Nenhum discurso encontrado."
    
    meta_prop = fetch_original_proposition_meta_internal(id_votacao)
    contexto_ementa = ""
    if meta_prop:
        contexto_ementa = f"PROJETO ORIGINAL: {meta_prop.get('siglaTipo')} {meta_prop.get('numero')}/{meta_prop.get('ano')} - {meta_prop.get('ementa')}"

    prompt = f"""
    Analise esta votação da Câmara dos Deputados:
    
    DADOS:
    - Item: {proposicao_formatted}
    - Descrição: {raw_desc}
    - Órgão: {nome_orgao}
    - Data: {data_votacao}
    
    {contexto_ementa}
    
    ORIENTAÇÕES PARTIDÁRIAS:
    {orientacoes_text}
    
    DISCURSOS RECENTES:
    {contexto_discursos}
    
    TAREFA:
    1. Tema Macro (Ex: Economia, Saúde, Segurança, Educação, Direitos Humanos).
    2. Pauta do Governo (Sim/Não/Indiferente). Baseie-se na orientação 'Governo' ou 'Fdr PT...'. 
       - Governo Orientou Sim -> Sim. 
       - Governo Orientou Não -> Não. 
       - Sem orientação -> Indiferente.
    3. Resumo Leigo (Explique o impacto real de forma jornalística).

    Retorne JSON puro:
    {{
        "tema_macro": "...",
        "pauta_governo": "...",
        "resumo_leigo": "..."
    }}
    """
    
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Analista político."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"   ⚠️ Erro na Classification AI: {e}")
        return None

if __name__ == "__main__":
    main_loop()

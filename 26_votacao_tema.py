import sqlite3
import pandas as pd
import json
import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

# Configuração Inicial
load_dotenv()
DB_PATH = "tabelao.db"
DISCURSOS_DB_PATH = "discursos.db"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("⚠️  ERRO: OPENAI_API_KEY não encontrada no .env")
    exit(1)

client = OpenAI(api_key=OPENAI_API_KEY)

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_tables():
    """Garante que a tabela de enrichment existe."""
    conn = get_db_connection()
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

def get_full_organ_name(id_votacao, sigla_orgao):
    """
    Tenta obter o nome completo do órgão via API da Câmara ou mapeamento.
    Isso é importante para bater com o nome na tabela de discursos.
    """
    # Mapeamento manual de siglas comuns para facilitar
    map_siglas = {
        "PLEN": "Plenário",
        "CCJC": "Comissão de Constituição e Justiça e de Cidadania",
        "CFT": "Comissão de Finanças e Tributação",
        "CDEICS": "Comissão de Desenvolvimento Econômico, Indústria, Comércio e Serviços",
        "CMADS": "Comissão de Meio Ambiente e Desenvolvimento Sustentável",
        "MERCOSUL": "Representação Brasileira no Parlamento do Mercosul",
        "MESA": "Mesa Diretora da Câmara dos Deputados"
    }
    
    if sigla_orgao in map_siglas:
        return map_siglas[sigla_orgao]
        
    try:
        # Tentar buscar detalhes da votação na API para pegar idEvento -> Órgão
        url = f"https://dadosabertos.camara.leg.br/api/v2/votacoes/{id_votacao}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            dados = resp.json().get('dados', {})
            orgao = dados.get('siglaOrgao') # A API as vezes retorna sigla mesmo
            # Se tiver idOrgao, poderiamos buscar details do orgao, mas vamos simplificar
            return orgao
    except Exception as e:
        print(f"Erro ao buscar orgao API: {e}")
        
    return sigla_orgao

def generate_keywords(text):
    """Gera palavras-chave para busca de discursos."""
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

def get_relevant_speeches(date_str, organ_name, proposition_text):
    """
    Busca discursos relevantes no banco de dados.
    """
    if not os.path.exists(DISCURSOS_DB_PATH):
        print("⚠️  discursos.db não encontrado.")
        return []
        
    try:
        conn = sqlite3.connect(DISCURSOS_DB_PATH)
        cursor = conn.cursor()
        
        # Filtrar por data (exato ou D-1, D+1 poderia ser útil, mas vamos tentar exato primeiro)
        # Formato no banco discursos parece ser YYYY-MM-DDT... ou algo assim?
        # Check anterior na conversa mostrou YYYY-MM-DD
        
        # 1. Gerar keywords
        keywords = generate_keywords(proposition_text)
        keywords = [k.strip() for k in keywords if k.strip()]
        
        if not keywords:
            keywords = [proposition_text.split()[0]] # Fallback
            
        print(f"   🔑 Keywords para discursos: {keywords}")
        
        # Montar query dinamica
        conditions = []
        params = []
        
        # Filtro de Data (Tenta pegar o dia exato)
        # O banco de discursos tem coluna Data. Formato YYYY-MM-DD.
        conditions.append("date(substr(Data, 1, 10)) = ?")
        params.append(date_str.split('T')[0])
        
        # Filtro de Orgao (Fuzzy match)
        if organ_name and organ_name != "Plenário":
            conditions.append("Comissao LIKE ?")
            params.append(f"%{organ_name}%")
        elif organ_name == "Plenário":
             conditions.append("Comissao = 'Plenário'")
             
        # Filtro de Keywords no Texto
        keyword_clauses = []
        for k in keywords:
            keyword_clauses.append("Texto LIKE ?")
            params.append(f"%{k}%")
            
        if keyword_clauses:
             conditions.append(f"({' OR '.join(keyword_clauses)})")
             
        query = f"SELECT Parlamentar, Partido, Texto FROM discursos WHERE {' AND '.join(conditions)} LIMIT 10"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        speeches = []
        for r in rows:
            speeches.append(f"- {r[0]} ({r[1]}): {r[2][:300]}...")
            
        return speeches
        
    except Exception as e:
        print(f"Erro ao buscar discursos: {e}")
        return []

def get_original_proposition_data(id_votacao):
    """
    Busca a EMENTA da proposição original (Projeto de Lei, PEC, etc) associada à votação.
    Isso é crucial quando a votação é apenas um "Parecer", para saber O QUE está sendo votado.
    """
    try:
        # 1. Obter dados da votação para achar a proposição vinculada
        url_votacao = f"https://dadosabertos.camara.leg.br/api/v2/votacoes/{id_votacao}"
        resp = requests.get(url_votacao, timeout=5)
        if resp.status_code != 200:
            return None
            
        dados_votacao = resp.json().get('dados', {})
        
        # Estratégia de Busca:
        # 1. 'proposicoesAfetadas' (Geralmente contém a lei principal sendo alterada/votada)
        # 2. 'proposicaoObjeto' (O objeto direto da votação)
        # 3. 'objetosPossiveis' (Lista de objetos, pegamos o primeiro PL/PEC/MPV)
        
        # Tentativa 1: Proposicoes Afetadas (A melhor fonte para PLs)
        if 'proposicoesAfetadas' in dados_votacao and dados_votacao['proposicoesAfetadas']:
            prop = dados_votacao['proposicoesAfetadas'][0] # Pega a primeira
            print(f"   📄 Proposição Afetada Encontrada: {prop.get('siglaTipo')} {prop.get('numero')}/{prop.get('ano')}")
            return {
                'ementa': prop.get('ementa'),
                'siglaTipo': prop.get('siglaTipo'),
                'numero': prop.get('numero'),
                'ano': prop.get('ano')
            }

        # Tentativa 2: Proposicao Objeto Direto
        if 'proposicaoObjeto' in dados_votacao and dados_votacao['proposicaoObjeto']:
            prop = dados_votacao['proposicaoObjeto']
            # Se for ID/String, precisa buscar. Se for dict, ja tem.
            # Mas geralmente a API traz so URI/ID aqui se nao for expandido.
            id_prop = prop.get('id') if isinstance(prop, dict) else (prop.split('/')[-1] if isinstance(prop, str) else None)
            
            if id_prop:
                url_prop = f"https://dadosabertos.camara.leg.br/api/v2/proposicoes/{id_prop}"
                r_p = requests.get(url_prop)
                if r_p.status_code == 200:
                    d_p = r_p.json().get('dados')
                    return {
                        'ementa': d_p.get('ementa'),
                        'siglaTipo': d_p.get('siglaTipo'),
                        'numero': d_p.get('numero'),
                        'ano': d_p.get('ano')
                    }

        # Tentativa 3: Objetos Possiveis (Procurar PL, PEC, PLP, MPV)
        tipos_relevantes = ['PL', 'PEC', 'PLP', 'MPV']
        if 'objetosPossiveis' in dados_votacao:
            for obj in dados_votacao['objetosPossiveis']:
                if obj.get('siglaTipo') in tipos_relevantes:
                    print(f"   📄 Objeto Possível Encontrado: {obj.get('siglaTipo')} {obj.get('numero')}")
                    return {
                        'ementa': obj.get('ementa'),
                        'siglaTipo': obj.get('siglaTipo'),
                        'numero': obj.get('numero'),
                        'ano': obj.get('ano')
                    }
                    
        # ... Mantem logica antiga de efeitosRegistro como fallback ...
        id_proposicao = None
        if 'efeitosRegistro' in dados_votacao: # (Note: API returned efeitosRegistrados, check keys match)
            # A API retorna 'efeitosRegistrados' (plural) no JSON debugado
            pass 
            
    except Exception as e:
        print(f"Erro ao buscar proposição original: {e}")
        
    return None

def get_orientations(id_votacao):
    """
    Busca orientações partidárias do cofre (votacoes_raw_vault) ou API.
    Retorna string formatada para o prompt.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Tenta pegar do vault (muito mais rápido)
        cursor.execute("SELECT raw_json FROM votacoes_raw_vault WHERE id_votacao = ? AND tipo_dado = 'orientacoes'", (id_votacao,))
        row = cursor.fetchone()
        conn.close()
        
        data = None
        if row:
            data = json.loads(row[0])
        else:
            # Fallback API (se não tiver no vault)
            url = f"https://dadosabertos.camara.leg.br/api/v2/votacoes/{id_votacao}/orientacoes"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()

        if data:
            lista = data.get('dados', [])
            if not lista: return "Nenhuma orientação registrada."
            
            # Formatar: "Governo: Sim, Oposição: Não, PT: Sim..."
            parts = []
            for o in lista:
                sigla = o.get('siglaPartidoBloco', 'Desconhecido')
                ori = o.get('orientacaoVoto')
                if ori: # Só adiciona se tiver orientação
                    parts.append(f"{sigla}: {ori}")
            return ", ".join(parts)

    except Exception as e:
        print(f"Erro ao buscar orientações: {e}")
        
    return "Não foi possível obter orientações."

def classify_voting_with_ai(row):
    """
    Usa GPT para classificar tema, alinhamento do governo e gerar resumo, 
    agora com contexto dos discursos, ementa original E orientações partidárias.
    """
    proposicao = row.get('proposicao') or row.get('nome_projeto') or "Proposição sem nome"
    descricao = row.get('descricao') or ""
    objeto = row.get('objeto_votacao') or ""
    sigla_orgao = row.get('sigla_orgao') or ""
    data_votacao = row.get('data_votacao') or ""
    id_votacao = row.get('id_votacao') or ""
    
    # 1. Obter Nome Completo do Órgão
    nome_orgao = get_full_organ_name(id_votacao, sigla_orgao)
    
    # 2. Buscar Contexto (Discursos)
    discursos_contexto = []
    if data_votacao:
        data_clean = data_votacao.split('T')[0]
        discursos_contexto = get_relevant_speeches(data_clean, nome_orgao, proposicao)
    
    contexto_discursos = "\n".join(discursos_contexto) if discursos_contexto else "Nenhum discurso específico encontrado."
    
    # 3. Buscar Contexto (Ementa da Proposição Original)
    contexto_ementa = ""
    dados_prop = get_original_proposition_data(id_votacao)
    if dados_prop:
        contexto_ementa = f"""
        PROJETO ORIGINAL SENDO VOTADO:
        - Tipo/Número: {dados_prop.get('siglaTipo')} {dados_prop.get('numero')}/{dados_prop.get('ano')}
        - EMENTA (Resumo Oficial): {dados_prop.get('ementa')}
        """

    # 4. Buscar Orientações Partidárias (CRUCIAL PARA PAUTA GOVERNO)
    orientacoes_text = get_orientations(id_votacao)
    
    prompt = f"""
    Analise a seguinte votação legislativa da Câmara dos Deputados do Brasil:
    
    DADOS TÉCNICOS:
    - Proposição na Pauta: {proposicao}
    - Órgão: {nome_orgao} ({sigla_orgao})
    - Objeto da Votação: {objeto}
    
    {contexto_ementa}
    
    ORIENTAÇÕES PARTIDÁRIAS (Como os partidos orientaram o voto):
    {orientacoes_text}
    
    CONTEXTO DOS DISCURSOS (O que foi falado na reunião):
    {contexto_discursos}
    
    TAREFA:
    1. Defina um **Tema Macro** específico (Ex: "Segurança Pública", "Economia", "Educação").
    2. Defina o **Alinhamento com o Governo Lula (2023-2026)** ("Sim"/"Não"/"Indiferente").
       - REGRA PRIORITÁRIA: Verifique a orientação do "Governo" ou da Federação do PT ("Fdr PT-PCdoB-PV").
       - Se "Governo" orientou "Sim" -> Pauta do Governo: "Sim".
       - Se "Governo" orientou "Não" -> Pauta do Governo: "Indiferente" (se perdeu) ou "Não" (se foi contra).
       - Se "Governo" NÃO orientou (vazio) mas "Fdr PT..." ou Liderança do Governo votou "Não", considere como NÃO sendo interesse do governo aprovar (portanto, "Indiferente" ou contra).
       - Se a Oposição votou "Sim" e o Governo "Não", NÃO É PAUTA DO GOVERNO.
    
    3. Gere um **Resumo para Leigo** (jornalístico e direto).
       
       - Se for "Encerramento de Discussão" ou "Votação de Requerimento": O usúario quer saber DISCUSSÃO SO SOBRE O QUE?
         NUNCA diga apenas "encerrou a discussão de um requerimento". Diga "Encerrou a discussão sobre o Projeto de Lei X que prevê Y".
         Se o objeto for "Requerimento de Urgência", diga "Aprovada urgência para votar o projeto que..."
       
       - Se for "Requerimento de Retirada de Pauta": EXPLIQUE O QUE ESTAVA NA PAUTA.
         Exemplo: "Rejeitada a retirada de pauta do PL da Taxação de Shopee".
         Se não souber o assunto, diga "do item da pauta (PL XXX/XXXX)". NUNCA diga só "retirar um assunto desconhecido".

       - Se for "Parecer": Explique o mérito da proposta linkada na EMENTA.
         Exemplo: "Aprovada proposta que altera o Código Penal para..."

       PROIBIÇÕES:
       - NÃO comece com "A votação rejeitou um requerimento que significa que a proposta não avançará" (VAGO!).
       - NÃO use "importante para a gestão pública" sem dizer O QUE É.
       - Se a Ementa for genérica ("Altera a Lei..."), tente inferir o TEMA pelo nome da lei ou discursos.
    
    Retorne ESTRITAMENTE um JSON no seguinte formato:
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
                {"role": "system", "content": "Você é um analista político sênior especializado em traduzir 'legislaquês' para o cidadão comum."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        content = json.loads(resp.choices[0].message.content)
        return content
    except Exception as e:
        print(f"   ⚠️  Erro na OpenAI: {e}")
        return None

def process_missing_classifications(limit=50):
    init_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Busca votações que estão na tabela principal mas que:
    # 1. Não estão na enrichment
    # 2. OU estão na enrichment mas com tema nulo/Geral ou pauta_governo nula
    
    print("🔍 Buscando votações pendentes de classificação...")
    
    # Query unificada (Votacoes <-> Enrichment)
    query = """
    SELECT v.id_votacao, v.data_votacao, v.sigla_orgao, v.descricao, 
           v.nome_projeto, v.objeto_votacao,
           e.tema_macro, e.pauta_governo
    FROM votacoes v
    LEFT JOIN votacoes_analise_enrichment e ON v.id_votacao = e.id_votacao
    WHERE (e.tema_macro IS NULL OR e.tema_macro = 'Geral' OR e.tema_macro = '' 
           OR e.pauta_governo IS NULL OR e.pauta_governo = '')
    ORDER BY v.data_votacao DESC
    LIMIT ?
    """
    
    df_pendentes = pd.read_sql_query(query, conn, params=[limit])
    
    if df_pendentes.empty:
        print("✅ Nenhuma votação pendente de classificação encontrada.")
        conn.close()
        return

    print(f"🚀 Encontradas {len(df_pendentes)} votações para classificar.")
    
    for _, row in df_pendentes.iterrows():
        id_votacao = row['id_votacao']
        print(f"📌 Classificando {id_votacao} ({row['sigla_orgao']}): {str(row['nome_projeto'])[:40]}...")
        
        ai_data = classify_voting_with_ai(row)
        
        if ai_data:
            print(f"   ✅ Resultado: {ai_data.get('tema_macro')} | Gov: {ai_data.get('pauta_governo')}")
            
            # Upsert na tabela enrichment
            cursor.execute("""
            INSERT INTO votacoes_analise_enrichment (id_votacao, tema_macro, resumo_leigo, pauta_governo, atualizado_em)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id_votacao) DO UPDATE SET
                tema_macro = excluded.tema_macro,
                resumo_leigo = COALESCE(excluded.resumo_leigo, votacoes_analise_enrichment.resumo_leigo),
                pauta_governo = excluded.pauta_governo,
                atualizado_em = excluded.atualizado_em
            """, (
                id_votacao,
                ai_data.get('tema_macro', 'Geral'),
                ai_data.get('resumo_leigo', ''),
                ai_data.get('pauta_governo', 'Indiferente'),
                datetime.now().isoformat()
            ))
            
            # Opcional: Atualizar tabela 'votacoes' também se necessário
            # (Mas o frontend usa enrichment prioritariamente)
            
            conn.commit()
            time.sleep(0.5) # Evitar rate limit
            
        else:
            print("   ❌ Falha na classificação.")

    conn.close()
    print("🏁 Processamento concluído.")

if __name__ == "__main__":
    process_missing_classifications(limit=300)

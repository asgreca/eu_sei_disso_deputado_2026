import sqlite3
import pandas as pd
from dotenv import load_dotenv
import os
import openai
import json
import time
from tqdm import tqdm
import math

# --- CONFIGURAÇÃO E PARÂMETROS ---
load_dotenv()
MODELO_OPENAI = "gpt-4o-mini"
MAX_CARACTERES_POR_DISCURSO = int(os.getenv("LLM_MAX_CHARS_PER_DISCURSO", "6000"))
BATCH_STATUS_FILE = "pending_batch_status.json"
MAX_REQUESTS_PER_BATCH = 20000  # Reduzido para 20k porque 45k excedeu o limite de 200MB de arquivo

print(f"INFO: Usando o modelo da OpenAI: {MODELO_OPENAI} com BATCH API (50% Desconto)")

try:
    openai.api_key = os.getenv("OPENAI_API_KEY")
    if not openai.api_key:
        raise ValueError("A chave da OpenAI não foi encontrada no arquivo .env")
    client = openai.Client()
except Exception as e:
    print(f"Erro ao configurar a API da OpenAI: {e}")
    client = None

def carregar_prompt_de_arquivo(filepath="system_prompt.txt"):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"ERRO CRÍTICO: O arquivo de prompt '{filepath}' não foi encontrado.")
        return None

def setup_tabela_integrada(conn):
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS discursos_integrados (
        hash_linha TEXT PRIMARY KEY,
        id INTEGER,
        sessao TEXT,
        parlamentar TEXT,
        estado TEXT,
        partido TEXT,
        origem TEXT,
        comissao TEXT,
        data TEXT,
        sentimento_geral TEXT,
        temas_principais TEXT,
        projetos_de_lei_mencionados TEXT,
        citacoes TEXT,
        data_processamento DATETIME
    )
    """)
    conn.commit()

def carregar_discursos_pendentes(conn, limite=MAX_REQUESTS_PER_BATCH):
    query_sqlite = """
    SELECT d.*
    FROM discursos d
    LEFT JOIN discursos_integrados i ON d.hash_linha = i.hash_linha
    WHERE i.hash_linha IS NULL
      AND LENGTH(d.Texto) > 1000
      AND substr(d.Data, 7, 4) >= '2023'
    ORDER BY substr(d.Data, 7, 4), substr(d.Data, 4, 2), substr(d.Data, 1, 2), d.ID
    LIMIT ?
    """
    return pd.read_sql_query(query_sqlite, conn, params=(limite,))

def gerar_arquivo_jsonl(df, system_prompt, filename="batch_requests.jsonl"):
    with open(filename, 'w', encoding='utf-8') as f:
        for idx, row in df.iterrows():
            hash_linha = str(row['hash_linha'])
            
            # Formatar prompt (adaptado do existente)
            prompt = f"=== DISCURSO (Hash: {hash_linha}) ===\n"
            prompt += f"Texto: {str(row['Texto'])[:MAX_CARACTERES_POR_DISCURSO]}\n\n"
            prompt += """Retorne um JSON com a seguinte estrutura exatamente para este discurso:
{
  "sentimento_geral": "sentimento",
  "temas_principais": ["tema1", "tema2"],
  "projetos_de_lei_mencionados": ["PL1", "PL2"],
  "citacoes": [
    {
      "nome_citado": "Nome",
      "sentenca_exata": "texto da citação",
      "sentimento_da_citacao": "sentimento",
      "tom_da_citacao": "tom"
    }
  ]
}
"""
            # Criar o objeto para BATCH API
            request_obj = {
                "custom_id": hash_linha[:64], # Max chars for custom_id is 64
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": MODELO_OPENAI,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ]
                }
            }
            f.write(json.dumps(request_obj) + "\n")
    return filename

def processar_resultados_batch(conn, input_df, results_content: str):
    print("Processando respostas do Batch e inserindo no banco SQLite...")
    cursor = conn.cursor()
    dados_para_integrar = []
    
    # Criar um dict indexado por hash do dataframe de entrada,
    # caso precisemos extrair dados adicionais
    df_dict = input_df.set_index('hash_linha').to_dict('index')
    
    total_linhas = len(results_content.strip().split('\n'))
    
    for line in tqdm(results_content.strip().split('\n'), desc="Salvando DB"):
        if not line:
            continue
        try:
            res_obj = json.loads(line)
            hash_linha = res_obj.get("custom_id")
            
            error = res_obj.get("error")
            if error:
                print(f"Erro na resposta pro id {hash_linha}: {error}")
                continue
                
            body = res_obj.get("response", {}).get("body", {})
            choices = body.get("choices", [])
            
            if not choices:
                continue
                
            content = choices[0].get("message", {}).get("content", "{}")
            resultado = json.loads(content)
            
            # Se estiber em 'discursos' (caso a LLM mandou como array, tentamos reparar)
            if 'discursos' in resultado and len(resultado['discursos']) > 0:
                resultado = resultado['discursos'][0]
                
            # Dados do DF original
            row = df_dict.get(hash_linha, {})
            if not row:
                print(f"Aviso: Hash {hash_linha} retornado pela OpenAI mas não achado no cache do lote local.")
                continue
                
            dados_para_integrar.append((
                hash_linha,
                row.get('ID'),
                row.get('Sessao'),
                row.get('Parlamentar'),
                row.get('Estado'),
                row.get('Partido'),
                row.get('Origem'),
                row.get('Comissao'),
                row.get('Data'),
                resultado.get('sentimento_geral', 'N/A'),
                json.dumps(resultado.get('temas_principais', [])),
                json.dumps(resultado.get('projetos_de_lei_mencionados', [])),
                json.dumps(resultado.get('citacoes', []))
            ))
        except Exception as e:
            print(f"Erro no parseamento JSON de resposta: {e}")
            
    if dados_para_integrar:
        cursor.executemany("""
            INSERT OR REPLACE INTO discursos_integrados 
            (hash_linha, id, sessao, parlamentar, estado, partido, origem, comissao, data,
                sentimento_geral, temas_principais, projetos_de_lei_mencionados, citacoes, data_processamento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, dados_para_integrar)
        conn.commit()
        print(f"✅ {len(dados_para_integrar)} discursos integrados no SQLite com sucesso!")

def main():
    if not client:
        print("ERRO CRÍTICO: Cliente OpenAI não inicializado.")
        return
        
    db_path = 'discursos.db'
    conn = sqlite3.connect(db_path)
    
    # SETUP
    setup_tabela_integrada(conn)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    conn.commit()

    # Lançar fluxo principal de retroalimentação automática
    while True:
        # Checar status da batch salva
        batch_status = {}
        if os.path.exists(BATCH_STATUS_FILE):
            with open(BATCH_STATUS_FILE, 'r') as f:
                batch_status = json.load(f)

        batch_id = batch_status.get("batch_id")
        
        # Se não temos um BATCH pendente, então criamos um
        if not batch_id:
            print("\n📥 Lendo discursos elegíveis do SQLite...")
            df = carregar_discursos_pendentes(conn, limite=MAX_REQUESTS_PER_BATCH)
            if df.empty:
                print("✅ Todos os discursos já foram processados! Processo finalizado com sucesso.")
                break

            total_discursos = len(df)
            print(f"📊 Encontrados {total_discursos} discursos não processados.")
            
            system_prompt = carregar_prompt_de_arquivo()
            if not system_prompt:
                break
                
            print("⚙️ Preparando arquivo JSONL de Batch...")
            jsonl_file = gerar_arquivo_jsonl(df, system_prompt, "batch_requests.jsonl")
            
            # Guardar dataset localmente para depois combinar no DB sem precisar de nova Query
            df.to_pickle("batch_current_dataset.pkl")
            
            print("📤 Fazendo upload do arquivo para OpenAI...")
            try:
                batch_input_file = client.files.create(
                  file=open(jsonl_file, "rb"),
                  purpose="batch"
                )
                print(f"   Arquivo enviado. File ID: {batch_input_file.id}")
                
                print("🚀 Iniciando processamento em Lote (Batch API) na OpenAI...")
                batch = client.batches.create(
                    input_file_id=batch_input_file.id,
                    endpoint="/v1/chat/completions",
                    completion_window="24h",
                    metadata={
                      "description": f"Processamento de {total_discursos} discursos"
                    }
                )
                batch_id = batch.id
                
                # Salvar BATCH ID localmente!
                with open(BATCH_STATUS_FILE, 'w') as f:
                    json.dump({"batch_id": batch_id}, f)
                    
                print(f"✅ Lote aceito! Batch ID: {batch_id}")
                
            except Exception as e:
                print(f"❌ Erro ao criar Batch na OpenAI: {e}")
                break
                
        print(f"👀 Observando o Batch {batch_id} no lado da OpenAI...")
        
        try:
            df_input = pd.read_pickle("batch_current_dataset.pkl")
        except:
            print("⚠️ Aviso: batch_current_dataset.pkl ausente. Tentando recuperar pelo SQL...")
            df_input = carregar_discursos_pendentes(conn, limite=50000)

        # Monitoramento (Poling contínuo com barra progresso)
        pbar = None
        
        while True:
            try:
                batch = client.batches.retrieve(batch_id)
            except Exception as e:
                print(f"  ❌ Erro de conexão com a OpenAI ao checar status: {e}. Tentando em 30s...")
                time.sleep(30)
                continue
                
            status = batch.status
            request_counts = batch.request_counts
            
            if request_counts:
                total = request_counts.total
                completed = request_counts.completed
                failed = request_counts.failed
                
                if pbar is None and total > 0:
                    pbar = tqdm(total=total, desc="Processando na OpenAI", unit="req")
                    if completed > 0:
                        pbar.update(completed)
                elif pbar is not None:
                    current_completed = pbar.n
                    if completed > current_completed:
                        pbar.update(completed - current_completed)
                
                print(f"  [Status: {status.upper()}] - Concluídos: {completed}/{total} - Com falha: {failed}", end='\r')
            else:
                 print(f"  [Status: {status.upper()}] - Aguardando contagem...", end='\r')
            
            if status == 'completed':
                if pbar: pbar.close()
                print("\n🎉 O Batch foi concluído com sucesso!")
                
                output_file_id = batch.output_file_id
                print(f"📥 Baixando arquivo de resposta ({output_file_id})...")
                
                # API da OpenAI atual exige request pro arquivo via cliente file.content()
                file_response = client.files.content(output_file_id)
                resultados_texto = file_response.text
                
                processar_resultados_batch(conn, df_input, resultados_texto)
                
                # Limpar o tracker de BATCH
                if os.path.exists(BATCH_STATUS_FILE):
                    os.remove(BATCH_STATUS_FILE)
                if os.path.exists("batch_current_dataset.pkl"):
                    os.remove("batch_current_dataset.pkl")
                if os.path.exists("batch_requests.jsonl"):
                    os.remove("batch_requests.jsonl")    
                    
                print("\n✔️ Arquivos temporários limpos.")
                print("🔄 Iniciando o próximo lote automaticamente...")
                break # Quebra o loop interno para reiniciar o loop externo
                
            elif status in ['failed', 'expired', 'cancelling', 'cancelled']:
                if pbar: pbar.close()
                print(f"\n❌ O Batch falhou ou foi abortado. Status final: {status}")
                
                if hasattr(batch, 'errors') and batch.errors and batch.errors.data:
                    print("Detalhes do erro:", batch.errors.data)
                    
                print("Apagando do registro para que possa ser refeito...")
                if os.path.exists(BATCH_STATUS_FILE):
                    os.remove(BATCH_STATUS_FILE)
                # No erro saímos da ferramenta totalmente para você investigar
                return
                
            time.sleep(30) # Poll de 30 em 30 segundos, não onere tão forte a API OpenAI

if __name__ == "__main__":
    main()

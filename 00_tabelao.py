import pandas as pd
import pandas as pd
from datetime import datetime   
import requests
import zipfile
import io
import pandas as pd
from io import StringIO
from tqdm import tqdm  # Importar tqdm

url = 'https://dadosabertos.camara.leg.br/arquivos/deputados/csv/deputados.csv'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
}

try:
    response = requests.get(url, headers=headers)
    response.raise_for_status()  # Isso irá lançar uma exceção se o código da resposta não for 200
    deputados = pd.read_csv(StringIO(response.text), sep=';', dtype=str)
except requests.exceptions.HTTPError as e:
    print(f"Erro HTTP: {e}")
except pd.errors.ParserError:
    print("Erro ao analisar o arquivo CSV. Verifique o delimitador e a formatação.")

deputados['idLegislaturaFinal'] = deputados['idLegislaturaFinal'].astype('int')
deputados = deputados[deputados["idLegislaturaFinal"] > 56]

urls = deputados['uri'].tolist()

# Lista para armazenar todos os dados
all_data = []

# Loop para processar cada URL com tqdm para visualizar o progresso
for url in tqdm(urls, desc="Processando URLs"):  # tqdm envolve a lista urls
    response = requests.get(url)
    if response.status_code == 200:
        json_data = response.json()
        data = json_data['dados']
        # Inclui dados do último status e gabinete no dicionário principal
        if 'ultimoStatus' in data:
            for key, value in data['ultimoStatus'].items():
                if key == 'gabinete':
                    for g_key, g_value in value.items():
                        data[f'gabinete_{g_key}'] = g_value
                else:
                    data[f'ultimoStatus_{key}'] = value
            del data['ultimoStatus']  # Remove a chave 'ultimoStatus' para evitar aninhamento
        all_data.append(data)
    else:
        print(f"Erro ao acessar {url}")

# Convertendo a lista de dicionários em DataFrame
deputados = pd.DataFrame(all_data)

deputados = deputados.iloc[:, [0, 2, 14, 15, 16, 17, 18, 19]]

import requests
import zipfile
import io
import pandas as pd

anos = [2023, 2024, 2025, 2026]
dfs = []

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
}

for ano in anos:
    url = f"https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip"
    print(f"Baixando: {url}")
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as thezip:
            for zipinfo in thezip.infolist():
                print(f"  Extraindo: {zipinfo.filename}")
                with thezip.open(zipinfo) as thefile:
                    df = pd.read_csv(thefile, sep=';')
                    dfs.append(df)
    except requests.RequestException as e:
        print(f"Houve um erro ao baixar o arquivo de {ano}: {e}")
    except zipfile.BadZipFile:
        print(f"Arquivo ZIP inválido para o ano {ano}.")
    except Exception as e:
        print(f"Erro inesperado para o ano {ano}: {e}")

print(f"Total de arquivos baixados: {len(dfs)}")

if dfs:
    df_final = pd.concat(dfs, ignore_index=True)
    print("Concatenação realizada com sucesso!")
else:
    print("Nenhum arquivo foi baixado ou lido com sucesso.")
    df_final = pd.DataFrame()

df_final = df_final.dropna(subset=['cpf'])
df_final['cpf'] = df_final['cpf'].astype('str')
df_final['cpf'] = df_final['cpf'].astype(str).str[:-2]
df_final['ideCadastro'] = df_final['ideCadastro'].astype('str')
df_final['ideCadastro'] = df_final['ideCadastro'].astype(str).str[:-2]
#del(df_final['nuCarteiraParlamentar'])
del(df_final['numSubCota'])
del(df_final['numEspecificacaoSubCota'])
del(df_final['txtDescricaoEspecificacao'])
del(df_final['indTipoDocumento'])
del(df_final['vlrDocumento'])
del(df_final['vlrGlosa'])
del(df_final['numParcela'])
del(df_final['numLote'])
del(df_final['numRessarcimento'])
del(df_final['datPagamentoRestituicao'])
del(df_final['vlrRestituicao'])
df_final['datEmissao'] = pd.to_datetime(df_final['datEmissao'])

# Formatando a data no formato 'dia/mês/ano'
df_final['datEmissao'] = df_final['datEmissao'].dt.strftime('%d/%m/%Y')
df_final = df_final[df_final["codLegislatura"] > 56]
df_final['nome'] = df_final['txNomeParlamentar']
del(df_final['txNomeParlamentar'])

deputados['nome'] = deputados['ultimoStatus_nome']
del(deputados['ultimoStatus_nome'])

import pandas as pd

# Leitura dos arquivos CSV
partidos = pd.read_csv('partido.csv', dtype=str)
estados = pd.read_csv('estados.csv', sep=',', dtype=str)  # <-- Corrigido aqui!
estados.columns = estados.columns.str.strip()  # Remove espaços

print(estados.columns)  # Veja o nome real das colunas

# Se necessário, renomeie:
# estados.rename(columns={'sgUf': 'sgUF'}, inplace=True)

# Realizando os merges
df_final = pd.merge(df_final, deputados, how='inner', on='nome')
df_final = pd.merge(df_final, partidos, how='inner', on='sgPartido')
df_final = pd.merge(df_final, estados, how='inner', on='sgUF')
import pandas as pd

# A expressão regular r'\D' significa "qualquer coisa que não seja um dígito"
df_final['cnpj'] = df_final['txtCNPJCPF'].str.replace(r'\D', '', regex=True)

def process_dataframe(df):
    # Transformando colunas específicas em maiúsculas
    df['txtPassageiro'] = df['txtPassageiro'].str.upper()
    df['nomeCivil'] = df['nomeCivil'].str.upper()
    df['nome'] = df['nome'].str.upper()
    
    # Substituindo txtPassageiro se nomeCivil for igual a txtPassageiro
    df.loc[df['nomeCivil'] == df['txtPassageiro'], 'txtPassageiro'] = df['nome']
    
    return df

# Aplicando a função ao DataFrame
df_final = process_dataframe(df_final)

import pandas as pd
import sqlite3

# Nomes do banco de dados e da tabela
nome_banco_dados = 'tabelao.db'
nome_tabela = 'tabelao'
coluna_chave = 'ideDocumento'

conn = None
try:
    print(f"Conectando ao banco de dados: {nome_banco_dados}")
    conn = sqlite3.connect(nome_banco_dados)

    # Verifica se a tabela já existe
    query_check_table = f"SELECT name FROM sqlite_master WHERE type='table' AND name='{nome_tabela}';"
    cursor = conn.cursor()
    cursor.execute(query_check_table)
    table_exists = cursor.fetchone() is not None

    if table_exists:
        # Se a tabela existe, encontra as novas linhas
        print(f"Tabela '{nome_tabela}' encontrada.")
        
        # Lê apenas a coluna-chave para otimizar a memória
        df_existente = pd.read_sql_query(f"SELECT {coluna_chave} FROM {nome_tabela};", conn)
        chaves_existentes = set(df_existente[coluna_chave].astype(str))
        
        # Filtra o df_final para pegar somente o que não está no banco
        df_novas_linhas = df_final[~df_final[coluna_chave].astype(str).isin(chaves_existentes)]
        
        if not df_novas_linhas.empty:
            print(f"\n{len(df_novas_linhas)} novas linhas prontas para serem inseridas.")
            df_novas_linhas.to_sql(nome_tabela, conn, if_exists='append', index=False)
            print("Novas linhas inseridas com sucesso!")
        else:
            print("\nNenhuma nova linha para inserir. O DataFrame já está atualizado no banco de dados.")

    else:
        # Se a tabela não existe, cria e insere tudo
        print(f"Tabela '{nome_tabela}' não encontrada. Criando uma nova e inserindo todos os dados.")
        df_final.to_sql(nome_tabela, conn, if_exists='append', index=False)
        print(f"\n{len(df_final)} linhas inseridas com sucesso!")

except sqlite3.Error as e:
    print(f"Ocorreu um erro com o banco de dados: {e}")

finally:
    if conn:
        conn.close()
        print("Conexão com o banco de dados fechada.")
        
df_final['cnpjCpfFornecedor'] = df_final['txtCNPJCPF'].astype(str)
#df_final[['cnpjCpfFornecedor','apagar']] = df_final['cnpjCpfFornecedor'].str.split('.',expand=True)
df_final['cnpj'] = df_final['cnpjCpfFornecedor'] 
df_final = df_final.drop(columns=['cnpjCpfFornecedor'])
#df_final = df_final.drop(columns=['apagar'])
df_final['valorLiquido'] = df_final['vlrLiquido'].astype(str)
#df_final['valorDocumento'] = df_final['vlrDocumento'].astype(str)

df_final['cnpj'] = df_final['cnpj'].astype(str)
df_final['ideCadastro'] = df_final['ideCadastro'].astype(str)
#deputados['ideCadastro'] = deputados['ideCadastro'].astype(str)
df_final['ideCadastro'] = df_final['ideCadastro'].str.replace('.0', '')
df_final['cpf'] = df_final['cpf'].astype(str)
df_final['cpf'] = df_final['cpf'].str.replace('.0', '')
df_final['nuCarteiraParlamentar'] = df_final['nuCarteiraParlamentar'].astype(str)
df_final['nuCarteiraParlamentar'] = df_final['nuCarteiraParlamentar'].str.replace('.0', '')
#df_final['nome'] = df_final['txNomeParlamentar']
#del(df_final['txNomeParlamentar'])
lista_cnpj = df_final.drop_duplicates(subset='cnpj', keep="first")
import pandas as pd
import sqlite3

# Nome do arquivo do banco de dados e da tabela
nome_banco_dados = 'tabelao.db'
nome_tabela = 'lista_cnpj_geral'

# --- 1. Conectar ao banco de dados e ler a tabela ---
try:
    print(f"Conectando ao banco de dados: {nome_banco_dados}")
    # Cria uma conexão com o banco de dados SQLite
    conn = sqlite3.connect(nome_banco_dados)
    
    # Executa a consulta SQL para ler a tabela inteira e a carrega para um DataFrame
    # A opção dtype=str garante que a coluna 'cnpj' será lida como string
    query = f"SELECT * FROM {nome_tabela};"
    lista_total = pd.read_sql_query(query, conn, dtype=str)
    
    print(f"Tabela '{nome_tabela}' lida com sucesso. Total de linhas: {len(lista_total)}")
    
except sqlite3.Error as e:
    print(f"Ocorreu um erro ao ler o banco de dados: {e}")
    exit()

finally:
    # Sempre feche a conexão
    if 'conn' in locals() and conn:
        conn.close()
        print("Conexão com o banco de dados fechada.")

# --- 2. Realizar as operações no DataFrame ---
# Removendo linhas onde a coluna 'cnpj' é NaN
lista_total = lista_total.dropna(subset=['cnpj'])

# Substituir caracteres não numéricos no CNPJ
lista_total['cnpj'] = lista_total['cnpj'].str.replace('.', '', regex=False)
lista_total['cnpj'] = lista_total['cnpj'].str.replace('-', '', regex=False)
lista_total['cnpj'] = lista_total['cnpj'].str.replace('/', '', regex=False)

print("\nOperações de limpeza no DataFrame concluídas.")

# Opcional: Para verificar o resultado, você pode exibir as primeiras linhas
#print("\nPrimeiras linhas do DataFrame após a limpeza:")
#print(lista_total.head())

lista_cnpj.dropna(subset=['cnpj'], inplace=True)
lista_cnpj['cnpj'] = lista_cnpj['cnpj'].str.replace('.', '', regex=False)
lista_cnpj['cnpj'] = lista_cnpj['cnpj'].str.replace('-', '', regex=False)
lista_cnpj['cnpj'] = lista_cnpj['cnpj'].str.replace('/', '', regex=False)
cnpjs = list(lista_cnpj['cnpj'])
import pandas as pd

def limpar_espacos_cnpjs(lista_cnpj):
    cnpjs = [cnpj.strip() for cnpj in lista_cnpj['cnpj']]
    return cnpjs

# Exemplo de uso
cnpjs_limpos = limpar_espacos_cnpjs(lista_cnpj)
#print(cnpjs_limpos)
cnpjs = cnpjs_limpos
import pandas as pd
import sqlite3

def filtrar_cnpjs_novos(lista_cnpjs, nome_banco_dados='tabelao.db', nome_tabela='lista_cnpj_geral'):
    """
    Filtra uma lista de CNPJs, mantendo apenas aqueles que ainda não 
    estão presentes no banco de dados.

    Args:
        lista_cnpjs (list): Uma lista de CNPJs a serem verificados.
        nome_banco_dados (str): O nome do arquivo do banco de dados SQLite.
        nome_tabela (str): O nome da tabela onde os CNPJs já estão salvos.

    Returns:
        list: Uma lista com os CNPJs que são novos.
    """
    cnpjs_processados = set()
    conn = None # Inicializa a conexão como None para o bloco 'finally'

    try:
        # Conecta ao banco de dados SQLite
        conn = sqlite3.connect(nome_banco_dados)

        # Lê a coluna 'cnpj' do banco de dados para um DataFrame.
        # Use uma consulta SQL específica para ler apenas a coluna que você precisa.
        query = f"SELECT cnpj FROM {nome_tabela};"
        df_existente = pd.read_sql_query(query, conn, dtype=str)
        
        # Converte a coluna 'cnpj' para um conjunto (set) para busca rápida
        cnpjs_processados = set(df_existente['cnpj'])
        print(f"Banco de dados: {len(cnpjs_processados)} CNPJs existentes encontrados.")

    except sqlite3.OperationalError as e:
        # Ocorre se a tabela ou o banco de dados não existirem
        print(f"Aviso: Tabela '{nome_tabela}' não encontrada no banco. Nenhum CNPJ será filtrado.")
    
    except Exception as e:
        print(f"Ocorreu um erro ao conectar ou ler o banco de dados: {e}")

    finally:
        if conn:
            conn.close()

    # Filtra a lista de CNPJs, mantendo apenas aqueles que não estão no set
    # A lista de compreensão é a forma mais "Pythonica" e eficiente de fazer isso
    cnpjs_novos = [cnpj for cnpj in lista_cnpjs if cnpj not in cnpjs_processados]

    print(f"Total de CNPJs para processar: {len(cnpjs_novos)}")
    return cnpjs_novos



cnpjs_para_processar = filtrar_cnpjs_novos(cnpjs)
cnpjs_processados = cnpjs_para_processar
import pandas as pd
import sqlite3
import os


# Nomes do banco de dados e da tabela
nome_banco_dados = 'tabelao.db'
nome_tabela = 'lista_cnpj_geral'

# --- Conectar ao banco de dados e ler a lista de CNPJs ---
checar = []
conn = None # Inicializa a conexão

try:
    print(f"Conectando ao banco de dados '{nome_banco_dados}' para ler a tabela '{nome_tabela}'...")
    conn = sqlite3.connect(nome_banco_dados)
    
    # Executa a consulta SQL para pegar apenas a coluna 'cnpj'
    query = f"SELECT cnpj FROM {nome_tabela};"
    df_checar = pd.read_sql_query(query, conn, dtype=str)
    
    # Converte a coluna 'cnpj' do DataFrame para uma lista
    checar = df_checar['cnpj'].tolist()
    print(f"Total de CNPJs lidos do banco de dados: {len(checar)}")

except sqlite3.Error as e:
    print(f"Ocorreu um erro ao ler o banco de dados: {e}")

finally:
    # Garante que a conexão seja fechada
    if conn:
        conn.close()

# --- Fazer a comparação entre as listas ---
# CNPJs que estão em cnpjs_processados, mas não em checar
cnpjs_nao_em_checar = [cnpj for cnpj in cnpjs_processados if cnpj not in checar]

print(f"\nCNPJs que estão no seu conjunto local, mas não na tabela do banco: {len(cnpjs_nao_em_checar)}")
print(cnpjs_nao_em_checar)
cnpjs_processados = cnpjs_nao_em_checar
len(cnpjs_nao_em_checar)
cnpjs_processados = list(set(cnpjs_processados))
len(cnpjs_processados)

import requests
import time
import pandas as pd
import sqlite3
from tqdm import tqdm

def consultar_empresas(cnpjs, nome_banco_dados='tabelao.db', nome_tabela='lista_cnpj_geral'):
    """
    Consulta uma lista de CNPJs na ReceitaWS, grava os resultados em um banco de dados SQLite,
    verificando a existência de cada CNPJ antes de processar.

    Args:
        cnpjs (list): Uma lista de CNPJs a serem consultados.
        nome_banco_dados (str): O nome do arquivo do banco de dados SQLite.
        nome_tabela (str): O nome da tabela onde os dados serão salvos.

    Returns:
        pandas.DataFrame: Um DataFrame com todos os dados da tabela após o processamento.
    """
    conn = None
    try:
        # Conecta ao banco de dados uma única vez no início da função
        conn = sqlite3.connect(nome_banco_dados)

        # Prepara a consulta para verificar a existência de um CNPJ
        # Usamos '?' como placeholder para evitar SQL injection
        query_check_exists = f"SELECT COUNT(*) FROM {nome_tabela} WHERE cnpj = ?;"
        cursor = conn.cursor()

        # Limpar a lista de CNPJs de entrada
        cnpjs_limpos = [
            cnpj.replace('.', '').replace('-', '').replace('/', '').strip()
            for cnpj in cnpjs
        ]
        
        # Filtra a lista para remover duplicatas e CNPJs vazios na origem
        cnpjs_para_processar = list(set(filter(None, cnpjs_limpos)))
        
        print(f"Total de {len(cnpjs_para_processar)} CNPJs únicos para processar.")

        for cnpj in tqdm(cnpjs_para_processar, desc="Processando CNPJs"):
            # Verifica se o CNPJ já existe no banco de dados
            cursor.execute(query_check_exists, (cnpj,))
            if cursor.fetchone()[0] > 0:
                # CNPJ já existe, pule para o próximo
                continue
            
            url = f"https://www.receitaws.com.br/v1/cnpj/{cnpj}"
            
            try:
                response = requests.get(url, timeout=10)
                data = response.json()

                if response.status_code == 200 and data.get('status') == 'OK':
                    # Dados principais da empresa
                    base_empresa = {
                        'cnpj': str(cnpj),
                        'Nome': data.get('nome'),
                        'Logradouro': data.get('logradouro'),
                        'Número': data.get('numero'),
                        'Complemento': data.get('complemento'),
                        'Bairro': data.get('bairro'),
                        'Cidade': data.get('municipio'),
                        'Estado': data.get('uf'),
                        'CEP': data.get('cep'),
                        'Nome_Socio': None,
                        'Qualificação_Socio': None,
                        'CPF/CNPJ_Socio': None,
                        'Erro': None
                    }

                    # Cria um DataFrame para a empresa e grava no banco
                    empresa_df = pd.DataFrame([base_empresa])
                    empresa_df.to_sql(nome_tabela, conn, if_exists='append', index=False)
                    conn.commit()
                    
                    # Adiciona os sócios, se houver
                    for socio in data.get('qsa', []):
                        socio_data = base_empresa.copy()
                        socio_data.update({
                            'Nome_Socio': socio.get('nome'),
                            'Qualificação_Socio': socio.get('qual'),
                            'CPF/CNPJ_Socio': socio.get('cpf', socio.get('cnpj'))
                        })
                        socio_df = pd.DataFrame([socio_data])
                        socio_df.to_sql(nome_tabela, conn, if_exists='append', index=False)
                        conn.commit()

                    print(f"CNPJ {cnpj} gravado com sucesso!")
                else:
                    # Lida com erros da API
                    erro_msg = data.get('message', f"Código de resposta {response.status_code}")
                    erro_df = pd.DataFrame([{'cnpj': str(cnpj), 'Erro': erro_msg}])
                    erro_df.to_sql(nome_tabela, conn, if_exists='append', index=False)
                    conn.commit()
                    print(f"Erro para CNPJ {cnpj}: {erro_msg}")
            
            except requests.exceptions.Timeout:
                # Lida com timeout da requisição
                erro_df = pd.DataFrame([{'cnpj': str(cnpj), 'Erro': "Timeout da requisição"}])
                erro_df.to_sql(nome_tabela, conn, if_exists='append', index=False)
                conn.commit()
                print(f"Erro para CNPJ {cnpj}: Timeout da requisição.")

            except Exception as e:
                # Lida com outros erros inesperados
                erro_df = pd.DataFrame([{'cnpj': str(cnpj), 'Erro': str(e)}])
                erro_df.to_sql(nome_tabela, conn, if_exists='append', index=False)
                conn.commit()
                print(f"Erro geral ao processar CNPJ {cnpj}: {e}")
            
            # Pausa para respeitar a taxa de requisições da API
            time.sleep(20)

    except sqlite3.Error as e:
        print(f"Ocorreu um erro com o banco de dados: {e}")
    finally:
        # Garante que a conexão seja fechada
        if conn:
            conn.close()
            print("Conexão com o banco de dados fechada.")

    # Retorna o DataFrame completo do banco de dados
    conn = sqlite3.connect(nome_banco_dados)
    df_final = pd.read_sql_query(f"SELECT * FROM {nome_tabela}", conn)
    conn.close()
    return df_final

import time
dados_empresas = consultar_empresas(cnpjs_processados)

import pandas as pd
import sqlite3
import re
import time
import requests
from tqdm import tqdm
# <-- MUDANÇA 1: Importar o geocodificador ArcGIS em vez do Nominatim
from geopy.geocoders import ArcGIS
from geopy.extra.rate_limiter import RateLimiter

# --- Configurações ---
nome_banco_dados = 'tabelao.db'
tabela_principal = 'lista_cnpj_geral'
tabela_coordenadas = 'coordenadas_empresas'
BATCH_SIZE = 50

# --- Funções Auxiliares (sem alterações) ---
def limpar_cep(cep):
    if cep is None or str(cep).lower() == "nan": return None
    s = str(cep).strip()
    s = re.sub(r"\D", "", s)
    return s if len(s) == 8 else None

def cep8_to_hifen(cep8):
    return f"{cep8[:5]}-{cep8[5:]}" if cep8 else None

def consultar_cep(cep):
    if not cep or len(cep) != 8: return None
    url = f"https://viacep.com.br/ws/{cep}/json/"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("erro"): return None
        return {"logradouro": data.get("logradouro", ""),"localidade": data.get("localidade", ""),"uf": data.get("uf", "")}
    except requests.exceptions.RequestException:
        return None

# --- Função de Processamento Refatorada ---
def processar_geocoding(row, geocode_func):
    cnpj = row.get('cnpj')
    cep_original = row.get('CEP')
    
    latitude, longitude = None, None
    endereco_completo = "N/A"
    query_location = "CEP inválido"
    cep8 = limpar_cep(cep_original)
    
    if cep8:
        endereco_info = consultar_cep(cep8)
        if endereco_info and endereco_info.get('localidade'):
            endereco_completo = f"{endereco_info['logradouro']}, {endereco_info['localidade']}, {endereco_info['uf']}"
            query_location = f"{endereco_completo}, Brazil"
        else:
            endereco_completo = f"CEP {cep8_to_hifen(cep8)} não encontrado na API"
            query_location = f"{cep8_to_hifen(cep8)}, Brazil"
        
        # O ArcGIS não gosta de queries muito longas e vazias, vamos limpar
        if query_location.strip().startswith(','):
             query_location = query_location.strip()[1:].strip()

        location = geocode_func(query_location, timeout=10)
        if location:
            latitude = location.latitude
            longitude = location.longitude

    if latitude:
        print(f"\nCNPJ: {cnpj} | Buscando por: '{query_location}' -> SUCESSO: Lat={latitude:.6f}, Lon={longitude:.6f}")
    else:
        print(f"\nCNPJ: {cnpj} | Buscando por: '{query_location}' -> FALHA")

    return {
        'cnpj': cnpj, 'CEP': cep8, 'endereco_completo': endereco_completo,
        'latitude': latitude, 'longitude': longitude
    }, latitude is not None


def salvar_lote(conn, lote, nome_tabela):
    if not lote: return
    print(f"\nSalvando lote de {len(lote)} registros no banco de dados...")
    df_lote = pd.DataFrame(lote)
    df_lote.to_sql(nome_tabela, conn, if_exists='append', index=False)
    conn.commit()
    lote.clear()

# --- Lógica Principal com Retentativas ---
if __name__ == "__main__":
    # <-- MUDANÇA 2: Usar o geolocator ArcGIS
    geolocator = ArcGIS(user_agent="aislan_geocoding_app_v4/1.0 (contato: email@dominio.com)")
    # O ArcGIS é mais rápido, podemos usar um delay menor com segurança
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=0.5, max_retries=2, error_wait_seconds=5.0, swallow_exceptions=True)
    
    conn = None
    cnpjs_a_processar = []
    
    try:
        # 1. Conectar e preparar os dados
        print(f"Conectando ao banco de dados: {nome_banco_dados}")
        conn = sqlite3.connect(nome_banco_dados, timeout=20)

        df_principal = pd.read_sql_query(f"SELECT cnpj, CEP FROM {tabela_principal};", conn)
        try:
            df_existentes = pd.read_sql_query(f"SELECT cnpj FROM {tabela_coordenadas};", conn)
            cnpjs_ja_processados = set(df_existentes['cnpj'])
        except pd.io.sql.DatabaseError:
            cnpjs_ja_processados = set()
        
        print(f"Total de {len(cnpjs_ja_processados)} CNPJs com coordenadas já encontradas.")
        
        df_principal['cnpj'] = df_principal['cnpj'].astype(str).str.strip().str.replace(r'\D', '', regex=True)
        df_para_geocodificar = df_principal[~df_principal['cnpj'].isin(cnpjs_ja_processados)].copy()
        df_para_geocodificar.drop_duplicates(subset=['cnpj'], keep='first', inplace=True)
        
        cnpjs_a_processar = df_para_geocodificar.to_dict('records')
        
        if not cnpjs_a_processar:
            print("\nNenhuma nova empresa para geocodificar. O banco de dados está atualizado.")
        else:
            print(f"\n--- INICIANDO PROCESSAMENTO PRINCIPAL PARA {len(cnpjs_a_processar)} EMPRESAS ---")
            resultados_sucesso = []
            falhas_para_retentativa = []

            for row in tqdm(cnpjs_a_processar, desc="Processamento Principal"):
                # <-- MUDANÇA 3: Tratamento de erro individual para evitar que o script pare
                try:
                    resultado, sucesso = processar_geocoding(row, geocode)
                    if sucesso:
                        resultados_sucesso.append(resultado)
                    else:
                        falhas_para_retentativa.append(row)
                except Exception as e:
                    print(f"\nERRO CRÍTICO NO CNPJ {row.get('cnpj')}: {e}. Adicionando à lista de retentativas.")
                    falhas_para_retentativa.append(row)
                
                if len(resultados_sucesso) >= BATCH_SIZE:
                    salvar_lote(conn, resultados_sucesso, tabela_coordenadas)

            salvar_lote(conn, resultados_sucesso, tabela_coordenadas)

            if falhas_para_retentativa:
                print(f"\n--- INICIANDO RETENTATIVA PARA {len(falhas_para_retentativa)} EMPRESAS QUE FALHARAM ---")
                time.sleep(5)
                resultados_retentativa = []
                
                for row in tqdm(falhas_para_retentativa, desc="Retentativas"):
                    try:
                        resultado, sucesso = processar_geocoding(row, geocode)
                        if sucesso:
                            resultados_retentativa.append(resultado)
                    except Exception as e:
                         print(f"\nERRO CRÍTICO NA RETENTATIVA DO CNPJ {row.get('cnpj')}: {e}.")

                    if len(resultados_retentativa) >= BATCH_SIZE:
                        salvar_lote(conn, resultados_retentativa, tabela_coordenadas)

                salvar_lote(conn, resultados_retentativa, tabela_coordenadas)
            else:
                print("\nNenhuma falha registrada para retentativa.")

    except Exception as e:
        print(f"\nOcorreu um erro geral no script: {e}")
    finally:
        if conn:
            conn.close()
            print("\nProcesso finalizado. Conexão com o banco de dados fechada.")
            
import pandas as pd
import sqlite3

# Nomes do banco de dados e da tabela
nome_banco_dados = 'tabelao.db'
nome_tabela = 'coordenadas_empresas'

# Colunas para verificar duplicatas
colunas_para_verificar = ['cnpj', 'Cidade', 'CEP', 'latitude', 'longitude']

conn = None
try:
    print(f"Conectando ao banco de dados: {nome_banco_dados}")
    conn = sqlite3.connect(nome_banco_dados)
    
    # Lê todos os dados da tabela
    df_coordenadas = pd.read_sql_query(f"SELECT * FROM {nome_tabela};", conn)
    
    linhas_antes = len(df_coordenadas)
    print(f"Tabela lida com sucesso. Total de {linhas_antes} linhas.")
    
    # Remove as duplicatas com base nas colunas especificadas
    df_sem_duplicatas = df_coordenadas.drop_duplicates(subset=colunas_para_verificar, keep='last')
    
    linhas_depois = len(df_sem_duplicatas)
    linhas_removidas = linhas_antes - linhas_depois
    
    if linhas_removidas > 0:
        print(f"\n{linhas_removidas} linhas duplicadas removidas com sucesso!")
        
        # Opcional: Salve o DataFrame limpo de volta no banco de dados
        # df_sem_duplicatas.to_sql(nome_tabela, conn, if_exists='replace', index=False)
        # conn.commit()
        
    else:
        print("\nNenhuma duplicata encontrada com base nas colunas especificadas.")

    print(f"A tabela agora tem {linhas_depois} linhas únicas.")
    
except sqlite3.Error as e:
    print(f"Ocorreu um erro com o banco de dados: {e}")

finally:
    if conn:
        conn.close()
        print("\nConexão com o banco de dados fechada.")
        
import sqlite3
import pandas as pd
import os

# --- Configurações ---
DB_FILENAME = 'tabelao.db'
SOURCE_TABLE = 'tabelao'
OUTPUT_TABLE = 'gastos'

def criar_tabela_maiores_gastos(db_path, source_table, output_table):
    """
    Analisa os dados da tabela de origem, encontra o maior gastador por rubrica
    (unificando as rubricas de passagens aéreas) e salva o resultado em uma 
    nova tabela, substituindo-a se já existir.
    """
    if not os.path.exists(db_path):
        print(f"❌ ERRO: O arquivo do banco de dados '{db_path}' não foi encontrado.")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        print(f"✅ Conectado ao banco de dados: {db_path}")

        query = f"SELECT txtDescricao, nome, vlrLiquido FROM {source_table}"
        print(f"📊 Lendo e processando dados da tabela '{source_table}'...")
        df = pd.read_sql_query(query, conn)

        # --- Limpeza e Preparação ---
        df['vlrLiquido'] = pd.to_numeric(df['vlrLiquido'], errors='coerce')
        df.dropna(subset=['txtDescricao', 'nome', 'vlrLiquido'], inplace=True)
        df = df[df['vlrLiquido'] > 0]

        # --------------------------------------------------------------------
        #  >>> AJUSTE ADICIONADO AQUI <<<
        # Unifica todas as rubricas de passagem aérea em uma só.
        # A função .str.contains() procura o texto em qualquer parte da string.
        # O argumento 'na=False' trata possíveis valores nulos na coluna.
        print("🔧 Padronizando as rubricas de 'PASSAGEM AÉREA'...")
        df.loc[df['txtDescricao'].str.contains('PASSAGEM AÉREA', na=False), 'txtDescricao'] = 'PASSAGENS AÉREAS (TODAS)'
        # --------------------------------------------------------------------
        
        # --- Análise dos Dados ---
        print("⚙️  Calculando os maiores gastos por rubrica...")
        gastos_totais = df.groupby(['txtDescricao', 'nome'])['vlrLiquido'].sum().reset_index()
        idx = gastos_totais.groupby('txtDescricao')['vlrLiquido'].idxmax()
        resultado_final_df = gastos_totais.loc[idx]
        
        resultado_final_df = resultado_final_df.sort_values(by='vlrLiquido', ascending=False).reset_index(drop=True)

        print(f"💾 Gravando resultado na tabela '{output_table}'...")
        
        # --- Gravação no Banco de Dados ---
        resultado_final_df.to_sql(output_table, conn, if_exists='replace', index=False)
        print(f"✅ Tabela '{output_table}' criada/atualizada com sucesso com {len(resultado_final_df)} registros.")

        # --- Verificação ---
        print("\n" + "="*80)
        print(f"🔍 VERIFICANDO DADOS SALVOS NA TABELA '{output_table}' (primeiros 10 registros):")
        print("="*80)
        df_verificacao = pd.read_sql_query(f"SELECT * FROM {output_table} LIMIT 10", conn)
        df_verificacao['vlrLiquido'] = df_verificacao['vlrLiquido'].apply(
            lambda x: f'R$ {x:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        )
        print(df_verificacao.to_string(index=False))
        print("="*80 + "\n")

    except sqlite3.Error as e:
        print(f"❌ ERRO de SQL: {e}")
    except Exception as e:
        print(f"❌ Ocorreu um erro inesperado: {e}")
    finally:
        if conn:
            conn.close()
            print("🔌 Conexão com o banco de dados fechada.")


criar_tabela_maiores_gastos(DB_FILENAME, SOURCE_TABLE, OUTPUT_TABLE)
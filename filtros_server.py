#!/usr/bin/env python3
"""
Servidor simples para os filtros
"""
import sqlite3
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from datetime import datetime

app = FastAPI()

# Database path - using local tabelao.db
DB_PATH = "tabelao.db"

def get_partido_logo_url(sigla_partido):
    """Retorna URL do logo do partido"""
    logos = {
        'UNIÃO': 'https://upload.wikimedia.org/wikipedia/commons/thumb/7/73/Uni%C3%A3o_Brasil_logo.svg/72px-Uni%C3%A3o_Brasil_logo.svg.png',
        'PP': 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Progressistas_logotipo_%28cortado%29.png/72px-Progressistas_logotipo_%28cortado%29.png',
        'PV': 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/6e/PV_Logo.svg/72px-PV_Logo.svg.png',
        'PSB': 'https://upload.wikimedia.org/wikipedia/en/thumb/e/eb/Logo_of_the_Brazilian_Socialist_Party.svg/250px-Logo_of_the_Brazilian_Socialist_Party.svg.png',
        'PT': 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/PT_%28Brazil%29_logo_2021.svg/72px-PT_%28Brazil%29_logo_2021.svg.png',
        'REPUBLICANOS': 'https://images.seeklogo.com/logo-png/38/2/republicanos-10-logo-png_seeklogo-386777.png',
        'PDT': 'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e7/Logomarca_do_Partido_Democr%C3%A1tico_Trabalhista%2C_do_Brasil.png/71px-Logomarca_do_Partido_Democr%C3%A1tico_Trabalhista%2C_do_Brasil.png',
        'PSOL': 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/8d/Psol_ziraldo_%28cropped%29.png/72px-Psol_ziraldo_%28cropped%29.png',
        'PL': 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Logotipo_do_Partido_Liberal.svg/120px-Logotipo_do_Partido_Liberal.svg.png',
        'MDB': 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Movimento_Democr%C3%A1tico_Brasileiro_%282017%29.png/72px-Movimento_Democr%C3%A1tico_Brasileiro_%282017%29.png',
        'PODE': 'https://upload.wikimedia.org/wikipedia/commons/thumb/d/d8/Logo-podemos.png/72px-Logo-podemos.png',
        'PCdoB': 'https://upload.wikimedia.org/wikipedia/commons/thumb/d/d0/PCdoB_%28comprimido%29.png/62px-PCdoB_%28comprimido%29.png',
        'PSD': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/PSD_Brazil_logo.svg/72px-PSD_Brazil_logo.svg.png',
        'PSDB': 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/Brazilian_Social_Democracy_Party_2023_logo.png/72px-Brazilian_Social_Democracy_Party_2023_logo.png',
        'AVANTE': 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/93/AVANTE_Brazil_Logo.png/72px-AVANTE_Brazil_Logo.png',
        'CIDADANIA': 'https://upload.wikimedia.org/wikipedia/commons/thumb/d/db/Logomarca_Partido_Cidadania.png/72px-Logomarca_Partido_Cidadania.png',
        'SOLIDARIEDADE': 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/fe/Logomarca_do_Partido_Solidariedade.png/72px-Logomarca_do_Partido_Solidariedade.png',
        'NOVO': 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/b0/NOVO_Logo_2023.png/72px-NOVO_Logo_2023.png',
        'REDE': 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/ca/Logomarca_da_Rede_Sustentabilidade_%28REDE%29%2C_do_Brasil_%28cropped%29.png/72px-Logomarca_da_Rede_Sustentabilidade_%28REDE%29%2C_do_Brasil_%28cropped%29.png',
        'PRD': 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/54/Logomarca_Partido_Renova%C3%A7%C3%A3o_Democr%C3%A1tica.png/72px-Logomarca_Partido_Renova%C3%A7%C3%A3o_Democr%C3%A1tica.png',
        'MOBILIZA': 'https://upload.wikimedia.org/wikipedia/commons/thumb/7/7f/Logomarca_Partido_Mobiliza.png/72px-Logomarca_Partido_Mobiliza.png',
        'AGIR': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Logomarca_do_Partido_Agir.png/72px-Logomarca_do_Partido_Agir.png',
        'PRTB': 'https://upload.wikimedia.org/wikipedia/pt/thumb/f/f8/Prtb.jpg/72px-Prtb.jpg',
        'PMB': 'https://upload.wikimedia.org/wikipedia/pt/thumb/a/ac/Pmb_logo_site-300x104.png/72px-Pmb_logo_site-300x104.png',
        'PSTU': 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a6/Logo_PSTU.png/72px-Logo_PSTU.png',
        'PCB': 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/81/PCB_logo.svg/60px-PCB_logo.svg.png',
        'UP': 'https://upload.wikimedia.org/wikipedia/pt/thumb/0/00/Logo_-_UP_site.png/72px-Logo_-_UP_site.png',
        'PCO': 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/99/IMG3498Pco.png/72px-IMG3498Pco.png',
        'MISSÃO': 'https://commons.wikimedia.org/wiki/Special:FilePath/Logo_Partido_Missão.jpg',
        'S.PART': 'https://www.imagensempng.com.br/wp-content/uploads/2021/06/04-12.png'
    }
    return logos.get(sigla_partido, f'https://via.placeholder.com/72x72/cccccc/666666?text={sigla_partido}')

def get_estado_logo_url(sigla_estado):
    """Retorna URL da bandeira do estado"""
    bandeiras = {
        'AC': 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/Bandeira_do_Acre.svg/243px-Bandeira_do_Acre.svg.png',
        'AL': 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/88/Bandeira_de_Alagoas.svg/255px-Bandeira_de_Alagoas.svg.png',
        'AM': 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/Bandeira_do_Amazonas.svg/238px-Bandeira_do_Amazonas.svg.png',
        'BA': 'https://upload.wikimedia.org/wikipedia/commons/thumb/2/28/Bandeira_da_Bahia.svg/800px-Bandeira_da_Bahia.svg.png',
        'CE': 'https://i.ibb.co/g6dHqSw/Bandeira-do-Cear-svg.png',
        'ES': 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/43/Bandeira_do_Esp%C3%ADrito_Santo.svg/243px-Bandeira_do_Esp%C3%ADrito_Santo.svg.png',
        'AP': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/Bandeira_do_Amap%C3%A1.svg/640px-Bandeira_do_Amap%C3%A1.svg.png',
        'GO': 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/Flag_of_Goi%C3%A1s.svg/243px-Flag_of_Goi%C3%A1s.svg.png',
        'MA': 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Bandeira_do_Maranh%C3%A3o.svg/300px-Bandeira_do_Maranh%C3%A3o.svg.png',
        'MT': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0b/Bandeira_de_Mato_Grosso.svg/243px-Bandeira_de_Mato_Grosso.svg.png',
        'MS': 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/64/Bandeira_de_Mato_Grosso_do_Sul.svg/243px-Bandeira_de_Mato_Grosso_do_Sul.svg.png',
        'MG': 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f4/Bandeira_de_Minas_Gerais.svg/243px-Bandeira_de_Minas_Gerais.svg.png',
        'PA': 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/02/Bandeira_do_Par%C3%A1.svg/1200px-Bandeira_do_Par%C3%A1.svg.png',
        'PB': 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/bb/Bandeira_da_Para%C3%ADba.svg/300px-Bandeira_da_Para%C3%ADba.svg.png',
        'PR': 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/93/Bandeira_do_Paran%C3%A1.svg/300px-Bandeira_do_Paran%C3%A1.svg.png',
        'PE': 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Bandeira_de_Pernambuco.svg/1200px-Bandeira_de_Pernambuco.svg.png',
        'PI': 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/33/Bandeira_do_Piau%C3%AD.svg/255px-Bandeira_do_Piau%C3%AD.svg.png',
        'RN': 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/42/Bandeira_do_Rio_Grande_do_Norte_%28original%29.png/1200px-Bandeira_do_Rio_Grande_do_Norte_%28original%29.png',
        'RS': 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/63/Bandeira_do_Rio_Grande_do_Sul.svg/243px-Bandeira_do_Rio_Grande_do_Sul.svg.png',
        'RJ': 'https://upload.wikimedia.org/wikipedia/commons/thumb/7/73/Bandeira_do_estado_do_Rio_de_Janeiro.svg/275px-Bandeira_do_estado_do_Rio_de_Janeiro.svg.png',
        'RO': 'https://i.ibb.co/092QwtK/Bandeira-de-Rond-nia-svg.png',
        'RR': 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/98/Bandeira_de_Roraima.svg/1200px-Bandeira_de_Roraima.svg.png',
        'SC': 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/Bandeira_de_Santa_Catarina.svg/300px-Bandeira_de_Santa_Catarina.svg.png',
        'SP': 'https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/Bandeira_do_estado_de_S%C3%A3o_Paulo.svg/300px-Bandeira_do_estado_de_S%C3%A3o_Paulo.svg.png',
        'SE': 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/Bandeira_de_Sergipe.svg/1200px-Bandeira_de_Sergipe.svg.png',
        'TO': 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/ff/Bandeira_do_Tocantins.svg/1200px-Bandeira_do_Tocantins.svg.png',
        'DF': 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Bandeira_do_Distrito_Federal_%28Brasil%29.svg/800px-Bandeira_do_Distrito_Federal_%28Brasil%29.svg.png'
    }
    return bandeiras.get(sigla_estado, f'https://via.placeholder.com/300x200/cccccc/666666?text={sigla_estado}')

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/filtros/estados")
async def get_estados():
    """Retorna lista de estados"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT DISTINCT sgUF FROM tabelao WHERE sgUF IS NOT NULL ORDER BY sgUF"
        df = pd.read_sql_query(query, conn)
        conn.close()
        estados = df['sgUF'].tolist()
        return {"estados": estados}
    except Exception as e:
        print(f"Erro ao carregar estados: {e}")
        return {"estados": []}

@app.get("/api/filtros/partidos")
async def get_partidos(estado: str = None):
    """Retorna lista de partidos filtrados por estado"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT DISTINCT sgPartido FROM tabelao WHERE sgPartido IS NOT NULL"
        params = []
        if estado and estado != 'Todos':
            query += " AND sgUF = ?"
            params.append(estado)
        query += " ORDER BY sgPartido"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        partidos = df['sgPartido'].tolist()
        return {"partidos": partidos}
    except Exception as e:
        print(f"Erro ao carregar partidos: {e}")
        return {"partidos": []}

@app.get("/api/filtros/parlamentares")
async def get_parlamentares(estado: str = None, partido: str = None, partido_atual: str = None):
    """Retorna lista de parlamentares filtrados por estado e partido"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT DISTINCT nome FROM tabelao WHERE nome IS NOT NULL"
        params = []
        if estado and estado != 'Todos':
            query += " AND sgUF = ?"
            params.append(estado)
        partido_filtrar = partido or partido_atual
        if partido_filtrar and partido_filtrar != 'Todos':
            query += " AND sgPartido = ?"
            params.append(partido_filtrar)
        query += " ORDER BY nome"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        parlamentares = df['nome'].tolist()
        return {"parlamentares": parlamentares}
    except Exception as e:
        print(f"Erro ao carregar parlamentares: {e}")
        return {"parlamentares": []}

@app.get("/api/filtros/despesas")
async def get_despesas():
    """Retorna lista de tipos de despesa"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT DISTINCT txtDescricao FROM tabelao WHERE txtDescricao IS NOT NULL ORDER BY txtDescricao"
        df = pd.read_sql_query(query, conn)
        conn.close()
        despesas = df['txtDescricao'].tolist()
        return {"despesas": despesas}
    except Exception as e:
        return {"despesas": []}

@app.get("/api/filtros/despesas-parlamentar")
async def get_despesas_parlamentar(parlamentar: str, estado: str = None, partido: str = None):
    """Retorna lista de tipos de despesa para um parlamentar específico"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT DISTINCT txtDescricao FROM tabelao WHERE nome = ?"
        params = [parlamentar]
        if estado and estado != 'Todos':
            query += " AND sgUF = ?"
            params.append(estado)
        if partido and partido != 'Todos':
            query += " AND sgPartido = ?"
            params.append(partido)
        query += " ORDER BY txtDescricao"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        despesas = df['txtDescricao'].tolist()
        return {"despesas": despesas}
    except Exception as e:
        print(f"Erro ao carregar despesas do parlamentar: {e}")
        return {"despesas": []}

@app.get("/api/gastos/dados-parlamentar")
async def get_dados_parlamentar(parlamentar: str, estado: str = None, partido: str = None, despesa: str = None):
    """Retorna dados do parlamentar para análise de gastos"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT * FROM tabelao WHERE nome = ?"
        params = [parlamentar]
        if estado and estado != 'Todos':
            query += " AND sgUF = ?"
            params.append(estado)
        if partido and partido != 'Todos':
            query += " AND sgPartido = ?"
            params.append(partido)
        if despesa and despesa != 'Todos':
            query += " AND txtDescricao LIKE ?"
            params.append(f"%{despesa}%")
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        # Converter para formato compatível com o frontend
        dados = []
        for _, row in df.iterrows():
            dados.append({
                "data": row['datEmissao'],
                "fornecedor": row['txtFornecedor'],
                "descricao": row['txtDescricao'],
                "valor": row['vlrLiquido'],
                "estado": row['sgUF'],
                "cnpj": row['txtCNPJCPF'],
                "numero_nota": row['txtNumero'],
                "url_documento": row.get('urlDocumento', ''),
                "parlamentar": row['nome'],
                "partido": row['sgPartido']
            })
        
        # Calcular métricas básicas
        total_gasto = df['vlrLiquido'].sum() if not df.empty else 0
        num_notas = len(dados)
        media_gasto = total_gasto / num_notas if num_notas > 0 else 0
        
        # Calcular limite atípico (2 desvios padrão)
        if not df.empty and len(df) > 1:
            desvio_padrao = df['vlrLiquido'].std()
            limite_atipico = media_gasto + (2 * desvio_padrao)
        else:
            limite_atipico = media_gasto * 2
        
        # Dados temporais (agrupar por ano/mês)
        dados_temporais = []
        if not df.empty:
            df['ano_mes'] = df['numAno'].astype(str) + '-' + df['numMes'].astype(str).str.zfill(2)
            temporal = df.groupby('ano_mes')['vlrLiquido'].sum().reset_index()
            temporal.columns = ['periodo', 'valor']
            dados_temporais = temporal.to_dict('records')
        
        # Top fornecedores
        top_fornecedores = []
        if not df.empty:
            fornecedores = df.groupby(['txtFornecedor', 'txtCNPJCPF'])['vlrLiquido'].agg(['sum', 'count']).reset_index()
            fornecedores.columns = ['fornecedor', 'cnpj', 'total', 'num_notas']
            fornecedores = fornecedores.sort_values('total', ascending=False).head(10)
            top_fornecedores = fornecedores.to_dict('records')
        
        # Info do parlamentar
        info_parlamentar = None
        if not df.empty:
            primeiro_registro = df.iloc[0]
            info_parlamentar = {
                "nome": primeiro_registro['nome'],
                "partido": primeiro_registro['sgPartido'],
                "estado": primeiro_registro['sgUF'],
                "despesa": despesa,
                "foto_url": f"https://www.camara.leg.br/internet/deputado/bandep/{primeiro_registro['ideCadastro']}.jpg",
                "partido_logo_url": get_partido_logo_url(primeiro_registro['sgPartido']),
                "estado_logo_url": get_estado_logo_url(primeiro_registro['sgUF'])
            }
        
        return {
            "success": True,
            "dados": dados,
            "total_registros": len(dados),
            "parlamentar": parlamentar,
            "filtros": {"estado": estado, "partido": partido, "despesa": despesa},
            "metricas_basicas": {
                "total_gasto": total_gasto,
                "num_notas": num_notas,
                "media_gasto": media_gasto,
                "limite_atipico": limite_atipico
            },
            "dados_temporais": dados_temporais,
            "top_fornecedores": top_fornecedores,
            "info_parlamentar": info_parlamentar
        }
    except Exception as e:
        print(f"Erro ao carregar dados do parlamentar: {e}")
        return {"success": False, "error": str(e), "dados": []}

@app.get("/api/gastos/ranking-geral")
async def get_ranking_geral(estado: str = None, partido: str = None, despesa: str = None):
    """Endpoint para ranking geral de gastos"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = """
        SELECT 
            nome, sgUF, sgPartido, txtDescricao,
            SUM(vlrLiquido) as total_gasto,
            COUNT(*) as num_notas,
            ideCadastro
        FROM tabelao 
        WHERE 1=1
        """
        params = []
        if estado and estado != 'Todos':
            query += " AND sgUF = ?"
            params.append(estado)
        if partido and partido != 'Todos':
            query += " AND sgPartido = ?"
            params.append(partido)
        if despesa and despesa != 'Todos':
            query += " AND UPPER(txtDescricao) LIKE UPPER(?)"
            params.append(f'%{despesa}%')
        
        query += """
        GROUP BY nome, sgUF, sgPartido, txtDescricao, ideCadastro
        ORDER BY total_gasto DESC
        LIMIT 50
        """
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        ranking = []
        for _, row in df.iterrows():
            ranking.append({
                "nome": row['nome'],
                "sgUF": row['sgUF'],
                "sgPartido": row['sgPartido'],
                "txtDescricao": row['txtDescricao'],
                "total_gasto": float(row['total_gasto']),
                "num_notas": int(row['num_notas']),
                "ideCadastro": row['ideCadastro'],
                "ultimoStatus_urlFoto": f"https://www.camara.leg.br/internet/deputado/bandep/{row['ideCadastro']}.jpg",
                "URL_Estado": get_estado_logo_url(row['sgUF']),
                "URL_Partido": get_partido_logo_url(row['sgPartido'])
            })
        return {"success": True, "ranking": ranking, "total": len(ranking)}
    except Exception as e:
        print(f"Erro ao carregar ranking geral: {e}")
        return {"success": False, "error": str(e), "ranking": []}

@app.get("/api/contatos/deputado/{ideCadastro}")
async def get_contatos_deputado(ideCadastro: str):
    """Busca contatos do deputado na API da Câmara"""
    try:
        import requests
        url = f"https://dadosabertos.camara.leg.br/api/v2/deputados/{ideCadastro}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            deputado = data.get('dados', {})
            ultimo_status = deputado.get('ultimoStatus', {})
            gabinete_status = ultimo_status.get('gabinete', {})
            contatos = {
                "nome": deputado.get('nomeCivil', ultimo_status.get('nome', '')),
                "email": gabinete_status.get('email', ''),
                "telefone": gabinete_status.get('telefone', ''),
                "gabinete": gabinete_status,
                "ultimoStatus": ultimo_status
            }
            return {"success": True, "contatos": contatos}
        return {"success": False, "error": "Deputado não encontrado"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    print(f"🔧 Iniciando servidor de filtros na porta 8006 (DB: {DB_PATH})...")
    uvicorn.run(app, host="0.0.0.0", port=8006)

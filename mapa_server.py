import os
import sys
import json
import sqlite3
import pandas as pd
import duckdb
import folium
try:
    from folium import JsCode
except ImportError:
    try:
        from folium.utilities import JsCode
    except ImportError:
        # Fallback para versões muito antigas ou se tudo falhar
        from branca.element import Element as JsCode
from folium.plugins import HeatMap, MarkerCluster
import branca
import unicodedata
import tempfile
import shutil
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import hashlib
from openai import OpenAI
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# Configuração do cliente OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Configuração do Cache LLM
LLM_CACHE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_cache.db")

def init_llm_cache():
    conn = sqlite3.connect(LLM_CACHE_DB)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_cache (
            hash_id TEXT PRIMARY KEY,
            parlamentar TEXT,
            prompt TEXT,
            response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# Inicializar cache ao iniciar
init_llm_cache()
# Configuração básica
app = FastAPI(title="Mapa Eleitoral Server Local")

# Configurar CORS para permitir requisições do frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, restringir para a URL do frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/status")
async def mapa_status():
    return {"status": "ok", "service": "mapa-eleitoral"}

# Diretório base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Caminhos dos bancos de dados — prioriza bancos/ subdirectory
def _local_db_mapa(name, subdir=None):
    if subdir:
        in_bancos = os.path.join(BASE_DIR, "bancos", subdir, name)
        in_root = os.path.join(BASE_DIR, subdir, name)
    else:
        in_bancos = os.path.join(BASE_DIR, "bancos", name)
        in_root = os.path.join(BASE_DIR, name)
    return in_bancos if os.path.exists(in_bancos) and os.path.getsize(in_bancos) > 0 else in_root

DATABASE_PATHS_LOCAL = {
    "tabelao": _local_db_mapa("tabelao.db"),
    "votacao": _local_db_mapa("votacao.duckdb")
}

# Verificar disponibilidade do DuckDB
try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False
    print("⚠️ DuckDB não instalado. Mapa eleitoral não funcionará.")

from shapely.geometry import shape, Point

# Carregar GeoJSON dos estados
ESTADOS_GEOJSON = {}
try:
    with open(os.path.join(BASE_DIR, "mapa", "br_states.json"), "r", encoding="utf-8") as f:
        geojson_data = json.load(f)
        for feature in geojson_data["features"]:
            sigla = feature["properties"]["SIGLA"]
            ESTADOS_GEOJSON[sigla] = shape(feature["geometry"])
    print(f"✅ GeoJSON dos estados carregado: {len(ESTADOS_GEOJSON)} estados")
except Exception as e:
    print(f"❌ Erro ao carregar GeoJSON dos estados: {e}")

def get_db_connection(db_name):
    """Retorna conexão com o banco de dados especificado"""
    if db_name not in DATABASE_PATHS_LOCAL:
        raise ValueError(f"Banco de dados desconhecido: {db_name}")
    
    db_path = DATABASE_PATHS_LOCAL[db_name]
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Banco de dados não encontrado: {db_path}")
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def normalizar(texto):
    """Remove acentos e converte para maiúsculas"""
    if not isinstance(texto, str):
        return str(texto)
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('ASCII').upper()

@app.get("/api/mapa-eleitoral/votos/{nome_parlamentar}")
def get_votos_deputado(
    nome_parlamentar: str,
    estado: Optional[str] = None,
    partido: Optional[str] = None
):
    """Carrega dados de votação de um deputado específico, agrega por município e gera mapa Folium"""
    try:
        if not DUCKDB_AVAILABLE:
            raise HTTPException(status_code=500, detail="DuckDB não disponível")
        
        votacao_db = DATABASE_PATHS_LOCAL["votacao"]
        if not os.path.exists(votacao_db):
            raise HTTPException(status_code=404, detail="Banco de votação não encontrado")
        
        # PRIMEIRO: Buscar o nomeCivil no tabelao.db usando o nome parlamentar (nome eleitoral)
        conn_tabelao = get_db_connection("tabelao")
        query_nome_civil = """
            SELECT *
            FROM tabelao
            WHERE nome = ?
              AND ultimoStatus_idLegislatura = 57
            LIMIT 1
        """
        df_nome_civil = pd.read_sql_query(query_nome_civil, conn_tabelao, params=[nome_parlamentar])
        conn_tabelao.close()
        
        # Preparar lista de nomes para tentar (nomeCivil primeiro, depois nome eleitoral)
        nomes_para_tentar = []
        uf_oficial = None
        partido_oficial = None
        info_parlamentar = {}
        municipios_data = [] # Inicialização defensiva

        if not df_nome_civil.empty:
            row_oficial = df_nome_civil.iloc[0]
            if pd.notna(row_oficial.get('sgUF')):
                uf_oficial = str(row_oficial['sgUF']).strip().upper()
            if pd.notna(row_oficial.get('sgPartido')):
                partido_oficial = str(row_oficial['sgPartido']).strip().upper()
            if pd.notna(row_oficial.get('nomeCivil')):
                nome_civil = row_oficial['nomeCivil']
                if nome_civil != nome_parlamentar:
                    nomes_para_tentar.append(("nomeCivil", nome_civil))
                    print(f"📋 Nome eleitoral: {nome_parlamentar} -> Nome civil: {nome_civil}")
            
            # Tentar pegar URL da foto e logo com nomes variados
            foto = row_oficial.get('ultimoStatus_urlFoto') or row_oficial.get('urlFoto')
            logo = row_oficial.get('URL_Partido') or row_oficial.get('urlPartidoLogo') or row_oficial.get(' URL_Partido')

            info_parlamentar = {
                "nome": row_oficial.get('nome'),
                "nomeCivil": row_oficial.get('nomeCivil'),
                "partido": row_oficial.get('sgPartido'),
                "estado": row_oficial.get('sgUF'),
                "foto": foto,
                "logoPartido": logo,
                "estado_logo_url": row_oficial.get('URL_Estado') or row_oficial.get('URL_Estado')
            }

        nomes_para_tentar.append(("nomeEleitoral", nome_parlamentar))
        
        temp_copy_path = None
        try:
            conn_votacao = duckdb.connect(votacao_db, read_only=True)
        except duckdb.IOException as duck_ex:
            try:
                fd, temp_path = tempfile.mkstemp(suffix=".duckdb")
                os.close(fd)
                shutil.copy2(votacao_db, temp_path)
                temp_copy_path = temp_path
                conn_votacao = duckdb.connect(temp_copy_path, read_only=True)
                print("ℹ️  Arquivo votacao.duckdb estava bloqueado. Utilizando cópia temporária somente leitura.")
            except Exception as copy_ex:
                print(f"⚠️  Erro ao criar cópia temporária do votacao.duckdb: {copy_ex}")
                raise duck_ex

        # Se achou no tabelao, vamos usar esses nomes para buscar no DuckDB
        nomes_para_tentar = []
        nome_real_no_banco = None
        if info_parlamentar:
            nomes_para_tentar.append(('nomeCivil', info_parlamentar['nomeCivil']))
            nomes_para_tentar.append(('nome', info_parlamentar['nome']))
        
        nomes_para_tentar.append(('original', nome_parlamentar))
        
        # Buscar no DuckDB
        # Vamos pegar todos os nomes distintos do DuckDB para comparar
        # Isso pode ser pesado, então vamos tentar query direta primeiro
        
        # Otimização: Buscar apenas nomes que contêm partes do nome buscado
        # Mas o DuckDB é rápido.
        
        # Tentar encontrar o nome exato no banco
        # Tentar encontrar o nome exato no banco
        for tipo, nome_tentativa in nomes_para_tentar:
            if not nome_tentativa:
                continue
                
            nome_normalizado = normalizar(nome_tentativa)
            print(f"🔍 Tentando buscar por {tipo}: '{nome_tentativa}' (Norm: '{nome_normalizado}')")
            
            # Verificar se existe algum registro com esse nome
            # Usando strip_accents e upper para garantir match
            check_query = f"""
                SELECT NM_PARLAMENTAR 
                FROM votacao 
                WHERE strip_accents(upper(NM_PARLAMENTAR)) = '{nome_normalizado}'
                LIMIT 1
            """
            try:
                result = conn_votacao.execute(check_query).fetchone()
                if result:
                    nome_real_no_banco = result[0]
                    print(f"✅ Encontrado no DuckDB ({tipo}): {nome_real_no_banco}")
                    break
            except Exception as e:
                print(f"⚠️ Erro ao verificar nome '{nome_tentativa}': {e}")

        # --- FALLBACK 1: Busca por partes do Nome Parlamentar ---
        if not nome_real_no_banco:
            print(f"⚠️ Tentando busca por partes do nome parlamentar: {nome_parlamentar}")
            partes_parlamentar = normalizar(nome_parlamentar).split()
            if len(partes_parlamentar) >= 2:
                # Monta query dinâmica: LIKE '%PART1%' AND LIKE '%PART2%' ...
                conditions = []
                for p in partes_parlamentar:
                    if len(p) > 2: # Ignora preposições curtas
                        conditions.append(f"strip_accents(upper(NM_PARLAMENTAR)) LIKE '%{p}%'")
                
                if conditions:
                    fallback_query_1 = f"""
                        SELECT DISTINCT NM_PARLAMENTAR 
                        FROM votacao 
                        WHERE {' AND '.join(conditions)}
                    """
                    try:
                        candidates = conn_votacao.execute(fallback_query_1).fetchall()
                        if candidates:
                            # Se houver múltiplos, tentamos achar o mais curto ou similar
                            # Mas geralmente retorna o correto
                            nome_real_no_banco = candidates[0][0]
                            print(f"✅ Encontrado por partes do nome parlamentar: {nome_real_no_banco}")
                    except Exception as e:
                        print(f"⚠️ Erro na busca por partes do parlamentar: {e}")

        # --- FALLBACK 2: Busca Inteligente por Partes do Nome Civil ---
        if not nome_real_no_banco and info_parlamentar and info_parlamentar.get('nomeCivil'):
            print("⚠️ Tentando busca inteligente por partes do nome civil...")
            nome_civil = normalizar(info_parlamentar['nomeCivil'])
            partes = nome_civil.split()
            
            if len(partes) >= 2:
                primeiro = partes[0]
                ultimo = partes[-1]
                
                # Se o segundo nome não for abreviado (não termina com ponto), usa ele também
                segundo = ""
                if len(partes) > 2 and not partes[1].endswith('.'):
                    segundo = partes[1]
                
                conditions = [f"strip_accents(upper(NM_PARLAMENTAR)) LIKE '%{primeiro}%'"]
                if segundo:
                    conditions.append(f"strip_accents(upper(NM_PARLAMENTAR)) LIKE '%{segundo}%'")
                conditions.append(f"strip_accents(upper(NM_PARLAMENTAR)) LIKE '%{ultimo}%'")
                
                fallback_query_2 = f"""
                    SELECT DISTINCT NM_PARLAMENTAR 
                    FROM votacao 
                    WHERE {' AND '.join(conditions)}
                """
                try:
                    candidates = conn_votacao.execute(fallback_query_2).fetchall()
                    if candidates:
                        nome_real_no_banco = candidates[0][0]
                        print(f"✅ Encontrado por busca inteligente civil: {nome_real_no_banco}")
                except Exception as e:
                    print(f"⚠️ Erro na busca inteligente civil: {e}")
        # -------------------------------------------------------
        
        if not nome_real_no_banco:
            return {"error": f"Parlamentar '{nome_parlamentar}' não encontrado na base de votação."}

        # 4. Buscar dados de votação (agrupados por município/seção)
        # Vamos buscar as coordenadas das seções onde ele teve voto
        
        # Filtro de segurança por estado (se disponível)
        estado_deputado = info_parlamentar.get('estado')
        if estado_deputado:
            estado_deputado = estado_deputado.strip().upper()
            
        filtro_estado_sql = ""
        if estado_deputado:
            filtro_estado_sql = f"AND SG_UF = '{estado_deputado}'"
            print(f"🔒 Aplicando filtro SQL por estado: {estado_deputado}")

        # Query base por sessão eleitoral, preservando zona/seção para posterior consolidação por coordenada.
        query_secoes = f"""
            SELECT
                NM_MUNICIPIO, SG_UF, NR_ZONA, NR_SECAO,
                FIRST(LAT) AS LAT, FIRST(LONG) AS LONG,
                MAX(NM_LOCAL_VOTACAO) as local_votacao,
                MAX(DS_ENDERECO) as endereco,
                MAX(NM_BAIRRO) as bairro,
                MAX(QT_VOTOS_NOMINAIS) as total_votos,
                1 as qtd_secoes
            FROM votacao
            WHERE NM_PARLAMENTAR = '{nome_real_no_banco.replace("'", "''")}'
              AND LAT IS NOT NULL AND LONG IS NOT NULL
              {filtro_estado_sql}
            GROUP BY NM_MUNICIPIO, SG_UF, NR_ZONA, NR_SECAO
            HAVING total_votos > 0
            ORDER BY total_votos DESC
        """
        
        df_secoes = conn_votacao.execute(query_secoes).fetchdf()
        conn_votacao.close()
        
        if df_secoes.empty:
            return {"error": "Nenhum voto com geolocalização encontrado para este parlamentar."}

        # --- FILTRO DE POLÍGONO (SEGURANÇA) ---
        # Bypass temporário para evitar que discrepâncias de precisão ocultem 100% dos dados.
        # Confiamos no filtro SQL por estado (SG_UF) que já foi aplicado.
        print(f"✅ Filtro de polígono ignorado para {estado_deputado}. Exibindo todos os votos geolocalizados.")
        # ---------------------------------------
        # ---------------------------------------

        # Preparar dados para resposta
        total_votos = int(df_secoes['total_votos'].sum())
        total_municipios = int(df_secoes['NM_MUNICIPIO'].nunique())
        total_secoes = int(df_secoes['qtd_secoes'].sum())

        def valores_unicos_ordenados(series):
            valores = []
            vistos = set()
            for value in series:
                if pd.isna(value):
                    continue
                texto = str(value).strip()
                if not texto or texto in vistos:
                    continue
                vistos.add(texto)
                valores.append(texto)
            return valores

        df_coordenadas = df_secoes.groupby(['LAT', 'LONG']).agg({
            'NM_MUNICIPIO': 'first',
            'SG_UF': 'first',
            'local_votacao': lambda s: valores_unicos_ordenados(s),
            'endereco': lambda s: valores_unicos_ordenados(s),
            'bairro': lambda s: valores_unicos_ordenados(s),
            'NR_ZONA': lambda s: valores_unicos_ordenados(s),
            'NR_SECAO': lambda s: valores_unicos_ordenados(s),
            'total_votos': 'sum',
            'qtd_secoes': 'sum',
        }).reset_index()

        df_coordenadas['quantidade_zonas'] = df_coordenadas['NR_ZONA'].apply(len)
        df_coordenadas['quantidade_secoes'] = df_coordenadas['NR_SECAO'].apply(len)
        
        # Top Municípios
        top_municipios_df = df_secoes.groupby(['NM_MUNICIPIO', 'SG_UF'])['total_votos'].sum().reset_index().sort_values('total_votos', ascending=False).head(20)
        top_municipios = top_municipios_df.to_dict('records')
        
        principal_reduto = top_municipios[0]['NM_MUNICIPIO'] if top_municipios else "N/A"

        # Gerar Mapa Folium
        # Centro do mapa: média das coordenadas ou centro do estado
        center_lat = df_coordenadas['LAT'].mean()
        center_long = df_coordenadas['LONG'].mean()
        
        m = folium.Map(location=[center_lat, center_long], zoom_start=6, tiles="cartodbpositron")
        
        if not df_coordenadas.empty:
            heat_data = [[row['LAT'], row['LONG'], row['total_votos']] for _, row in df_coordenadas.iterrows()]
            HeatMap(heat_data, radius=15, blur=10, max_zoom=10).add_to(m)

        # 2. Adicionar Círculos por Município (Camada Principal)
        # Agrupar por município para pegar centroide e total de votos
        df_municipios_geo = df_coordenadas.groupby(['NM_MUNICIPIO', 'SG_UF']).agg({
            'total_votos': 'sum',
            'LAT': 'mean',
            'LONG': 'mean'
        }).reset_index()

        # REMOVIDO: Círculos verdes grandes que atrapalhavam a visualização
        # for _, row in df_municipios_geo.iterrows():
        #     # Tamanho do círculo proporcional aos votos
        #     radius = min(max(row['total_votos'] / 10, 200), 10000)
            
        #     popup_html = f"""
        #     <div style="font-family: Arial; min-width: 150px;">
        #         <b>{row['NM_MUNICIPIO']} - {row['SG_UF']}</b><br>
        #         Votos: {row['total_votos']:,}
        #     </div>
        #     """
            
        #     folium.Circle(
        #         location=[row['LAT'], row['LONG']],
        #         radius=radius,
        #         popup=folium.Popup(popup_html, max_width=300),
        #         tooltip=f"{row['NM_MUNICIPIO']}: {row['total_votos']} votos",
        #         color="#009739",
        #         fill=True,
        #         fill_color="#009739",
        #         fill_opacity=0.4
        #     ).add_to(m)
        
        # 3. Adicionar Pontos das Seções (MarkerCluster para não poluir)
        # Customizar ícone do cluster para mostrar SOMA de votos
        icon_create_function = """
        function(cluster) {
            var markers = cluster.getAllChildMarkers();
            var sum = 0;
            for (var i = 0; i < markers.length; i++) {
                sum += markers[i].options.votes || 0;
            }
            
            var c = ' marker-cluster-';
            if (sum < 1000) {
                c += 'small';
            } else if (sum < 10000) {
                c += 'medium';
            } else {
                c += 'large';
            }
            
            return new L.DivIcon({
                html: '<div><span>' + sum.toLocaleString('pt-BR') + '</span></div>',
                className: 'marker-cluster' + c,
                iconSize: new L.Point(40, 40)
            });
        }
        """
        
        marker_cluster = MarkerCluster(
            name="Locais de Votação",
            icon_create_function=icon_create_function
        ).add_to(m)
        
        df_secoes_sample = df_coordenadas
        
        # Criar GeoJSON features
        features = []
        for _, row in df_secoes_sample.iterrows():
            locais = row['local_votacao'] if isinstance(row['local_votacao'], list) else []
            bairros = row['bairro'] if isinstance(row['bairro'], list) else []
            zonas = row['NR_ZONA'] if isinstance(row['NR_ZONA'], list) else []
            secoes = row['NR_SECAO'] if isinstance(row['NR_SECAO'], list) else []
            local = locais[0] if locais else "Local desconhecido"
            bairro = bairros[0] if bairros else "Bairro desconhecido"
            
            popup_content = f"""
            <div style="font-family: Arial; min-width: 200px;">
                <b>{local}</b><br>
                {bairro} - {row['NM_MUNICIPIO']}/{row['SG_UF']}<br>
                <b>Votos: {int(row['total_votos']):,}</b>
            </div>
            """.replace(",", ".") # Trocar vírgula por ponto para padrão BR
            
            feature = {
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [row['LONG'], row['LAT']]
                },
                'properties': {
                    'votes': int(row['total_votos']),
                    'popup': popup_content
                }
            }
            features.append(feature)
            
        # Usar GeoJson com point_to_layer para garantir que 'votes' seja passado nas opções
        folium.GeoJson(
            {'type': 'FeatureCollection', 'features': features},
            point_to_layer=JsCode("""
                function(feature, latlng) {
                    return L.circleMarker(latlng, {
                        radius: 5,
                        color: '#003366',
                        fill: true,
                        fillColor: '#003366',
                        fillOpacity: 0.8,
                        votes: feature.properties.votes // Passar votos para opções do Leaflet
                    }).bindPopup(feature.properties.popup);
                }
            """)
        ).add_to(marker_cluster)

        folium.LayerControl().add_to(m)
        
        # Preparar lista de municípios para retorno JSON (mantendo para compatibilidade se necessário, ou para o gráfico)
        df_municipios_geo = df_municipios_geo.sort_values('total_votos', ascending=False)
        
        # Renomear colunas para o padrão esperado pelo frontend
        df_municipios_geo = df_municipios_geo.rename(columns={
            'NM_MUNICIPIO': 'municipio',
            'SG_UF': 'estado'
        })
        
        municipios_data = df_municipios_geo.to_dict('records')

        # --- NOVO: Agrupamento por BAIRROS ---
        # IMPORTANTE: Usar 'bairro' pois foi esse o alias dado na query SQL
        df_bairros = df_secoes.groupby(['bairro', 'NM_MUNICIPIO', 'SG_UF'])['total_votos'].sum().reset_index()
        df_bairros = df_bairros.sort_values('total_votos', ascending=False)
        
        # Calcular percentual
        df_bairros['percentual'] = (df_bairros['total_votos'] / total_votos) * 100
        
        # Renomear para frontend (bairro já está correto, renomear os outros)
        df_bairros = df_bairros.rename(columns={
            'NM_MUNICIPIO': 'municipio',
            'SG_UF': 'estado'
        })
        
        bairros_data = df_bairros.to_dict('records')
        # -------------------------------------

        secoes_data = df_secoes_sample.rename(columns={
            'NM_MUNICIPIO': 'municipio',
            'SG_UF': 'estado',
            'LAT': 'lat',
            'LONG': 'lng'
        }).to_dict('records')
                
        mapa_html = m._repr_html_()
        
        return {
            "success": True,
            "info": info_parlamentar,
            "stats": {
                "total_votos": total_votos,
                "total_municipios": total_municipios,
                "total_secoes": total_secoes,
                "principal_reduto": principal_reduto
            },
            "zonas": secoes_data,
            "municipios": municipios_data,
            "bairros": bairros_data, # Adicionado retorno de bairros
            "topMunicipios": municipios_data[:20],
            "mapa_html": mapa_html
        }
    except Exception as e:
        print(f"Erro ao gerar mapa: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}



def get_llm_analysis(parlamentar, top_locais_text, partido=None):
    # 1. Gerar Hash para Cache
    # Incluir partido no hash para garantir que mudanças de contexto invalidem o cache antigo se necessário
    prompt_input = f"{parlamentar}|{partido}|{top_locais_text}"
    hash_id = hashlib.md5(prompt_input.encode()).hexdigest()
    
    # 2. Verificar Cache
    conn = sqlite3.connect(LLM_CACHE_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT response FROM llm_cache WHERE hash_id = ?", (hash_id,))
    cached = cursor.fetchone()
    
    if cached:
        conn.close()
        print(f"🧠 Cache hit para {parlamentar}")
        return cached[0]
    
    # 3. Se não tiver cache, chamar OpenAI
    print(f"🧠 Gerando nova análise para {parlamentar} ({partido})...")
    
    system_prompt = """
    Você é um cientista político sênior e analista de dados demográficos.
    Sua tarefa é gerar uma análise OBJETIVA e baseada em dados sobre o perfil do eleitorado de um parlamentar.
    
    DIRETRIZES ESTRITAS:
    1. EVITE ESPECULAÇÕES sobre motivações subjetivas ("sentimentos", "esperanças"). Foque em fatos e alinhamento político.
    2. COMPARE O IDH: Ao mencionar o IDH das cidades/bairros, compare explicitamente com a média do Brasil (~0.760). Diga se é acima, abaixo ou na média.
    3. PERFIL DEMOGRÁFICO: Cite dados prováveis de escolaridade e renda baseados nos locais (ex: "Bairros de classe média-alta sugerem ensino superior completo").
    4. ALINHAMENTO PARTIDÁRIO: Cruze o perfil do eleitorado com as pautas históricas do partido do deputado. (Ex: PL -> Conservadorismo/Agro; PT -> Social/Trabalhador; PSB -> Progressismo/Urbano).
    5. FORMATAÇÃO: NÃO use negrito (**), itálico (*) ou qualquer formatação Markdown. Use apenas texto puro.
    
    O texto deve ter EXATAMENTE 6 parágrafos numerados:
    1. Geografia do Voto: Onde se concentra a votação.
    2. Análise Socioeconômica (IDH e Renda): Compare com a média nacional.
    3. Demografia e Educação: Perfil de idade e escolaridade.
    4. Contexto Urbano/Rural: Predominância de áreas.
    5. Cruzamento Político (Partido vs Eleitor): Análise de alinhamento.
    6. Conclusão Sintética: Resumo em 2 frases.
    
    Ao final, adicione: "Fontes consultadas: Dados do TSE 2022, Censo IBGE 2022, Atlas do Desenvolvimento Humano e diretrizes partidárias públicas."
    """
    
    user_prompt = f"""
    Parlamentar: {parlamentar}
    Partido: {partido if partido else 'Não informado'}
    
    Locais com mais votos (Cidade - Bairro - Votos):
    {top_locais_text}
    
    Gere a análise seguindo estritamente as diretrizes de objetividade e comparação de dados.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Ou gpt-4-turbo
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5, # Temperatura menor para ser mais objetivo
            max_tokens=1200
        )
        
        analysis_text = response.choices[0].message.content
        
        # 4. Salvar no Cache
        cursor.execute("INSERT OR REPLACE INTO llm_cache (hash_id, parlamentar, prompt, response) VALUES (?, ?, ?, ?)", 
                       (hash_id, parlamentar, prompt_input, analysis_text))
        conn.commit()
        conn.close()
        
        return analysis_text
        
    except Exception as e:
        conn.close()
        return f"Erro ao gerar análise: {str(e)}"

@app.get("/api/analise-perfil-eleitor/{parlamentar}")
def api_analise_perfil(parlamentar: str):
    # 1. Obter dados de votação existentes
    dados_votos = get_votos_deputado(parlamentar)
    
    if "error" in dados_votos:
        return {"error": dados_votos["error"]}
        
    # Extrair partido
    partido = dados_votos.get("info", {}).get("partido", "")
        
    # 2. Preparar resumo dos top locais para o prompt
    # Pegar top 15 bairros/cidades para dar contexto
    bairros = dados_votos.get("bairros", [])
    top_items = bairros[:15] if bairros else []
    
    if not top_items:
        # Fallback para municipios se não tiver bairros
        municipios = dados_votos.get("municipios", [])
        top_items = municipios[:15]
    
    text_lines = []
    for item in top_items:
        local = item.get('bairro', 'Centro')
        cidade = item.get('municipio', '')
        uf = item.get('estado', '')
        votos = item.get('total_votos', 0)
        text_lines.append(f"- {cidade}/{uf} ({local}): {votos} votos")
        
    top_locais_text = "\n".join(text_lines)
    
    # 3. Chamar LLM com partido
    analise = get_llm_analysis(parlamentar, top_locais_text, partido)
    
    return {"analise": analise}

if __name__ == "__main__":
    import uvicorn
    print("🗺️  Iniciando servidor dedicado do Mapa Eleitoral na porta 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)

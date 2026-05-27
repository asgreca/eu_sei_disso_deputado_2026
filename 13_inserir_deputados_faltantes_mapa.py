"""
Script para inserir deputados faltantes no banco votacao.duckdb
Processa estado por estado para não travar
"""
import duckdb
import pandas as pd
import sqlite3
import unicodedata
from pathlib import Path
import sys

def normalizar(text):
    """Remove acentos e normaliza"""
    if pd.isna(text) or not text:
        return ""
    text = str(text)
    nfkd = unicodedata.normalize('NFD', text)
    sem_acento = ''.join([c for c in nfkd if not unicodedata.combining(c)])
    return sem_acento.upper().strip()

print("\n" + "="*90)
print("🔄 INSERINDO DEPUTADOS FALTANTES NO BANCO votacao.duckdb")
print("="*90)

# ===== 1. CARREGAR LISTA =====
print("\n📋 Carregando lista...")
df_encontrados = pd.read_excel('deputados_ENCONTRADOS_nos_csvs.xlsx')
print(f"   ✅ {len(df_encontrados)} deputados")

# Criar mapeamento por estado
deputados_por_estado = {}
for _, row in df_encontrados.iterrows():
    uf = row['Estado']
    if uf not in deputados_por_estado:
        deputados_por_estado[uf] = []
    deputados_por_estado[uf].append({
        'nome_parlamentar': row['Nome Parlamentar'],
        'nome_civil': row['Nome Civil'],
        'nome_civil_norm': row['Nome Civil Normalizado'],
        'partido': row['Partido']
    })

# ===== 2. BUSCAR FOTOS =====
print("\n📊 Buscando fotos...")
conn_tabelao = sqlite3.connect('tabelao.db')
fotos = {}
for nome_civil, url_foto in conn_tabelao.execute("""
    SELECT nomeCivil, ultimoStatus_urlFoto
    FROM tabelao
    WHERE ultimoStatus_idLegislatura = 57
    AND nomeCivil IS NOT NULL
""").fetchall():
    fotos[normalizar(nome_civil)] = url_foto
conn_tabelao.close()

# ===== 3. CONECTAR AO BANCO =====
print("\n🔍 Conectando ao banco...")
conn_db = duckdb.connect('mapa/votacao.duckdb')

deputados_existentes = set(
    conn_db.execute(
        "SELECT DISTINCT NM_PARLAMENTAR FROM votacao"
    ).fetchdf()['NM_PARLAMENTAR'].apply(normalizar)
)

print(f"   ✅ {len(deputados_existentes)} já no banco")

# ===== 4. PROCESSAR ESTADO POR ESTADO =====
print("\n📂 Processando CSVs...")

pasta_votacao = Path("votacao")
total_inseridos = 0
total_novos = 0

for uf, deputados_uf in sorted(deputados_por_estado.items()):
    # Filtrar apenas os novos
    deputados_novos = [
        d for d in deputados_uf 
        if normalizar(d['nome_parlamentar']) not in deputados_existentes
    ]
    
    if len(deputados_novos) == 0:
        continue
    
    print(f"\n   📊 {uf}: {len(deputados_novos)} deputados novos")
    
    # Buscar arquivo CSV deste estado
    arquivo = pasta_votacao / f"votacao_secao_2022_{uf}.csv"
    
    if not arquivo.exists():
        print(f"      ⚠️  Arquivo não encontrado: {arquivo}")
        continue
    
    try:
        # Ler CSV com pandas
        print(f"      📖 Lendo CSV...", end=" ")
        sys.stdout.flush()
        
        df_csv = pd.read_csv(
            arquivo,
            encoding='latin1',
            sep=';',
            dtype=str,
            usecols=['SG_UF', 'NM_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 
                    'NM_LOCAL_VOTACAO', 'DS_LOCAL_VOTACAO_ENDERECO',
                    'DS_CARGO', 'NM_VOTAVEL', 'QT_VOTOS'],
            low_memory=False
        )
        
        print(f"{len(df_csv):,} linhas")
        
        # Normalizar para busca
        df_csv['NM_VOTAVEL_NORM'] = df_csv['NM_VOTAVEL'].apply(normalizar)
        
        # Processar cada deputado
        for dep in deputados_novos:
            # Filtrar registros deste deputado
            df_dep = df_csv[df_csv['NM_VOTAVEL_NORM'] == dep['nome_civil_norm']].copy()
            
            if len(df_dep) == 0:
                print(f"      ⚠️  {dep['nome_parlamentar']}: 0 registros")
                continue
            
            # Preparar para inserção
            df_dep['NM_PARLAMENTAR'] = dep['nome_parlamentar']
            df_dep['urlFoto_camara'] = fotos.get(dep['nome_civil_norm'])
            df_dep['SIGLA_PARTIDO_FINAL'] = dep['partido']
            df_dep['NOME_PARTIDO_FINAL'] = None
            df_dep['URL_FOTO_PARTIDO_FINAL'] = None
            df_dep['ALINHAMENTO_IDEOLOGICO'] = None
            df_dep['NM_BAIRRO'] = None
            df_dep['NR_CEP'] = None
            df_dep['LAT'] = None
            df_dep['LONG'] = None
            df_dep['percentual_de_votos'] = None
            
            # Renomear e organizar colunas
            df_insert = pd.DataFrame({
                'SG_UF': df_dep['SG_UF'],
                'NM_MUNICIPIO': df_dep['NM_MUNICIPIO'],
                'NR_ZONA': df_dep['NR_ZONA'],
                'NR_SECAO': df_dep['NR_SECAO'],
                'NM_LOCAL_VOTACAO': df_dep['NM_LOCAL_VOTACAO'],
                'DS_ENDERECO': df_dep['DS_LOCAL_VOTACAO_ENDERECO'],
                'NM_BAIRRO': None,
                'NR_CEP': None,
                'LAT': None,
                'LONG': None,
                'DS_CARGO': df_dep.get('DS_CARGO', 'DEPUTADO FEDERAL'),
                'NM_VOTAVEL': df_dep['NM_VOTAVEL'],
                'QT_VOTOS_NOMINAIS': pd.to_numeric(df_dep['QT_VOTOS'], errors='coerce').fillna(0).astype('int64'),
                'percentual_de_votos': None,
                'NM_PARLAMENTAR': dep['nome_parlamentar'],
                'urlFoto_camara': fotos.get(dep['nome_civil_norm']),
                'SIGLA_PARTIDO_FINAL': dep['partido'],
                'NOME_PARTIDO_FINAL': None,
                'URL_FOTO_PARTIDO_FINAL': None,
                'ALINHAMENTO_IDEOLOGICO': None
            })
            
            # Inserir no DuckDB
            conn_db.execute("INSERT INTO votacao SELECT * FROM df_insert")
            
            total_inseridos += len(df_insert)
            total_novos += 1
            print(f"      ✅ {dep['nome_parlamentar']}: {len(df_insert):,} registros")
        
    except Exception as e:
        print(f"      ❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        continue

# ===== 5. VERIFICAR RESULTADO =====
print("\n" + "="*90)
print("📊 RESULTADO:")
print("="*90)

try:
    total_registros = conn_db.execute("SELECT COUNT(*) FROM votacao").fetchone()[0]
    total_deputados = conn_db.execute("SELECT COUNT(DISTINCT NM_PARLAMENTAR) FROM votacao").fetchone()[0]
    
    print(f"\n✅ Total de registros:   {total_registros:,}")
    print(f"✅ Total de deputados:   {total_deputados}")
    print(f"✅ Deputados inseridos:  {total_novos}")
    print(f"✅ Registros inseridos:  {total_inseridos:,}")
    
except Exception as e:
    print(f"❌ Erro: {e}")

conn_db.close()

print("\n" + "="*90)
print("✅ CONCLUÍDO!")
print("="*90 + "\n")


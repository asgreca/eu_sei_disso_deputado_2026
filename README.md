# Eu Sei Disso, Deputado!

**Sistema de auditoria e transparencia parlamentar** que integra dados abertos da Camara dos Deputados, TSE, IBGE e outras fontes publicas para analise de gastos, votacoes, emendas, discursos e conexoes entre parlamentares brasileiros.

Desenvolvido como Trabalho de Conclusao de Curso (TCC) na **UNIVESP** - Universidade Virtual do Estado de Sao Paulo.

---

## Funcionalidades

| Modulo | Descricao |
|---|---|
| **Detalhamento de Gastos** | Analise por fornecedor, rubrica e geolocalizacao com deteccao de notas atipicas |
| **Ranking de Gastos** | Comparativo entre parlamentares por categoria de despesa |
| **Passagens Aereas** | Rastreamento de trechos, frequencias e padroes de viagem |
| **Emendas Parlamentares** | Fluxo do dinheiro: emenda - convenio - fornecedor - socios |
| **Conflitos de Interesse** | Cruzamento emendas x doacoes x socios de fornecedores |
| **Mapa Eleitoral** | Geolocalizacao de votos por secao eleitoral (dados TSE 2022) |
| **Mapa Partidario** | Dominancia partidaria por local de votacao |
| **Sociograma de Fornecedores** | Grafo de conexoes entre parlamentares via fornecedores compartilhados |
| **Votacoes** | Posicionamento em plenario, alinhamento partidario e opiniao publica |
| **Presenca Parlamentar** | Frequencia em sessoes deliberativas e comissoes |
| **Analise de Imprensa** | Monitoramento de noticias e mencoes na midia |
| **Busca Semantica** | Pesquisa por similaridade em discursos e documentos via ChromaDB |
| **Chat Parlamentar** | Assistente IA para perguntas sobre qualquer parlamentar |
| **Assessores** | Quadro de pessoal e custos de gabinete |

## Arquitetura

```
+---------------------------------------------------------+
|  Frontend (React)                                       |
|  Porta 80/443 via Nginx                                 |
+----------------+----------------------------------------+
                 |
      +----------+----------+
      v          v          v
  +--------+ +--------+ +--------+
  | main   | | mapa   | |filtros |
  | :8000  | | :8001  | | :8006  |
  | FastAPI| | FastAPI| | FastAPI|
  +----+---+ +----+---+ +----+---+
       |          |          |
       v          v          v
  +-----------------------------------+
  |  SQLite (tabelao.db)              |
  |  DuckDB (votacao.duckdb)          |
  |  ChromaDB (vetores/)              |
  +-----------------------------------+
```

## Estrutura do Projeto

```
|-- main.py                    # API principal (gastos, emendas, sociograma, chat, relatorios)
|-- mapa_server.py             # API do mapa eleitoral (votos geolocalizados)
|-- filtros_server.py          # API de filtros (estados, partidos, parlamentares)
|-- frontend/                  # React SPA
|   |-- src/pages/             # Paginas do sistema
|   +-- src/components/        # Componentes reutilizaveis
|-- modules/                   # Modulos Python auxiliares
|-- mapa/                      # GeoJSON dos estados brasileiros
|-- deploy.sh                  # Script de deploy automatizado
|-- requirements-backend.txt   # Dependencias Python
|-- partido.csv                # Logos dos partidos
|-- estados.csv                # Bandeiras dos estados
|-- municipios_brasileiros.csv # Lista de municipios
|-- airport.csv                # Aeroportos (passagens aereas)
|-- .env_exemplo               # Template de variaveis de ambiente
|
|  -- Scripts de Coleta (pipeline) --
|-- 000_pipeline_final.py      # Orquestrador geral do pipeline
|-- 00_tabelao.py              # Coleta de dados da API da Camara
|-- 01_Coleta_Noticias.py      # Scraping de noticias
|-- 02_*.py                    # Limpeza e normalizacao
|-- 03_*.py                    # Recuperacao textual
|-- 04_*.py                    # Auditoria via GPT-4
|-- 05_*.py                    # RAG e cruzamento de emendas
|-- 06-08_*.py                 # Normalizacao de citacoes
|-- 11-13_*.py                 # Monitoramento e sync
|-- 14_emendas.py              # Coleta de emendas parlamentares
|-- 15_votacao.py              # Coleta de votacoes
|-- 16_presenca.py             # Coleta de presenca
|-- 17-35_*.py                 # Comissoes, processos, doacoes, assessores, etc.
```

## Instalacao

### Pre-requisitos

- Python 3.10+
- Node.js 18+
- SQLite3
- Chave de API da OpenAI

### Backend

```bash
# Clonar o repositorio
git clone https://github.com/asgreca/eu_sei_disso_deputado_2026.git
cd eu_sei_disso_deputado_2026

# Criar ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements-backend.txt

# Configurar variaveis de ambiente
cp .env_exemplo .env
# Editar .env com suas credenciais

# Executar o pipeline de coleta (primeira vez)
python 000_pipeline_final.py

# Iniciar os servidores
uvicorn main:app --host 0.0.0.0 --port 8000 &
uvicorn mapa_server:app --host 0.0.0.0 --port 8001 &
uvicorn filtros_server:app --host 0.0.0.0 --port 8006 &
```

### Frontend

```bash
cd frontend
npm install
npm start          # Desenvolvimento (localhost:3000)
npm run build      # Build de producao
```

### Deploy

```bash
# Deploy completo (frontend + backend + bancos)
./deploy.sh

# Apenas frontend
./deploy.sh --front

# Apenas backend
./deploy.sh --back

# Status dos servicos
./deploy.sh --status
```

## Fontes de Dados

| Fonte | Dados |
|---|---|
| [API da Camara dos Deputados](https://dadosabertos.camara.leg.br/) | Gastos, votacoes, presenca, proposicoes, comissoes |
| [TSE](https://dadosabertos.tse.jus.br/) | Resultados eleitorais 2022, geolocalizacao de votos |
| [Portal da Transparencia](https://portaldatransparencia.gov.br/) | Emendas parlamentares, convenios |
| [IBGE](https://www.ibge.gov.br/) | Dados censitarios, IDH, indicadores municipais |
| [Receita Federal (CNPJ)](https://dados.rfb.gov.br/) | Dados cadastrais de empresas e socios |

## Tecnologias

**Backend:** Python, FastAPI, SQLite, DuckDB, ChromaDB, OpenAI GPT-4o, Pandas, NetworkX

**Frontend:** React, Material-UI, ECharts, Leaflet, Recharts

**Infraestrutura:** Nginx, Let's Encrypt, Systemd, rsync

## Licenca e Uso

Este projeto e **open source** e esta disponivel para uso, estudo e adaptacao.

**Se voce pretende usar este projeto** - seja para fins academicos, jornalisticos, de fiscalizacao ou qualquer outro -, por favor comunique para:

**aislan@greca.dev.br**

Gostaria de conhecer os desdobramentos e usos derivados deste trabalho.

## Autor

**Aislan Greca** - Fundador e CTO

Trabalho de Conclusao de Curso - UNIVESP (2026)

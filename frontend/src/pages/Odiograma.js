import React, { useState, useEffect } from 'react';
import {
    Box,
    Typography,
    Container,
    Paper,
    Grid,
    FormControl,
    InputLabel,
    Select,
    MenuItem,
    Button,
    CircularProgress,
    Alert,
    Card,
    CardContent,
    Chip,
    Autocomplete,
    TextField,
    Avatar,
    Tooltip,
    Switch,
    FormControlLabel,
} from '@mui/material';
import {
    AccountTree as NetworkIcon,
    Search as SearchIcon,
    TrendingUp as TrendingUpIcon,
    Psychology as PsychologyIcon,
    Assessment as AssessmentIcon,
    Info as InfoIcon,
} from '@mui/icons-material';
import ReactECharts from 'echarts-for-react';
import ReactMarkdown from 'react-markdown';
import api from '../config/axios';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

// URLs de logos de partidos (Special:FilePath - Imunes a bloqueios)
const normalizeWikiUrl = (url) => {
    if (!url || typeof url !== 'string') return url;
    if (url.includes('flagcdn.com') || url.includes('Special:FilePath')) return url;

    const match = url.match(/wikipedia\/(?:commons|pt)\/(?:thumb\/)?(?:[a-f0-9]\/[a-f0-9]{2}\/)?([^\/]+)(?:\/\d+px-[^\/]+)?$/i);
    if (match && match[1]) {
        return `https://commons.wikimedia.org/wiki/Special:FilePath/${match[1]}?width=150`;
    }
    return url;
};

const getPartidoLogo = (info) => {
    if (!info) return '';
    const partido = (info.sgPartido || info.partido || "").toUpperCase();
    if (info.urlPartido) return normalizeWikiUrl(info.urlPartido);
    return PARTIDO_LOGOS_FALLBACK[partido] || '';
};

const getEstadoLogo = (info) => {
    if (!info) return '';
    if (info.urlEstado) return normalizeWikiUrl(info.urlEstado);
    const uf = (info.sgUF || info.estado || "").toUpperCase();

    // Tratamento especial para RN que falha no FlagCDN ou links quebrados
    if (uf === 'RN') return 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/30/Bandeira_do_Rio_Grande_do_Norte.svg/300px-Bandeira_do_Rio_Grande_do_Norte.svg.png';

    return uf ? `https://flagcdn.com/w160/br-${uf.toLowerCase()}.png` : '';
};

function Odiograma() {
    const [estados, setEstados] = useState([]);
    const [partidos, setPartidos] = useState([]);
    const [sentimentos, setSentimentos] = useState([]);
    const [parlamentaresInfo, setParlamentaresInfo] = useState([]);
    const [conexoes, setConexoes] = useState([]);
    const [loading, setLoading] = useState(false);
    const [loadingFiltros, setLoadingFiltros] = useState(false);
    const [loadingParlamentares, setLoadingParlamentares] = useState(false);
    const [error, setError] = useState(null);
    const [relatorioIA, setRelatorioIA] = useState(null);
    const [loadingRelatorio, setLoadingRelatorio] = useState(false);

    // Listas filtradas dinamicamente
    const [partidosCitanteFiltrados, setPartidosCitanteFiltrados] = useState([]);
    const [parlamentaresCitanteFiltrados, setParlamentaresCitanteFiltrados] = useState([]);
    const [partidosCitadoFiltrados, setPartidosCitadoFiltrados] = useState([]);
    const [parlamentaresCitadoFiltrados, setParlamentaresCitadoFiltrados] = useState([]);

    // Filtros (agora com arrays para seleção múltipla)
    const [filtros, setFiltros] = useState({
        sentimento: 'Todos',
        estadosCitantes: [],
        partidosCitantes: [],
        parlamentaresCitantes: [],
        estadosCitados: [],
        partidosCitados: [],
        parlamentaresCitados: [],
    });

    // Filtros de Data e Rigor
    const [startDate, setStartDate] = useState('2023-01-01');
    const [endDate, setEndDate] = useState('');
    const [apenasNominais, setApenasNominais] = useState(true);

    // Filtros de cores para o grafo
    const [filtrosCores, setFiltrosCores] = useState({
        verde: true,
        vermelho: true,
        amarelo: true,
        laranja: true,
    });

    // Filtros de tipos de nós
    const [mostrarPartidos, setMostrarPartidos] = useState(true);
    const [mostrarEstados, setMostrarEstados] = useState(true);

    // Filtros Visuais (para o grafo)
    const [visualFilters, setVisualFilters] = useState({
        estados: [],
        partidos: [],
        parlamentares: []
    });

    // Fallbacks para filtros se a API falhar
    const ESTADOS_BR = [
        'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS',
        'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC',
        'SP', 'SE', 'TO',
    ];
    const PARTIDOS_PADRAO = ["PL", "PT", "UNIÃO", "PP", "MDB", "PSD", "REPUBLICANOS", "PSB", "PDT", "PSDB", "PSOL", "PODE", "AVANTE", "CIDADANIA", "NOVO", "REDE", "PV", "SOLIDARIEDADE", "PCdoB"];
    const SENTIMENTOS_PADRAO = ["Apoio", "Crítica", "Neutro", "Questionador"];

    // Helper para criar imagem circular via SVG - REMOVIDO (Causa erro de imagem quebrada)
    // Vamos usar CSS + SVG Renderer para fazer o recorte circular


    // Carregar dados iniciais
    useEffect(() => {
        carregarFiltros();
        carregarParlamentaresInfo();
        carregarDatas();
    }, []);

    const carregarDatas = async () => {
        try {
            const response = await api.get('/api/redes/datas');
            if (response.data.min_data) {
                setStartDate('2023-01-01');
            }
            if (response.data.max_data) {
                setEndDate(response.data.max_data);
            } else {
                setEndDate(new Date().toISOString().split('T')[0]);
            }
        } catch (err) {
            console.error('Erro ao carregar datas:', err);
            setEndDate(new Date().toISOString().split('T')[0]);
        }
    };

    // Atualizar partidos citantes quando estados citantes mudarem
    useEffect(() => {
        if (filtros.estadosCitantes.length > 0) {
            const partidosFiltrados = [...new Set(
                parlamentaresInfo
                    .filter(p => filtros.estadosCitantes.includes(p.estado))
                    .map(p => p.partido)
            )].sort();
            setPartidosCitanteFiltrados(partidosFiltrados);
        } else {
            setPartidosCitanteFiltrados(partidos);
        }
    }, [filtros.estadosCitantes, parlamentaresInfo, partidos]);

    // Atualizar parlamentares citantes quando estados/partidos mudarem
    useEffect(() => {
        let parlamentaresFiltrados = parlamentaresInfo;

        if (filtros.estadosCitantes.length > 0) {
            parlamentaresFiltrados = parlamentaresFiltrados.filter(p => filtros.estadosCitantes.includes(p.estado));
        }
        if (filtros.partidosCitantes.length > 0) {
            parlamentaresFiltrados = parlamentaresFiltrados.filter(p => filtros.partidosCitantes.includes(p.partido));
        }

        setParlamentaresCitanteFiltrados([...new Set(parlamentaresFiltrados.map(p => p.nome))].sort());
    }, [filtros.estadosCitantes, filtros.partidosCitantes, parlamentaresInfo]);

    // Atualizar partidos citados quando estados citados mudarem
    useEffect(() => {
        if (filtros.estadosCitados.length > 0) {
            const partidosFiltrados = [...new Set(
                parlamentaresInfo
                    .filter(p => filtros.estadosCitados.includes(p.estado))
                    .map(p => p.partido)
            )].sort();
            setPartidosCitadoFiltrados(partidosFiltrados);
        } else {
            setPartidosCitadoFiltrados(partidos);
        }
    }, [filtros.estadosCitados, parlamentaresInfo, partidos]);

    // Atualizar parlamentares citados quando estados/partidos mudarem
    useEffect(() => {
        let parlamentaresFiltrados = parlamentaresInfo;

        if (filtros.estadosCitados.length > 0) {
            parlamentaresFiltrados = parlamentaresFiltrados.filter(p => filtros.estadosCitados.includes(p.estado));
        }
        if (filtros.partidosCitados.length > 0) {
            parlamentaresFiltrados = parlamentaresFiltrados.filter(p => filtros.partidosCitados.includes(p.partido));
        }

        setParlamentaresCitadoFiltrados([...new Set(parlamentaresFiltrados.map(p => p.nome))].sort());
    }, [filtros.estadosCitados, filtros.partidosCitados, parlamentaresInfo]);

    // Calcular opções dinâmicas para os filtros visuais (baseado nos dados do grafo atual)
    const opcoesFiltrosVisuais = React.useMemo(() => {
        if (conexoes.length === 0) return { estados: [], partidos: [], parlamentares: [] };

        const parlamentaresNoGrafo = new Set();
        conexoes.forEach(c => {
            parlamentaresNoGrafo.add(c.citante);
            parlamentaresNoGrafo.add(c.citado);
        });

        const estadosNoGrafo = new Set();
        const partidosNoGrafo = new Set();

        parlamentaresNoGrafo.forEach(nome => {
            const info = parlamentaresInfo.find(p => p.nome === nome);
            if (info) {
                if (info.estado) estadosNoGrafo.add(info.estado);
                if (info.partido) partidosNoGrafo.add(info.partido);
            }
        });

        return {
            estados: Array.from(estadosNoGrafo).sort(),
            partidos: Array.from(partidosNoGrafo).sort(),
            parlamentares: Array.from(parlamentaresNoGrafo).sort()
        };
    }, [conexoes, parlamentaresInfo]);


    const carregarFiltros = async () => {
        setLoadingFiltros(true);
        try {
            const response = await api.get('/api/redes/filtros');
            const data = response.data || {};
            setEstados(Array.isArray(data.estados) && data.estados.length > 0 ? data.estados : ESTADOS_BR);
            setPartidos(Array.isArray(data.partidos) && data.partidos.length > 0 ? data.partidos : PARTIDOS_PADRAO);
            setSentimentos(Array.isArray(data.sentimentos) && data.sentimentos.length > 0 ? data.sentimentos : SENTIMENTOS_PADRAO);
        } catch (err) {
            console.error('Erro ao carregar filtros:', err);
            setEstados(ESTADOS_BR);
            setPartidos(PARTIDOS_PADRAO);
            setSentimentos(SENTIMENTOS_PADRAO);
        } finally {
            setLoadingFiltros(false);
        }
    };

    const carregarParlamentaresInfo = async () => {
        setLoadingParlamentares(true);
        try {
            const response = await api.get('/api/redes/parlamentares-info');
            const data = response.data || [];
            setParlamentaresInfo(Array.isArray(data) ? data : []);
        } catch (err) {
            console.error('Erro ao carregar parlamentares:', err);
            setParlamentaresInfo([]);
        } finally {
            setLoadingParlamentares(false);
        }
    };

    const carregarConexoes = async () => {
        setLoading(true);
        setError(null);

        try {
            // Buscar todas as conexões (com filtro de data no backend)
            const params = {};
            if (startDate) params.data_inicio = startDate;
            if (endDate) params.data_fim = endDate;
            if (apenasNominais) params.apenas_nominais = true;

            const response = await api.get('/api/redes/conexoes', { params });
            let conexoesFiltradas = response.data;

            // Aplicar filtros localmente para suportar seleção múltipla
            if (filtros.sentimento !== 'Todos') {
                conexoesFiltradas = conexoesFiltradas.filter(c => c.sentimento === filtros.sentimento);
            }

            if (filtros.estadosCitantes.length > 0) {
                conexoesFiltradas = conexoesFiltradas.filter(c => filtros.estadosCitantes.includes(c.estado_citante));
            }

            if (filtros.partidosCitantes.length > 0) {
                conexoesFiltradas = conexoesFiltradas.filter(c => filtros.partidosCitantes.includes(c.partido_citante));
            }

            if (filtros.parlamentaresCitantes.length > 0) {
                conexoesFiltradas = conexoesFiltradas.filter(c => filtros.parlamentaresCitantes.includes(c.citante));
            }

            // Filtros para quem é citado
            if (filtros.estadosCitados.length > 0) {
                const parlamentaresEstado = parlamentaresInfo
                    .filter(p => filtros.estadosCitados.includes(p.estado))
                    .map(p => p.nome);
                conexoesFiltradas = conexoesFiltradas.filter(c => parlamentaresEstado.includes(c.citado));
            }

            if (filtros.partidosCitados.length > 0) {
                const parlamentaresPartido = parlamentaresInfo
                    .filter(p => filtros.partidosCitados.includes(p.partido))
                    .map(p => p.nome);
                conexoesFiltradas = conexoesFiltradas.filter(c => parlamentaresPartido.includes(c.citado));
            }

            if (filtros.parlamentaresCitados.length > 0) {
                conexoesFiltradas = conexoesFiltradas.filter(c => filtros.parlamentaresCitados.includes(c.citado));
            }

            setConexoes(conexoesFiltradas);
        } catch (err) {
            setError('Erro ao carregar conexões');
            console.error('Erro ao carregar conexões:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleFiltroChange = (campo, valor) => {
        setFiltros(prev => {
            const novosFiltros = { ...prev, [campo]: valor };

            // Resetar filtros dependentes quando filtro superior mudar
            if (campo === 'estadosCitantes') {
                novosFiltros.partidosCitantes = [];
                novosFiltros.parlamentaresCitantes = [];
            }
            if (campo === 'partidosCitantes') {
                novosFiltros.parlamentaresCitantes = [];
            }
            if (campo === 'estadosCitados') {
                novosFiltros.partidosCitados = [];
                novosFiltros.parlamentaresCitados = [];
            }
            if (campo === 'partidosCitados') {
                novosFiltros.parlamentaresCitados = [];
            }

            return novosFiltros;
        });
    };

    const gerarRelatorioIA = async () => {
        setLoadingRelatorio(true);

        try {
            // Filtrar conexões com base nos filtros visuais atuais
            let conexoesFiltradas = conexoes;

            // Filtro de Estados
            if (visualFilters.estados.length > 0) {
                conexoesFiltradas = conexoesFiltradas.filter(c =>
                    visualFilters.estados.includes(c.estado_citante) ||
                    (c.estado_citado && visualFilters.estados.includes(c.estado_citado))
                );
            }

            // Filtro de Partidos
            if (visualFilters.partidos.length > 0) {
                conexoesFiltradas = conexoesFiltradas.filter(c =>
                    visualFilters.partidos.includes(c.partido_citante) ||
                    (c.partido_citado && visualFilters.partidos.includes(c.partido_citado))
                );
            }

            // Filtro de Parlamentares (Ego Network)
            if (visualFilters.parlamentares.length > 0) {
                conexoesFiltradas = conexoesFiltradas.filter(c =>
                    visualFilters.parlamentares.includes(c.citante) ||
                    visualFilters.parlamentares.includes(c.citado)
                );
            }

            const response = await api.post('/api/redes/gerar-relatorio', {
                conexoes: conexoesFiltradas,
                filtros_aplicados: { ...filtros, ...visualFilters }
            });

            setRelatorioIA(response.data);
        } catch (err) {
            setError('Erro ao gerar relatório com IA');
            console.error('Erro ao gerar relatório:', err);
        } finally {
            setLoadingRelatorio(false);
        }
    };

    const copiarTexto = (texto) => {
        navigator.clipboard.writeText(texto);
        alert('Texto copiado para a área de transferência!');
    };

    const criarGrafoECharts = () => {
        if (conexoes.length === 0) return null;

        // Mapear cores por sentimento
        const coresSentimento = {
            'Apoio': '#2E8B57',      // Verde
            'Crítica': '#DC143C',    // Vermelho
            'Neutro': '#FFD700',     // Amarelo
            'Questionador': '#FF8C00' // Laranja
        };

        // Filtrar conexões por cores ativas
        const conexoesFiltradas = conexoes.filter(conexao => {
            const sent = conexao.sentimento;
            if (sent === 'Apoio' && !filtrosCores.verde) return false;
            if (sent === 'Crítica' && !filtrosCores.vermelho) return false;
            if (sent === 'Neutro' && !filtrosCores.amarelo) return false;
            if (sent === 'Questionador' && !filtrosCores.laranja) return false;
            return true;
        });

        // Criar nós
        const parlamentaresUnicos = new Set();
        conexoesFiltradas.forEach(c => {
            parlamentaresUnicos.add(c.citante);
            parlamentaresUnicos.add(c.citado);
        });

        // Criar nós dos parlamentares
        const nodes = Array.from(parlamentaresUnicos).map(parlamentar => {
            const info = parlamentaresInfo.find(p => p.nome === parlamentar);
            const grau = conexoesFiltradas.filter(c =>
                c.citante === parlamentar || c.citado === parlamentar
            ).length;

            const nodeSize = Math.max(50, Math.min(80, grau * 4));

            return {
                id: parlamentar,
                name: parlamentar,
                category: 'Parlamentar',
                symbolSize: [nodeSize, nodeSize],
                value: grau,
                symbolSize: [nodeSize, nodeSize],
                value: grau,
                symbol: info?.urlFoto ? `image://${info.urlFoto}` : 'circle',
                estado: info?.estado,
                partido: info?.partido,
                tooltip: {
                    formatter: `<b>${parlamentar}</b><br/>Estado: ${info?.estado || 'N/A'}<br/>Partido: ${info?.partido || 'N/A'}<br/>Conexões: ${grau}`
                },
                label: {
                    show: true,
                    position: 'bottom',
                    color: '#333333',
                    fontSize: 11,
                    fontWeight: 'bold',
                    backgroundColor: 'rgba(255, 255, 255, 0.9)',
                    borderColor: '#003366',
                    borderWidth: 1,
                    borderRadius: 4,
                    padding: [4, 8]
                },
                itemStyle: {
                    borderWidth: 3,
                    borderColor: '#003366',
                    shadowBlur: 10,
                    shadowColor: 'rgba(0, 51, 102, 0.3)',
                    borderRadius: '50%',
                }
            };
        });

        // Adicionar nós dos partidos
        const partidosComConexoes = new Set();
        Array.from(parlamentaresUnicos).forEach(parlamentar => {
            const info = parlamentaresInfo.find(p => p.nome === parlamentar);
            if (info?.partido) {
                partidosComConexoes.add(info.partido);
            }
        });

        const partidosUnicos = {};
        parlamentaresInfo.forEach(p => {
            if (partidosComConexoes.has(p.partido) && !partidosUnicos[p.partido]) {
                partidosUnicos[p.partido] = {
                    urlPartido: p.urlPartido,
                    estado: p.estado
                };
            }
        });

        Object.entries(partidosUnicos).forEach(([partido, info]) => {
            const partidoLogoUrl = getPartidoLogo({ partido, ...info });
            nodes.push({
                id: `PARTIDO_${partido}`,
                name: `${partido}`,
                category: 'Partido',
                symbolSize: [40, 40],
                symbolSize: [40, 40],
                symbol: partidoLogoUrl ? `image://${partidoLogoUrl}` : 'rect',
                tooltip: {
                    formatter: `<b>Partido: ${partido}</b><br/>Clique para ver parlamentares`
                },
                label: {
                    show: true,
                    position: 'bottom',
                    color: '#333333',
                    fontSize: 10,
                    fontWeight: 'bold',
                    backgroundColor: 'rgba(255, 255, 255, 0.9)',
                    borderColor: '#009739',
                    borderWidth: 1,
                    borderRadius: 4,
                    padding: [3, 6]
                },
                itemStyle: {
                    color: '#FFFFFF',
                    borderWidth: 2,
                    borderColor: '#009739',
                    shadowBlur: 8,
                    shadowColor: 'rgba(0, 151, 57, 0.3)',
                    opacity: 1,
                }
            });
        });

        // Adicionar nós dos estados
        const estadosComConexoes = new Set();
        Array.from(parlamentaresUnicos).forEach(parlamentar => {
            const info = parlamentaresInfo.find(p => p.nome === parlamentar);
            if (info?.estado) {
                estadosComConexoes.add(info.estado);
            }
        });

        const estadosUnicos = {};
        parlamentaresInfo.forEach(p => {
            if (estadosComConexoes.has(p.estado) && !estadosUnicos[p.estado]) {
                estadosUnicos[p.estado] = {
                    urlEstado: p.urlEstado
                };
            }
        });

        Object.entries(estadosUnicos).forEach(([estado, info]) => {
            const estadoLogoUrl = getEstadoLogo({ estado, ...info });
            nodes.push({
                id: `ESTADO_${estado}`,
                name: `${estado}`,
                category: 'Estado',
                symbolSize: [35, 35],
                symbolSize: [35, 35],
                symbol: estadoLogoUrl ? `image://${estadoLogoUrl}` : 'diamond',
                tooltip: {
                    formatter: `<b>Estado: ${estado}</b><br/>Clique para ver parlamentares`
                },
                label: {
                    show: true,
                    position: 'bottom',
                    color: '#333333',
                    fontSize: 10,
                    fontWeight: 'bold',
                    backgroundColor: 'rgba(255, 255, 255, 0.9)',
                    borderColor: '#ED8B00',
                    borderWidth: 1,
                    borderRadius: 4,
                    padding: [3, 6]
                },
                itemStyle: {
                    color: '#FFFFFF',
                    borderWidth: 2,
                    borderColor: '#ED8B00',
                    shadowBlur: 8,
                    shadowColor: 'rgba(237, 139, 0, 0.3)',
                    opacity: 1,
                }
            });
        });

        // Criar links (agregados)
        const linksMap = {};
        conexoesFiltradas.forEach(conexao => {
            const chave = `${conexao.citante}|${conexao.citado}`;
            if (!linksMap[chave]) {
                linksMap[chave] = {
                    source: conexao.citante,
                    target: conexao.citado,
                    conexoes: []
                };
            }
            linksMap[chave].conexoes.push(conexao);
        });

        const links = Object.values(linksMap).map(item => {
            // Remover frases duplicadas mantendo apenas citações únicas
            const citacoesUnicas = [];
            const frasesVistas = new Set();

            item.conexoes.forEach(c => {
                // Normalizar a frase para comparação (remover espaços extras e lowercase)
                const fraseNormalizada = c.sentenca.toLowerCase().trim().replace(/\s+/g, ' ');

                // Critério de desduplicação inteligente (Similarity Check)
                const tokensAtuais = new Set(fraseNormalizada.split(' ').filter(t => t.length > 3));
                
                const ehDuplicada = citacoesUnicas.some(existente => {
                    const fraseExistenteNormalizada = existente.sentenca.toLowerCase().trim().replace(/\s+/g, ' ');
                    
                    // Match exato
                    if (fraseNormalizada === fraseExistenteNormalizada) return true;
                    
                    // Match por similaridade de tokens (se > 80% das palavras longas forem iguais)
                    const tokensExistentes = new Set(fraseExistenteNormalizada.split(' ').filter(t => t.length > 3));
                    if (tokensAtuais.size === 0 || tokensExistentes.size === 0) return false;
                    
                    let intersecao = 0;
                    tokensAtuais.forEach(t => { if (tokensExistentes.has(t)) intersecao++; });
                    
                    const similaridade = intersecao / Math.max(tokensAtuais.size, tokensExistentes.size);
                    return similaridade > 0.85; // Se for 85% similar, considera duplicada
                });

                if (!ehDuplicada && c.sentenca.length > 10) {
                    citacoesUnicas.push(c);
                }
            });

            // Limitar a 5 citações para não sobrecarregar o tooltip
            const citacoesLimitadas = citacoesUnicas.slice(0, 5);

            const tooltipTexto = citacoesLimitadas.map((c, i) => {
                const frase = c.sentenca.substring(0, 250) + (c.sentenca.length > 250 ? '...' : '');
                const data = c.data ? `<br/><small style="color: #666;">📅 ${c.data}</small>` : '';
                const comissao = c.comissao ? `<br/><small style="color: #666;">🏛️ ${c.comissao}</small>` : '';
                return `<div style="margin-bottom: 8px;">
          <b style='color: ${coresSentimento[c.sentimento] || '#999'}; display: block; margin-bottom: 4px;'>${c.sentimento} (${c.tom})</b>
          <div style="text-align: justify; line-height: 1.5; word-wrap: break-word; overflow-wrap: break-word;">${frase}</div>
          ${data}${comissao}
        </div>`;
            }).join('<hr style="margin: 8px 0; border: 1px solid #ddd; border-top: 1px solid #ddd;"/>');

            const totalCitacoes = citacoesUnicas.length;
            const avisoMais = totalCitacoes > 5 ? `<div style="margin-top: 8px; padding-top: 8px; border-top: 2px dashed #ccc;"><small style="color: #666;"><i>+ ${totalCitacoes - 5} citações adicionais...</i></small></div>` : '';

            const corPrincipal = coresSentimento[item.conexoes[0].sentimento] || '#999999';

            return {
                source: item.source,
                target: item.target,
                value: citacoesUnicas.length,
                tooltip: {
                    formatter: `<div style="word-wrap: break-word; overflow-wrap: break-word;">
            <b style="font-size: 14px; color: #003366; display: block; margin-bottom: 4px;">${item.source} → ${item.target}</b>
            <small style="color: #666; display: block; margin-bottom: 12px;">${citacoesUnicas.length} citação(ões) única(s)</small>
            ${tooltipTexto}
            ${avisoMais}
          </div>`
                },
                lineStyle: {
                    color: corPrincipal,
                    width: Math.max(2, Math.min(8, 2 + citacoesUnicas.length)),
                    curveness: 0.3,
                    opacity: 0.8,
                },
                symbol: ['none', 'arrow'],
                symbolSize: [0, 8],
            };
        });

        // Adicionar links dos parlamentares para seus partidos (linhas brancas tracejadas)
        Array.from(parlamentaresUnicos).forEach(parlamentar => {
            const info = parlamentaresInfo.find(p => p.nome === parlamentar);
            if (info?.partido && partidosComConexoes.has(info.partido)) {
                links.push({
                    source: parlamentar,
                    target: `PARTIDO_${info.partido}`,
                    value: 0.5,
                    tooltip: {
                        formatter: `<b>${parlamentar} → Partido ${info.partido}</b><br/>Conexão de afiliação partidária`
                    },
                    lineStyle: {
                        color: '#8A8A8A',
                        width: 2.5,
                        type: 'dashed',
                        opacity: 0.7,
                    },
                    symbol: ['none', 'none'],
                });
            }
        });

        // Adicionar links dos parlamentares para seus estados (linhas brancas pontilhadas)
        Array.from(parlamentaresUnicos).forEach(parlamentar => {
            const info = parlamentaresInfo.find(p => p.nome === parlamentar);
            if (info?.estado && estadosComConexoes.has(info.estado)) {
                links.push({
                    source: parlamentar,
                    target: `ESTADO_${info.estado}`,
                    value: 0.3,
                    tooltip: {
                        formatter: `<b>${parlamentar} → Estado ${info.estado}</b><br/>Conexão de origem geográfica`
                    },
                    lineStyle: {
                        color: '#A0A0A0',
                        width: 2,
                        type: 'dotted',
                        opacity: 0.6,
                    },
                    symbol: ['none', 'none'],
                });
            }
        });

        // 1. Filtrar Nós Base (por Estado e Partido - Filtro Estrito)
        let nodesBase = nodes.filter(node => {
            if (node.category === 'Partido' && !mostrarPartidos) return false;
            if (node.category === 'Estado' && !mostrarEstados) return false;

            // Filtros de Estado
            if (visualFilters.estados.length > 0) {
                if (node.category === 'Estado' && !visualFilters.estados.includes(node.name)) return false;
                if (node.category === 'Parlamentar' && node.estado && !visualFilters.estados.includes(node.estado)) return false;
            }

            // Filtros de Partido
            if (visualFilters.partidos.length > 0) {
                if (node.category === 'Partido' && !visualFilters.partidos.includes(node.name)) return false;
                if (node.category === 'Parlamentar' && node.partido && !visualFilters.partidos.includes(node.partido)) return false;
            }

            return true;
        });

        // 2. Filtrar Links (Baseado nos Nós Base + Filtro de Nome Ego Network)
        const linksFiltrados = links.filter(link => {
            const sourceNode = nodesBase.find(n => n.id === link.source);
            const targetNode = nodesBase.find(n => n.id === link.target);

            // Se um dos nós não existe na base (foi filtrado por estado/partido), remove o link
            if (!sourceNode || !targetNode) return false;

            // Filtro de Nome (Lógica Ego Network: Mostra conexões ONDE o parlamentar selecionado participa)
            if (visualFilters.parlamentares.length > 0) {
                const sourceIsSelected = visualFilters.parlamentares.includes(link.source);
                const targetIsSelected = visualFilters.parlamentares.includes(link.target);

                // Mantém o link se Pelo Menos Um dos lados for um parlamentar selecionado
                if (!sourceIsSelected && !targetIsSelected) return false;
            }

            return true;
        });

        // 3. Filtrar Nós Finais (Manter apenas nós com links ou os próprios selecionados)
        const activeNodeIds = new Set();
        linksFiltrados.forEach(l => {
            activeNodeIds.add(l.source);
            activeNodeIds.add(l.target);
        });

        // Garantir que os parlamentares selecionados apareçam mesmo se isolados (se passarem no filtro de estado/partido)
        if (visualFilters.parlamentares.length > 0) {
            visualFilters.parlamentares.forEach(p => {
                if (nodesBase.find(n => n.id === p)) {
                    activeNodeIds.add(p);
                }
            });
        } else {
            // Se não tem filtro de nome, mostra todos os nós base que sobraram (ou apenas os conectados?)
            // Vamos mostrar todos os base para manter consistência com o comportamento padrão
            nodesBase.forEach(n => activeNodeIds.add(n.id));
        }

        const nodesFiltrados = nodesBase.filter(n => activeNodeIds.has(n.id));

        const option = {
            title: {
                text: '🤝 Redes de Relacionamento Parlamentar',
                subtext: `${parlamentaresUnicos.size} parlamentares, ${conexoesFiltradas.length} conexões`,
                top: 'bottom',
                left: 'right',
                textStyle: { color: '#003366', fontSize: 16, fontWeight: 'bold' },
                subtextStyle: { color: '#666666' }
            },
            tooltip: {
                trigger: 'item',
                backgroundColor: 'rgba(255, 255, 255, 0.98)',
                borderColor: '#003366',
                borderWidth: 2,
                textStyle: {
                    color: '#333333',
                    fontSize: 12,
                    lineHeight: 18,
                    overflow: 'visible'
                },
                extraCssText: 'width: 400px; max-height: 400px; overflow-y: auto; overflow-x: hidden; padding: 15px; border-radius: 8px; box-shadow: 0 4px 16px rgba(0,51,102,0.3); word-wrap: break-word; white-space: normal;',
                triggerOn: 'click',  // Tooltip só aparece ao clicar
                alwaysShowContent: false,
                enterable: true,  // Permite entrar no tooltip
                hideDelay: 0,  // Não esconde automaticamente
                confine: true,  // Mantém o tooltip dentro do container
            },
            backgroundColor: '#FFFFFF',
            animationDuration: 1500,
            legend: {
                data: ['Parlamentar', 'Partido', 'Estado'],
                orient: 'vertical',
                left: 'left',
                top: 'top',
                textStyle: {
                    color: '#333333'
                },
                borderColor: '#E0E0E0',
                borderWidth: 1,
                padding: 10,
                backgroundColor: 'rgba(255, 255, 255, 0.9)',
            },
            series: [{
                type: 'graph',
                layout: 'force',
                data: nodesFiltrados,
                links: linksFiltrados,
                categories: [
                    { name: 'Parlamentar', itemStyle: { color: '#003366' } },
                    { name: 'Partido', itemStyle: { color: '#009739' } },
                    { name: 'Estado', itemStyle: { color: '#ED8B00' } }
                ],
                roam: true,
                label: {
                    show: false, // Ocultar rótulos por padrão
                    position: 'right',
                    formatter: '{b}'
                },
                force: {
                    repulsion: 2500,
                    edgeLength: 250,
                    gravity: 0.08
                },
                emphasis: {
                    focus: 'adjacency',
                    lineStyle: { width: 8 },
                    itemStyle: {
                        shadowBlur: 20,
                        shadowColor: 'rgba(0, 51, 102, 0.5)',
                        borderWidth: 4,
                    },
                    label: {
                        show: true, // Mostrar rótulos ao passar o mouse
                        fontSize: 14,
                        fontWeight: 'bold',
                        backgroundColor: 'rgba(255, 255, 255, 0.8)',
                        padding: [4, 8],
                        borderRadius: 4
                    }
                },
                lineStyle: {
                    curveness: 0.3,
                    opacity: 0.8
                }
            }]
        };

        return option;
    };

    const getEstatisticas = () => {
        if (conexoes.length === 0) return null;

        const parlamentaresUnicos = new Set([
            ...conexoes.map(c => c.citante),
            ...conexoes.map(c => c.citado)
        ]);

        const sentimentosCont = {};
        conexoes.forEach(c => {
            sentimentosCont[c.sentimento] = (sentimentosCont[c.sentimento] || 0) + 1;
        });

        const topCitados = {};
        conexoes.forEach(c => {
            topCitados[c.citado] = (topCitados[c.citado] || 0) + 1;
        });

        return {
            totalConexoes: conexoes.length,
            parlamentares: parlamentaresUnicos.size,
            sentimentos: sentimentosCont,
            topCitados: Object.entries(topCitados)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10)
        };
    };

    const stats = getEstatisticas();

    const SpinnerIcon = () => (
        <CircularProgress size={18} thickness={4} sx={{ mr: 1, color: 'inherit', opacity: 0.6 }} />
    );

    return (
        <Container maxWidth="xl">
            <Box sx={{ mb: 4, backgroundColor: 'white', p: 3, borderRadius: '16px', display: 'flex', alignItems: 'center', gap: 4 }}>
                <Box sx={{ flex: 1 }}>
                    <Typography
                        variant="h3"
                        component="h1"
                        sx={{
                            color: '#003366',
                            fontWeight: 700,
                            mb: 2,
                            display: 'flex',
                            alignItems: 'center',
                            gap: 2,
                        }}
                    >
                        <NetworkIcon sx={{ fontSize: 40, color: '#009739' }} />
                        Redes de Relacionamento Parlamentar
                    </Typography>
                    <Typography variant="h6" sx={{ color: '#666666' }}>
                        Visualize as conexões entre parlamentares baseadas nas citações nos discursos
                    </Typography>
                </Box>
                <Box
                    component="img"
                    src="/Redes_de_Relacionamento_Parlamentar.png"
                    alt="Ilustração Redes Parlamentares"
                    sx={{
                        maxHeight: '220px',
                        width: 'auto',
                        borderRadius: '8px',
                        display: { xs: 'none', md: 'block' }
                    }}
                />
            </Box>

            {/* Filtros */}
            <Paper elevation={2} sx={{ p: 4, mb: 4 }}>
                <Typography variant="h5" sx={{ color: '#003366', mb: 3 }}>
                    🔍 Filtros de Análise
                </Typography>

                {/* Sentimento, Período e Rigor */}
                <Grid container spacing={3} sx={{ mb: 3 }} alignItems="center">
                    <Grid item xs={12} md={4}>
                        <FormControl fullWidth>
                            <InputLabel>Sentimento das Citações</InputLabel>
                            <Select
                                value={filtros.sentimento}
                                label="Sentimento das Citações"
                                disabled={loadingFiltros}
                                IconComponent={loadingFiltros ? SpinnerIcon : undefined}
                                onChange={(e) => handleFiltroChange('sentimento', e.target.value)}
                            >
                                <MenuItem value="Todos">Todos</MenuItem>
                                {sentimentos.map(sent => (
                                    <MenuItem key={sent} value={sent}>{sent}</MenuItem>
                                ))}
                            </Select>
                        </FormControl>
                    </Grid>
                    <Grid item xs={12} md={4}>
                        <TextField
                            fullWidth
                            label="Data Início"
                            type="date"
                            value={startDate}
                            onChange={(e) => setStartDate(e.target.value)}
                            InputLabelProps={{ shrink: true }}
                        />
                    </Grid>
                    <Grid item xs={12} md={4}>
                        <TextField
                            fullWidth
                            label="Data Fim"
                            type="date"
                            value={endDate}
                            onChange={(e) => setEndDate(e.target.value)}
                            InputLabelProps={{ shrink: true }}
                        />
                    </Grid>
                </Grid>

                <Grid container spacing={3}>
                    {/* Filtros: Quem Cita */}
                    <Grid item xs={12} md={6}>
                        <Paper elevation={1} sx={{ p: 3, backgroundColor: '#f5f5f5' }}>
                            <Typography variant="h6" sx={{ color: '#003366', mb: 2 }}>
                                👤 Quem Cita
                            </Typography>

                            <Grid container spacing={2}>
                                <Grid item xs={12}>
                                    <Autocomplete
                                        multiple
                                        options={estados}
                                        value={filtros.estadosCitantes}
                                        onChange={(e, newValue) => handleFiltroChange('estadosCitantes', newValue)}
                                        loading={loadingFiltros}
                                        loadingText="Carregando..."
                                        renderInput={(params) => <TextField {...params} label="Estados (múltiplo)" size="small" />}
                                        renderTags={(value, getTagProps) =>
                                            value.map((option, index) => (
                                                <Chip label={option} size="small" {...getTagProps({ index })} />
                                            ))
                                        }
                                    />
                                </Grid>

                                <Grid item xs={12}>
                                    <Autocomplete
                                        multiple
                                        options={partidosCitanteFiltrados}
                                        value={filtros.partidosCitantes}
                                        onChange={(e, newValue) => handleFiltroChange('partidosCitantes', newValue)}
                                        loading={loadingFiltros}
                                        loadingText="Carregando..."
                                        renderInput={(params) => <TextField {...params} label="Partidos (múltiplo)" size="small" />}
                                        renderTags={(value, getTagProps) =>
                                            value.map((option, index) => (
                                                <Chip label={option} size="small" {...getTagProps({ index })} />
                                            ))
                                        }
                                    />
                                </Grid>

                                <Grid item xs={12}>
                                    <Autocomplete
                                        multiple
                                        options={parlamentaresCitanteFiltrados}
                                        value={filtros.parlamentaresCitantes}
                                        onChange={(e, newValue) => handleFiltroChange('parlamentaresCitantes', newValue)}
                                        loading={loadingParlamentares}
                                        loadingText="Carregando..."
                                        renderInput={(params) => <TextField {...params} label="Parlamentares (múltiplo)" size="small" />}
                                        renderTags={(value, getTagProps) =>
                                            value.map((option, index) => (
                                                <Chip label={option} size="small" {...getTagProps({ index })} />
                                            ))
                                        }
                                    />
                                </Grid>
                            </Grid>
                        </Paper>
                    </Grid>

                    {/* Filtros: Quem é Citado */}
                    <Grid item xs={12} md={6}>
                        <Paper elevation={1} sx={{ p: 3, backgroundColor: '#f5f5f5' }}>
                            <Typography variant="h6" sx={{ color: '#003366', mb: 2 }}>
                                👥 Quem é Citado
                            </Typography>

                            <Grid container spacing={2}>
                                <Grid item xs={12}>
                                    <Autocomplete
                                        multiple
                                        options={estados}
                                        value={filtros.estadosCitados}
                                        onChange={(e, newValue) => handleFiltroChange('estadosCitados', newValue)}
                                        loading={loadingFiltros}
                                        loadingText="Carregando..."
                                        renderInput={(params) => <TextField {...params} label="Estados (múltiplo)" size="small" />}
                                        renderTags={(value, getTagProps) =>
                                            value.map((option, index) => (
                                                <Chip label={option} size="small" {...getTagProps({ index })} />
                                            ))
                                        }
                                    />
                                </Grid>

                                <Grid item xs={12}>
                                    <Autocomplete
                                        multiple
                                        options={partidosCitadoFiltrados}
                                        value={filtros.partidosCitados}
                                        onChange={(e, newValue) => handleFiltroChange('partidosCitados', newValue)}
                                        loading={loadingFiltros}
                                        loadingText="Carregando..."
                                        renderInput={(params) => <TextField {...params} label="Partidos (múltiplo)" size="small" />}
                                        renderTags={(value, getTagProps) =>
                                            value.map((option, index) => (
                                                <Chip label={option} size="small" {...getTagProps({ index })} />
                                            ))
                                        }
                                    />
                                </Grid>

                                <Grid item xs={12}>
                                    <Autocomplete
                                        multiple
                                        options={parlamentaresCitadoFiltrados}
                                        value={filtros.parlamentaresCitados}
                                        onChange={(e, newValue) => handleFiltroChange('parlamentaresCitados', newValue)}
                                        loading={loadingParlamentares}
                                        loadingText="Carregando..."
                                        renderInput={(params) => <TextField {...params} label="Parlamentares (múltiplo)" size="small" />}
                                        renderTags={(value, getTagProps) =>
                                            value.map((option, index) => (
                                                <Chip label={option} size="small" {...getTagProps({ index })} />
                                            ))
                                        }
                                    />
                                </Grid>
                            </Grid>
                        </Paper>
                    </Grid>
                </Grid>


                <Box sx={{ mt: 3, textAlign: 'center' }}>
                    <Button
                        variant="contained"
                        size="large"
                        onClick={carregarConexoes}
                        disabled={loading}
                        startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <Avatar src="/expressions/antunes_angry.png" sx={{ width: 28, height: 28, mr: 0.5 }} />}
                        sx={{
                            backgroundColor: '#003366',
                            '&:hover': {
                                backgroundColor: '#001a33',
                            },
                            px: 4,
                            py: 1.5,
                            fontSize: '1.1rem',
                            fontWeight: 'bold',
                            borderRadius: '12px'
                        }}
                    >
                        {loading ? 'Analisando...' : 'Gerar Análise de Conexões'}
                    </Button>
                </Box>
            </Paper>

            {/* Error Alert */}
            {error && (
                <Alert severity="error" sx={{ mb: 4 }}>
                    {error}
                </Alert>
            )}

            {/* Resultados */}
            {conexoes.length > 0 && (
                <>
                    {/* Estatísticas */}
                    <Grid container spacing={3} sx={{ mb: 4 }}>
                        <Grid item xs={12} md={3}>
                            <Card elevation={2}>
                                <CardContent>
                                    <Typography variant="h6" color="text.secondary">
                                        Total de Conexões
                                    </Typography>
                                    <Typography variant="h3" sx={{ color: '#009739', fontWeight: 700 }}>
                                        {stats.totalConexoes}
                                    </Typography>
                                </CardContent>
                            </Card>
                        </Grid>

                        <Grid item xs={12} md={3}>
                            <Card elevation={2}>
                                <CardContent>
                                    <Typography variant="h6" color="text.secondary">
                                        Parlamentares
                                    </Typography>
                                    <Typography variant="h3" sx={{ color: '#003366', fontWeight: 700 }}>
                                        {stats.parlamentares}
                                    </Typography>
                                </CardContent>
                            </Card>
                        </Grid>

                        <Grid item xs={12} md={3}>
                            <Card elevation={2}>
                                <CardContent>
                                    <Typography variant="h6" color="text.secondary">
                                        Estados
                                    </Typography>
                                    <Typography variant="h3" sx={{ color: '#ED8B00', fontWeight: 700 }}>
                                        {new Set(conexoes.map(c => c.estado_citante)).size}
                                    </Typography>
                                </CardContent>
                            </Card>
                        </Grid>

                        <Grid item xs={12} md={3}>
                            <Card elevation={2}>
                                <CardContent>
                                    <Typography variant="h6" color="text.secondary">
                                        Partidos
                                    </Typography>
                                    <Typography variant="h3" sx={{ color: '#4ECDC4', fontWeight: 700 }}>
                                        {new Set(conexoes.map(c => c.partido_citante)).size}
                                    </Typography>
                                </CardContent>
                            </Card>
                        </Grid>
                    </Grid>

                    {/* Layout Vertical (Sem Abas) */}
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>

                        {/* 1. Grafo de Conexões */}
                        <Paper elevation={2} sx={{ p: 4 }}>
                            <Typography variant="h5" sx={{ color: '#003366', mb: 3, display: 'flex', alignItems: 'center', gap: 1 }}>
                                🗺️ Grafo de Conexões
                            </Typography>

                            {/* Filtros de Visualização */}
                            <Box sx={{ mb: 3 }}>
                                <Typography variant="h6" sx={{ color: '#003366', mb: 2 }}>
                                    👁️ Visualização do Grafo
                                </Typography>
                                <Grid container spacing={2} sx={{ mb: 3 }}>
                                    <Grid item>
                                        <Chip
                                            label="🏛️ Mostrar Partidos"
                                            onClick={() => setMostrarPartidos(!mostrarPartidos)}
                                            color={mostrarPartidos ? "primary" : "default"}
                                            variant={mostrarPartidos ? "filled" : "outlined"}
                                        />
                                    </Grid>
                                    <Grid item>
                                        <Chip
                                            label="🗺️ Mostrar Estados"
                                            onClick={() => setMostrarEstados(!mostrarEstados)}
                                            color={mostrarEstados ? "primary" : "default"}
                                            variant={mostrarEstados ? "filled" : "outlined"}
                                        />
                                    </Grid>
                                </Grid>

                                <Typography variant="h6" sx={{ color: '#003366', mb: 2, mt: 2 }}>
                                    🕵️ Filtros Específicos do Grafo
                                </Typography>
                                <Grid container spacing={2} sx={{ mb: 3 }}>
                                    <Grid item xs={12} md={4}>
                                        <Autocomplete
                                            multiple
                                            options={opcoesFiltrosVisuais.estados}
                                            value={visualFilters.estados}
                                            onChange={(e, newValue) => setVisualFilters({ ...visualFilters, estados: newValue })}
                                            loading={loading}
                                            loadingText="Carregando..."
                                            renderInput={(params) => <TextField {...params} label="Filtrar por Estados" size="small" />}
                                            renderTags={(value, getTagProps) =>
                                                value.map((option, index) => (
                                                    <Chip label={option} size="small" {...getTagProps({ index })} />
                                                ))
                                            }
                                        />
                                    </Grid>
                                    <Grid item xs={12} md={4}>
                                        <Autocomplete
                                            multiple
                                            options={opcoesFiltrosVisuais.partidos}
                                            value={visualFilters.partidos}
                                            onChange={(e, newValue) => setVisualFilters({ ...visualFilters, partidos: newValue })}
                                            loading={loading}
                                            loadingText="Carregando..."
                                            renderInput={(params) => <TextField {...params} label="Filtrar por Partidos" size="small" />}
                                            renderTags={(value, getTagProps) =>
                                                value.map((option, index) => (
                                                    <Chip label={option} size="small" {...getTagProps({ index })} />
                                                ))
                                            }
                                        />
                                    </Grid>
                                    <Grid item xs={12} md={4}>
                                        <Autocomplete
                                            multiple
                                            options={opcoesFiltrosVisuais.parlamentares}
                                            value={visualFilters.parlamentares}
                                            onChange={(e, newValue) => setVisualFilters({ ...visualFilters, parlamentares: newValue })}
                                            loading={loading}
                                            loadingText="Carregando..."
                                            renderInput={(params) => <TextField {...params} label="Filtrar Parlamentares" size="small" />}
                                            renderTags={(value, getTagProps) =>
                                                value.map((option, index) => (
                                                    <Chip label={option} size="small" {...getTagProps({ index })} />
                                                ))
                                            }
                                        />
                                    </Grid>
                                </Grid>

                                <Typography variant="h6" sx={{ color: '#003366', mb: 2 }}>
                                    🎨 Filtros de Sentimento das Conexões
                                </Typography>
                                <Grid container spacing={2}>
                                    <Grid item>
                                        <Chip
                                            label="🟢 Verde (Apoio)"
                                            onClick={() => setFiltrosCores({ ...filtrosCores, verde: !filtrosCores.verde })}
                                            color={filtrosCores.verde ? "success" : "default"}
                                            variant={filtrosCores.verde ? "filled" : "outlined"}
                                        />
                                    </Grid>
                                    <Grid item>
                                        <Chip
                                            label="🔴 Vermelho (Crítica)"
                                            onClick={() => setFiltrosCores({ ...filtrosCores, vermelho: !filtrosCores.vermelho })}
                                            color={filtrosCores.vermelho ? "error" : "default"}
                                            variant={filtrosCores.vermelho ? "filled" : "outlined"}
                                        />
                                    </Grid>
                                    <Grid item>
                                        <Chip
                                            label="🟡 Amarelo (Neutro)"
                                            onClick={() => setFiltrosCores({ ...filtrosCores, amarelo: !filtrosCores.amarelo })}
                                            color={filtrosCores.amarelo ? "warning" : "default"}
                                            variant={filtrosCores.amarelo ? "filled" : "outlined"}
                                        />
                                    </Grid>
                                    <Grid item>
                                        <Chip
                                            label="🟠 Laranja (Questionador)"
                                            onClick={() => setFiltrosCores({ ...filtrosCores, laranja: !filtrosCores.laranja })}
                                            sx={{
                                                backgroundColor: filtrosCores.laranja ? '#FF8C00' : 'transparent',
                                                color: filtrosCores.laranja ? '#fff' : '#FF8C00',
                                                borderColor: '#FF8C00',
                                            }}
                                            variant={filtrosCores.laranja ? "filled" : "outlined"}
                                        />
                                    </Grid>
                                </Grid>
                            </Box>

                            {/* Grafo */}
                            <Box sx={{
                                backgroundColor: '#FFFFFF',
                                borderRadius: 2,
                                p: 2,
                                border: '2px solid #E0E0E0',
                                boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                            }}>
                                {criarGrafoECharts() && (
                                    <Box sx={{
                                        '& svg image': {
                                            clipPath: 'circle(50%)'
                                        }
                                    }}>
                                        <ReactECharts
                                            option={criarGrafoECharts()}
                                            style={{ height: '800px', width: '100%' }}
                                            opts={{ renderer: 'svg' }}
                                        />
                                    </Box>
                                )}
                            </Box>

                            <Alert severity="warning" sx={{ mt: 2, mb: 2 }}>
                                ⚠️ <strong>Importante:</strong> Os sentimentos analisados (Apoio, Crítica, Neutro, Questionador)
                                se referem às frases coletadas e não representam o sentimento geral entre os parlamentares.
                                Para entender o contexto completo, <strong>clique nas conexões</strong> para ler os textos exatos das citações.
                            </Alert>

                            <Alert severity="info" sx={{ mt: 1 }}>
                                💡 <strong>Dicas de uso:</strong> Clique e arraste para navegar, use o scroll para zoom.
                                <strong>Clique nas conexões (linhas) ou nos parlamentares para ver os detalhes completos.</strong>
                                O tooltip ficará travado para você ler com calma.
                            </Alert>
                        </Paper>

                        {/* 2. Análise de Sentimentos */}
                        {stats && (
                            <Paper elevation={2} sx={{ p: 4 }}>
                                <Typography variant="h5" sx={{ color: '#003366', mb: 3, display: 'flex', alignItems: 'center', gap: 1 }}>
                                    📊 Análise de Sentimentos
                                </Typography>

                                <Grid container spacing={3}>
                                    {Object.entries(stats.sentimentos).map(([sent, qtd]) => (
                                        <Grid item xs={12} md={3} key={sent}>
                                            <Card>
                                                <CardContent>
                                                    <Typography variant="h6">{sent}</Typography>
                                                    <Typography variant="h3" sx={{ color: '#009739' }}>
                                                        {qtd}
                                                    </Typography>
                                                    <Typography variant="body2" color="text.secondary">
                                                        {((qtd / stats.totalConexoes) * 100).toFixed(1)}% do total
                                                    </Typography>
                                                </CardContent>
                                            </Card>
                                        </Grid>
                                    ))}
                                </Grid>
                            </Paper>
                        )}

                        {/* Aba 3: Relatório IA */}
                        {/* 3. Estatísticas Gerais */}
                        {stats && (
                            <Paper elevation={2} sx={{ p: 4 }}>
                                <Typography variant="h5" sx={{ color: '#003366', mb: 3, display: 'flex', alignItems: 'center', gap: 1 }}>
                                    📈 Estatísticas Gerais
                                </Typography>

                                <Grid container spacing={3}>
                                    <Grid item xs={12} md={6}>
                                        <Card sx={{ height: '100%' }}>
                                            <CardContent>
                                                <Typography variant="h6" gutterBottom>📊 Resumo dos Dados</Typography>
                                                <Box sx={{ mt: 2 }}>
                                                    <Typography sx={{ mb: 1 }}><strong>Total de Conexões:</strong> {stats.totalConexoes}</Typography>
                                                    <Typography sx={{ mb: 1 }}><strong>Parlamentares Únicos:</strong> {stats.parlamentares}</Typography>
                                                    <Typography sx={{ mb: 1 }}><strong>Estados Representados:</strong> {new Set(conexoes.map(c => c.estado_citante)).size}</Typography>
                                                    <Typography sx={{ mb: 1 }}><strong>Partidos Representados:</strong> {new Set(conexoes.map(c => c.partido_citante)).size}</Typography>
                                                </Box>
                                            </CardContent>
                                        </Card>
                                    </Grid>

                                    <Grid item xs={12} md={6}>
                                        <Card sx={{ height: '100%' }}>
                                            <CardContent>
                                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                                                    <Typography variant="h6">🎯 Top Conexões</Typography>
                                                    <Tooltip title="As conexões mais frequentes entre parlamentares no período selecionado.">
                                                        <InfoIcon fontSize="small" color="action" />
                                                    </Tooltip>
                                                </Box>
                                                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                                                    {conexoes.slice(0, 5).map((c, i) => (
                                                        <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1, borderRadius: 1, bgcolor: '#f5f5f5' }}>
                                                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                                                <Avatar src={c.foto_citante} alt={c.citante} sx={{ width: 32, height: 32 }} />
                                                                <Typography variant="body2" sx={{ fontWeight: 'bold', fontSize: '0.85rem' }}>{c.citante}</Typography>
                                                            </Box>
                                                            <Typography variant="body2" color="text.secondary">→</Typography>
                                                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                                                <Avatar src={c.foto_citado} alt={c.citado} sx={{ width: 32, height: 32 }} />
                                                                <Typography variant="body2" sx={{ fontWeight: 'bold', fontSize: '0.85rem' }}>{c.citado}</Typography>
                                                            </Box>
                                                        </Box>
                                                    ))}
                                                </Box>
                                            </CardContent>
                                        </Card>
                                    </Grid>

                                    <Grid item xs={12}>
                                        <Typography variant="h6" sx={{ mt: 2, mb: 2 }}>🏆 Top 10 Parlamentares Mais Citados</Typography>
                                        <Grid container spacing={2}>
                                            {stats.topCitados.map(([nome, qtd], index) => {
                                                // Encontrar info do parlamentar para pegar foto/partido/estado
                                                // Como topCitados é [nome, qtd], precisamos buscar nos dados completos
                                                // Tentamos achar nos conexoes (como citado) ou parlamentaresInfo
                                                const info = parlamentaresInfo.find(p => p.nome === nome) || {};
                                                const conexaoExemplo = conexoes.find(c => c.citado === nome);
                                                const fotoUrl = conexaoExemplo?.foto_citado || `https://www.camara.leg.br/internet/deputado/bandep/${info.id}.jpg`; // Fallback se tiver ID no info

                                                return (
                                                    <Grid item xs={12} sm={6} md={4} key={nome}>
                                                        <Paper elevation={1} sx={{ p: 2, height: '100%', display: 'flex', alignItems: 'center', gap: 2 }}>
                                                            <Typography variant="h4" sx={{ color: '#ED8B00', fontWeight: 700, minWidth: 30 }}>
                                                                {index + 1}º
                                                            </Typography>
                                                            <Avatar
                                                                src={fotoUrl}
                                                                alt={nome}
                                                                sx={{ width: 56, height: 56, border: '2px solid #009739' }}
                                                            />
                                                            <Box>
                                                                <Typography variant="subtitle1" sx={{ fontWeight: 600, lineHeight: 1.2, mb: 0.5 }}>
                                                                    {nome}
                                                                </Typography>
                                                                <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                                                                    {info.partido && <Chip label={info.partido} size="small" sx={{ height: 20, fontSize: '0.7rem' }} />}
                                                                    {info.estado && <Chip label={info.estado} size="small" sx={{ height: 20, fontSize: '0.7rem' }} />}
                                                                    <Chip label={`${qtd} citações`} size="small" color="primary" sx={{ height: 20, fontSize: '0.7rem' }} />
                                                                </Box>
                                                            </Box>
                                                        </Paper>
                                                    </Grid>
                                                );
                                            })}
                                        </Grid>
                                    </Grid>
                                </Grid>
                            </Paper>
                        )}

                        {/* 4. Relatório IA - Design Robo Antunes */}
                        <Box sx={{ my: 4 }}>
                            {!relatorioIA && (
                                <Button
                                    variant="contained"
                                    size="large"
                                    fullWidth
                                    onClick={gerarRelatorioIA}
                                    disabled={loadingRelatorio || conexoes.length === 0}
                                    startIcon={
                                        loadingRelatorio ? (
                                            <CircularProgress size={30} color="inherit" />
                                        ) : (
                                            <Box
                                                component="img"
                                                src="/expressions/antunes_angry.png"
                                                alt="IA Antunes"
                                                sx={{
                                                    height: 100,
                                                    width: 100,
                                                    borderRadius: '50%',
                                                    border: '4px solid #FFF',
                                                    objectFit: 'cover',
                                                    objectPosition: 'center 15%',
                                                    marginRight: 2,
                                                    boxShadow: '0 4px 8px rgba(0,0,0,0.3)',
                                                    bgcolor: '#FFF'
                                                }}
                                            />
                                        )
                                    }
                                    sx={{
                                        bgcolor: '#003366',
                                        '&:hover': { bgcolor: '#004488' },
                                        py: 3,
                                        px: 4,
                                        fontSize: '1.2rem',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'flex-start',
                                        textAlign: 'left',
                                        borderRadius: 4,
                                        boxShadow: 3,
                                        textTransform: 'none'
                                    }}
                                >
                                    {loadingRelatorio 
                                        ? 'O Robô Antunes está analisando o sociograma...' 
                                        : `Acione o Robô Antunes para gerar o Relatório de Análise de Influência e Conexões (${conexoes.length} interações)`}
                                </Button>
                            )}
                        </Box>

                            {relatorioIA && (
                                <>
                                    <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
                                        <Button
                                            variant="outlined"
                                            onClick={() => copiarTexto(relatorioIA.relatorio)}
                                            sx={{ borderColor: '#009739', color: '#009739' }}
                                        >
                                            📋 Copiar Relatório
                                        </Button>
                                        <Button
                                            variant="outlined"
                                            onClick={() => setRelatorioIA(null)}
                                            sx={{ borderColor: '#ED8B00', color: '#ED8B00' }}
                                        >
                                            🔄 Gerar Novo
                                        </Button>
                                    </Box>

                                    <Paper elevation={1} sx={{ p: 3, backgroundColor: '#f9f9f9', mb: 3 }}>
                                        <Grid container spacing={2}>
                                            <Grid item xs={12} md={3}>
                                                <Typography variant="body2" color="text.secondary">
                                                    Total de Conexões
                                                </Typography>
                                                <Typography variant="h6" sx={{ color: '#009739' }}>
                                                    {relatorioIA.total_conexoes_analisadas}
                                                </Typography>
                                            </Grid>
                                            <Grid item xs={12} md={3}>
                                                <Typography variant="body2" color="text.secondary">
                                                    Parlamentares
                                                </Typography>
                                                <Typography variant="h6" sx={{ color: '#003366' }}>
                                                    {relatorioIA.parlamentares_envolvidos}
                                                </Typography>
                                            </Grid>
                                            <Grid item xs={12} md={3}>
                                                <Typography variant="body2" color="text.secondary">
                                                    Comissões
                                                </Typography>
                                                <Typography variant="h6" sx={{ color: '#ED8B00' }}>
                                                    {relatorioIA.comissoes?.length || 0}
                                                </Typography>
                                            </Grid>
                                            <Grid item xs={12} md={3}>
                                                <Typography variant="body2" color="text.secondary">
                                                    Período
                                                </Typography>
                                                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                                    {relatorioIA.periodo?.inicio || 'N/A'} a {relatorioIA.periodo?.fim || 'N/A'}
                                                </Typography>
                                            </Grid>
                                        </Grid>
                                    </Paper>

                                    <Paper elevation={1} sx={{ p: 4, backgroundColor: '#fff' }}>
                                        <Box
                                            sx={{
                                                '& h1, & h2, & h3, & h4, & h5, & h6': {
                                                    color: '#003366',
                                                    marginTop: 3,
                                                    marginBottom: 2,
                                                    fontWeight: 700,
                                                },
                                                '& p': {
                                                    lineHeight: 1.8,
                                                    textAlign: 'justify',
                                                    marginBottom: 2,
                                                    color: '#333',
                                                },
                                                '& strong': {
                                                    color: '#009739',
                                                    fontWeight: 700,
                                                },
                                                '& ul, & ol': {
                                                    paddingLeft: 3,
                                                    marginBottom: 2,
                                                },
                                                '& li': {
                                                    marginBottom: 1,
                                                },
                                            }}
                                        >
                                            <ReactMarkdown>{relatorioIA.relatorio}</ReactMarkdown>
                                        </Box>
                                    </Paper>
                                </>
                            )}
                    
      <DataSourceFooter
        sources={[{"label":"Votações — API da Câmara","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Votacoes","type":"camara"}]}
        note="Convergência/divergência calculada com base em votações nominais registradas na Câmara dos Deputados."
      />
    </Box>
                </>
            )
            }

            {
                conexoes.length === 0 && !loading && !error && (
                    <Alert severity="info">
                        👆 Configure os filtros acima e clique em 'Gerar Análise de Conexões' para visualizar os dados.
                    </Alert>
                )
            }
        </Container >
    );
}

export default Odiograma;

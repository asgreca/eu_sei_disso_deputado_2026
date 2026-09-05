import React, { useEffect, useState } from 'react';
import {
    Box,
    Container,
    Typography,
    Paper,
    Grid,
    Card,
    CardContent,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Chip,
    Button,
    CircularProgress,
    Alert,
    FormControl,
    InputLabel,
    Select,
    MenuItem,
    Divider,
    Tooltip,
    Avatar,
} from '@mui/material';
import {
    HowToVote as VoteIcon,
    History as HistoryIcon,
    Gavel as GavelIcon,
    Info as InfoIcon,
    TrendingUp as TrendingUpIcon,
    TrendingDown as TrendingDownIcon,
    AccountBalance as GovIcon,
    ExpandMore as ExpandMoreIcon,
    ExpandLess as ExpandLessIcon,
    ListAlt as ListAltIcon,
    Newspaper as NewspaperIcon,
    Description as DescriptionIcon,
    Link as LinkIcon,
    YouTube as YouTubeIcon,
    School as SchoolIcon,
    LocalHospital as HospitalIcon,
    AttachMoney as MoneyIcon,
    Forest as ForestIcon,
    LocalPolice as PoliceIcon,
    Public as PublicIcon,
} from '@mui/icons-material';
import ReactECharts from 'echarts-for-react';
import axios from '../config/axios';
import { useNavigate } from 'react-router-dom';
import FilterSelector from '../components/FilterSelector';
import { Collapse } from '@mui/material';
import DataSourceFooter from '../components/DataSourceFooter';

const VotacoesGeral = () => {
    // State for filters including Date Range, Scope, Theme, Gov
    const [filtros, setFiltros] = useState({
        estado: 'Todos',
        partido: 'Todos',
        parlamentar: 'Todos',
        dataInicio: '2023-01-01',
        dataFim: new Date().toISOString().split('T')[0],
        orgao: 'Todos',
        tema: '',
        governo: ''
    });

    const [loading, setLoading] = useState(false);
    const [stats, setStats] = useState({ tipos: [], governo: [], temas: [] });
    const [votos, setVotos] = useState([]);
    const [temas, setTemas] = useState([]); // Kept for future use if needed, though we filter by macro themes now
    const [opcoesFiltros, setOpcoesFiltros] = useState({ orgaos: [], temas: [] });
    const [expandedId, setExpandedId] = useState(null);
    const [expandedData, setExpandedData] = useState({});
    const [detailErrors, setDetailErrors] = useState({});
    const [loadingDetail, setLoadingDetail] = useState(false);
    const [hasSearched, setHasSearched] = useState(false);
    const [loadingOrgaos, setLoadingOrgaos] = useState(false);
    const [loadingTemas, setLoadingTemas] = useState(false);
    const navigate = useNavigate();

    // --- 1. Identidade Visual (Manual da Marca) ---
    // --- 1. Identidade Visual (Manual da Marca) ---
    const colors = {
        // Cores Principais
        verde: '#009739',      // Botões, Sim
        amarelo: '#FFF81C',    // Alertas, Abstenção
        azul: '#003366',       // Cabeçalhos, Não
        branco: '#FFFFFF',
        cinza: '#666666',      // Texto secundário

        // Suporte
        azulClaro: '#4F81BD',
        verdeClaro: '#66BB6A',
        cinzaClaro: '#E0E0E0',
        laranja: '#ED8B00',    // (Laranja Escuro do manual) - Atenção
        laranjaClaro: '#FFB74D',

        // Mapeamento para código existente
        fundo: '#FFFFFF',
        textoPrincipal: '#003366', // Azul para textos principais/títulos
        textoSecundario: '#666666'
    };

    const fonts = {
        titulo: 'Montserrat, sans-serif',
        texto: 'Inter, sans-serif',
        dados: 'Roboto Mono, monospace'
    };

    const fetchFilters = async () => {
        setLoadingOrgaos(true);
        setLoadingTemas(true);
        try {
            const res = await axios.get('/api/filtros');
            setOpcoesFiltros(res.data);
            if (res.data.temas && res.data.temas.length > 0) {
                setTemas(res.data.temas);
            }
        } catch (err) {
            console.error("Erro ao buscar filtros dinamicos", err);
        } finally {
            setLoadingOrgaos(false);
            setLoadingTemas(false);
        }
    };

    const fetchStats = async () => {
        try {
            // Stats now respect filters too
            const params = {
                data_inicio: filtros.dataInicio,
                data_fim: filtros.dataFim,
                orgao: filtros.orgao,
                tema: filtros.tema,
                governo: filtros.governo
            };
            const res = await axios.get('/api/votos/stats', { params });
            setStats(res.data);

            // Extract unique themes for the dropdown if needed, though usually fixed
            if (res.data.temas) {
                setTemas(res.data.temas.map(t => t.tema_macro).filter(Boolean));
            }
        } catch (err) {
            console.error("Erro ao buscar stats", err);
        }
    };

    const fetchVotos = async () => {
        setLoading(true);
        try {
            const params = {
                data_inicio: filtros.dataInicio,
                data_fim: filtros.dataFim,
                orgao: filtros.orgao,
                tema: filtros.tema,
                governo: filtros.governo
            };
            const res = await axios.get('/api/votos/lista', { params });
            setVotos(res.data);
        } catch (err) {
            console.error("Erro ao buscar votos", err);
        } finally {
            setLoading(false);
        }
    };

    // Initial Load - Filters Only
    useEffect(() => {
        fetchFilters();
    }, []);

    const onFiltersChange = (newFilters) => {
        setFiltros(prev => ({ ...prev, ...newFilters }));
    };

    // No auto-fetch on mount for data (User must search)

    const handleSearch = () => {
        setHasSearched(true);
        fetchStats();
        fetchVotos();
    };

    const handleFilterChange = (field) => (event) => {
        setFiltros(prev => ({ ...prev, [field]: event.target.value }));
    };

    const toggleExpand = async (id) => {
        if (expandedId === id) {
            setExpandedId(null);
            return;
        }
        setExpandedId(id);

        if (!expandedData[id]) {
            setLoadingDetail(true);
            try {
                const res = await axios.get(`/api/votos/detalhe/${id}`);
                setExpandedData(prev => ({ ...prev, [id]: res.data }));
                setDetailErrors(prev => ({ ...prev, [id]: null }));
            } catch (err) {
                console.error("Erro ao carregar detalhes", err);
                const message = err?.response?.data?.detail || err?.message || 'Não foi possível carregar os detalhes desta votação.';
                setDetailErrors(prev => ({ ...prev, [id]: message }));
            } finally {
                setLoadingDetail(false);
            }
        }
    };

    // ... (Charts configuration remain same) ...
    const totalVotacoes = (stats.tipos || []).reduce((acc, curr) => acc + (parseInt(curr.total) || 0), 0);

    const getGovernmentVictoryTitle = () => {
        if (filtros.governo === 'Não') {
            return 'PERCENTUAL DE PAUTAS DE OPOSIÇÃO APROVADAS';
        }
        if (filtros.governo === 'Sim') {
            return 'PERCENTUAL DE PAUTAS DE INTERESSE DO GOVERNO QUE O GOVERNO VENCEU';
        }
        return 'PERCENTUAL DE PROJETOS QUE O GOVERNO VENCEU';
    };

    const getGovernmentVictoryExplanation = () => {
        if (filtros.governo === 'Não') {
            return 'Aqui o indicador mostra a derrota do governo: se uma pauta de oposição é aprovada, ela entra no percentual; se é rejeitada, fica fora.';
        }
        if (filtros.governo === 'Sim') {
            return 'Aqui vitória do governo significa aprovação de uma pauta classificada como favorável ao governo.';
        }
        return 'A taxa combina os dois sentidos: pautas pró-governo aprovadas e pautas de oposição rejeitadas contam como vitória do governo.';
    };

    // Configuração Gráfico de Pizza (Tipos)
    const getPieOption = () => ({
        title: { text: 'Tipo de Votação', left: 'center', textStyle: { color: colors.azul, fontWeight: 'bold' } },
        tooltip: { trigger: 'item' },
        legend: { bottom: '0%' },
        series: [
            {
                name: 'Total',
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: false,
                itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
                label: { show: false, position: 'center' },
                emphasis: { label: { show: true, fontSize: '20', fontWeight: 'bold' } },
                data: (stats.tipos || []).map(t => ({
                    value: t.total,
                    name: t.tipo_votacao,
                    itemStyle: { color: t.tipo_votacao === 'Nominal' ? colors.verde : colors.laranja }
                }))
            }
        ]
    });

    // Configuração Gráfico Treemap (Temas Macro)
    const getTreemapOption = () => ({
        tooltip: { formatter: '{b}: {c}' },
        series: [{
            type: 'treemap',
            leafDepth: 1,
            roam: false,
            nodeClick: false,
            breadcrumb: { show: false },
            itemStyle: { borderColor: '#fff', gapWidth: 2 },
            data: (stats.temas || []).map((t, index) => ({
                name: t.macro_tema || t.tema_macro || 'Outros',
                value: t.total,
                itemStyle: { color: [colors.azul, colors.verde, colors.azulClaro, colors.verdeClaro, colors.laranja, colors.amarelo][index % 6] }
            }))
        }]
    });

    // Configuração Gráfico de Vitória do Governo (Gauge)
    const getVictoryOption = () => {
        const vitorias = (stats.vitoria && stats.vitoria[0]) ? stats.vitoria[0].vitorias : 0;
        const total = (stats.vitoria && stats.vitoria[0]) ? stats.vitoria[0].total_validos : 0;
        const taxaBase = total > 0 ? (vitorias / total) * 100 : 0;
        const taxa = filtros.governo === 'Não'
            ? (100 - taxaBase).toFixed(1)
            : taxaBase.toFixed(1);

        return {
            series: [{
                type: 'gauge',
                startAngle: 180, endAngle: 0,
                min: 0, max: 100,
                radius: '100%',
                center: ['50%', '70%'],
                axisLine: { lineStyle: { width: 40, color: [[1, '#e6ebf8']] } },
                progress: { show: true, width: 40, itemStyle: { color: colors.verde } },
                pointer: { show: false },
                axisTick: { show: false },
                splitLine: { show: false },
                axisLabel: { show: false },
                title: { show: false },
                detail: {
                    valueAnimation: true,
                    fontSize: 40,
                    offsetCenter: [0, '-20%'],
                    formatter: '{value}%',
                    color: colors.azul,
                    fontWeight: 'bold'
                },
                data: [{ value: taxa }]
            }]
        };
    };

    // Configuração Gráfico de Alinhamento Governo (Pizza)
    const getGovPieOption = () => ({
        tooltip: { trigger: 'item' },
        legend: { bottom: '0%' },
        color: [colors.verde, colors.azul, colors.amarelo, colors.cinza],
        series: [
            {
                name: 'Alinhamento',
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: false,
                itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
                label: { show: false, position: 'center' },
                emphasis: { label: { show: true, fontSize: '18', fontWeight: 'bold' } },
                data: (stats.governo || []).map(g => {
                    let name = g.pauta_governo;
                    let color = colors.cinza;
                    // Manual: Sim = Verde, Não = Azul, Indiferente/Abstenção = Amarelo
                    if (name === 'Sim') { name = 'Pauta Governo'; color = colors.verde; }
                    else if (name === 'Não') { name = 'Contra Governo'; color = colors.azul; }
                    else { name = 'Indiferente'; color = colors.amarelo; }
                    return { value: g.total, name, itemStyle: { color } };
                })
            }
        ]
    });

    // Configuração Gráfico Evolução Mensal (Barras Empilhadas)
    const getEvolutionOption = () => {
        const rawData = stats.evolucao || [];
        // 1. Extrair meses únicos ordenados
        const months = [...new Set(rawData.map(r => r.mes))].sort();

        // 2. Map data for each series
        const dataSim = months.map(m => rawData.find(r => r.mes === m && r.pauta_governo === 'Sim')?.total || 0);
        const dataNao = months.map(m => rawData.find(r => r.mes === m && r.pauta_governo === 'Não')?.total || 0);
        const dataInd = months.map(m => rawData.find(r => r.mes === m && r.pauta_governo !== 'Sim' && r.pauta_governo !== 'Não')?.total || 0);

        return {
            tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
            legend: { top: '0%' },
            grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
            xAxis: { type: 'category', data: months },
            yAxis: { type: 'value' },
            series: [
                {
                    name: 'Interesse Gov',
                    type: 'bar',
                    stack: 'total',
                    emphasis: { focus: 'series' },
                    data: dataSim,
                    itemStyle: { color: colors.verde }
                },
                {
                    name: 'Contra Gov',
                    type: 'bar',
                    stack: 'total',
                    emphasis: { focus: 'series' },
                    data: dataNao,
                    itemStyle: { color: colors.azul }
                },
                {
                    name: 'Indiferente',
                    type: 'bar',
                    stack: 'total',
                    emphasis: { focus: 'series' },
                    data: dataInd,
                    itemStyle: { color: colors.amarelo }
                }
            ]
        };
    };

    // ... (ParlCardMini and Icons helper remain same) ...
    const ParlCardMini = ({ parl, tipo }) => (
        <Card
            elevation={0}
            sx={{
                borderRadius: 2,
                border: '1px solid #eee',
                bgcolor: tipo === 'Sim' ? '#f0fdf4' : '#fef2f2',
                display: 'flex',
                alignItems: 'center',
                p: 1,
                mb: 1
            }}
        >
            <Avatar src={parl.foto} sx={{ width: 32, height: 32, mr: 1, border: `1px solid ${colors.azulClaro}` }} />
            <Box>
                <Typography variant="caption" sx={{ fontWeight: 'bold', color: colors.azul, display: 'block', lineHeight: 1.1 }}>
                    {parl.nome}
                </Typography>
                <Typography variant="caption" color="textSecondary" sx={{ fontSize: '0.65rem' }}>
                    {parl.partido}-{parl.uf}
                </Typography>
            </Box>
        </Card>
    );

    const getThemeIcon = (tema) => {
        if (!tema) return <GavelIcon fontSize="small" sx={{ color: colors.laranja }} />;
        const t = tema.toLowerCase();
        if (t.includes('ambie') || t.includes('florest')) return <ForestIcon fontSize="small" sx={{ color: colors.verde }} />;
        if (t.includes('econo') || t.includes('tribu') || t.includes('finan')) return <MoneyIcon fontSize="small" sx={{ color: colors.azul }} />;
        if (t.includes('saú') || t.includes('medi')) return <HospitalIcon fontSize="small" sx={{ color: '#d32f2f' }} />;
        if (t.includes('educ') || t.includes('escola')) return <SchoolIcon fontSize="small" sx={{ color: colors.azulClaro }} />;
        if (t.includes('seguran') || t.includes('polí')) return <PoliceIcon fontSize="small" sx={{ color: '#333' }} />;
        if (t.includes('exter') || t.includes('interna')) return <PublicIcon fontSize="small" sx={{ color: colors.azul }} />;
        return <GavelIcon fontSize="small" sx={{ color: colors.laranja }} />;
    };

    const SpinnerIcon = () => (
        <CircularProgress size={18} thickness={4} sx={{ mr: 1, color: 'inherit', opacity: 0.6 }} />
    );

    return (
        <Container maxWidth="xl" sx={{ mt: 4, mb: 4, fontFamily: 'Inter, sans-serif' }}>
            <Box sx={{ mb: 4, backgroundColor: 'white', p: 3, borderRadius: '16px', display: 'flex', alignItems: 'center', gap: 4 }}>
                <Box sx={{ flex: 1 }}>
                    <Box display="flex" alignItems="center" mb={1}>
                        <Avatar sx={{ bgcolor: colors.azul, mr: 2 }}>
                            <GavelIcon />
                        </Avatar>
                        <Typography variant="h4" sx={{ fontWeight: 700, color: colors.azul, fontFamily: 'Montserrat, sans-serif' }}>
                            Votações em Geral
                        </Typography>
                    </Box>
                    <Typography variant="subtitle1" color="textSecondary" sx={{ ml: 7 }}>
                        Transparência e análise profunda da atividade legislativa. Explore os resultados e o alinhamento das votações na Câmara.
                    </Typography>
                </Box>
                <Box
                    component="img"
                    src="/Votacoes_em_Geral.png"
                    alt="Ilustração Votações Gerais"
                    sx={{
                        maxHeight: '220px',
                        width: 'auto',
                        borderRadius: '8px',
                        display: { xs: 'none', md: 'block' }
                    }}
                />
            </Box>

            {/* FilterSelector Unificado */}
            <FilterSelector 
                onFiltersChange={onFiltersChange}
                fields={['estado', 'partido']}
                useCurrentParty={true}
            />

            {/* Filtros específicos de Votações */}
            <Paper sx={{ p: 3, mb: 4, mt: 2, borderRadius: 2, backgroundColor: '#fff', border: `1px solid ${colors.azulClaro}44`, boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }}>
                <Grid container spacing={2} alignItems="center">
                    <Grid item xs={12} md={3}>
                        <FormControl fullWidth size="small">
                            <Typography variant="caption" sx={{ fontWeight: 600, mb: 0.5 }}>De:</Typography>
                            <input
                                type="date"
                                style={{
                                    padding: '8px',
                                    borderRadius: '4px',
                                    border: '1px solid #c4c4c4',
                                    fontFamily: 'inherit',
                                    width: '100%'
                                }}
                                value={filtros.dataInicio}
                                onChange={handleFilterChange('dataInicio')}
                            />
                        </FormControl>
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <FormControl fullWidth size="small">
                            <Typography variant="caption" sx={{ fontWeight: 600, mb: 0.5 }}>Até:</Typography>
                            <input
                                type="date"
                                style={{
                                    padding: '8px',
                                    borderRadius: '4px',
                                    border: '1px solid #c4c4c4',
                                    fontFamily: 'inherit',
                                    width: '100%'
                                }}
                                value={filtros.dataFim}
                                onChange={handleFilterChange('dataFim')}
                            />
                        </FormControl>
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <FormControl fullWidth size="small" sx={{ mt: 2.5 }}>
                            <InputLabel id="scope-label">Âmbito / Órgão</InputLabel>
                            <Select
                                labelId="scope-label"
                                value={filtros.orgao}
                                label="Âmbito / Órgão"
                                onChange={handleFilterChange('orgao')}
                                disabled={loadingOrgaos}
                                IconComponent={loadingOrgaos ? SpinnerIcon : undefined}
                            >
                                <MenuItem value="Todos">Todos os Órgãos</MenuItem>
                                <Divider />
                                <MenuItem value="PLEN">Plenário</MenuItem>
                                <MenuItem value="Comissao">Todas as Comissões (Agregado)</MenuItem>
                                <Divider />
                                {(opcoesFiltros.orgaos || []).map(o => (
                                    o.sigla !== 'PLEN' && (
                                        <MenuItem key={o.sigla} value={o.sigla}>
                                            {o.nome} ({o.sigla})
                                        </MenuItem>
                                    )
                                ))}
                            </Select>
                        </FormControl>
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <Button
                            variant="contained"
                            size="large"
                            fullWidth
                            onClick={handleSearch}
                            startIcon={<VoteIcon />}
                            sx={{ mt: 2.5, bgcolor: colors.azul, fontWeight: 'bold', height: '40px' }}
                        >
                            BUSCAR DADOS
                        </Button>
                    </Grid>
                </Grid>

                <Grid container spacing={2} sx={{ mt: 1 }}>
                    <Grid item xs={12} md={6}>
                        <FormControl fullWidth size="small">
                            <InputLabel>Filtrar por Tema</InputLabel>
                            <Select value={filtros.tema} onChange={handleFilterChange('tema')} label="Filtrar por Tema" disabled={loadingTemas} IconComponent={loadingTemas ? SpinnerIcon : undefined}>
                                <MenuItem value="">Todos os Temas</MenuItem>
                                {(temas || []).map(t => (
                                    <MenuItem key={t} value={t}>{t}</MenuItem>
                                ))}
                                {(!temas || temas.length === 0) && ['Direitos Humanos', 'Economia', 'Educação', 'Saúde', 'Segurança Pública', 'Meio Ambiente'].map(t => (
                                    <MenuItem key={t} value={t}>{t}</MenuItem>
                                ))}
                            </Select>
                        </FormControl>
                    </Grid>
                    <Grid item xs={12} md={6}>
                        <FormControl fullWidth size="small">
                            <InputLabel>Pauta do Governo</InputLabel>
                            <Select value={filtros.governo} onChange={handleFilterChange('governo')} label="Pauta do Governo">
                                <MenuItem value="">Todas as Pautas</MenuItem>
                                <MenuItem value="Sim">Interesse do Governo</MenuItem>
                                <MenuItem value="Não">Oposição ao Governo</MenuItem>
                                <MenuItem value="Indefinido">Indiferente / Outros</MenuItem>
                            </Select>
                        </FormControl>
                    </Grid>
                </Grid>
            </Paper>

            {/* Dashboards e Gráficos (Só mostra se buscou) */}
            {hasSearched ? (
                <Grid container spacing={3} sx={{ mb: 4, mt: 2 }}>

                    {/* KPI COLUMN */}
                    <Grid item xs={12} md={3}>
                        <Grid container spacing={2}>
                            <Grid item xs={12}>
                                <Card sx={{ bgcolor: colors.azul, color: 'white', borderRadius: 2 }}>
                                    <CardContent>
                                        <Typography variant="caption" sx={{ opacity: 0.8 }}>TOTAL DE VOTOS ANALISADOS NO PERÍODO</Typography>
                                        <Typography variant="h3" sx={{ fontWeight: 'bold', fontFamily: 'Roboto Mono', color: 'white' }}>{(totalVotacoes || 0).toLocaleString('pt-BR')}</Typography>
                                    </CardContent>
                                </Card>
                            </Grid>
                            <Grid item xs={12}>
                                <Card sx={{ borderLeft: `6px solid ${colors.verde}`, borderRadius: 2 }}>
                                    <CardContent>
                                        <Typography variant="caption" color="textSecondary">NOMINAIS</Typography>
                                        <Typography variant="h4" sx={{ color: colors.verde, fontWeight: 'bold' }}>
                                            {(stats.tipos || []).find(t => t.tipo_votacao === 'Nominal')?.total || 0}
                                        </Typography>
                                    </CardContent>
                                </Card>
                            </Grid>
                            <Grid item xs={12}>
                                <Card sx={{ borderLeft: `6px solid ${colors.laranja}`, borderRadius: 2 }}>
                                    <CardContent>
                                        <Typography variant="caption" color="textSecondary">SIMBÓLICAS</Typography>
                                        <Typography variant="h4" sx={{ color: colors.laranja, fontWeight: 'bold' }}>
                                            {(stats.tipos || []).find(t => t.tipo_votacao === 'Simbólica')?.total || 0}
                                        </Typography>
                                    </CardContent>
                                </Card>
                            </Grid>

                            {/* CRITÉRIOS LEGENDA (PERSISTENT CARD) */}
                            <Grid item xs={12}>
                                <Paper sx={{ p: 2, borderRadius: 2, bgcolor: '#f5f5f5' }}>
                                    <Box display="flex" alignItems="center" gap={1} mb={1}>
                                        <InfoIcon fontSize="small" sx={{ color: colors.cinza }} />
                                        <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: colors.textoPrincipal }}>
                                            Critérios Pauta Governo
                                        </Typography>
                                    </Box>
                                    <Box display="flex" alignItems="center" mb={0.5}>
                                        <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: colors.verde, mr: 1 }} />
                                        <Typography variant="caption" sx={{ color: colors.textoSecundario }}>
                                            <b>SIM:</b> Favorável ao Governo
                                        </Typography>
                                    </Box>
                                    <Box display="flex" alignItems="center" mb={0.5}>
                                        <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: colors.azul, mr: 1 }} />
                                        <Typography variant="caption" sx={{ color: colors.textoSecundario }}>
                                            <b>NÃO:</b> Oposição ao Governo
                                        </Typography>
                                    </Box>
                                    <Box display="flex" alignItems="center">
                                        <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: colors.amarelo, mr: 1, border: '1px solid #ddd' }} />
                                        <Typography variant="caption" sx={{ color: colors.textoSecundario }}>
                                            <b>INDIFERENTE:</b> Sem orientação
                                        </Typography>
                                    </Box>
                                </Paper>
                            </Grid>
                        </Grid>
                    </Grid>

                    {/* CHARTS COLUMN */}
                    <Grid item xs={12} md={9}>
                        <Grid container spacing={3}>
                            {/* ROW 1: ALIGNMENT & VICTORY */}
                            <Grid item xs={12} md={6}>
                                <Paper sx={{ p: 2, height: '100%', borderRadius: 2 }}>
                                    <Typography variant="subtitle2" align="center" sx={{ mb: 2, fontWeight: 'bold', color: colors.textoSecundario }}>
                                        TIPO DE PAUTA VOTADA
                                    </Typography>
                                    {stats.governo && stats.governo.length > 0 ? (
                                        <ReactECharts option={getGovPieOption()} style={{ height: '300px' }} />
                                    ) : (
                                        <Box display="flex" alignItems="center" justifyContent="center" height="300px">
                                            <Typography color="textSecondary">Sem dados.</Typography>
                                        </Box>
                                    )}
                                </Paper>
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <Paper sx={{ p: 2, height: '100%', borderRadius: 2 }}>
                                    <Typography variant="subtitle2" align="center" sx={{ mb: 2, fontWeight: 'bold', color: colors.textoSecundario }}>
                                        {getGovernmentVictoryTitle()}
                                    </Typography>
                                    <ReactECharts option={getVictoryOption()} style={{ height: '300px' }} />
                                    <Typography variant="caption" display="block" align="center" sx={{ mt: 1, color: colors.textoSecundario }}>
                                        {getGovernmentVictoryExplanation()}
                                    </Typography>
                                </Paper>
                            </Grid>

                            {/* ROW 2: MONTHLY EVOLUTION */}
                            <Grid item xs={12}>
                                <Paper sx={{ p: 2, height: '100%', borderRadius: 2 }}>
                                    <Typography variant="subtitle2" align="center" sx={{ mb: 2, fontWeight: 'bold', color: colors.textoSecundario }}>
                                        Tipo de pauta votada no período
                                    </Typography>
                                    {stats.evolucao && stats.evolucao.length > 0 ? (
                                        <ReactECharts option={getEvolutionOption()} style={{ height: '300px' }} />
                                    ) : (
                                        <Box display="flex" alignItems="center" justifyContent="center" height="300px">
                                            <Typography color="textSecondary">Sem dados.</Typography>
                                        </Box>
                                    )}
                                </Paper>
                            </Grid>

                            {/* ROW 3: THEMES TREEMAP */}
                            <Grid item xs={12}>
                                <Paper sx={{ p: 2, borderRadius: 2 }}>
                                    <Typography variant="subtitle2" align="center" sx={{ mb: 2, fontWeight: 'bold', color: colors.textoSecundario }}>
                                        VOTAÇÕES POR TEMA (MACRO)
                                    </Typography>
                                    {stats.temas && stats.temas.length > 0 ? (
                                        <ReactECharts option={getTreemapOption()} style={{ height: '400px' }} />
                                    ) : (
                                        <Box display="flex" alignItems="center" justifyContent="center" height="300px">
                                            <Typography color="textSecondary">Sem dados.</Typography>
                                        </Box>
                                    )}
                                </Paper>
                            </Grid>
                        </Grid>
                    </Grid>
                </Grid>
            ) : (
                <Box mb={4} p={5} component={Paper} elevation={0} sx={{ border: '2px dashed #ddd', borderRadius: 4, textAlign: 'center' }}>
                    <Typography variant="h6" color="textSecondary">
                        Configure os filtros acima e clique em "BUSCAR DADOS" para visualizar o painel.
                    </Typography>
                </Box>
            )}

            {/* Listagem Estilo "Expansion" */}
            <Typography variant="h6" sx={{ mb: 2, color: colors.azul, fontWeight: 'bold' }}>
                Histórico de Deliberações
            </Typography>

            {
                loading ? (
                    <Box display="flex" justifyContent="center" p={10}><CircularProgress /></Box>
                ) : (
                    <Grid container spacing={2}>
                        {!hasSearched ? (
                            <Grid item xs={12}>
                                <Alert severity="info" variant="outlined" sx={{ justifyContent: 'center', borderStyle: 'dashed' }}>
                                    Utilize os filtros acima e clique em "BUSCAR RESULTADOS" para visualizar as votações.
                                </Alert>
                            </Grid>
                        ) : votos.length === 0 ? (
                            <Grid item xs={12}>
                                <Typography align="center" color="textSecondary">Nenhuma votação encontrada para os filtros selecionados.</Typography>
                            </Grid>
                        ) : (
                            votos.map((v) => (
                                <Grid item xs={12} key={v.id_votacao}>
                                    <Card
                                        variant="outlined"
                                        sx={{
                                            borderRadius: 2,
                                            '&:hover': { borderColor: colors.verde, boxShadow: '0 4px 20px rgba(0,0,0,0.05)' },
                                            transition: 'all 0.2s ease',
                                            borderLeft: `6px solid ${v.tipo_votacao === 'Nominal' ? colors.verde : colors.laranja}`
                                        }}
                                    >
                                        <CardContent sx={{ p: 2 }}>
                                            <Grid container spacing={2} alignItems="center">
                                                <Grid item xs={12} md={2}>
                                                    <Typography variant="caption" color="textSecondary" display="block">DATA</Typography>
                                                    <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                                                        {v.data_registro ? v.data_registro.split('T')[0].split('-').reverse().join('/') : 'N/A'}
                                                    </Typography>
                                                    <Typography variant="caption" color="textSecondary" display="block" sx={{ mt: 1 }}>COMISSÃO</Typography>
                                                    <Typography variant="body2" sx={{ fontWeight: 'bold', color: colors.azul }}>
                                                        {v.sigla_orgao || 'PLEN'}
                                                    </Typography>
                                                </Grid>
                                                <Grid item xs={12} md={5}>
                                                    <Typography variant="caption" color="textSecondary" display="block">RESUMO</Typography>
                                                    <Typography variant="body1" sx={{ fontWeight: 800, color: colors.azul, lineHeight: 1.2 }}>
                                                        {v.resumo_leigo ? v.resumo_leigo : v.proposicao}
                                                    </Typography>
                                                    {v.resumo_leigo && v.tipo_votacao !== 'Simbólica' && (
                                                        <Typography variant="caption" sx={{ color: colors.cinza, mt: 0.5, display: 'block' }}>
                                                            {v.proposicao}
                                                        </Typography>
                                                    )}
                                                </Grid>
                                                <Grid item xs={6} md={1}>
                                                    <Typography variant="caption" color="textSecondary" display="block">TIPO</Typography>
                                                    {(() => {
                                                        const desc = v.ficha?.descricao || '';
                                                        const hasCounts = desc.match(/Sim:\s*\d+/i) || desc.match(/Não:\s*\d+/i);

                                                        let label = v.tipo_votacao || 'N/A';
                                                        let color = colors.laranja;
                                                        let bg = `${colors.laranja}22`;

                                                        if (v.tipo_votacao === 'Nominal') {
                                                            label = 'NOMINAL';
                                                            color = colors.verde;
                                                            bg = `${colors.verde}22`;
                                                        } else if (hasCounts) {
                                                            label = 'NOMINAL (AGREGADA)';
                                                            color = '#1565c0'; // Blue
                                                            bg = '#e3f2fd';
                                                        }

                                                        return (
                                                            <Chip
                                                                label={label}
                                                                size="small"
                                                                sx={{ bgcolor: bg, color: color, fontWeight: 'bold', border: 'none' }}
                                                            />
                                                        );
                                                    })()}
                                                </Grid>
                                                <Grid item xs={6} md={1}>
                                                    <Box display="flex" alignItems="center" gap={0.5}>
                                                        <Typography variant="caption" color="textSecondary" display="block">PAUTA DO GOVERNO</Typography>
                                                        <Tooltip title={
                                                            <Box sx={{ p: 1 }}>
                                                                <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 1 }}>Critérios de Classificação:</Typography>
                                                                <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>🔵 <b>SIM:</b> Base governista orientada a favor ou projeto enviado pelo Executivo.</Typography>
                                                                <Typography variant="caption" display="block" sx={{ mb: 0.5 }}>🔴 <b>NÃO:</b> Base governista orientada contra a proposta.</Typography>
                                                                <Typography variant="caption" display="block">⚪ <b>INDIFERENTE:</b> Governo liberou a bancada ou não manifestou orientação formal.</Typography>
                                                            </Box>
                                                        } arrow placement="top">
                                                            <InfoIcon sx={{ fontSize: 14, color: '#9e9e9e', cursor: 'pointer', '&:hover': { color: colors.azul } }} />
                                                        </Tooltip>
                                                    </Box>
                                                    <Tooltip title={v.pauta_governo === 'Sim' ? 'Pauta de interesse do Governo' : 'Pauta Geral'}>
                                                        <Chip
                                                            label={v.pauta_governo === 'Sim' ? 'SIM' : (v.pauta_governo === 'Não' ? 'NÃO' : 'INDIFERENTE')}
                                                            size="small"
                                                            sx={{
                                                                bgcolor: v.pauta_governo === 'Sim' ? colors.verde : (v.pauta_governo === 'Não' ? colors.azul : colors.amarelo),
                                                                color: ['Indiferente', 'Indefinido'].includes(v.pauta_governo) ? '#333' : 'white',
                                                                fontWeight: 'bold',
                                                                fontSize: '0.65rem',
                                                                height: 20,
                                                                mt: 0.5
                                                            }}
                                                        />
                                                    </Tooltip>
                                                </Grid>
                                                <Grid item xs={12} md={2}>
                                                    <Typography variant="caption" color="textSecondary" display="block">TEMA</Typography>
                                                    <Box display="flex" alignItems="center" gap={1}>
                                                        {getThemeIcon(v.tema_macro)}
                                                        <Typography variant="body2" noWrap sx={{ fontWeight: 500, color: colors.laranja }}>
                                                            {v.tema_macro || 'Geral'}
                                                        </Typography>
                                                    </Box>
                                                </Grid>
                                                <Grid item xs={12} md={1} align="right">
                                                    <Button
                                                        variant="contained"
                                                        onClick={() => toggleExpand(v.id_votacao)}
                                                        sx={{
                                                            borderRadius: 5,
                                                            bgcolor: colors.azul,
                                                            '&:hover': { bgcolor: colors.verde },
                                                            minWidth: '100px'
                                                        }}
                                                        endIcon={expandedId === v.id_votacao ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                                                    >
                                                        Detalhes
                                                    </Button>
                                                </Grid>
                                            </Grid>

                                            {/* Detalhe Expandido */}
                                            <Collapse in={expandedId === v.id_votacao}>
                                                <Divider sx={{ my: 2 }} />
                                                {loadingDetail && !expandedData[v.id_votacao] ? (
                                                    <Box display="flex" justifyContent="center" p={3}><CircularProgress size={24} /></Box>
                                                ) : detailErrors[v.id_votacao] ? (
                                                    <Alert severity="warning" sx={{ m: 2, borderRadius: 2 }}>
                                                        {detailErrors[v.id_votacao]}
                                                    </Alert>
                                                ) : (
                                                    expandedData[v.id_votacao] && (
                                                        <Box sx={{ p: 2, bgcolor: '#fdfdfd', borderRadius: 2 }}>
                                                            <Grid container spacing={3}>
                                                                {/* Coluna Dados */}
                                                                <Grid item xs={12} md={7}>
                                                                    {/* Título = Resumo Leigo */}
                                                                    <Typography variant="overline" color="textSecondary" sx={{ fontWeight: 'bold' }}>
                                                                        RESUMO DA VOTAÇÃO
                                                                    </Typography>
                                                                    <Typography variant="h5" sx={{ fontWeight: 800, color: colors.azul, mb: 1.5, fontFamily: 'Montserrat, sans-serif' }}>
                                                                        {expandedData[v.id_votacao].ficha.resumo_leigo ||
                                                                            expandedData[v.id_votacao].ficha.proposicao}
                                                                    </Typography>

                                                                    {/* Explicação Didática para Requerimentos/Obstrução */}
                                                                    {(expandedData[v.id_votacao].ficha.proposicao.toLowerCase().includes('requerimento') ||
                                                                        expandedData[v.id_votacao].ficha.proposicao.toLowerCase().includes('urgência')) && (
                                                                            <Alert severity="warning" icon={<InfoIcon fontSize="inherit" />} sx={{ mb: 2, py: 0, fontSize: '0.8rem', bgcolor: '#fff3e0' }}>
                                                                                <strong>Nota Técnica:</strong> Votações sucessivas de requerimentos (adiamento, retirada de pauta, urgência) são táticas comuns de <em>obstrução parlamentar</em> usada pela oposição para atrasar ou negociar a votação principal, ou pelo governo para acelerar pautas prioritárias (urgência).
                                                                            </Alert>
                                                                        )}

                                                                    {/* Descrição Técnica Secundária - HIDE IF SYMBOLIC */}
                                                                    {expandedData[v.id_votacao].ficha.tipo_votacao !== 'Simbólica' && (
                                                                        <Box sx={{ mb: 3 }}>
                                                                            <Typography variant="caption" sx={{ fontWeight: 'bold', color: colors.cinza }}>OBJETO TÉCNICO REGIMENTAL:</Typography>
                                                                            <Typography variant="body2" sx={{ color: colors.cinza }}>
                                                                                {expandedData[v.id_votacao].ficha.descricao}
                                                                            </Typography>
                                                                        </Box>
                                                                    )}

                                                                    {/* Grid de Metadados (Tipo | Governo | Tema) */}
                                                                    <Grid container spacing={2} sx={{ mb: 3 }}>
                                                                        <Grid item xs={4}>
                                                                            <Typography variant="caption" sx={{ color: colors.textoSecundario, fontWeight: 600, textTransform: 'uppercase' }}>
                                                                                TIPO
                                                                            </Typography>
                                                                            <Box>
                                                                                <Chip
                                                                                    label={(expandedData[v.id_votacao].ficha.tipo_votacao || 'N/A').toUpperCase()}
                                                                                    size="small"
                                                                                    sx={{
                                                                                        bgcolor: expandedData[v.id_votacao].ficha.tipo_votacao === 'Nominal' ? colors.verde : colors.laranja,
                                                                                        color: 'white',
                                                                                        fontWeight: 'bold',
                                                                                        mt: 0.5
                                                                                    }}
                                                                                />
                                                                            </Box>
                                                                        </Grid>
                                                                        <Grid item xs={4}>
                                                                            <Typography variant="caption" sx={{ color: colors.textoSecundario, fontWeight: 600, textTransform: 'uppercase' }}>
                                                                                PAUTA DO GOVERNO
                                                                            </Typography>
                                                                            <Box sx={{ mt: 0.5 }}>
                                                                                <Typography variant="body2" sx={{ fontWeight: 700, color: expandedData[v.id_votacao].ficha.pauta_governo === 'Sim' ? colors.azul : '#d32f2f' }}>
                                                                                    {expandedData[v.id_votacao].ficha.pauta_governo === 'Sim' ? 'SIM' : (expandedData[v.id_votacao].ficha.pauta_governo === 'Não' ? 'NÃO' : 'INDIFERENTE')}
                                                                                </Typography>
                                                                            </Box>
                                                                        </Grid>
                                                                        <Grid item xs={4}>
                                                                            <Typography variant="caption" sx={{ color: colors.textoSecundario, fontWeight: 600, textTransform: 'uppercase' }}>
                                                                                TEMA
                                                                            </Typography>
                                                                            <Typography variant="body2" sx={{ fontWeight: 700, color: colors.laranja, mt: 0.5 }}>
                                                                                {expandedData[v.id_votacao].ficha.tema_macro || 'Geral'}
                                                                            </Typography>
                                                                        </Grid>
                                                                    </Grid>

                                                                    <Divider sx={{ mb: 2 }} />

                                                                    {/* Video e Documentos */}
                                                                    <Box sx={{ mb: 2 }}>
                                                                        {expandedData[v.id_votacao].ficha.url_video ? (
                                                                            <Box sx={{ position: 'relative', paddingTop: '56.25%', borderRadius: 2, overflow: 'hidden', bgcolor: '#000', mb: 2 }}>
                                                                                <iframe
                                                                                    style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', border: 0 }}
                                                                                    src={expandedData[v.id_votacao].ficha.url_video.replace('watch?v=', 'embed/').split('&')[0]}
                                                                                    title="YouTube video player"
                                                                                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                                                                                    allowFullScreen
                                                                                />
                                                                            </Box>
                                                                        ) : (
                                                                            <Alert severity="info" sx={{ mb: 2 }}>Vídeo da votação não disponível.</Alert>
                                                                        )}

                                                                        <Box display="flex" gap={2}>
                                                                            {expandedData[v.id_votacao].ficha.url_proposicao && (
                                                                                <Button
                                                                                    variant="outlined"
                                                                                    startIcon={<DescriptionIcon />}
                                                                                    href={expandedData[v.id_votacao].ficha.url_proposicao}
                                                                                    target="_blank"
                                                                                    sx={{ fontWeight: 'bold', textTransform: 'none', color: colors.azul, borderColor: colors.azul }}
                                                                                >
                                                                                    Ver Projeto na Íntegra
                                                                                </Button>
                                                                            )}
                                                                            <Button
                                                                                variant="contained"
                                                                                onClick={() => navigate(`/votos/detalhe/${v.id_votacao}`)}
                                                                                sx={{ bgcolor: colors.azul, fontWeight: 'bold', textTransform: 'none' }}
                                                                            >
                                                                                Ver Ficha Completa
                                                                            </Button>
                                                                        </Box>
                                                                    </Box>

                                                                    {/* News and Polemic */}
                                                                    {expandedData[v.id_votacao].ficha.foi_polemico && (
                                                                        <Alert severity="warning" sx={{ mb: 2, borderRadius: 2 }}>
                                                                            <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>Votação Polêmica</Typography>
                                                                            <Typography variant="caption">{expandedData[v.id_votacao].ficha.motivo_polemica}</Typography>
                                                                        </Alert>
                                                                    )}

                                                                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 3 }}>
                                                                        {expandedData[v.id_votacao].nota_taquigrafica && (
                                                                            <Button
                                                                                variant="outlined"
                                                                                size="small"
                                                                                startIcon={<LinkIcon />}
                                                                                href={expandedData[v.id_votacao].nota_taquigrafica}
                                                                                target="_blank"
                                                                                sx={{ borderRadius: 10, textTransform: 'none', fontWeight: 600 }}
                                                                            >
                                                                                Nota Taquigráfica
                                                                            </Button>
                                                                        )}
                                                                        {expandedData[v.id_votacao].ficha.links_noticias && (
                                                                            <Button
                                                                                variant="outlined"
                                                                                size="small"
                                                                                color="warning"
                                                                                startIcon={<NewspaperIcon />}
                                                                                href={expandedData[v.id_votacao].ficha.links_noticias}
                                                                                target="_blank"
                                                                                sx={{ borderRadius: 10, textTransform: 'none', fontWeight: 600 }}
                                                                            >
                                                                                Ver Notícias
                                                                            </Button>
                                                                        )}
                                                                        {expandedData[v.id_votacao].ficha.url_video && (
                                                                            <Button
                                                                                variant="outlined"
                                                                                size="small"
                                                                                color="error"
                                                                                startIcon={<YouTubeIcon />}
                                                                                href={expandedData[v.id_votacao].ficha.url_video}
                                                                                target="_blank"
                                                                                sx={{ borderRadius: 10, textTransform: 'none', fontWeight: 600 }}
                                                                            >
                                                                                Ver Gravação (YouTube)
                                                                            </Button>
                                                                        )}
                                                                    </Box>
                                                                </Grid>

                                                                {/* Coluna Votos */}
                                                                {/* Coluna Votos */}
                                                                <Grid item xs={12} md={5}>
                                                                    <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: colors.azul, mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                                                                        <VoteIcon fontSize="small" /> DISTRIBUIÇÃO DE VOTOS
                                                                    </Typography>

                                                                    {/* Lógica de Exibição de Votos */}
                                                                    {(() => {
                                                                        // Lógica de Prioridade de Exibição Refinada
                                                                        const desc = expandedData[v.id_votacao].ficha.descricao || '';

                                                                        // Regex Robust para capturar variados formatos
                                                                        const matchSim1 = desc.match(/Sim:?\s*(\d+)/i);
                                                                        const matchNao1 = desc.match(/Não:?\s*(\d+)/i);

                                                                        const matchAbs1 = desc.match(/Abstenção:?\s*(\d+)/i);

                                                                        const matchSim2 = desc.match(/(\d+)\s*votos?\s*["']?Sim/i);
                                                                        const matchNao2 = desc.match(/(\d+)\s*votos?\s*["']?Não/i);
                                                                        const matchAbs2 = desc.match(/(\d+)\s*(?:votos?|abstenções|abstenção)\s*["']?Abstenção/i);

                                                                        let countSim = matchSim1 ? parseInt(matchSim1[1]) : (matchSim2 ? parseInt(matchSim2[1]) : 0);
                                                                        let countNao = matchNao1 ? parseInt(matchNao1[1]) : (matchNao2 ? parseInt(matchNao2[1]) : 0);
                                                                        let countAbs = matchAbs1 ? parseInt(matchAbs1[1]) : (matchAbs2 ? parseInt(matchAbs2[1]) : 0);

                                                                        // Override Logic requested by User:
                                                                        // If Symbolic, ignore text counts. Consider everyone present as 'A Favor' (Consensus).
                                                                        const isSymbolic = v.tipo_votacao === 'Simbólica';

                                                                        if (isSymbolic) {
                                                                            countSim = 0; // Will be handled by list count logic or ignored since we won't show scoreboard
                                                                            countNao = 0;
                                                                            countAbs = 0;
                                                                        }

                                                                        const hasRealCounts = !isSymbolic && (countSim > 0 || countNao > 0 || countAbs > 0);
                                                                        const isNominal = v.tipo_votacao === 'Nominal';

                                                                        const hasList = expandedData[v.id_votacao].aprovadores && expandedData[v.id_votacao].aprovadores.length > 0;

                                                                        // 1. Qualquer votação que tenha Lista (Nominal, Agregada ou Simbólica Inferida)
                                                                        if (hasList || isNominal) {
                                                                            return (
                                                                                <Grid container spacing={2}>
                                                                                    {isSymbolic && (
                                                                                        <Grid item xs={12}>
                                                                                            <Alert severity="info" sx={{ mb: 1, py: 0, fontSize: '0.8rem' }}>
                                                                                                <strong>Votação Simbólica:</strong> Considera-se aprovada por consenso tácito dos presentes. Lista abaixo reflete a onipresença na sessão (Art. 186 do Regimento Interno da Câmara dos Deputados - RICD).
                                                                                            </Alert>
                                                                                        </Grid>
                                                                                    )}
                                                                                    <Grid item xs={6}>
                                                                                        <Typography variant="caption" sx={{ color: colors.verde, fontWeight: 'bold', display: 'block', mb: 1 }}>
                                                                                            A FAVOR ({expandedData[v.id_votacao].aprovadores.length})
                                                                                        </Typography>
                                                                                        <Box sx={{ maxHeight: '250px', overflowY: 'auto', pr: 1 }}>
                                                                                            {expandedData[v.id_votacao].aprovadores.map(p => (
                                                                                                <ParlCardMini key={p.nome} parl={p} tipo="Sim" />
                                                                                            ))}
                                                                                        </Box>
                                                                                    </Grid>
                                                                                    <Grid item xs={6}>
                                                                                        <Typography variant="caption" sx={{ color: '#d32f2f', fontWeight: 'bold', display: 'block', mb: 1 }}>
                                                                                            CONTRA ({expandedData[v.id_votacao].opositores.length})
                                                                                        </Typography>
                                                                                        <Box sx={{ maxHeight: '250px', overflowY: 'auto', pr: 1 }}>
                                                                                            {expandedData[v.id_votacao].opositores.length > 0 ? (
                                                                                                expandedData[v.id_votacao].opositores.map(p => (
                                                                                                    <ParlCardMini key={p.nome} parl={p} tipo="Não" />
                                                                                                ))
                                                                                            ) : (
                                                                                                <Typography variant="caption" color="textSecondary">Nenhum voto contrário.</Typography>
                                                                                            )}
                                                                                        </Box>
                                                                                    </Grid>
                                                                                </Grid>
                                                                            );
                                                                        }
                                                                        // 2. Não Nominal mas com Contagem Texto -> Placar Agregado
                                                                        else if (hasRealCounts) {
                                                                            return (
                                                                                <Box sx={{ p: 2, bgcolor: '#fafafa', borderRadius: 2, border: '1px dashed #ccc' }}>
                                                                                    <Box>
                                                                                        <Typography variant="subtitle2" gutterBottom align="center" sx={{ fontWeight: 'bold', color: colors.azul }}>
                                                                                            PLACAR REAL (AGREGADO)
                                                                                        </Typography>
                                                                                        <Alert severity="info" size="small" sx={{ mb: 2, py: 0 }}>
                                                                                            <Typography variant="caption">
                                                                                                Votação com contagem nominal no texto.
                                                                                                Lista abaixo: Presença total (presunção de apoio).
                                                                                            </Typography>
                                                                                        </Alert>

                                                                                        <Box display="flex" justifyContent="space-around" mt={2} mb={2}>
                                                                                            <Box textAlign="center">
                                                                                                <Typography variant="h5" sx={{ color: colors.verde, fontWeight: 'bold' }}>{countSim}</Typography>
                                                                                                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>SIM</Typography>
                                                                                            </Box>
                                                                                            <Box textAlign="center">
                                                                                                <Typography variant="h5" sx={{ color: '#d32f2f', fontWeight: 'bold' }}>{countNao}</Typography>
                                                                                                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>NÃO</Typography>
                                                                                            </Box>
                                                                                            <Box textAlign="center">
                                                                                                <Typography variant="h5" sx={{ color: colors.cinza, fontWeight: 'bold' }}>{countAbs}</Typography>
                                                                                                <Typography variant="caption" sx={{ fontWeight: 'bold' }}>ABS</Typography>
                                                                                            </Box>
                                                                                        </Box>
                                                                                    </Box>

                                                                                    {hasList && (
                                                                                        <Box mt={2} pt={2} borderTop="1px solid #eee">
                                                                                            <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', mb: 1, fontStyle: 'italic', color: colors.cinza }}>
                                                                                                * A API não disponibiliza o voto individual (Sim/Não) para esta modalidade.
                                                                                                Exibindo lista completa de presença.
                                                                                            </Typography>
                                                                                            <Grid container spacing={2}>
                                                                                                <Grid item xs={12}>
                                                                                                    <Typography variant="caption" sx={{ color: colors.azul, fontWeight: 'bold', display: 'block', mb: 1 }}>
                                                                                                        LISTA DE PRESENÇA ({expandedData[v.id_votacao].aprovadores.length})
                                                                                                    </Typography>
                                                                                                    <Box sx={{ maxHeight: '50vh', overflowY: 'auto', pr: 1, '&::-webkit-scrollbar': { width: '6px' }, '&::-webkit-scrollbar-thumb': { bgcolor: '#ddd', borderRadius: '4px' } }}>
                                                                                                        {expandedData[v.id_votacao].aprovadores.map(p => (
                                                                                                            <ParlCardMini key={p.nome} parl={p} tipo="Sim" />
                                                                                                        ))}
                                                                                                    </Box>
                                                                                                </Grid>
                                                                                            </Grid>
                                                                                        </Box>
                                                                                    )}
                                                                                </Box>
                                                                            );
                                                                        }
                                                                        // 3. Fallback Lista (se existir)
                                                                        else if (hasList) {
                                                                            return (
                                                                                <Grid container spacing={2}>
                                                                                    <Grid item xs={6}>
                                                                                        <Typography variant="caption" sx={{ color: colors.verde, fontWeight: 'bold', display: 'block', mb: 1 }}>
                                                                                            A FAVOR ({expandedData[v.id_votacao].aprovadores.length})
                                                                                        </Typography>
                                                                                        <Box sx={{ maxHeight: '50vh', overflowY: 'auto', pr: 1, '&::-webkit-scrollbar': { width: '6px' }, '&::-webkit-scrollbar-thumb': { bgcolor: '#ddd', borderRadius: '4px' } }}>
                                                                                            {expandedData[v.id_votacao].aprovadores.map(p => (
                                                                                                <ParlCardMini key={p.nome} parl={p} tipo="Sim" />
                                                                                            ))}
                                                                                        </Box>
                                                                                    </Grid>
                                                                                    <Grid item xs={6}>
                                                                                        <Typography variant="caption" sx={{ color: '#d32f2f', fontWeight: 'bold', display: 'block', mb: 1 }}>
                                                                                            CONTRA ({expandedData[v.id_votacao].opositores.length})
                                                                                        </Typography>
                                                                                        <Box sx={{ maxHeight: '50vh', overflowY: 'auto', pr: 1, '&::-webkit-scrollbar': { width: '6px' }, '&::-webkit-scrollbar-thumb': { bgcolor: '#ddd', borderRadius: '4px' } }}>
                                                                                            {expandedData[v.id_votacao].opositores.length > 0 ? (
                                                                                                expandedData[v.id_votacao].opositores.map(p => (
                                                                                                    <ParlCardMini key={p.nome} parl={p} tipo="Não" />
                                                                                                ))
                                                                                            ) : (
                                                                                                <Typography variant="caption" color="textSecondary">Nenhum voto contrário.</Typography>
                                                                                            )}
                                                                                        </Box>
                                                                                    </Grid>
                                                                                </Grid>
                                                                            );
                                                                        }
                                                                        // 4. Consenso Simbólico
                                                                        else {
                                                                            return (
                                                                                <Box sx={{ p: 2, bgcolor: '#fafafa', borderRadius: 2, border: '1px dashed #ccc' }}>
                                                                                    <Typography variant="caption" sx={{ mt: 1, display: 'block', color: colors.cinza, fontStyle: 'italic' }}>
                                                                                        * Votação simbólica: Presunção de aprovação por consenso (Art. 186 RICD).
                                                                                    </Typography>
                                                                                </Box>
                                                                            );
                                                                        }
                                                                    })()}
                                                                </Grid>
                                                            </Grid>

                                                        
      <DataSourceFooter
        sources={[{"label":"Votações — API da Câmara","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Votacoes","type":"camara"},{"label":"Dados Abertos da Câmara","href":"https://dadosabertos.camara.leg.br","type":"camara"}]}
        note="Votações nominais do Plenário e de Comissões extraídas da API de Dados Abertos da Câmara dos Deputados."
      />
    </Box>
                                                    )
                                                )}
                                            </Collapse>
                                        </CardContent >
                                    </Card >
                                </Grid >
                            )))}
                    </Grid >
                )
            }
        </Container >
    );
};

export default VotacoesGeral;

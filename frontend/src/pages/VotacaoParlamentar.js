import React, { useEffect, useState } from 'react';
import {
    Box,
    Container,
    Typography,
    Paper,
    Grid,
    Card,
    CardContent,
    Chip,
    Button,
    CircularProgress,
    FormControl,
    InputLabel,
    Select,
    MenuItem,
    Avatar,
    LinearProgress,
} from '@mui/material';
import {
    HowToVote as VoteIcon,
    History as HistoryIcon,
    TrendingUp as TrendingUpIcon,
    TrendingDown as TrendingDownIcon,
    Gavel as GavelIcon,
} from '@mui/icons-material';
import ReactECharts from 'echarts-for-react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import FilterSelector from '../components/FilterSelector';

const VotacaoParlamentar = () => {
    const navigate = useNavigate();

    // Paleta de Cores
    const colors = {
        verde: '#009739',
        amarelo: '#FFF81C',
        azul: '#003366',
        azulClaro: '#4F81BD',
        verdeClaro: '#66BB6A',
        laranja: '#ED8B00',
        cinza: '#666666',
        cardBg: '#fcfcfc'
    };

    // Filtros
    const [estados, setEstados] = useState([]);
    const [partidos, setPartidos] = useState([]);
    const [parlamentares, setParlamentares] = useState([]);

    const [estadoSel, setEstadoSel] = useState('');
    const [partidoSel, setPartidoSel] = useState('');
    const [parlamentarSel, setParlamentarSel] = useState('');

    const [loadingFiltros, setLoadingFiltros] = useState(false);
    const [loadingDados, setLoadingDados] = useState(false);
    const [perfil, setPerfil] = useState(null);
    const [data, setData] = useState({ stats: null, votos: [] });

    // Carregamento de filtros removido em favor do FilterSelector unificado
    const onFiltersChange = (newFilters) => {
        setEstadoSel(newFilters.estado);
        setPartidoSel(newFilters.partido);
        setParlamentarSel(newFilters.parlamentar);
    };

    const handleBuscar = async () => {
        if (!parlamentarSel) return;
        setLoadingDados(true);
        try {
            const resPerfil = await axios.get(`/api/parlamentares/detalhes?nome=${parlamentarSel}`);
            setPerfil(resPerfil.data);
            const resVotos = await axios.get(`/api/votos/parlamentar/${parlamentarSel}`);
            setData(resVotos.data);
        } catch (err) {
            console.error("Erro ao buscar dados", err);
        } finally {
            setLoadingDados(false);
        }
    };

    // --- Configurações ECharts ---

    // 1. Radar Chart: Perfil por Temas
    const getRadarOption = () => {
        if (!data.stats?.temas_analise) return {};
        const temas = Object.keys(data.stats.temas_analise);
        const indicators = temas.map(t => ({ name: t, max: 100 }));
        const values = temas.map(t => {
            const stat = data.stats.temas_analise[t];
            return Math.round((stat.alinhado / stat.total) * 100);
        });

        return {
            title: { text: 'Consistência por Tema', left: 'center', textStyle: { color: colors.azul, fontSize: 14 } },
            radar: {
                indicator: indicators,
                shape: 'circle',
                splitNumber: 4,
                axisName: { color: colors.azul },
                splitLine: { lineStyle: { color: [colors.azulClaro] } },
                splitArea: { show: false }
            },
            series: [{
                type: 'radar',
                data: [{ value: values, name: 'Alinhamento %', areaStyle: { color: colors.verde, opacity: 0.3 }, itemStyle: { color: colors.verde } }]
            }]
        };
    };

    // 2. Line Chart: Evolução do Alinhamento
    const getEvolutionOption = () => {
        if (!data.stats?.evolucao) return {};
        const evolData = data.stats.evolucao || [];
        return {
            title: { text: 'Evolução do Alinhamento', left: 'center', textStyle: { color: colors.azul, fontSize: 14 } },
            tooltip: { trigger: 'axis' },
            xAxis: { type: 'category', data: evolData.map(e => new Date(e.data).toLocaleDateString('pt-BR', { month: 'short', year: '2y' })) },
            yAxis: { type: 'value', min: 0, max: 100 },
            series: [{
                data: evolData.map(e => e.pct),
                type: 'line',
                smooth: true,
                color: colors.azul,
                areaStyle: { color: colors.azul, opacity: 0.1 }
            }]
        };
    };

    // 3. Pie Chart: Distribuição de Votos
    const getPieOption = () => {
        if (!data.stats) return {};
        return {
            title: { text: 'Distribuição de Votos', left: 'center', textStyle: { color: colors.azul, fontSize: 14 } },
            tooltip: { trigger: 'item' },
            series: [{
                type: 'pie',
                radius: ['40%', '70%'],
                data: [
                    { value: data.stats.sim, name: 'Sim', itemStyle: { color: colors.verde } },
                    { value: data.stats.nao, name: 'Não', itemStyle: { color: '#d32f2f' } },
                    { value: data.stats.abstencao, name: 'Abst.', itemStyle: { color: colors.cinza } }
                ],
                label: { show: false }
            }]
        };
    };

    return (
        <Container maxWidth="xl" sx={{ mt: 4, mb: 4 }}>
            <Box display="flex" alignItems="center" mb={1}>
                <Avatar sx={{ bgcolor: colors.azul, mr: 2 }}>
                    <HistoryIcon />
                </Avatar>
                <Typography variant="h4" sx={{ fontWeight: 700, color: colors.azul, fontFamily: 'Montserrat, sans-serif' }}>
                    Análise de Votos por Parlamentar
                </Typography>
            </Box>

            {/* Filtros Premium */}
            <FilterSelector 
                onFiltersChange={onFiltersChange}
                fields={['estado', 'partido', 'parlamentar']}
                useCurrentParty={true}
            />

            <Box sx={{ mb: 4, display: 'flex', justifyContent: 'center' }}>
                <Button
                    variant="contained"
                    size="large"
                    onClick={handleBuscar}
                    disabled={!parlamentarSel || loadingDados}
                    startIcon={loadingDados ? <CircularProgress size={24} color="inherit" /> : <TrendingUpIcon />}
                    sx={{ 
                        bgcolor: colors.azul, 
                        borderRadius: '50px', 
                        px: 6,
                        py: 1.5,
                        fontWeight: 'bold',
                        fontSize: '1.1rem'
                    }}
                >
                    {loadingDados ? 'Analisando...' : 'Analisar Perfil'}
                </Button>
            </Box>

            {data.stats && perfil && (
                <>
                    {/* Perfil Header Card */}
                    <Paper sx={{ p: 4, mb: 4, borderRadius: 4, borderTop: `8px solid ${colors.verde}` }}>
                        <Grid container spacing={4} alignItems="center">
                            <Grid item>
                                <Avatar
                                    src={perfil.urlFoto}
                                    sx={{ width: 120, height: 120, border: `4px solid ${colors.azul}` }}
                                />
                            </Grid>
                            <Grid item xs>
                                <Typography variant="h4" sx={{ fontWeight: 800, color: colors.azul }}>{perfil.nome}</Typography>
                                <Box display="flex" alignItems="center" gap={2} mt={1}>
                                    <Chip
                                        icon={<Avatar src={perfil.urlPartido} sx={{ width: 20, height: 20 }} />}
                                        label={perfil.partido}
                                        variant="outlined"
                                        sx={{ fontWeight: 'bold', borderColor: colors.azul }}
                                    />
                                    <Chip
                                        icon={<Avatar src={perfil.urlEstado} sx={{ width: 15, height: 15 }} />}
                                        label={perfil.uf}
                                        variant="outlined"
                                    />
                                </Box>
                            </Grid>
                            <Grid item xs={12} md={3}>
                                <Card sx={{ bgcolor: colors.azul, color: 'white', borderRadius: 3 }}>
                                    <CardContent align="center">
                                        <Typography variant="caption" sx={{ opacity: 0.8 }}>ALINHAMENTO COM O GOVERNO</Typography>
                                        <Typography variant="h3" sx={{ fontWeight: 'bold' }}>{data.stats.alinhamento}%</Typography>
                                        <LinearProgress
                                            variant="determinate"
                                            value={data.stats.alinhamento}
                                            sx={{ mt: 2, height: 8, borderRadius: 4, bgcolor: 'rgba(255,255,255,0.2)', '& .MuiLinearProgress-bar': { bgcolor: colors.verde } }}
                                        />
                                    </CardContent>
                                </Card>
                            </Grid>
                        </Grid>
                    </Paper>

                    {/* Charts Grid */}
                    <Grid container spacing={3} sx={{ mb: 4 }}>
                        <Grid item xs={12} md={4}>
                            <Paper sx={{ p: 2, borderRadius: 3, height: '350px' }}>
                                <ReactECharts option={getPieOption()} style={{ height: '300px' }} />
                            </Paper>
                        </Grid>
                        <Grid item xs={12} md={4}>
                            <Paper sx={{ p: 2, borderRadius: 3, height: '350px' }}>
                                <ReactECharts option={getRadarOption()} style={{ height: '300px' }} />
                            </Paper>
                        </Grid>
                        <Grid item xs={12} md={4}>
                            <Paper sx={{ p: 2, borderRadius: 3, height: '350px' }}>
                                <ReactECharts option={getEvolutionOption()} style={{ height: '300px' }} />
                            </Paper>
                        </Grid>
                    </Grid>

                    {/* Histórico na Ficha */}
                    <Typography variant="h5" sx={{ mb: 3, fontWeight: 'bold', color: colors.azul }}>Histórico Parlamentar</Typography>
                    <Grid container spacing={2}>
                        {data.votos.map((v, idx) => (
                            <Grid item xs={12} key={idx}>
                                <Card sx={{ borderRadius: 2, borderLeft: `5px solid ${v.alinhamento === 'Alinhado' ? colors.verde : (v.alinhamento === 'Desalinhado' ? '#d32f2f' : colors.cinza)}` }}>
                                    <CardContent sx={{ py: '12px !important' }}>
                                        <Grid container spacing={2} alignItems="center">
                                            <Grid item xs={2} md={1}>
                                                <Typography variant="caption" color="textSecondary">DATA</Typography>
                                                <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{new Date(v.data_registro).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}</Typography>
                                            </Grid>
                                            <Grid item xs={10} md={5}>
                                                <Typography variant="body1" sx={{ fontWeight: 'bold', color: colors.azul }}>{v.proposicao}</Typography>
                                                <Typography variant="caption" color="textSecondary">{v.tema_macro}</Typography>
                                            </Grid>
                                            <Grid item xs={4} md={1}>
                                                <Typography variant="caption" color="textSecondary">VOTO</Typography>
                                                <Typography variant="body2" sx={{ fontWeight: 'bold', color: v.voto === 'Sim' ? colors.verde : '#d32f2f' }}>{v.voto.toUpperCase()}</Typography>
                                            </Grid>
                                            <Grid item xs={6} md={2}>
                                                <Typography variant="caption" color="textSecondary" display="block">ALINHAMENTO</Typography>
                                                <Chip label={v.alinhamento} size="small" variant="outlined" color={v.alinhamento === 'Alinhado' ? 'success' : (v.alinhamento === 'Desalinhado' ? 'error' : 'default')} />
                                            </Grid>
                                            <Grid item xs={2} md={3} align="right">
                                                <Button size="small" variant="text" sx={{ color: colors.azul, fontWeight: 'bold' }} onClick={() => navigate(`/votos/detalhe/${v.id_votacao}`)}>DETALHES</Button>
                                            </Grid>
                                        </Grid>
                                    </CardContent>
                                </Card>
                            </Grid>
                        ))}
                    </Grid>
                </>
            )}

            {!data.stats && !loadingDados && (
                <Box display="flex" flexDirection="column" alignItems="center" mt={10} color="text.secondary">
                    <VoteIcon sx={{ fontSize: 100, mb: 2, opacity: 0.1 }} />
                    <Typography variant="h5" sx={{ opacity: 0.5, fontWeight: 'bold' }}>Selecione um parlamentar para iniciar a auditoria</Typography>
                </Box>
            )}
        </Container>
    );
};

export default VotacaoParlamentar;

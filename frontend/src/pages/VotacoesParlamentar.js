import React, { useState, useEffect } from 'react';
import {
    Box,
    Container,
    Typography,
    Grid,
    Paper,
    MenuItem,
    Select,
    FormControl,
    InputLabel,
    Avatar,
    Chip,
    LinearProgress,
    Card,
    CardContent,
    Stack,
    Divider,
    Alert,
    TextField,
    Button,
    CircularProgress
} from '@mui/material';
import ReactECharts from 'echarts-for-react';
import * as echarts from 'echarts';
import ReactMarkdown from 'react-markdown';
import {
    EmojiEvents as TrophyIcon,
    ThumbUp as ThumbUpIcon,
    ThumbDown as ThumbDownIcon,
    RemoveCircle as AbstencaoIcon,
    Gavel as GavelIcon,
    FilterList as FilterListIcon
} from '@mui/icons-material';
import axios from '../config/axios';
import FilterSelector from '../components/FilterSelector';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

const API_HEADERS = { 'Content-Type': 'application/json' };
const CORES_MARCA = {
    verde: '#009739',
    verdeClaro: '#66BB6A',
    azul: '#003366',
    azulClaro: '#4F81BD',
    amarelo: '#FFCC00',
    branco: '#FFFFFF',
    cinza: '#666666',
    cinzaClaro: '#E0E0E0',
    laranjaEscuro: '#ED8B00',
    laranjaClaro: '#FFB74D',
};

const ESTADO_BANDEIRAS_FALLBACK = {
    AC: 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/Bandeira_do_Acre.svg/243px-Bandeira_do_Acre.svg.png',
    AL: 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/88/Bandeira_de_Alagoas.svg/255px-Bandeira_de_Alagoas.svg.png',
    AM: 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/Bandeira_do_Amazonas.svg/238px-Bandeira_do_Amazonas.svg.png',
    AP: 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/Bandeira_do_Amap%C3%A1.svg/640px-Bandeira_do_Amap%C3%A1.svg.png',
    BA: 'https://upload.wikimedia.org/wikipedia/commons/thumb/2/28/Bandeira_da_Bahia.svg/800px-Bandeira_da_Bahia.svg.png',
    CE: 'https://i.ibb.co/g6dHqSw/Bandeira-do-Cear-svg.png',
    DF: 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Bandeira_do_Distrito_Federal_%28Brasil%29.svg/800px-Bandeira_do_Distrito_Federal_%28Brasil%29.svg.png',
    ES: 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/43/Bandeira_do_Esp%C3%ADrito_Santo.svg/243px-Bandeira_do_Esp%C3%ADrito_Santo.svg.png',
    GO: 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/Flag_of_Goi%C3%A1s.svg/243px-Flag_of_Goi%C3%A1s.svg.png',
    MA: 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Bandeira_do_Maranh%C3%A3o.svg/300px-Bandeira_do_Maranh%C3%A3o.svg.png',
    MG: 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f4/Bandeira_de_Minas_Gerais.svg/243px-Bandeira_de_Minas_Gerais.svg.png',
    MS: 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/64/Bandeira_de_Mato_Grosso_do_Sul.svg/243px-Bandeira_de_Mato_Grosso_do_Sul.svg.png',
    MT: 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0b/Bandeira_de_Mato_Grosso.svg/243px-Bandeira_de_Mato_Grosso.svg.png',
    PA: 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/02/Bandeira_do_Par%C3%A1.svg/1200px-Bandeira_do_Par%C3%A1.svg.png',
    PB: 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/bb/Bandeira_da_Para%C3%ADba.svg/300px-Bandeira_da_Para%C3%ADba.svg.png',
    PE: 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Bandeira_de_Pernambuco.svg/1200px-Bandeira_de_Pernambuco.svg.png',
    PI: 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/33/Bandeira_do_Piau%C3%AD.svg/255px-Bandeira_do_Piau%C3%AD.svg.png',
    PR: 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/93/Bandeira_do_Paran%C3%A1.svg/300px-Bandeira_do_Paran%C3%A1.svg.png',
    RJ: 'https://upload.wikimedia.org/wikipedia/commons/thumb/7/73/Bandeira_do_estado_do_Rio_de_Janeiro.svg/275px-Bandeira_do_estado_do_Rio_de_Janeiro.svg.png',
    RN: 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/42/Bandeira_do_Rio_Grande_do_Norte_%28original%29.png/1200px-Bandeira_do_Rio_Grande_do_Norte_%28original%29.png',
    RO: 'https://i.ibb.co/092QwtK/Bandeira-de-Rond-nia-svg.png',
    RR: 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/98/Bandeira_de_Roraima.svg/1200px-Bandeira_de_Roraima.svg.png',
    RS: 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/63/Bandeira_do_Rio_Grande_do_Sul.svg/243px-Bandeira_do_Rio_Grande_do_Sul.svg.png',
    SC: 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/Bandeira_de_Santa_Catarina.svg/300px-Bandeira_de_Santa_Catarina.svg.png',
    SE: 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/Bandeira_de_Sergipe.svg/1200px-Bandeira_de_Sergipe.svg.png',
    SP: 'https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/Bandeira_do_estado_de_S%C3%A3o_Paulo.svg/300px-Bandeira_do_estado_de_S%C3%A3o_Paulo.svg.png',
    TO: 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/ff/Bandeira_do_Tocantins.svg/1200px-Bandeira_do_Tocantins.svg.png'
};

const normalizeWikiUrl = (url) => {
    if (!url || typeof url !== 'string') return url;
    if (url.includes('flagcdn.com') || url.includes('Special:FilePath')) return url;
    const match = url.match(/(?:wikipedia\.org\/wiki\/|wikipedia\.org\/w\/index\.php\?title=)(?:File|Ficheiro):([^&?#]+)/i) || 
                  url.match(/wikipedia\/(?:commons|pt)\/(?:thumb\/)?(?:[a-f0-9]\/[a-f0-9]{2}\/)?([^\/]+)(?:\/\d+px-[^\/]+)?$/i);
    if (match && match[1]) {
        return `https://commons.wikimedia.org/wiki/Special:FilePath/${decodeURIComponent(match[1])}?width=250`;
    }
    return url;
};

const getPartidoLogo = (partido, urlOriginal) => {
    const fallback = partido ? PARTIDO_LOGOS_FALLBACK[partido.trim().toUpperCase()] : null;
    return normalizeWikiUrl(fallback || urlOriginal);
};

const getEstadoBandeira = (uf, urlOriginal) => {
    const fallback = uf ? ESTADO_BANDEIRAS_FALLBACK[uf.trim().toUpperCase()] : null;
    return normalizeWikiUrl(fallback || urlOriginal || '');
};

const VotacoesParlamentar = () => {
    const getPartidoPerfil = (perfil) =>
        perfil?.sgPartidoExibicao ||
        perfil?.sgPartidoAtual ||
        perfil?.ultimoStatus_siglaPartido ||
        perfil?.sgPartido ||
        '';

    // Filtros
    const [filtros, setFiltros] = useState({
        estado: 'Todos',
        partido: 'Todos',
        parlamentar: '',
        comissao: 'Todos',
        tema: 'Todos',
        dataInicio: '2023-01-01',
        dataFim: '',
        tipoVoto: 'Todos'
    });

    const [comissoes, setComissoes] = useState([{ id: 'Todos', nome: 'Todos' }]);
    const [temas, setTemas] = useState([
        'Administração Pública',
        'Agropecuária e Meio Ambiente',
        'Cultura e Esporte',
        'Direitos Humanos e Sociais',
        'Economia e Desenvolvimento',
        'Educação',
        'Infraestrutura e Transportes',
        'Relações Exteriores',
        'Saúde',
        'Segurança Pública e Justiça'
    ]);

    const [loading, setLoading] = useState(false);
    const [loadingComissoes, setLoadingComissoes] = useState(false);
    const [stats, setStats] = useState(null);
    const [error, setError] = useState(null);

    const SpinnerIcon = () => (
        <CircularProgress size={18} thickness={4} sx={{ mr: 1, color: 'inherit', opacity: 0.6 }} />
    );

    // Funções de Busca (acionada pelo Botão)
    const onFiltersChange = (newFilters) => {
        setFiltros(prev => ({ ...prev, ...newFilters }));
    };

    // 4. Carregar Comissões em cascata com base no Parlamentar (Otimizado)
    useEffect(() => {
        const loadComissoes = async () => {
            if (!filtros.parlamentar || filtros.parlamentar === 'Todos') {
                setComissoes([{ id: 'Todos', nome: 'Todos' }]);
                return;
            }
            setLoadingComissoes(true);
            try {
                const res = await axios.get(`/api/filters/comissoes?parlamentar=${filtros.parlamentar}`, { headers: API_HEADERS });
                if (res.data && res.data.comissoes) {
                    const comissoesFormatadas = (res.data.comissoes || []).map((com) => {
                        if (typeof com === 'string') {
                            const nome = com.trim();
                            return nome ? { id: nome, nome } : null;
                        }
                        const id = String(com.id || com.sigla || '').trim();
                        const nomeBruto = com.nome || com.comissao || com.Comissao || id || '';
                        const nome = String(nomeBruto).trim();
                        if (!nome) return null;
                        return { id: id || nome, nome };
                    }).filter(Boolean);

                    const comissoesUnicas = Array.from(
                        new Map(comissoesFormatadas.map((item) => [item.id, item])).values()
                    );

                    setComissoes([{ id: 'Todos', nome: 'Todos' }, ...comissoesUnicas]);
                } else {
                    setComissoes([{ id: 'Todos', nome: 'Todos' }]);
                }
            } catch (err) {
                console.error('Erro ao carregar comissões:', err);
                setComissoes([{ id: 'Todos', nome: 'Todos' }]);
            } finally {
                setLoadingComissoes(false);
            }
        };
        loadComissoes();
    }, [filtros.parlamentar]);

    useEffect(() => {
        if (!comissoes.some((comissao) => comissao.id === filtros.comissao)) {
            setFiltros((prev) => ({ ...prev, comissao: 'Todos' }));
        }
    }, [comissoes, filtros.comissao]);


    // Função de Busca (acionada pelo Botão)
    const handleBuscar = async () => {
        if (!filtros.parlamentar) {
            setError('Selecione um parlamentar para pesquisar.');
            return;
        }

        setLoading(true);
        setError(null);

        try {
            let url = `/api/parlamentares/${filtros.parlamentar}/stats?`;
            if (filtros.tema !== 'Todos') url += `tema=${encodeURIComponent(filtros.tema)}&`;
            if (filtros.comissao !== 'Todos') url += `comissao=${encodeURIComponent(filtros.comissao)}&`;
            if (filtros.dataInicio) url += `data_inicio=${filtros.dataInicio}&`;
            if (filtros.dataFim) url += `data_fim=${filtros.dataFim}&`;
            if (filtros.tipoVoto) url += `tipo_voto_filtro=${filtros.tipoVoto}`;

            const res = await axios.get(url, { headers: API_HEADERS });
            setStats(res.data);
        } catch (err) {
            console.error('Erro na busca de votações:', err);
            setError('Erro ao carregar dados. Tente novamente.');
        } finally {
            setLoading(false);
        }
    };

    const handleFilterChange = (field, value) => {
        setFiltros(prev => ({ ...prev, [field]: value }));
    };

    const handleDownloadCSV = () => {
        if (!stats || !stats.votos_detalhe) return;

        const headers = ["Data", "ID Votação", "Órgão/Comissão", "Tipo", "Voto", "Orientação Governo", "Tema", "Ementa/Resumo"];
        const rows = stats.votos_detalhe.map(v => [
            v.data_votacao || '',
            v.id_votacao || '',
            v.sigla_orgao || 'PLEN',
            v.tipo_votacao || '',
            v.voto || '',
            v.pauta_governo || 'Indiferente',
            v.tema_macro || '',
            (v.resumo_leigo || v.descricao || '').replace(/\s+/g, ' ').trim()
        ]);

        let csvContent = "\ufeff" + headers.join(";") + "\n" // BOM para Excel BR e ponto e vírgula
            + rows.map(e => e.map(val => `"${val}"`).join(";")).join("\n");

        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("download", `auditoria_votos_${stats.perfil.nome.replace(/\s+/g, '_')}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    // ... (Render Functions: Charts are same as before) ...
    // Gráficos ECharts
    const renderPieChart = () => {
        if (!stats) return null;
        const { votos_favoraveis, votos_contrarios, abstencoes } = stats.stats;

        const option = {
            tooltip: { trigger: 'item' },
            legend: { bottom: '0%', left: 'center' },
            series: [{
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: false,
                itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
                label: { show: false, position: 'center' },
                emphasis: { label: { show: true, fontSize: 16, fontWeight: 'bold' } },
                data: [
                    { value: votos_favoraveis, name: 'Favorável', itemStyle: { color: CORES_MARCA.verde } },
                    { value: votos_contrarios, name: 'Contra', itemStyle: { color: CORES_MARCA.azul } },
                    { value: abstencoes, name: 'Abstenção/Isento', itemStyle: { color: CORES_MARCA.amarelo } }
                ]
            }]
        };
        return <ReactECharts option={option} style={{ height: '300px' }} />;
    };

    const renderEvolutionChart = () => {
        if (!stats || !stats.evolucao || stats.evolucao.length === 0) return null;

        const option = {
            title: { text: 'Alinhamento Temporal (%)', left: 'center', textStyle: { color: CORES_MARCA.azul, fontSize: 14 } },
            tooltip: { trigger: 'axis' },
            xAxis: { type: 'category', data: stats.evolucao.map(e => e.periodo) },
            yAxis: { type: 'value', min: 0, max: 100 },
            series: [{
                name: '% Alinhamento',
                type: 'line',
                data: stats.evolucao.map(e => e.governismo),
                smooth: true,
                itemStyle: { color: CORES_MARCA.verde },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: 'rgba(0, 151, 57, 0.3)' },
                        { offset: 1, color: 'rgba(0, 151, 57, 0.1)' }
                    ])
                }
            }]
        };
        return <ReactECharts option={option} style={{ height: '300px' }} />;
    };

    const renderTemasChart = () => {
        if (!stats || !stats.temas) return null;
        const sortedTemas = [...stats.temas].sort((a, b) => b.governismo - a.governismo);

        const option = {
            title: { text: 'Governismo por Tema Macro (%)', left: 'center', textStyle: { color: CORES_MARCA.azul, fontSize: 14 } },
            tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
            grid: {
                top: '60px',
                left: '20px',
                right: '60px',
                bottom: '20px',
                containLabel: true
            },
            xAxis: {
                type: 'value',
                max: 100,
                axisLabel: { formatter: '{value}%' }
            },
            yAxis: {
                type: 'category',
                data: sortedTemas.map(t => t.tema),
                axisLabel: {
                    interval: 0,
                    width: 140,
                    overflow: 'break',
                    fontSize: 10
                }
            },
            series: [{ name: '% Governismo', type: 'bar', data: sortedTemas.map(t => t.governismo), itemStyle: { color: CORES_MARCA.azul } }]
        };
        return <ReactECharts option={option} style={{ height: sortedTemas.length * 45 + 120 + 'px', minHeight: '450px' }} />;
    };


    return (
        <Box sx={{ minHeight: '100vh', backgroundColor: '#F3F6FA', py: 4 }}>
            <Container maxWidth="xl">
                <Box sx={{ mb: 4, display: 'flex', alignItems: 'center', backgroundColor: 'white', p: 3, borderRadius: '16px', color: CORES_MARCA.azul, gap: 4 }}>
                    <Box sx={{ flex: 1, display: 'flex', alignItems: 'center' }}>
                        <Box sx={{ mr: 2, backgroundColor: CORES_MARCA.azul, borderRadius: '50%', p: 1, display: 'flex' }}>
                            <GavelIcon sx={{ color: 'white', fontSize: 30 }} />
                        </Box>
                        <Box>
                            <Typography variant="h4" sx={{ fontWeight: 'bold', fontFamily: 'Montserrat, sans-serif' }}>
                                Votação por Parlamentar
                            </Typography>
                            <Typography variant="subtitle1" sx={{ color: CORES_MARCA.cinza, fontFamily: 'Inter, sans-serif' }}>
                                Análise detalhada do comportamento legislativo e alinhamento político.
                            </Typography>
                        </Box>
                    </Box>
                    <Box
                        component="img"
                        src="/Votacao_por_Parlamentar.png"
                        alt="Ilustração Votação Parlamentar"
                        sx={{
                            maxHeight: '220px',
                            width: 'auto',
                            borderRadius: '8px',
                            display: { xs: 'none', md: 'block' }
                        }}
                    />
                </Box>

                {/* Filtros */}
                <Paper elevation={3} sx={{ p: 3, mb: 4, borderRadius: 2, backgroundColor: 'white' }}>
                    <FilterSelector 
                        onFiltersChange={onFiltersChange}
                        fields={['estado', 'partido', 'parlamentar']}
                        useCurrentParty={true}
                    />

                    <Grid container spacing={2} sx={{ mt: 1 }}>
                        <Grid item xs={12} md={3}>
                            <FormControl fullWidth size="small">
                                <InputLabel>Comissão/Órgão</InputLabel>
                                <Select
                                    value={filtros.comissao}
                                    label="Comissão/Órgão"
                                    onChange={(e) => handleFilterChange('comissao', e.target.value)}
                                    disabled={loadingComissoes}
                                    IconComponent={loadingComissoes ? SpinnerIcon : undefined}
                                >
                                    {comissoes.map(com => <MenuItem key={com.id} value={com.id}>{com.nome}</MenuItem>)}
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} md={3}>
                            <FormControl fullWidth size="small">
                                <InputLabel>Tema</InputLabel>
                                <Select value={filtros.tema} label="Tema" onChange={(e) => handleFilterChange('tema', e.target.value)}>
                                    <MenuItem value="Todos">Todos</MenuItem>
                                    {temas.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} md={2}>
                            <TextField
                                label="Data Início"
                                type="date"
                                size="small"
                                fullWidth
                                InputLabelProps={{ shrink: true }}
                                value={filtros.dataInicio}
                                onChange={(e) => handleFilterChange('dataInicio', e.target.value)}
                            />
                        </Grid>
                        <Grid item xs={12} md={2}>
                            <TextField
                                label="Data Fim"
                                type="date"
                                size="small"
                                fullWidth
                                InputLabelProps={{ shrink: true }}
                                value={filtros.dataFim}
                                onChange={(e) => handleFilterChange('dataFim', e.target.value)}
                            />
                        </Grid>
                        <Grid item xs={12} md={2}>
                            <FormControl fullWidth size="small">
                                <InputLabel>Tipo de Votação</InputLabel>
                                <Select value={filtros.tipoVoto} label="Tipo de Votação" onChange={(e) => handleFilterChange('tipoVoto', e.target.value)}>
                                    <MenuItem value="Todos">Todos</MenuItem>
                                    <MenuItem value="Nominal">Nominal</MenuItem>
                                    <MenuItem value="Simbolico">Simbólico</MenuItem>
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
                            <Button
                                variant="contained"
                                color="primary"
                                size="large"
                                onClick={handleBuscar}
                                disabled={loading || !filtros.parlamentar}
                                startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <FilterListIcon />}
                                sx={{ 
                                    bgcolor: CORES_MARCA.verde, 
                                    '&:hover': { bgcolor: '#007a2d' },
                                    borderRadius: '50px',
                                    px: 6,
                                    height: '50px',
                                    fontWeight: 'bold'
                                }}
                            >
                                {loading ? 'Pesquisando...' : 'Pesquisar Comportamento'}
                            </Button>
                        </Grid>
                    </Grid>
                </Paper>

                {loading && <LinearProgress sx={{ mb: 4, bgcolor: CORES_MARCA.azulClaro, '& .MuiLinearProgress-bar': { bgcolor: CORES_MARCA.verde } }} />}
                {error && <Alert severity="error" sx={{ mb: 4 }}>{error}</Alert>}


                {stats && (
                    <Grid container spacing={3}>
                        {/* 1. Header do Parlamentar (Modelo Premium Gastos) */}
                        <Grid item xs={12}>
                            <Paper elevation={3} sx={{ p: 4, mb: 1, bgcolor: '#FFFFFF', borderRadius: 4, border: '1px solid #e0e0e0' }}>
                                <Grid container spacing={3} alignItems="center">
                                    {/* Foto */}
                                    <Grid item xs={12} md={2} sx={{ display: 'flex', justifyContent: 'center' }}>
                                        <Avatar
                                            src={stats.perfil.urlFoto || stats.perfil.ultimoStatus_urlFoto}
                                            referrerPolicy="no-referrer"
                                            alt={stats.perfil.nome}
                                            sx={{
                                                width: 140,
                                                height: 140,
                                                border: `4px solid ${CORES_MARCA.azul}`,
                                                boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                                            }}
                                        />
                                    </Grid>

                                    {/* Infos Centrais */}
                                    <Grid item xs={12} md={7}>
                                        <Box>
                                            <Typography variant="h3" fontWeight="bold" sx={{ color: CORES_MARCA.azul, letterSpacing: '-0.5px' }}>
                                                {stats.perfil.nome}
                                            </Typography>
                                            
                                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 2 }}>
                                                <Chip
                                                    label={getPartidoPerfil(stats.perfil) || 'N/A'}
                                                    sx={{ bgcolor: '#E8F5E9', color: '#2E7D32', fontWeight: 'bold', px: 1.5, fontSize: '0.95rem' }}
                                                />
                                                <Chip
                                                    label={stats.perfil.sgUF || 'BR'}
                                                    sx={{ bgcolor: '#E3F2FD', color: '#1565C0', fontWeight: 'bold', px: 1.5, fontSize: '0.95rem' }}
                                                />
                                            </Box>
                                            
                                            <Typography variant="body1" sx={{ mt: 1.5, color: '#444', fontWeight: 600 }}>
                                                Análise de Comportamento Legislativo
                                            </Typography>

                                            <Typography variant="body2" sx={{ mt: 0.5, color: CORES_MARCA.verde, fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                                📌 Escopo de Votações: {
                                                    filtros.comissao === 'Todos' ? 'Geral (Painel Pleno + Comissões)' : 
                                                    comissoes.find(c => c.id === filtros.comissao)?.nome || filtros.comissao
                                                }
                                            </Typography>
                                        </Box>
                                    </Grid>

                                    {/* Logos Direita */}
                                    <Grid item xs={12} md={3} sx={{ display: 'flex', justifyContent: { xs: 'center', md: 'flex-end' }, alignItems: 'center', gap: 3 }}>
                                        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                                            {getPartidoLogo(getPartidoPerfil(stats.perfil), stats.perfil.URL_Partido) && (
                                                <Box 
                                                    component="img" 
                                                    src={getPartidoLogo(getPartidoPerfil(stats.perfil), stats.perfil.URL_Partido)} 
                                                    referrerPolicy="no-referrer"
                                                    sx={{ height: 65, maxWidth: 110, objectFit: 'contain' }} 
                                                />
                                            )}
                                            {getEstadoBandeira(stats.perfil.sgUF, stats.perfil.URL_Estado) && (
                                                <Box 
                                                    component="img" 
                                                    src={getEstadoBandeira(stats.perfil.sgUF, stats.perfil.URL_Estado)} 
                                                    referrerPolicy="no-referrer"
                                                    onError={(e) => {
                                                        const fallback = stats?.perfil?.sgUF
                                                            ? ESTADO_BANDEIRAS_FALLBACK[stats.perfil.sgUF.trim().toUpperCase()]
                                                            : '';
                                                        if (fallback && e.currentTarget.src !== fallback) {
                                                            e.currentTarget.src = fallback;
                                                            return;
                                                        }
                                                        e.currentTarget.style.display = 'none';
                                                    }}
                                                    sx={{ height: 45, maxWidth: 70, objectFit: 'contain', borderRadius: '4px', border: '1px solid #e0e0e0', boxShadow: 1 }} 
                                                />
                                            )}
                                        </Box>
                                    </Grid>
                                </Grid>
                            </Paper>
                        </Grid>

                        {/* 2. Coluna Lateral (Estatísticas Secas) */}
                        <Grid item xs={12} md={4}>
                            <Stack spacing={3}>
                                <Card elevation={3} sx={{ p: 3, borderRadius: 3 }}>
                                    <Typography variant="h6" sx={{ color: CORES_MARCA.azul, fontWeight: 'bold', mb: 2, borderBottom: `2px solid ${CORES_MARCA.amarelo}`, pb: 1 }}>
                                        📜 Natureza das Votações
                                    </Typography>
                                    <Stack spacing={2}>
                                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                            <Typography variant="body2" sx={{ fontWeight: 500 }}>Votos Nominais:</Typography>
                                            <Typography variant="h6" sx={{ color: CORES_MARCA.azul, fontWeight: 'bold' }}>{stats.stats.votos_nominais}</Typography>
                                        </Box>
                                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                            <Typography variant="body2" sx={{ fontWeight: 500 }}>Votos Simbólicos:</Typography>
                                            <Typography variant="h6" sx={{ color: CORES_MARCA.azul, fontWeight: 'bold' }}>{stats.stats.votos_simbolicos}</Typography>
                                        </Box>
                                        <Divider />
                                        <Alert severity="info" sx={{ mt: 1, '& .MuiAlert-message': { fontSize: '0.8rem', lineHeight: 1.4 } }}>
                                            <strong>Nota Regimental (Art. 185 do RICD):</strong> A aprovação em rito simbólico pressupõe concordância tácita. O silêncio equivale ao apoio à decisão da maioria.
                                        </Alert>
                                    </Stack>
                                </Card>

                                <Card elevation={3} sx={{ p: 3, borderRadius: 3, bgcolor: '#f8f9fa' }}>
                                    <Typography variant="h6" sx={{ color: CORES_MARCA.azul, fontWeight: 'bold', mb: 1.5 }}>
                                        🎯 Interesse do Governo
                                    </Typography>
                                    <Typography variant="body2" sx={{ color: 'text.secondary', lineHeight: 1.6, fontSize: '0.9rem' }}>
                                        Uma proposta é classificada como de <strong>Interesse do Governo</strong> quando a Liderança do Governo na Câmara emite uma orientação oficial de voto (Sim ou Não).
                                        <br /><br />
                                        O <strong>Índice de Alinhamento</strong> reflete a porcentagem de vezes que o parlamentar seguiu essa orientação oficial. 
                                        Conforme o <strong>Art. 185 do Regimento Interno (RICD)</strong>, se o parlamentar concorda com uma votação simbólica onde o governo deu "OK" e não solicita votação nominal, considera-se que ele concordou com a pauta governista.
                                    </Typography>
                                </Card>
                            </Stack>
                        </Grid>

                        {/* 3. Coluna Principal (Métricas e Gráficos) */}
                        <Grid item xs={12} md={8}>
                            <Grid container spacing={3}>
                                <Grid item xs={12} md={4}>
                                    <Paper elevation={2} sx={{ p: 2, textAlign: 'center', bgcolor: 'white', borderRadius: 2, borderTop: `4px solid ${CORES_MARCA.azul}` }}>
                                        <Typography variant="body2" sx={{ color: CORES_MARCA.cinza, textTransform: 'uppercase', fontSize: '0.75rem', fontWeight: 'bold' }}>Total de Votos</Typography>
                                        <Typography variant="h4" sx={{ color: CORES_MARCA.azul, fontWeight: 'bold' }}>{stats.stats.total_votos}</Typography>
                                    </Paper>
                                </Grid>
                                <Grid item xs={12} md={4}>
                                    <Paper elevation={2} sx={{ p: 2, textAlign: 'center', bgcolor: 'white', borderRadius: 2, borderTop: `4px solid ${CORES_MARCA.verde}` }}>
                                        <Typography variant="body2" sx={{ color: CORES_MARCA.cinza, textTransform: 'uppercase', fontSize: '0.75rem', fontWeight: 'bold' }}>Alinhamento Gov.</Typography>
                                        <Typography variant="h4" sx={{ color: CORES_MARCA.verde, fontWeight: 'bold' }}>{stats.stats.governismo_perc}%</Typography>
                                    </Paper>
                                </Grid>
                                <Grid item xs={12} md={4}>
                                    <Paper elevation={2} sx={{ p: 2, textAlign: 'center', bgcolor: 'white', borderRadius: 2, borderTop: `4px solid ${CORES_MARCA.amarelo}` }}>
                                        <Typography variant="body2" sx={{ color: CORES_MARCA.cinza, textTransform: 'uppercase', fontSize: '0.75rem', fontWeight: 'bold' }}>Abstenções</Typography>
                                        <Typography variant="h4" sx={{ color: CORES_MARCA.laranjaEscuro, fontWeight: 'bold' }}>{stats.stats.abstencoes}</Typography>
                                    </Paper>
                                </Grid>

                                <Grid item xs={12}>
                                    <Paper elevation={3} sx={{ p: 3, borderRadius: 3 }}>
                                        {renderEvolutionChart()}
                                    </Paper>
                                </Grid>

                                <Grid item xs={12} md={6}>
                                    <Paper elevation={3} sx={{ p: 3, height: '100%', borderRadius: 3 }}>
                                        <Typography variant="h6" sx={{ color: CORES_MARCA.azul, mb: 2, fontWeight: 'bold' }}>Distribuição de Votos</Typography>
                                        {renderPieChart()}
                                    </Paper>
                                </Grid>

                                <Grid item xs={12} md={6}>
                                    <Paper elevation={3} sx={{ p: 3, height: '100%', borderRadius: 3 }}>
                                        <Typography variant="h6" sx={{ color: CORES_MARCA.azul, mb: 2, fontWeight: 'bold' }}>Alinhamento por Tema</Typography>
                                        {renderTemasChart()}
                                    </Paper>
                                </Grid>

                                {/* Auditoria de Transparência */}
                                <Grid item xs={12}>
                                    <Paper elevation={3} sx={{ p: 3, borderRadius: 2, border: `1px dashed ${CORES_MARCA.azul}`, bgcolor: '#f0f4f8' }}>
                                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
                                            <Box>
                                                <Typography variant="h6" sx={{ color: CORES_MARCA.azul, fontWeight: 'bold' }}>🔎 Transparência e Auditoria</Typography>
                                                <Typography variant="body2" sx={{ color: 'text.secondary' }}>Baixe o log completo de votações deste parlamentar para conferência offline.</Typography>
                                            </Box>
                                            <Button
                                                variant="outlined"
                                                onClick={handleDownloadCSV}
                                                startIcon={<FilterListIcon sx={{ transform: 'rotate(180deg)' }} />}
                                                sx={{ borderColor: CORES_MARCA.azul, color: CORES_MARCA.azul, fontWeight: 'bold' }}
                                            >
                                                Download CSV
                                            </Button>
                                        </Box>
                                    </Paper>
                                </Grid>
                            </Grid>
                        </Grid>
                    </Grid>
                )}
            
      <DataSourceFooter
        sources={[{"label":"Votações — API da Câmara","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Votacoes","type":"camara"}]}
        note="Votos nominais individuais por deputado conforme registrado no sistema da Câmara dos Deputados."
      />
    </Container>
        </Box>
    );
};

export default VotacoesParlamentar;

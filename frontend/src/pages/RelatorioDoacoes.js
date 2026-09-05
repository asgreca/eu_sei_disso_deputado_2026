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
    Card,
    CardContent,
    CircularProgress,
    Alert,
    Avatar,
    Chip,
    Divider,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    LinearProgress,
} from '@mui/material';
import {
    AccountBalance as BankIcon,
    Business as BusinessIcon,
    People as PeopleIcon,
    TrendingUp as TrendingUpIcon,
    Payments as PaymentsIcon,
} from '@mui/icons-material';
import api from '../config/axios';
import { API_BASE_URL, API_KEY } from '../config';

// O axios já está configurado no arquivo ../config/axios.js

const BRAND = {
    colors: {
        green: '#009739',
        yellow: '#FFF81C',
        blue: '#003366',
        white: '#FFFFFF',
        blueLight: '#4F81BD',
        grayBg: '#f5f7fa'
    },
    typography: {
        titles: "'Montserrat', sans-serif",
        body: "'Inter', sans-serif",
    }
};

const formatCurrency = (value) => {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
};

function RelatorioDoacoes() {
    const [parlamentaresComDados, setParlamentaresComDados] = useState([]); // Base de dados completa filtrada
    const [estados, setEstados] = useState([]);
    const [partidos, setPartidos] = useState([]);
    const [parlamentares, setParlamentares] = useState([]); // Lista exibida no select
    const [filtros, setFiltros] = useState({ estado: 'Todos', partido: 'Todos', parlamentar: 'Todos' });
    const [loading, setLoading] = useState(false);
    const [loadingFiltros, setLoadingFiltros] = useState(false);
    const [dados, setDados] = useState([]);
    const [error, setError] = useState(null);
    const [infoParlamentar, setInfoParlamentar] = useState(null);

    const SpinnerIcon = () => (
        <CircularProgress size={18} thickness={4} sx={{ mr: 1, color: 'inherit', opacity: 0.6 }} />
    );

    useEffect(() => {
        carregarBaseFiltros();
    }, []);

    // Efeito para filtrar a lista de Estados e Partidos baseada no que existe de dados
    useEffect(() => {
        if (parlamentaresComDados.length > 0) {
            // Estados únicos da base
            const ests = [...new Set(parlamentaresComDados.map(p => p.estado).filter(Boolean))].sort();
            setEstados(ests);
        }
    }, [parlamentaresComDados]);

    // Quando o Estado muda, filtra Partidos disponíveis
    useEffect(() => {
        if (filtros.estado !== 'Todos') {
            const parts = [...new Set(parlamentaresComDados
                .filter(p => p.estado === filtros.estado)
                .map(p => p.partido).filter(Boolean)
            )].sort();
            setPartidos(parts);
            // Resetar sub-filtros
            setFiltros(prev => ({ ...prev, partido: 'Todos', parlamentar: 'Todos' }));
        } else {
            setPartidos([]);
            setFiltros(prev => ({ ...prev, partido: 'Todos', parlamentar: 'Todos' }));
        }
    }, [filtros.estado]);

    // Quando o Partido muda, filtra Parlamentares disponíveis
    useEffect(() => {
        if (filtros.partido !== 'Todos') {
            const parls = parlamentaresComDados
                .filter(p => p.estado === filtros.estado && p.partido === filtros.partido)
                .map(p => p.parlamentar);
            setParlamentares(parls);
            setFiltros(prev => ({ ...prev, parlamentar: 'Todos' }));
        } else {
            setParlamentares([]);
            setFiltros(prev => ({ ...prev, parlamentar: 'Todos' }));
        }
    }, [filtros.partido]);

    const carregarBaseFiltros = async () => {
        setLoadingFiltros(true);
        setLoading(true);
        try {
            const resp = await api.get('/api/filtros/parlamentares-doacoes');
            setParlamentaresComDados(resp.data.parlamentares || []);
        } catch (e) {
            console.error('Erro ao carregar base de filtros:', e);
            setError("Erro ao carregar lista de parlamentares disponiveis.");
        } finally {
            setLoadingFiltros(false);
            setLoading(false);
        }
    };

    const buscarRelatorio = async () => {
        if (filtros.parlamentar === 'Todos') return;
        setLoading(true);
        setError(null);
        try {
            // Buscar detalhes do parlamentar para o cabeçalho
            const infoResp = await api.get(`/api/parlamentares/detalhes?nome=${filtros.parlamentar}`);
            setInfoParlamentar(infoResp.data);

            const response = await api.get(`/api/parlamentares/doacoes-fornecedores?parlamentar=${filtros.parlamentar}`);
            setDados(response.data);
        } catch (err) {
            setError("Erro ao carregar dados de doações.");
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Box sx={{ bgcolor: BRAND.colors.grayBg, minHeight: '100vh', py: 4 }}>
            <Container maxWidth="lg">
                <Box sx={{ mb: 4, backgroundColor: 'white', p: 3, borderRadius: '16px', display: 'flex', alignItems: 'center', gap: 4 }}>
                    <Box sx={{ flex: 1 }}>
                        <Typography variant="h4" sx={{ fontWeight: 700, fontFamily: BRAND.typography.titles, color: BRAND.colors.blue }}>
                            Relatório: Doadores vs. Fornecedores
                        </Typography>
                        <Typography variant="body1" sx={{ color: BRAND.colors.grayText }}>
                            Cruzamento de dados entre doadores de campanha e fornecedores contratados pelo gabinete.
                        </Typography>
                    </Box>
                    <Box
                        component="img"
                        src="/Relacao_Doador_x_Fornecedor.png"
                        alt="Ilustração Doadores x Fornecedores"
                        sx={{
                            maxHeight: '220px',
                            width: 'auto',
                            borderRadius: '8px',
                            display: { xs: 'none', md: 'block' }
                        }}
                    />
                </Box>

                {/* Filtros */}
                <Paper sx={{ p: 3, mb: 4, borderRadius: '16px', boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
                    <Grid container spacing={2} alignItems="center">
                        <Grid item xs={12} md={3}>
                            <FormControl fullWidth>
                                <InputLabel>Estado</InputLabel>
                                <Select
                                    value={filtros.estado}
                                    label="Estado"
                                    onChange={(e) => setFiltros({ ...filtros, estado: e.target.value })}
                                    disabled={loadingFiltros}
                                    IconComponent={loadingFiltros ? SpinnerIcon : undefined}
                                >
                                    <MenuItem value="Todos">Todos</MenuItem>
                                    {estados.map(est => <MenuItem key={est} value={est}>{est}</MenuItem>)}
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} md={3}>
                            <FormControl fullWidth disabled={loadingFiltros || filtros.estado === 'Todos'}>
                                <InputLabel>Partido</InputLabel>
                                <Select
                                    value={filtros.partido}
                                    label="Partido"
                                    onChange={(e) => setFiltros({ ...filtros, partido: e.target.value })}
                                    disabled={loadingFiltros || filtros.estado === 'Todos'}
                                    IconComponent={loadingFiltros ? SpinnerIcon : undefined}
                                >
                                    <MenuItem value="Todos">Todos</MenuItem>
                                    {partidos.map(p => <MenuItem key={p} value={p}>{p}</MenuItem>)}
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} md={4}>
                            <FormControl fullWidth disabled={loadingFiltros || filtros.partido === 'Todos'}>
                                <InputLabel>Parlamentar</InputLabel>
                                <Select
                                    value={filtros.parlamentar}
                                    label="Parlamentar"
                                    onChange={(e) => setFiltros({ ...filtros, parlamentar: e.target.value })}
                                    disabled={loadingFiltros || filtros.partido === 'Todos'}
                                    IconComponent={loadingFiltros ? SpinnerIcon : undefined}
                                >
                                    <MenuItem value="Todos">Selecione...</MenuItem>
                                    {parlamentares.map(p => <MenuItem key={p} value={p}>{p}</MenuItem>)}
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} md={2}>
                            <Button
                                fullWidth
                                variant="contained"
                                onClick={buscarRelatorio}
                                disabled={filtros.parlamentar === 'Todos' || loading}
                                sx={{ bgcolor: BRAND.colors.blue, height: '56px', borderRadius: '12px' }}
                            >
                                Analisar
                            </Button>
                        </Grid>
                    </Grid>
                </Paper>

                {loading && <Box sx={{ display: 'flex', justifyContent: 'center', my: 8 }}><CircularProgress /></Box>}

                {error && <Alert severity="error" sx={{ mb: 4 }}>{error}</Alert>}

                {infoParlamentar && !loading && (
                    <Card sx={{ mb: 4, borderRadius: '16px', borderLeft: `6px solid ${BRAND.colors.green}` }}>
                        <CardContent sx={{ display: 'flex', alignItems: 'center', p: 3 }}>
                            <Avatar src={infoParlamentar.foto} sx={{ width: 80, height: 80, mr: 3, border: `2px solid ${BRAND.colors.blueLight}` }} />
                            <Box>
                                <Typography variant="h5" fontWeight={700}>{infoParlamentar.nome}</Typography>
                                <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
                                    <Chip label={infoParlamentar.partido} size="small" sx={{ bgcolor: BRAND.colors.blue, color: 'white' }} />
                                    <Chip label={infoParlamentar.estado} size="small" variant="outlined" />
                                </Box>
                            </Box>
                        </CardContent>
                    </Card>
                )}

                {!loading && dados.length > 0 && (
                    <TableContainer component={Paper} sx={{ borderRadius: '16px', overflow: 'hidden' }}>
                        <Table>
                            <TableHead sx={{ bgcolor: BRAND.colors.blue }}>
                                <TableRow>
                                    <TableCell sx={{ color: 'white', fontWeight: 700 }}>Sócio (Doador 2022)</TableCell>
                                    <TableCell sx={{ color: 'white', fontWeight: 700 }}>Empresa (Fornecedor)</TableCell>
                                    <TableCell sx={{ color: 'white', fontWeight: 700 }}>Valor Doado</TableCell>
                                    <TableCell sx={{ color: 'white', fontWeight: 700 }}>Valor Pago (Gabinete)</TableCell>
                                    <TableCell sx={{ color: 'white', fontWeight: 700 }}>Relação (Doação/Faturamento)</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {dados.map((row, idx) => {
                                    const relacao = row.faturamento.total > 0 ? (row.doacao.valor / row.faturamento.total) * 100 : 0;
                                    return (
                                        <TableRow key={idx}>
                                            <TableCell>
                                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                                    <PeopleIcon color="action" fontSize="small" />
                                                    <Typography variant="body2" fontWeight={600}>{row.socio}</Typography>
                                                </Box>
                                            </TableCell>
                                            <TableCell>
                                                <Typography variant="body2">{row.faturamento.fornecedor}</Typography>
                                                <Typography variant="caption" color="textSecondary">{row.cnpj}</Typography>
                                            </TableCell>
                                            <TableCell sx={{ color: BRAND.colors.blue, fontWeight: 700 }}>
                                                {formatCurrency(row.doacao.valor)}
                                            </TableCell>
                                            <TableCell sx={{ color: BRAND.colors.green, fontWeight: 700 }}>
                                                {formatCurrency(row.faturamento.total)}
                                            </TableCell>
                                            <TableCell sx={{ width: '200px' }}>
                                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                                    <Box sx={{ flex: 1 }}>
                                                        <LinearProgress
                                                            variant="determinate"
                                                            value={Math.min(relacao, 100)}
                                                            sx={{ height: 8, borderRadius: 4, bgcolor: '#eee', '& .MuiLinearProgress-bar': { bgcolor: BRAND.colors.blue } }}
                                                        />
                                                    </Box>
                                                    <Typography variant="caption" fontWeight={700}>
                                                        {relacao.toFixed(1)}%
                                                    </Typography>
                                                </Box>
                                                <Typography variant="caption" color="textSecondary">
                                                    A doação representa {relacao.toFixed(2)}% do que a empresa recebeu.
                                                </Typography>
                                            </TableCell>
                                        </TableRow>
                                    );
                                })}
                            </TableBody>
                        </Table>
                    </TableContainer>
                )}

                {!loading && dados.length === 0 && filtros.parlamentar !== 'Todos' && (
                    <Box sx={{ textAlign: 'center', py: 10 }}>
                        <Typography variant="h6" color="textSecondary">
                            Nenhuma doação cruzada encontrada para este parlamentar.
                        </Typography>
                    </Box>
                )}
            </Container>
        </Box>
    );
}

export default RelatorioDoacoes;

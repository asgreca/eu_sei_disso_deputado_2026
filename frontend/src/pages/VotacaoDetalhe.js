import React, { useEffect, useState } from 'react';
import {
    Box,
    Container,
    Typography,
    Paper,
    Grid,
    Card,
    CardContent,
    Avatar,
    Chip,
    Button,
    CircularProgress,
    Alert,
    Divider,
    Tooltip,
} from '@mui/material';
import {
    ArrowBack as ArrowBackIcon,
    Gavel as GavelIcon,
    Groups as GroupsIcon,
    AccountBalance as GovIcon,
    Info as InfoIcon,
    Description as DescriptionIcon,
    VerifiedUser as VerifiedUserIcon,
} from '@mui/icons-material';
import axios from 'axios';
import { useParams, useNavigate } from 'react-router-dom';

const VotacaoDetalhe = () => {
    const { id } = useParams();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState(null);
    const [erro, setErro] = useState(null);

    // Paleta de Cores do Manual
    const colors = {
        verde: '#009739',
        amarelo: '#FFF81C',
        azul: '#003366',
        azulClaro: '#4F81BD',
        verdeClaro: '#66BB6A',
        laranja: '#ED8B00',
        cinza: '#666666',
        fundo: '#f4f7f9'
    };

    useEffect(() => {
        const fetchData = async () => {
            setLoading(true);
            try {
                const res = await axios.get(`/api/votos/detalhe/${id}`);
                setData(res.data);
            } catch (err) {
                console.error("Erro ao buscar detalhe da votação", err);
                setErro("Não foi possível carregar os detalhes desta votação.");
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, [id]);

    if (loading) {
        return (
            <Box display="flex" justifyContent="center" alignItems="center" height="80vh">
                <CircularProgress size={60} sx={{ color: colors.azul }} />
            </Box>
        );
    }

    if (erro || !data) {
        return (
            <Container sx={{ mt: 4 }}>
                <Alert severity="error">{erro || "Votação não encontrada"}</Alert>
                <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/votos/geral')} sx={{ mt: 2 }}>
                    Voltar para lista
                </Button>
            </Container>
        );
    }

    const { ficha, aprovadores, opositores, abstencoes, explicacao_ricd } = data;

    return (
        <Box sx={{ bgcolor: colors.fundo, minHeight: '100vh', py: 4 }}>
            <Container maxWidth="xl">
                <Button
                    startIcon={<ArrowBackIcon />}
                    onClick={() => navigate('/votos/geral')}
                    sx={{ mb: 3, color: colors.azul, fontWeight: 'bold' }}
                >
                    Voltar para a Listagem
                </Button>

                {/* Header Premium */}
                <Paper sx={{ p: 4, mb: 4, borderRadius: 4, borderLeft: `10px solid ${ficha.tipo_votacao === 'Nominal' ? colors.verde : colors.laranja}` }}>
                    <Grid container spacing={3} alignItems="center">
                        <Grid item xs={12} md={8}>
                            <Typography variant="caption" sx={{ color: colors.cinza, fontWeight: 'bold', letterSpacing: 1 }}>
                                FICHA TÉCNICA DA DELIBERAÇÃO
                            </Typography>

                            {/* Título Principal agora é o Resumo Leigo (se existir) */}
                            <Typography variant="h4" sx={{
                                fontWeight: 800,
                                color: colors.azul,
                                fontFamily: 'Montserrat, sans-serif',
                                mb: 1,
                                lineHeight: 1.3
                            }}>
                                {ficha.resumo_leigo || ficha.proposicao}
                            </Typography>

                            {/* Subtítulo com Proposição Original */}
                            {ficha.resumo_leigo && (
                                <Typography variant="body2" sx={{ color: colors.cinza, mb: 2, fontStyle: 'italic' }}>
                                    Nome Técnico: {ficha.proposicao}
                                </Typography>
                            )}

                            <Box display="flex" gap={1.5} flexWrap="wrap" sx={{ mt: 2 }}>
                                {/* Badge Nominal/Simbólica */}
                                {/* Badge Nominal/Simbólica */}
                                {/* Badge Nominal/Simbólica */}
                                {(() => {
                                    const desc = ficha?.descricao || '';
                                    const summary = ficha?.resumo_leigo || '';
                                    const combinedText = desc + ' ' + summary;

                                    const hasCounts = combinedText.match(/Sim:?\s*(\d+)/i) ||
                                        combinedText.match(/Não:?\s*(\d+)/i) ||
                                        combinedText.match(/(\d+)\s*votos?\s*["']?Sim/i) ||
                                        combinedText.match(/(\d+)\s*votos?\s*["']?Não/i) ||
                                        combinedText.match(/(\d+)\s*votos?\s*a favor/i);

                                    let label = (ficha.tipo_votacao || 'N/A').toUpperCase();
                                    let color = colors.laranja;

                                    if (ficha.tipo_votacao === 'Nominal') {
                                        color = colors.verde; // Green
                                    } else if (hasCounts) {
                                        label = 'NOMINAL (AGREGADA)';
                                        color = '#1565c0'; // Blue
                                    }

                                    return (
                                        <Chip
                                            label={label}
                                            sx={{
                                                bgcolor: color,
                                                color: 'white',
                                                fontWeight: 'bold'
                                            }}
                                        />
                                    );
                                })()}

                                {/* Badge Tema */}
                                <Chip
                                    label={(ficha.tema_macro || 'GERAL').toUpperCase()}
                                    variant="outlined"
                                    sx={{ fontWeight: 'bold', borderColor: colors.azul, color: colors.azul }}
                                />

                                {/* Badge Governo */}
                                {ficha.pauta_governo && (
                                    <Chip
                                        icon={ficha.pauta_governo === 'Sim' ? <GovIcon style={{ color: 'white' }} /> : undefined}
                                        label={ficha.pauta_governo === 'Sim' ? 'INTERESSE DO GOVERNO' : (ficha.pauta_governo === 'Não' ? 'PAUTA DA OPOSIÇÃO' : 'INDIFERENTE AO GOVERNO')}
                                        sx={{
                                            bgcolor: ficha.pauta_governo === 'Sim' ? colors.azul : (ficha.pauta_governo === 'Não' ? '#d32f2f' : '#78909c'),
                                            color: 'white',
                                            fontWeight: 'bold'
                                        }}
                                    />
                                )}

                                {/* Botão Projeto */}
                                {ficha.url_proposicao && (
                                    <Button
                                        variant="outlined"
                                        size="small"
                                        startIcon={<DescriptionIcon />}
                                        href={ficha.url_proposicao}
                                        target="_blank"
                                        sx={{
                                            fontWeight: 'bold',
                                            borderColor: colors.azul,
                                            color: colors.azul,
                                            height: 32,
                                            textTransform: 'none'
                                        }}
                                    >
                                        Ver Projeto
                                    </Button>
                                )}
                            </Box>
                        </Grid>

                        <Grid item xs={12} md={4} align="right">
                            {/* Box de Data e Local */}
                            <Box sx={{ p: 2, bgcolor: '#f0f4f8', borderRadius: 3, textAlign: 'right' }}>
                                <Typography variant="caption" color="textSecondary" display="block" sx={{ mb: 0.5 }}>DATE E LOCAL</Typography>
                                <Typography variant="h5" sx={{ fontWeight: 'bold', color: colors.azul }}>
                                    {ficha.data_registro ? ficha.data_registro.split('T')[0].split('-').reverse().join('/') : 'N/A'}
                                </Typography>
                                <Typography variant="body2" sx={{ fontWeight: 500, color: colors.cinza, mt: 0.5 }}>
                                    {ficha.nome_orgao_completo || ficha.sigla_orgao || 'Câmara dos Deputados'}
                                </Typography>
                            </Box>
                        </Grid>
                    </Grid>
                </Paper>

                <Grid container spacing={4}>
                    {/* Detalhes e Resumo */}
                    <Grid item xs={12} md={5}>
                        <Paper sx={{ p: 4, borderRadius: 4, height: '100%' }}>
                            {ficha.tipo_votacao !== 'Simbólica' && (
                                <>
                                    <Typography variant="h5" sx={{ fontWeight: 700, color: colors.azul, mb: 3, display: 'flex', alignItems: 'center', gap: 1 }}>
                                        <GavelIcon sx={{ color: colors.verde }} /> Objeto da Votação
                                    </Typography>

                                    <Box sx={{ mb: 4 }}>
                                        <Typography variant="body1" sx={{ fontWeight: 500, lineHeight: 1.6, color: colors.cinza }}>
                                            {ficha.descricao || 'Descrição não disponível.'}
                                        </Typography>
                                    </Box>
                                    <Divider sx={{ my: 3 }} />
                                </>
                            )}

                            <Box display="flex" justifyContent="space-between">
                                <Box>
                                    <Typography variant="caption" color="textSecondary">CÓDIGO VOTAÇÃO</Typography>
                                    <Typography variant="body2" sx={{ fontFamily: 'Roboto Mono' }}>{id}</Typography>
                                </Box>
                            </Box>

                            <Box mt={4}>
                                <Alert severity="info" icon={<InfoIcon sx={{ color: colors.azul }} />} sx={{ borderRadius: 2, bgcolor: '#e3f2fd' }}>
                                    <Typography variant="caption" sx={{ fontSize: '0.75rem', color: colors.azul }}>
                                        <strong>Premissa Regimental (Art. 186):</strong> {explicacao_ricd}
                                    </Typography>
                                </Alert>
                            </Box>
                        </Paper>
                    </Grid>

                    {/* Aprovadores e Placar */}
                    <Grid item xs={12} md={7}>
                        <Paper sx={{ p: 4, borderRadius: 4 }}>
                            {/* Check Logic: List vs Aggregate */}
                            {/* Logic: Priority to Scoreboard/Text counts over partial lists for Symbolic votes */}
                            {(() => {
                                const desc = ficha.descricao || '';

                                // Regex Robust logic (Same as VotacoesGeral)
                                const matchSim1 = desc.match(/Sim:?\s*(\d+)/i);
                                const matchNao1 = desc.match(/Não:?\s*(\d+)/i);
                                const matchAbs1 = desc.match(/Abstenção:?\s*(\d+)/i);

                                const matchSim2 = desc.match(/(\d+)\s*votos?\s*["']?Sim/i);
                                const matchNao2 = desc.match(/(\d+)\s*votos?\s*["']?Não/i);
                                const matchAbs2 = desc.match(/(\d+)\s*(?:votos?|abstenções|abstenção)\s*["']?Abstenção/i);

                                let countSim = matchSim1 ? parseInt(matchSim1[1]) : (matchSim2 ? parseInt(matchSim2[1]) : 0);
                                let countNao = matchNao1 ? parseInt(matchNao1[1]) : (matchNao2 ? parseInt(matchNao2[1]) : 0);
                                let countAbs = matchAbs1 ? parseInt(matchAbs1[1]) : (matchAbs2 ? parseInt(matchAbs2[1]) : 0);

                                // Override: If Symbolic, ignore text counts. Assume Consensus (A Favor).
                                const isSymbolic = ficha.tipo_votacao === 'Simbólica';
                                if (isSymbolic) {
                                    countSim = 0;
                                    countNao = 0;
                                    countAbs = 0;
                                }

                                const hasRealCounts = !isSymbolic && (countSim > 0 || countNao > 0 || countAbs > 0);
                                const isNominal = ficha.tipo_votacao === 'Nominal';
                                const hasList = aprovadores && aprovadores.length > 0;
                                const hasOpposition = opositores && opositores.length > 0;
                                const hasAbstention = abstencoes && abstencoes.length > 0;

                                // 1. Nominal Oficial -> Lista
                                if (isNominal) {
                                    return (
                                        <>
                                            <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
                                                <Typography variant="h5" sx={{ fontWeight: 700, color: colors.azul, display: 'flex', alignItems: 'center', gap: 1 }}>
                                                    <GroupsIcon sx={{ color: colors.verde }} />
                                                    Votos Favoráveis
                                                </Typography>
                                                <Chip label={`${aprovadores.length} Parlamentares`} sx={{ fontWeight: 'bold', bgcolor: colors.azul, color: 'white' }} />
                                            </Box>
                                            <Divider sx={{ mb: 4 }} />
                                            <Box sx={{ maxHeight: '75vh', overflowY: 'auto', pr: 2 }}>
                                                <Grid container spacing={2}>
                                                    {aprovadores.map((aprov) => (
                                                        <Grid item xs={6} sm={4} lg={3} key={aprov.nome}>
                                                            <Card elevation={0} sx={{ borderRadius: 3, border: '1px solid #eee', transition: 'all 0.2s', '&:hover': { borderColor: colors.verde, bgcolor: '#f9fff9', transform: 'translateY(-2px)' } }}>
                                                                <CardContent sx={{ p: 2, textAlign: 'center' }}>
                                                                    <Avatar src={aprov.foto} alt={aprov.nome} sx={{ width: 70, height: 70, mb: 1.5, mx: 'auto', border: `2px solid ${colors.azulClaro}` }} />
                                                                    <Typography variant="caption" sx={{ fontWeight: 800, color: colors.azul, height: 32, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                                                                        {aprov.nome.toUpperCase()}
                                                                    </Typography>
                                                                    <Box display="flex" alignItems="center" justifyContent="center" gap={1} mt={1}>
                                                                        {aprov.logo_partido && (<img src={aprov.logo_partido} alt={aprov.partido} style={{ height: 18 }} />)}
                                                                        <Typography variant="caption" sx={{ fontWeight: 'bold', color: colors.cinza }}>{aprov.partido}-{aprov.uf}</Typography>
                                                                    </Box>
                                                                </CardContent>
                                                            </Card>
                                                        </Grid>
                                                    ))}
                                                </Grid>
                                            </Box>

                                            {/* Opositores (Adicionado) */}
                                            {hasOpposition && (
                                                <>
                                                    <Box display="flex" justifyContent="space-between" alignItems="center" mb={3} mt={4}>
                                                        <Typography variant="h5" sx={{ fontWeight: 700, color: '#d32f2f', display: 'flex', alignItems: 'center', gap: 1 }}>
                                                            <GroupsIcon sx={{ color: '#d32f2f' }} />
                                                            Votos Contrários
                                                        </Typography>
                                                        <Chip label={`${opositores.length} Parlamentares`} sx={{ fontWeight: 'bold', bgcolor: '#d32f2f', color: 'white' }} />
                                                    </Box>
                                                    <Divider sx={{ mb: 4 }} />
                                                    <Box sx={{ maxHeight: '75vh', overflowY: 'auto', pr: 2 }}>
                                                        <Grid container spacing={2}>
                                                            {opositores.map((oprov) => (
                                                                <Grid item xs={6} sm={4} lg={3} key={oprov.nome}>
                                                                    <Card elevation={0} sx={{ borderRadius: 3, border: '1px solid #eee', transition: 'all 0.2s', '&:hover': { borderColor: '#d32f2f', bgcolor: '#fff0f0', transform: 'translateY(-2px)' } }}>
                                                                        <CardContent sx={{ p: 2, textAlign: 'center' }}>
                                                                            <Avatar src={oprov.foto} alt={oprov.nome} sx={{ width: 70, height: 70, mb: 1.5, mx: 'auto', border: '2px solid #d32f2f' }} />
                                                                            <Typography variant="caption" sx={{ fontWeight: 800, color: '#d32f2f', height: 32, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                                                                                {oprov.nome.toUpperCase()}
                                                                            </Typography>
                                                                            <Box display="flex" alignItems="center" justifyContent="center" gap={1} mt={1}>
                                                                                {oprov.logo_partido && (<img src={oprov.logo_partido} alt={oprov.partido} style={{ height: 18 }} />)}
                                                                                <Typography variant="caption" sx={{ fontWeight: 'bold', color: colors.cinza }}>{oprov.partido}-{oprov.uf}</Typography>
                                                                            </Box>
                                                                        </CardContent>
                                                                    </Card>
                                                                </Grid>
                                                            ))}
                                                        </Grid>
                                                    </Box>
                                                </>
                                            )}

                                            {/* Abstenções (Adicionado) */}
                                            {hasAbstention && (
                                                <>
                                                    <Box display="flex" justifyContent="space-between" alignItems="center" mb={3} mt={4}>
                                                        <Typography variant="h5" sx={{ fontWeight: 700, color: '#757575', display: 'flex', alignItems: 'center', gap: 1 }}>
                                                            <GroupsIcon sx={{ color: '#757575' }} />
                                                            Abstenções
                                                        </Typography>
                                                        <Chip label={`${abstencoes.length} Parlamentares`} sx={{ fontWeight: 'bold', bgcolor: '#757575', color: 'white' }} />
                                                    </Box>
                                                    <Divider sx={{ mb: 4 }} />
                                                    <Box sx={{ maxHeight: '75vh', overflowY: 'auto', pr: 2 }}>
                                                        <Grid container spacing={2}>
                                                            {abstencoes.map((abst) => (
                                                                <Grid item xs={6} sm={4} lg={3} key={abst.nome}>
                                                                    <Card elevation={0} sx={{ borderRadius: 3, border: '1px solid #eee', transition: 'all 0.2s', '&:hover': { borderColor: '#757575', bgcolor: '#f5f5f5', transform: 'translateY(-2px)' } }}>
                                                                        <CardContent sx={{ p: 2, textAlign: 'center' }}>
                                                                            <Avatar src={abst.foto} alt={abst.nome} sx={{ width: 70, height: 70, mb: 1.5, mx: 'auto', border: '2px solid #757575' }} />
                                                                            <Typography variant="caption" sx={{ fontWeight: 800, color: '#757575', height: 32, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                                                                                {abst.nome.toUpperCase()}
                                                                            </Typography>
                                                                            <Box display="flex" alignItems="center" justifyContent="center" gap={1} mt={1}>
                                                                                {abst.logo_partido && (<img src={abst.logo_partido} alt={abst.partido} style={{ height: 18 }} />)}
                                                                                <Typography variant="caption" sx={{ fontWeight: 'bold', color: colors.cinza }}>{abst.partido}-{abst.uf}</Typography>
                                                                            </Box>
                                                                        </CardContent>
                                                                    </Card>
                                                                </Grid>
                                                            ))}
                                                        </Grid>
                                                    </Box>
                                                </>
                                            )}
                                        </>
                                    );
                                }
                                // 2. Symbolic + Counts -> Scoreboard (Placar Agregado) AND List (if available)
                                else if (hasRealCounts) {
                                    return (
                                        <>
                                            <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" py={5}>
                                                <Typography variant="h5" sx={{ fontWeight: 'bold', color: colors.azul, mb: 1 }}>
                                                    Placar Real (Agregado)
                                                </Typography>
                                                <Alert severity="info" variant="outlined" sx={{ mb: 4, maxWidth: 600, bgcolor: '#e3f2fd', borderColor: '#90caf9' }}>
                                                    <Typography variant="body2" sx={{ fontWeight: 'bold', color: '#0d47a1' }}>
                                                        Votação Simbólica com contagem nominal.
                                                    </Typography>
                                                    <Typography variant="caption" color="textSecondary">
                                                        Exibindo placar oficial e lista total de presença. A API não discrimina votos individuais nesta modalidade.
                                                    </Typography>
                                                </Alert>

                                                <Box display="flex" justifyContent="center" gap={8} width="100%">
                                                    <Box textAlign="center">
                                                        <Typography variant="h2" sx={{ fontWeight: 900, color: colors.verde }}>{countSim}</Typography>
                                                        <Typography variant="h6" sx={{ fontWeight: 'bold', color: colors.cinza }}>SIM</Typography>
                                                    </Box>
                                                    <Box textAlign="center">
                                                        <Typography variant="h2" sx={{ fontWeight: 900, color: '#d32f2f' }}>{countNao}</Typography>
                                                        <Typography variant="h6" sx={{ fontWeight: 'bold', color: colors.cinza }}>NÃO</Typography>
                                                    </Box>
                                                    <Box textAlign="center">
                                                        <Typography variant="h2" sx={{ fontWeight: 900, color: colors.cinza }}>{countAbs}</Typography>
                                                        <Typography variant="h6" sx={{ fontWeight: 'bold', color: colors.cinza }}>ABSTENÇÃO</Typography>
                                                    </Box>
                                                </Box>
                                            </Box>

                                            {hasList && (
                                                <>
                                                    <Box mb={3}>
                                                        <Alert severity="warning" variant="outlined" sx={{ bgcolor: '#fff3e0', borderColor: '#ffb74d' }}>
                                                            <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: '#e65100', mb: 0.5 }}>
                                                                Atenção ao Processo Legislativo (Art. 186 RICD)
                                                            </Typography>
                                                            <Typography variant="body2" color="#e65100">
                                                                Votações simbólicas implicam concordância tácita. Parlamentares que não solicitam votação nominal (Art. 185) são considerados favoráveis ao consenso.
                                                            </Typography>
                                                        </Alert>
                                                    </Box>

                                                    <Divider sx={{ my: 4 }} />
                                                    <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
                                                        <Typography variant="h6" sx={{ fontWeight: 700, color: colors.verde, display: 'flex', alignItems: 'center', gap: 1 }}>
                                                            <GroupsIcon />
                                                            A FAVOR (Aprovação Simbólica)
                                                        </Typography>
                                                        <Chip label={`${aprovadores.length} Votos (Consenso)`} size="small" sx={{ bgcolor: colors.verde, color: 'white' }} />
                                                    </Box>
                                                    <Box sx={{ maxHeight: '75vh', overflowY: 'auto', pr: 2 }}>
                                                        <Grid container spacing={2}>
                                                            {aprovadores.map((aprov) => (
                                                                <Grid item xs={6} sm={4} lg={3} key={aprov.nome}>
                                                                    <Card elevation={0} sx={{ borderRadius: 3, border: '1px solid #eee', transition: 'all 0.2s', '&:hover': { borderColor: colors.verde, bgcolor: '#f9fff9', transform: 'translateY(-2px)' } }}>
                                                                        <CardContent sx={{ p: 2, textAlign: 'center' }}>
                                                                            <Avatar src={aprov.foto} alt={aprov.nome} sx={{ width: 70, height: 70, mb: 1.5, mx: 'auto', border: `2px solid ${colors.azulClaro}` }} />
                                                                            <Typography variant="caption" sx={{ fontWeight: 800, color: colors.azul, height: 32, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                                                                                {aprov.nome.toUpperCase()}
                                                                            </Typography>
                                                                            <Box display="flex" alignItems="center" justifyContent="center" gap={1} mt={1}>
                                                                                {aprov.logo_partido && (<img src={aprov.logo_partido} alt={aprov.partido} style={{ height: 18 }} />)}
                                                                                <Typography variant="caption" sx={{ fontWeight: 'bold', color: colors.cinza }}>{aprov.partido}-{aprov.uf}</Typography>
                                                                            </Box>
                                                                        </CardContent>
                                                                    </Card>
                                                                </Grid>
                                                            ))}
                                                        </Grid>
                                                    </Box>

                                                    {/* Opositores (Adicionado - Agregada) */}
                                                    {hasOpposition && (
                                                        <>
                                                            <Box display="flex" justifyContent="space-between" alignItems="center" mb={3} mt={4}>
                                                                <Typography variant="h5" sx={{ fontWeight: 700, color: '#d32f2f', display: 'flex', alignItems: 'center', gap: 1 }}>
                                                                    <GroupsIcon sx={{ color: '#d32f2f' }} />
                                                                    Votos Contrários
                                                                </Typography>
                                                                <Chip label={`${opositores.length} Parlamentares`} sx={{ fontWeight: 'bold', bgcolor: '#d32f2f', color: 'white' }} />
                                                            </Box>
                                                            <Divider sx={{ mb: 4 }} />
                                                            <Box sx={{ maxHeight: '75vh', overflowY: 'auto', pr: 2 }}>
                                                                <Grid container spacing={2}>
                                                                    {opositores.map((oprov) => (
                                                                        <Grid item xs={6} sm={4} lg={3} key={oprov.nome}>
                                                                            <Card elevation={0} sx={{ borderRadius: 3, border: '1px solid #eee', transition: 'all 0.2s', '&:hover': { borderColor: '#d32f2f', bgcolor: '#fff0f0', transform: 'translateY(-2px)' } }}>
                                                                                <CardContent sx={{ p: 2, textAlign: 'center' }}>
                                                                                    <Avatar src={oprov.foto} alt={oprov.nome} sx={{ width: 70, height: 70, mb: 1.5, mx: 'auto', border: '2px solid #d32f2f' }} />
                                                                                    <Typography variant="caption" sx={{ fontWeight: 800, color: '#d32f2f', height: 32, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                                                                                        {oprov.nome.toUpperCase()}
                                                                                    </Typography>
                                                                                    <Box display="flex" alignItems="center" justifyContent="center" gap={1} mt={1}>
                                                                                        {oprov.logo_partido && (<img src={oprov.logo_partido} alt={oprov.partido} style={{ height: 18 }} />)}
                                                                                        <Typography variant="caption" sx={{ fontWeight: 'bold', color: colors.cinza }}>{oprov.partido}-{oprov.uf}</Typography>
                                                                                    </Box>
                                                                                </CardContent>
                                                                            </Card>
                                                                        </Grid>
                                                                    ))}
                                                                </Grid>
                                                            </Box>
                                                        </>
                                                    )}

                                                    {/* Abstenções (Adicionado - Agregada) */}
                                                    {hasAbstention && (
                                                        <>
                                                            <Box display="flex" justifyContent="space-between" alignItems="center" mb={3} mt={4}>
                                                                <Typography variant="h5" sx={{ fontWeight: 700, color: '#757575', display: 'flex', alignItems: 'center', gap: 1 }}>
                                                                    <GroupsIcon sx={{ color: '#757575' }} />
                                                                    Abstenções
                                                                </Typography>
                                                                <Chip label={`${abstencoes.length} Parlamentares`} sx={{ fontWeight: 'bold', bgcolor: '#757575', color: 'white' }} />
                                                            </Box>
                                                            <Divider sx={{ mb: 4 }} />
                                                            <Box sx={{ maxHeight: '75vh', overflowY: 'auto', pr: 2 }}>
                                                                <Grid container spacing={2}>
                                                                    {abstencoes.map((abst) => (
                                                                        <Grid item xs={6} sm={4} lg={3} key={abst.nome}>
                                                                            <Card elevation={0} sx={{ borderRadius: 3, border: '1px solid #eee', transition: 'all 0.2s', '&:hover': { borderColor: '#757575', bgcolor: '#f5f5f5', transform: 'translateY(-2px)' } }}>
                                                                                <CardContent sx={{ p: 2, textAlign: 'center' }}>
                                                                                    <Avatar src={abst.foto} alt={abst.nome} sx={{ width: 70, height: 70, mb: 1.5, mx: 'auto', border: '2px solid #757575' }} />
                                                                                    <Typography variant="caption" sx={{ fontWeight: 800, color: '#757575', height: 32, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                                                                                        {abst.nome.toUpperCase()}
                                                                                    </Typography>
                                                                                    <Box display="flex" alignItems="center" justifyContent="center" gap={1} mt={1}>
                                                                                        {abst.logo_partido && (<img src={abst.logo_partido} alt={abst.partido} style={{ height: 18 }} />)}
                                                                                        <Typography variant="caption" sx={{ fontWeight: 'bold', color: colors.cinza }}>{abst.partido}-{abst.uf}</Typography>
                                                                                    </Box>
                                                                                </CardContent>
                                                                            </Card>
                                                                        </Grid>
                                                                    ))}
                                                                </Grid>
                                                            </Box>
                                                        </>
                                                    )}
                                                </>
                                            )}
                                        </>
                                    );
                                }
                                // 3. Fallback List (If exists and no counts, usually partial symbolic)
                                else if (hasList) {
                                    return (
                                        <>
                                            <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
                                                <Typography variant="h5" sx={{ fontWeight: 700, color: colors.azul, display: 'flex', alignItems: 'center', gap: 1 }}>
                                                    <GroupsIcon sx={{ color: colors.verde }} />
                                                    Presença Registrada
                                                </Typography>
                                                <Chip label={`${aprovadores.length} Parlamentares`} sx={{ fontWeight: 'bold', bgcolor: colors.orange, color: 'white' }} />
                                            </Box>
                                            <Divider sx={{ mb: 4 }} />
                                            <Box sx={{ maxHeight: '75vh', overflowY: 'auto', pr: 2 }}>
                                                <Grid container spacing={2}>
                                                    {aprovadores.map((aprov) => (
                                                        <Grid item xs={6} sm={4} lg={3} key={aprov.nome}>
                                                            <Card elevation={0} sx={{ borderRadius: 3, border: '1px solid #eee', transition: 'all 0.2s', '&:hover': { borderColor: colors.verde, bgcolor: '#f9fff9', transform: 'translateY(-2px)' } }}>
                                                                <CardContent sx={{ p: 2, textAlign: 'center' }}>
                                                                    <Avatar src={aprov.foto} alt={aprov.nome} sx={{ width: 70, height: 70, mb: 1.5, mx: 'auto', border: `2px solid ${colors.azulClaro}` }} />
                                                                    <Typography variant="caption" sx={{ fontWeight: 800, color: colors.azul, height: 32, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                                                                        {aprov.nome.toUpperCase()}
                                                                    </Typography>
                                                                    <Box display="flex" alignItems="center" justifyContent="center" gap={1} mt={1}>
                                                                        {aprov.logo_partido && (<img src={aprov.logo_partido} alt={aprov.partido} style={{ height: 18 }} />)}
                                                                        <Typography variant="caption" sx={{ fontWeight: 'bold', color: colors.cinza }}>{aprov.partido}-{aprov.uf}</Typography>
                                                                    </Box>
                                                                </CardContent>
                                                            </Card>
                                                        </Grid>
                                                    ))}
                                                </Grid>
                                            </Box>
                                        </>
                                    );
                                }
                                // 4. Consensus
                                else {
                                    return (
                                        <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" py={5}>
                                            <GavelIcon sx={{ fontSize: 60, color: colors.laranja, mb: 2 }} />
                                            <Typography variant="h5" sx={{ fontWeight: 'bold', color: colors.laranja }}>
                                                Votação Simbólica
                                            </Typography>
                                            <Typography variant="body1" align="center" color="textSecondary" sx={{ mt: 2, maxWidth: 400 }}>
                                                Não há registro nominal de votos.
                                                Presume-se a aprovação por consenso dos presentes (Art. 186 RICD).
                                            </Typography>
                                        </Box>
                                    );
                                }
                            })()}
                        </Paper>
                    </Grid>
                </Grid>
            </Container>

            {/* Footer de Verificação */}
            {voto.hash_integridade && (
                <Box sx={{ width: '100%', bgcolor: '#f5f5f5', borderTop: '1px solid #ddd', py: 1.5, textAlign: 'center', mt: 4 }}>
                    <Tooltip title={`Hash SHA256: ${voto.hash_integridade}`} arrow>
                        <Box display="flex" alignItems="center" justifyContent="center" gap={1} sx={{ cursor: 'pointer' }}>
                            <VerifiedUserIcon sx={{ color: colors.verde, fontSize: 18 }} />
                            <Typography variant="caption" sx={{ color: colors.verde, fontWeight: 'bold' }}>
                                DADO AUDITADO E SEGURO
                            </Typography>
                            <Typography variant="caption" sx={{ color: colors.cinza }}>
                                • Cópia fiel do servidor oficial da Câmara
                            </Typography>
                        </Box>
                    </Tooltip>
                </Box>
            )}
        </Box>
    );
};

export default VotacaoDetalhe;

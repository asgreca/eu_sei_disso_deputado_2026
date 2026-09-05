import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Container,
  Grid,
  Card,
  CardContent,
  CardActionArea,
  Chip,
  Paper,
  Button,
  CircularProgress,
  Divider
} from '@mui/material';
import {
  Search as SearchIcon,
  Assessment as AssessmentIcon,
  People as PeopleIcon,
  Flight as FlightIcon,
  Newspaper as NewspaperIcon,
  AccountBalance as AccountBalanceIcon,
  Timeline as TimelineIcon,
  ArrowForward as ArrowForwardIcon,
  AttachMoney as AttachMoneyIcon,
  Groups as GroupsIcon,
  RecordVoiceOver as RecordVoiceOverIcon,
  Ballot as BallotIcon,
  Map as MapIcon,
  PieChart as PieChartIcon,
  SmartToy as SmartToyIcon,
  CheckCircle as CheckCircleIcon,
  Badge as BadgeIcon,
  Gavel as GavelIcon,
  ReportProblem as ReportProblemIcon
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import axios from '../config/axios';
import Logo from '../components/Logo';

const features = [
  {
    title: 'Busca Semântica Avançada',
    description: 'Encontre discursos de deputados federais e discursos parlamentares por tema usando inteligência artificial.',
    icon: <SearchIcon sx={{ fontSize: 40, color: '#009739' }} />,
    path: '/busca/semantica',
    color: '#009739',
  },
  {
    title: 'Atuação em Comissões',
    description: 'Analise a presença e a atuação de parlamentares nas comissões temáticas da Câmara dos Deputados.',
    icon: <AccountBalanceIcon sx={{ fontSize: 40, color: '#003366' }} />,
    path: '/comissoes/atuacao',
    color: '#003366',
  },
  {
    title: 'Sociograma Parlamentar',
    description: 'Visualize redes de relacionamento, afinidades e conexões entre deputados federais.',
    icon: <TimelineIcon sx={{ fontSize: 40, color: '#009739' }} />,
    path: '/conexoes/sociograma',
    color: '#009739',
  },
  {
    title: 'Votações da Câmara',
    description: 'Acompanhe as votações em plenário e veja como votam os deputados federais nos projetos de lei.',
    icon: <BallotIcon sx={{ fontSize: 40, color: '#003366' }} />,
    path: '/votos/geral',
    color: '#003366',
  },
  {
    title: 'Detalhamento de Gastos',
    description: 'Audite as despesas da cota parlamentar (CEAP) e verba de gabinete de cada deputado federal.',
    icon: <AssessmentIcon sx={{ fontSize: 40, color: '#009739' }} />,
    path: '/gastos/detalhamento',
    color: '#009739',
  },
  {
    title: 'Ranking de Gastos',
    description: 'Compare gastos da cota parlamentar por deputado, partido e estado com rankings de despesas.',
    icon: <AssessmentIcon sx={{ fontSize: 40, color: '#003366' }} />,
    path: '/gastos/ranking',
    color: '#003366',
  },
  {
    title: 'Emendas Parlamentares',
    description: 'Consulte a destinação, valores e execução das emendas parlamentares ao orçamento da União.',
    icon: <AttachMoneyIcon sx={{ fontSize: 40, color: '#009739' }} />,
    path: '/gastos/emendas',
    color: '#009739',
  },
  {
    title: 'Conflitos de Interesses',
    description: 'Identifique potenciais conflitos de interesse na destinação de emendas e gastos públicos.',
    icon: <ReportProblemIcon sx={{ fontSize: 40, color: '#003366' }} />,
    path: '/gastos/conflitos',
    color: '#003366',
  },
  {
    title: 'Mapa Eleitoral',
    description: 'Veja a votação de deputados federais por município brasileiro e seu desempenho eleitoral histórico.',
    icon: <MapIcon sx={{ fontSize: 40, color: '#009739' }} />,
    path: '/mapa/eleitoral2',
    color: '#009739',
  },
  {
    title: 'Mapa Partidário',
    description: 'Consulte a distribuição geográfica de votos e a força eleitoral de cada partido no Brasil.',
    icon: <PieChartIcon sx={{ fontSize: 40, color: '#003366' }} />,
    path: '/mapa/partidario',
    color: '#003366',
  },
  {
    title: 'Chat Parlamentar AI',
    description: 'Converse com o Antunes, nosso assistente virtual de inteligência artificial, para tirar dúvidas.',
    icon: <SmartToyIcon sx={{ fontSize: 40, color: '#009739' }} />,
    path: '/analise/chat',
    color: '#009739',
  },
  {
    title: 'Análise de Imprensa',
    description: 'Monitore o potencial midiático e a menção na imprensa dos deputados federais.',
    icon: <NewspaperIcon sx={{ fontSize: 40, color: '#003366' }} />,
    path: '/analise/imprensa',
    color: '#003366',
  },
  {
    title: 'Passagens Aéreas',
    description: 'Audite detalhadamente o uso de dinheiro público com passagens aéreas e viagens de parlamentares.',
    icon: <FlightIcon sx={{ fontSize: 40, color: '#009739' }} />,
    path: '/gastos/passagens',
    color: '#009739',
  },
  {
    title: 'Presença em Comissões',
    description: 'Consulte o ranking de presença, faltas e assiduidade dos deputados federais nas reuniões.',
    icon: <CheckCircleIcon sx={{ fontSize: 40, color: '#003366' }} />,
    path: '/comissoes/presenca',
    color: '#003366',
  },
  {
    title: 'Assessores de Gabinete',
    description: 'Consulte a lista e os salários de assessores e secretários lotados nos gabinetes parlamentares.',
    icon: <BadgeIcon sx={{ fontSize: 40, color: '#009739' }} />,
    path: '/parlamentar/assessores',
    color: '#009739',
  },
];

function HomePage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState({
    total_gastos: 0,
    total_parlamentares: 0,
    total_discursos: 0,
    total_comissoes: 0,
    ultimo_dado: '...'
  });
  const [loadingStats, setLoadingStats] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await axios.get('/api/home/stats');
        setStats(response.data);
      } catch (error) {
        console.error('Erro ao buscar estatísticas:', error);
      } finally {
        setLoadingStats(false);
      }
    };

    fetchStats();
  }, []);

  const formatCurrency = (value) => {
    if (value >= 1000000000) {
      const val = (value / 1000000000).toFixed(1).replace('.', ',');
      return `R$ ${val} ${parseFloat(val.replace(',', '.')) === 1.0 ? 'bilhão' : 'bilhões'}`;
    }
    if (value >= 1000000) {
      const val = (value / 1000000).toFixed(1).replace('.', ',');
      return `R$ ${val} ${parseFloat(val.replace(',', '.')) === 1.0 ? 'milhão' : 'milhões'}`;
    }
    if (value >= 1000) {
      const val = (value / 1000).toFixed(1).replace('.', ',');
      return `R$ ${val} mil`;
    }
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
  };

  const formatNumber = (value) => {
    if (value >= 1000000000) {
      const val = (value / 1000000000).toFixed(1).replace('.', ',');
      return `${val} ${parseFloat(val.replace(',', '.')) === 1.0 ? 'bilhão' : 'bilhões'}`;
    }
    if (value >= 1000000) {
      const val = (value / 1000000).toFixed(1).replace('.', ',');
      return `${val} ${parseFloat(val.replace(',', '.')) === 1.0 ? 'milhão' : 'milhões'}`;
    }
    if (value >= 1000) {
      const val = (value / 1000).toFixed(1).replace('.', ',');
      return `${val} mil`;
    }
    return value;
  };

  return (
    <Container maxWidth="xl" sx={{ pb: 8 }}>
      {/* Hero Section */}
      <Paper
        elevation={0}
        component="header"
        sx={{
          position: 'relative',
          backgroundColor: '#FFFFFF',
          color: '#003366',
          pt: { xs: 4, md: 8 },
          pb: { xs: 8, md: 12 },
          px: { xs: 2, md: 6 },
          overflow: 'hidden',
          borderRadius: 4,
          borderBottom: '1px solid #E0E0E0'
        }}
      >
        {/* Background Element */}
        <Box
          sx={{
            position: 'absolute',
            top: -50,
            right: -50,
            width: 300,
            height: 300,
            borderRadius: '50%',
            background: 'rgba(255, 255, 255, 0.05)',
            zIndex: 0
          }}
        />

        <Grid container spacing={4} alignItems="center" sx={{ position: 'relative', zIndex: 1 }}>
          <Grid item xs={12} md={7}>
            <Box sx={{ mb: 4 }}>
              <Logo variant="horizontal" sx={{ maxHeight: '180px' }} />
            </Box>
            {/* H1 Oculto para SEO */}
            <Typography
              component="h1"
              sx={{
                position: 'absolute',
                width: '1px',
                height: '1px',
                padding: 0,
                margin: '-1px',
                overflow: 'hidden',
                clip: 'rect(0, 0, 0, 0)',
                border: 0,
              }}
            >
              Eu Sei Disso Deputado - Fiscalização de Deputados Federais e Transparência Parlamentar
            </Typography>
            <Typography
              variant="h2"
              component="p"
              sx={{
                fontFamily: 'Montserrat, sans-serif',
                fontWeight: 700,
                mb: 2,
                fontSize: { xs: '2.5rem', md: '3.5rem' },
                color: '#003366',
                lineHeight: 1.2
              }}
            >
              Monitoramos o poder.<br />
              Você cobra o resultado.
            </Typography>
            <Typography
              variant="h6"
              sx={{
                fontFamily: 'Inter, sans-serif',
                fontWeight: 400,
                mb: 3,
                opacity: 0.9,
                maxWidth: '600px',
                lineHeight: 1.6,
                color: '#555555'
              }}
            >
              Dados claros sobre projetos, gastos e a atuação dos deputados federais.
              Transparência total para o cidadão.
            </Typography>

            {/* Storytelling Antunes */}
            <Box sx={{
              mb: 4,
              p: 3,
              backgroundColor: '#FFFFFF',
              borderLeft: '4px solid #009739',
              borderRadius: 2,
              boxShadow: '0 2px 8px rgba(0,0,0,0.05)'
            }}>
              <Typography variant="body1" sx={{ color: '#333333', fontStyle: 'italic', lineHeight: 1.8 }}>
                "Eu sou o <strong>Antunes</strong>, um robô auditor especializado em contas públicas.
                Minha missão é vasculhar cada centavo gasto e cada discurso feito.
                Não deixo passar nada. Comigo, a fiscalização é rigorosa e sem filtros."
              </Typography>
            </Box>

            <Button
              variant="contained"
              size="large"
              endIcon={<ArrowForwardIcon />}
              onClick={() => navigate('/gastos/ranking')}
              sx={{
                backgroundColor: '#009739',
                color: 'white',
                fontWeight: 'bold',
                px: 5,
                py: 2,
                fontSize: '1.1rem',
                borderRadius: 2,
                boxShadow: '0 4px 14px 0 rgba(0,151,57,0.39)',
                '&:hover': {
                  backgroundColor: '#007a2d',
                  transform: 'translateY(-2px)',
                  boxShadow: '0 6px 20px rgba(0,151,57,0.23)'
                },
                transition: 'all 0.3s ease'
              }}
            >
              COMEÇAR A INVESTIGAR
            </Button>
          </Grid>

          <Grid item xs={12} md={5} sx={{ display: { xs: 'none', md: 'flex' }, justifyContent: 'center', alignItems: 'center' }}>
            <Box
              component="img"
              src="/antunes_mascot.png"
              alt="Antunes - O Auditor Robô"
              sx={{
                maxHeight: '500px',
                width: 'auto',
                transform: 'scale(1.05)'
              }}
            />
          </Grid>
        </Grid>
      </Paper>

      {/* Big Numbers Section */}
      <Box component="section" aria-label="Estatísticas da Câmara" sx={{ mb: 8 }}>
        <Typography
          variant="h5"
          component="h2"
          sx={{
            color: '#003366',
            fontWeight: 'bold',
            mb: 1,
            fontFamily: 'Montserrat, sans-serif'
          }}
        >
          Estatísticas de Transparência da Câmara Federal
        </Typography>
        <Typography
          variant="subtitle2"
          sx={{
            color: '#666',
            mb: 3,
            fontFamily: 'Inter, sans-serif'
          }}
        >
          Dados atualizados até {stats.ultimo_dado} • Coleta e auditoria desde 01/01/2023
        </Typography>

        <Box sx={{ mt: 3, position: 'relative', zIndex: 2, px: { xs: 2, md: 6 } }}>
          <Grid container spacing={3} justifyContent="center">
            {/* Gastos Card */}
            <Grid item xs={12} sm={6} md={3}>
              <Paper
                elevation={3}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  alignItems: 'center',
                  borderTop: '4px solid #009739',
                  borderRadius: 4
                }}
              >
                <AssessmentIcon sx={{ fontSize: 40, color: '#009739', mb: 2 }} />
                <Typography variant="h4" component="div" sx={{ fontWeight: 'bold', color: '#333' }}>
                  {loadingStats ? <CircularProgress size={24} /> : formatCurrency(stats.total_gastos)}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Gastos Analisados
                </Typography>
              </Paper>
            </Grid>

            {/* Emendas Card */}
            <Grid item xs={12} sm={6} md={3}>
              <Paper
                elevation={3}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  alignItems: 'center',
                  borderTop: '4px solid #003366',
                  borderRadius: 4
                }}
              >
                <AttachMoneyIcon sx={{ fontSize: 40, color: '#003366', mb: 2 }} />
                <Typography variant="h4" component="div" sx={{ fontWeight: 'bold', color: '#333', fontSize: '1.8rem' }}>
                  {loadingStats ? <CircularProgress size={24} /> : formatCurrency(stats.total_emendas || 0)}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Emendas Parlamentares
                </Typography>
              </Paper>
            </Grid>

            {/* Parlamentares Card */}
            <Grid item xs={12} sm={6} md={3}>
              <Paper
                elevation={3}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  alignItems: 'center',
                  borderTop: '4px solid #003366',
                  borderRadius: 4
                }}
              >
                <GroupsIcon sx={{ fontSize: 40, color: '#003366', mb: 2 }} />
                <Typography variant="h4" component="div" sx={{ fontWeight: 'bold', color: '#333' }}>
                  {loadingStats ? <CircularProgress size={24} /> : stats.total_parlamentares}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Parlamentares
                </Typography>
              </Paper>
            </Grid>

            {/* Discursos Card */}
            <Grid item xs={12} sm={6} md={3}>
              <Paper
                elevation={3}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  alignItems: 'center',
                  borderTop: '4px solid #FFD700',
                  borderRadius: 4
                }}
              >
                <RecordVoiceOverIcon sx={{ fontSize: 40, color: '#FFD700', mb: 2 }} />
                <Typography variant="h4" component="div" sx={{ fontWeight: 'bold', color: '#333' }}>
                  {loadingStats ? <CircularProgress size={24} /> : formatNumber(stats.total_discursos)}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Discursos Processados
                </Typography>
              </Paper>
            </Grid>

            {/* Comissoes Card */}
            <Grid item xs={12} sm={6} md={4}>
              <Paper
                elevation={3}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  alignItems: 'center',
                  borderTop: '4px solid #009739',
                  borderRadius: 4
                }}
              >
                <AccountBalanceIcon sx={{ fontSize: 40, color: '#009739', mb: 2 }} />
                <Typography variant="h4" component="div" sx={{ fontWeight: 'bold', color: '#333' }}>
                  {loadingStats ? <CircularProgress size={24} /> : stats.total_comissoes}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Comissões Ativas
                </Typography>
              </Paper>
            </Grid>

            {/* Noticias Card */}
            <Grid item xs={12} sm={6} md={4}>
              <Paper
                elevation={3}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  alignItems: 'center',
                  borderTop: '4px solid #003366',
                  borderRadius: 4
                }}
              >
                <NewspaperIcon sx={{ fontSize: 40, color: '#003366', mb: 2 }} />
                <Typography variant="h4" component="div" sx={{ fontWeight: 'bold', color: '#333' }}>
                  {loadingStats ? <CircularProgress size={24} /> : formatNumber(stats.total_noticias || 0)}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Notícias Compiladas
                </Typography>
              </Paper>
            </Grid>

            {/* Votos Card */}
            <Grid item xs={12} sm={6} md={4}>
              <Paper
                elevation={3}
                sx={{
                  p: 3,
                  textAlign: 'center',
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                  alignItems: 'center',
                  borderTop: '4px solid #FFD700',
                  borderRadius: 4
                }}
              >
                <BallotIcon sx={{ fontSize: 40, color: '#FFD700', mb: 2 }} />
                <Typography variant="h4" component="div" sx={{ fontWeight: 'bold', color: '#333' }}>
                  {loadingStats ? <CircularProgress size={24} /> : formatNumber(stats.total_votos || 0)}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Votos Analisados
                </Typography>
                <Typography variant="caption" sx={{ color: '#888', mt: 0.5, fontSize: '0.72rem', fontStyle: 'italic' }}>
                  em Comissões e Plenário
                </Typography>
                {!loadingStats && stats.votos_nominais !== undefined && (
                  <Typography variant="caption" sx={{ color: '#666', mt: 0.5, fontSize: '0.7rem' }}>
                    {formatNumber(stats.votos_nominais)} Nominais | {formatNumber(stats.votos_simbolicos)} Simbólicos
                  </Typography>
                )}
              </Paper>
            </Grid>
          </Grid>
        </Box>
      </Box>
      {/* Mission Section */}
      <Box component="section" sx={{ mt: 12, mb: 12 }}>
        <Container maxWidth="lg">
          <Grid container spacing={6} alignItems="center">
            <Grid item xs={12} md={6}>
              <Box
                component="img"
                src="/assets/images/manifesto/antunes_analysis.png"
                alt="Antunes Analysis"
                sx={{
                  width: '100%',
                  borderRadius: 4,
                  boxShadow: '0 20px 40px rgba(0,51,102,0.15)'
                }}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <Typography variant="h4" component="h2" sx={{ color: '#003366', fontWeight: 'bold', mb: 3, fontFamily: 'Montserrat, sans-serif' }}>
                O Eu Sei Disso Deputado: Inteligência Cidadã e Transparência
              </Typography>
            <Typography variant="body1" paragraph sx={{ fontSize: '1.1rem', color: '#444', fontFamily: 'Inter, sans-serif' }}>
              Nasceu de uma convicção simples: a informação pública deve ser, de fato, pública. Não apenas disponível, mas acessível, compreensível e, acima de tudo, acionável.
            </Typography>
            <Typography variant="body1" paragraph sx={{ fontSize: '1.1rem', color: '#444', fontFamily: 'Inter, sans-serif' }}>
              Nós não somos um portal de notícias. Somos uma plataforma de inteligência cidadã. Utilizamos Dados Abertos e Inteligência Artificial de ponta para traduzir a burocracia em clareza.
            </Typography>
            <Box sx={{ borderLeft: '4px solid #009739', pl: 3, py: 1, my: 3, bgcolor: '#f9f9f9', borderRadius: '0 8px 8px 0' }}>
              <Typography variant="body1" sx={{ fontStyle: 'italic', color: '#003366', fontWeight: 500 }}>
                "Monitoramos cada centavo de verba de gabinete, rastreamos padrões em passagens aéreas e conectamos os pontos entre discursos e votações."
              </Typography>
            </Box>
          </Grid>
        </Grid>
      </Container>
    </Box>

      {/* Features Grid */}
      <Box component="section" sx={{ mb: 12 }}>
        <Typography
          variant="h5"
          component="h2"
          sx={{
            color: '#003366',
            fontWeight: 'bold',
            mb: 3,
            fontFamily: 'Montserrat, sans-serif'
          }}
        >
          Ferramentas de Auditoria e Fiscalização Parlamentar
        </Typography>
      <Grid container spacing={3}>
        {features.map((feature, index) => (
          <Grid item xs={12} sm={6} md={4} key={index}>
            <Card
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                transition: 'transform 0.2s, box-shadow 0.2s',
                '&:hover': {
                  transform: 'translateY(-4px)',
                  boxShadow: '0 8px 25px rgba(0, 51, 102, 0.15)',
                },
                borderRadius: 2
              }}
            >
              <CardActionArea
                onClick={() => navigate(feature.path)}
                sx={{
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'flex-start',
                  p: 2,
                }}
              >
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    mb: 2,
                    p: 2,
                    backgroundColor: '#f5f5f5',
                    borderRadius: 2,
                  }}
                >
                  {feature.icon}
                </Box>
                <CardContent sx={{ flexGrow: 1, p: 0 }}>
                  <Typography
                    variant="h6"
                    component="h3"
                    sx={{
                      color: '#003366',
                      fontWeight: 600,
                      mb: 1,
                      fontFamily: 'Montserrat, sans-serif'
                    }}
                  >
                    {feature.title}
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{
                      color: '#666666',
                      lineHeight: 1.6,
                      fontFamily: 'Inter, sans-serif'
                    }}
                  >
                    {feature.description}
                  </Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>

      {/* Antunes Section */}
      <Box component="section" aria-label="Antunes Auditor AI" sx={{ bgcolor: '#F5F5F5', py: 10, mt: 12, borderRadius: 4 }}>
        <Container maxWidth="lg">
          <Grid container spacing={6} alignItems="center" direction="row-reverse">
            <Grid item xs={12} md={5}>
              <Box
                component="img"
                src="/assets/images/manifesto/antunes_community.png"
                alt="Antunes Community"
                sx={{
                  width: '100%',
                  borderRadius: 4,
                  boxShadow: '0 20px 40px rgba(0,151,57,0.15)'
                }}
              />
            </Grid>
            <Grid item xs={12} md={7}>
              <Typography variant="overline" sx={{ color: '#009739', fontWeight: 'bold', letterSpacing: 1 }}>
                Inteligência Artificial Cidadã
              </Typography>
              <Typography variant="h3" component="h2" sx={{ color: '#003366', fontWeight: 'bold', mb: 3, fontFamily: 'Montserrat, sans-serif' }}>
                Antunes: O Robô de Auditoria de Gastos Públicos
              </Typography>
              <Typography variant="body1" paragraph sx={{ fontSize: '1.1rem', color: '#444', fontFamily: 'Inter, sans-serif' }}>
                "Eu sou o Antunes, um robô auditor especializado em contas públicas. Minha missão é vasculhar cada centavo gasto e cada discurso feito. Não deixo passar nada. Comigo, a fiscalização é rigorosa e sem filtros."
              </Typography>
              <Grid container spacing={3} sx={{ mt: 2 }}>
                {[
                  { title: 'Incansável', desc: 'O Antunes não se cansa. Monitoramento 24/7 de gastos parlamentares.' },
                  { title: 'Imparcial', desc: 'O Antunes não tem partido. Apenas analisa dados abertos do portal da transparência.' },
                  { title: 'Rigoroso', desc: 'Não aceita desculpas de preenchimento para cota parlamentar (CEAP).' }
                ].map((item, index) => (
                  <Grid item xs={12} sm={4} key={index}>
                    <Paper elevation={0} sx={{ p: 3, bgcolor: 'white', height: '100%', borderRadius: 2 }}>
                      <Typography variant="h6" component="h3" sx={{ color: '#003366', fontWeight: 'bold', mb: 1, fontSize: '1.1rem' }}>
                        {item.title}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {item.desc}
                      </Typography>
                    </Paper>
                  </Grid>
                ))}
              </Grid>
            </Grid>
          </Grid>
        </Container>
      </Box>

      {/* Commitments Section */}
      <Box component="section" sx={{ mt: 12, mb: 12 }}>
        <Container maxWidth="lg">
          <Typography variant="h4" component="h2" align="center" sx={{ color: '#003366', fontWeight: 'bold', mb: 6, fontFamily: 'Montserrat, sans-serif' }}>
            Compromisso com a Transparência Pública e Fiscalização Cidadã
          </Typography>
          <Grid container spacing={4}>
            {[
              { title: 'Monitorar o Poder', desc: 'Se é público, nós mostramos. Gastos, viagens, conexões de redes e atuação na Câmara.', icon: '🔍' },
              { title: 'Clareza Absoluta', desc: 'Sem burocracia ou termos técnicos complexos. Dados visuais, gráficos e rankings diretos.', icon: '💡' },
              { title: 'Cidadania Ativa', desc: 'Damos a munição necessária em dados abertos para você exercer o controle social.', icon: '📢' }
            ].map((item, index) => (
              <Grid item xs={12} md={4} key={index}>
                <Paper
                  elevation={2}
                  sx={{
                    p: 4,
                    height: '100%',
                    textAlign: 'center',
                    transition: 'transform 0.3s',
                    '&:hover': { transform: 'translateY(-8px)' },
                    borderTop: '4px solid #009739',
                    borderRadius: 3
                  }}
                >
                  <Typography variant="h2" sx={{ mb: 2 }}>{item.icon}</Typography>
                  <Typography variant="h5" component="h3" sx={{ color: '#003366', fontWeight: 'bold', mb: 2, fontFamily: 'Montserrat, sans-serif' }}>
                    {item.title}
                  </Typography>
                <Typography variant="body1" color="text.secondary" sx={{ fontFamily: 'Inter, sans-serif' }}>
                  {item.desc}
                </Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
      </Container>
    </Box>

      {/* Footer Info */}
      <Box component="footer" sx={{ textAlign: 'center', mt: 8, mb: 4, pt: 4, borderTop: '1px solid #eee' }}>
        <Typography variant="body2" sx={{ color: '#666666' }}>
          Sistema desenvolvido para promover transparência e accountability parlamentar.
        </Typography>
        <Typography variant="caption" sx={{ color: '#999', mt: 1, display: 'block' }}>
          © 2025 Eu Sei Disso Deputado. Todos os direitos reservados.
        </Typography>
      </Box>
    </Container>
  );
}

export default HomePage;

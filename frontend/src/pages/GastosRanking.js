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
  TextField,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Avatar,
  Chip,
  CircularProgress,
  Alert,
  Card,
  CardContent,
  TableSortLabel,
  Tooltip,
  Divider
} from '@mui/material';
import {
  Assessment as AssessmentIcon,
  Search as SearchIcon,
  TrendingUp as TrendingUpIcon,
} from '@mui/icons-material';
import api from '../config/axios';
import { API_BASE_URL, API_KEY, API_HEADERS } from '../config';
import { useNavigate } from 'react-router-dom';
import badgesData from '../data/badges.json';
import FilterSelector from '../components/FilterSelector';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';

// O axios já está configurado no arquivo ../config/axios.js

// URLs de logos de partidos (Special:FilePath - Imunes a bloqueios)
function GastosRanking() {
  const navigate = useNavigate();
  const [ranking, setRanking] = useState([]);
  const [metricasRanking, setMetricasRanking] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [badges, setBadges] = useState({});
  const [hasSearched, setHasSearched] = useState(false);

  // Paginação e Ordenação
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [orderBy, setOrderBy] = useState('total_gasto');
  const [orderDirection, setOrderDirection] = useState('desc');
  const [searchTerm, setSearchTerm] = useState('');

  // Filtros
  const [filtros, setFiltros] = useState({
    estado: 'Todos',
    partido: 'Todos',
    despesa: 'Todos',
  });

  const [filtrosAplicados, setFiltrosAplicados] = useState({
    estado: 'Todos',
    partido: 'Todos',
    despesa: 'Todos',
  });

  // Mapa de despesas
  const mapaDespesas = {
    "Todos": "Todos",
    "🚗 Gasto com veículos": "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES",
    "📢 Gasto com divulgação": "DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR.",
    "🏢 Gasto com locação de imóveis": "MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR",
    "⛽ Gasto com Combustível": "COMBUSTÍVEIS E LUBRIFICANTES.",
    "👮‍♂️ Gasto com segurança": "SERVIÇO DE SEGURANÇA PRESTADO POR EMPRESA ESPECIALIZADA.",
    "📞 Gasto com telefonia": "TELEFONIA",
    "📖 Gasto com revistas": "ASSINATURA DE PUBLICAÇÕES",
    "🍽️ Gasto com Alimentação": "FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR",
    "🏨 Gasto com hospedagem": "HOSPEDAGEM ,EXCETO DO PARLAMENTAR NO DISTRITO FEDERAL.",
    "🔑 Gasto com tokens": "AQUISIÇÃO DE TOKENS E CERTIFICADOS DIGITAIS",
    "🛩️ Gasto com locação de aeronaves": "LOCAÇÃO OU FRETAMENTO DE AERONAVES",
    "🎤 Gasto com palestras": "PARTICIPAÇÃO EM CURSO, PALESTRA OU EVENTO SIMILAR",
    "🚌 Gasto com passagem terrestre": "PASSAGENS TERRESTRES, MARÍTIMAS OU FLUVIAIS",
    "🚤 Locação de embarcações": "LOCAÇÃO OU FRETAMENTO DE EMBARCAÇÕES"
  };

  const formatarMoeda = (valor) => {
    if (valor === null || valor === undefined || Number.isNaN(valor)) {
      return 'R$ 0,00';
    }
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL',
      minimumFractionDigits: 2,
    }).format(valor);
  };

  const DESPESA_TO_BADGE_IMG = {
    "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES": "badge_car",
    "DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR.": "badge_influencer",
    "MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR": "badge_office",
    "COMBUSTÍVEIS E LUBRIFICANTES.": "badge_fuel",
    "SERVIÇO DE SEGURANÇA PRESTADO POR EMPRESA ESPECIALIZADA.": "badge_security",
    "TELEFONIA": "badge_phone",
    "ASSINATURA DE PUBLICAÇÕES": "badge_magazine",
    "FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR": "badge_food",
    "HOSPEDAGEM ,EXCETO DO PARLAMENTAR NO DISTRITO FEDERAL.": "badge_hotel",
    "AQUISIÇÃO DE TOKENS E CERTIFICADOS DIGITAIS": "badge_token",
    "LOCAÇÃO OU FRETAMENTO DE AERONAVES": "badge_jet",
    "PARTICIPAÇÃO EM CURSO, PALESTRA OU EVENTO SIMILAR": "badge_course",
    "PASSAGENS TERRESTRES, MARÍTIMAS OU FLUVIAIS": "badge_bus",
    "LOCAÇÃO OU FRETAMENTO DE EMBARCAÇÕES": "badge_boat",
    "PASSAGENS AÉREAS": "badge_travel"
  };

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

  const handlePartidoLogoError = (event, info) => {
    const partido = (info.sgPartido || info.partido || "").toUpperCase();
    const fallback = PARTIDO_LOGOS_FALLBACK[partido];
    if (fallback && event.target.src !== fallback) {
      event.target.src = fallback;
    } else {
      event.target.style.display = 'none';
    }
  };

  const fetchBadges = () => {
    try {
      setBadges(badgesData || {});
    } catch (err) {
      console.error('Erro ao carregar badges:', err);
    }
  };

  useEffect(() => {
    fetchBadges();
  }, []);

  useEffect(() => {
    if (hasSearched) {
      carregarRankingGeral();
    }
  }, [filtrosAplicados, page, orderBy, orderDirection]);

  const carregarRankingGeral = async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (filtrosAplicados.estado !== 'Todos') params.append('estado', filtrosAplicados.estado);
      if (filtrosAplicados.partido !== 'Todos') params.append('partido', filtrosAplicados.partido);

      // Converter nome fantasia para nome real da rubrica
      const despesaReal = mapaDespesas[filtrosAplicados.despesa] || filtrosAplicados.despesa;
      if (despesaReal !== 'Todos') params.append('despesa', despesaReal);

      // Adicionar paginação e busca
      params.append('skip', (page - 1) * 10);
      params.append('limit', 10);
      if (searchTerm) params.append('search', searchTerm);
      params.append('order_by', orderBy);
      params.append('direction', orderDirection);

      const response = await fetch(`${API_BASE_URL}/api/gastos/ranking-geral?${params.toString()}`, {
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY
        }
      });
      const dados = await response.json();

      // Ajustar formato dos dados conforme a resposta da API
      if (Array.isArray(dados)) {
        setRanking(dados);
        setTotalPages(1); // API atual não retorna paginação no root
      } else if (dados.ranking) {
        setRanking(dados.ranking);
        setMetricasRanking(dados.metricas);
      } else if (dados.data) {
        setRanking(dados.data);
        setTotalPages(dados.total_pages || 1);
      } else {
        setRanking([]);
      }

    } catch (err) {
      setError('Erro ao carregar ranking geral');
      console.error('Erro ao carregar ranking geral:', err);
      setRanking([]);
    } finally {
      setLoading(false);
    }
  };

  const handleFiltroChange = (campo, valor) => {
    setFiltros(prev => {
      const novosFiltros = { ...prev, [campo]: valor };
      if (campo === 'estado') {
        novosFiltros.partido = 'Todos';
      }
      return novosFiltros;
    });
  };

  const handleAplicarFiltros = () => {
    setFiltrosAplicados({ ...filtros });
    setHasSearched(true);
    setPage(1); 
  };

  const handleSearch = (event) => {
    setSearchTerm(event.target.value);
    setPage(1);
  };

  const handleSort = (property) => {
    const isAsc = orderBy === property && orderDirection === 'asc';
    setOrderDirection(isAsc ? 'desc' : 'asc');
    setOrderBy(property);
  };

  const getBadgeForDeputy = (deputy, isTopOne) => {
    if (!badges) return null;
    const deputyName = deputy.nome;
    const currentFilter = filtros.despesa;

    let officialBadges = null;
    const normalizedName = deputyName.trim().toUpperCase();
    const badgeKey = Object.keys(badges).find(key => key.trim().toUpperCase() === normalizedName);
    if (badgeKey) { officialBadges = badges[badgeKey]; }

    const despesaReal = mapaDespesas[currentFilter] || currentFilter;
    
    // 1. Verificar se é campeão nacional oficial
    if (officialBadges) {
      // Se houver filtro de despesa, procurar especificamente nesta rubrica
      if (despesaReal !== 'Todos') {
        const matchingBadge = officialBadges.find(b => b.categoria === despesaReal);
        if (matchingBadge) return { ...matchingBadge, scope: 'nacional' };
      } else {
        // Se for ranking geral, mostrar o badge de "DEPUTADO GASTÃO"
        const gastaoBadge = officialBadges.find(b => b.icone === 'badge_gastao');
        if (gastaoBadge) return { ...gastaoBadge, scope: 'nacional' };
      }
    }

    // 2. Se não for campeão nacional, mas for o Top 1 Estadual da busca atual
    if (isTopOne && filtrosAplicados.estado !== 'Todos' && despesaReal !== 'Todos') {
      const icone = DESPESA_TO_BADGE_IMG[despesaReal] || 'badge_gastao';
      return {
        titulo: `Líder em ${filtrosAplicados.estado}`,
        descricao: `Este parlamentar é o 1º colocado em gastos com "${currentFilter}" no estado do ${filtrosAplicados.estado}.`,
        icone: icone,
        scope: 'estadual'
      };
    }

    return null;
  };

  return (
    <Container maxWidth="xl" sx={{ pb: 8 }}>
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
            <AssessmentIcon sx={{ fontSize: 40, color: '#009739' }} />
            Ranking por Tipo de Gasto
          </Typography>
          <Typography variant="h6" sx={{ color: '#666666' }}>
            Compare gastos parlamentares por estado, partido e tipo de despesa
          </Typography>
        </Box>
        <Box
          component="img"
          src="/Ranking_por_Tipo_de_Gasto.png"
          alt="Ilustração Ranking de Gastos"
          sx={{
            maxHeight: '220px',
            width: 'auto',
            borderRadius: '8px',
            display: { xs: 'none', md: 'block' }
          }}
        />
      </Box>

      <FilterSelector 
        onFiltersChange={setFiltros}
        fields={['estado', 'partido']}
        useCurrentParty={true}
      />

      {/* Filtro de Despesa Adicional */}
      {/* Explicação de Filtros */}
      <Alert severity="info" sx={{ mb: 4, borderRadius: '12px', '& .MuiAlert-message': { width: '100%' } }}>
        <Typography variant="subtitle1" fontWeight="bold">💡 Dica de Busca:</Typography>
        <Typography variant="body2">
          Se você não selecionar nenhum <strong>Estado</strong> ou <strong>Tipo de Despesa</strong> específico (deixando como "Todos"), o sistema processará o <strong>Ranking Nacional Geral</strong>, comparando todos os parlamentares e todas as rubricas de gastos de uma só vez.
        </Typography>
      </Alert>

      {/* Galeria de Selinhos */}
      <Paper elevation={2} sx={{ p: 4, mb: 4, borderRadius: '16px', background: 'linear-gradient(135deg, #ffffff 0%, #f9fafb 100%)', border: '1px solid #e5e7eb' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
          <Typography variant="h5" fontWeight="bold" color="#003366" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            🏆 Galeria de Selinhos de Transparência
          </Typography>
        </Box>
        <Typography variant="body2" sx={{ mb: 4, color: '#4b5563' }}>
          Parlamentares que ocupam o <strong>1º lugar nacional</strong> em categorias específicas de gastos recebem selinhos exclusivos. Passe o mouse sobre eles no ranking para ver os detalhes da "conquista".
        </Typography>
        
        <Grid container spacing={2} justifyContent="center">
          {[
            { img: 'badge_gastao', title: 'Deputado Gastão', desc: 'Líder do ranking geral de despesas' },
            { img: 'badge_travel', title: 'Viajante VIP', desc: 'Maior gasto com passagens aéreas' },
            { img: 'badge_fuel', title: 'Maria Gasolina', desc: 'Líder em gastos com combustível' },
            { img: 'badge_influencer', title: 'O Influencer', desc: 'Maior investimento em divulgação' },
            { img: 'badge_jet', title: 'Barão dos Ares', desc: 'Líder em fretamento de aeronaves' },
            { img: 'badge_car', title: 'Dono da Locadora', desc: 'Maior gasto com aluguel de carros' },
            { img: 'badge_office', title: 'Escritório de Luxo', desc: 'Maior custo de manutenção de base' },
            { img: 'badge_security', title: 'Segurança Máxima', desc: 'Líder em gastos com segurança privada' },
            { img: 'badge_food', title: 'Bom de Garfo', desc: 'Maior gasto com alimentação parlamentar' },
            { img: 'badge_hotel', title: 'Hóspede Vitalício', desc: 'Líder em gastos com hospedagem' },
            { img: 'badge_phone', title: 'Call Center', desc: 'Maior gasto com telefonia' },
            { img: 'badge_boat', title: 'Capitão do Barco', desc: 'Líder em fretamento de embarcações' },
            { img: 'badge_magazine', title: 'Leitor Ávido', desc: 'Maior gasto com jornais e revistas' },
            { img: 'badge_course', title: 'Eterno Estudante', desc: 'Maior gasto com cursos e palestras' },
            { img: 'badge_token', title: 'Rei do Token', desc: 'Líder em certificados digitais' },
            { img: 'badge_bus', title: 'Viajante Terrestre', desc: 'Maior gasto com ônibus e trens' }
          ].map((item, idx) => (
            <Grid item xs={4} sm={3} md={2} lg={1.2} key={idx}>
              <Tooltip title={item.desc} arrow>
                <Box sx={{ textAlign: 'center', p: 1, '&:hover img': { transform: 'scale(1.1)' } }}>
                  <Box 
                    component="img" 
                    src={`/badges/${item.img}.png`} 
                    alt={item.title}
                    sx={{ width: 60, height: 60, mb: 1, transition: 'transform 0.2s' }}
                  />
                  <Typography variant="caption" sx={{ fontWeight: 'bold', display: 'block', lineHeight: 1.2, height: 30 }}>
                    {item.title}
                  </Typography>
                </Box>
              </Tooltip>
            </Grid>
          ))}
        </Grid>
      </Paper>

      <Paper elevation={1} sx={{ p: 3, mb: 4, borderRadius: '12px' }}>
        <Grid container spacing={3} alignItems="center">
          <Grid item xs={12} md={9}>
            <FormControl fullWidth>
              <InputLabel>💰 Tipo de Despesa</InputLabel>
              <Select
                value={filtros.despesa}
                label="💰 Tipo de Despesa"
                onChange={(e) => setFiltros(prev => ({ ...prev, despesa: e.target.value }))}
              >
                {Object.keys(mapaDespesas).map(despesa => (
                  <MenuItem key={despesa} value={despesa}>{despesa}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={3}>
            <Button
              fullWidth
              variant="contained"
              size="large"
              startIcon={<SearchIcon />}
              onClick={handleAplicarFiltros}
              sx={{
                backgroundColor: '#003366',
                height: '56px',
                fontWeight: 'bold',
                borderRadius: 2,
                '&:hover': { backgroundColor: '#002244' }
              }}
            >
              Buscar Ranking
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {/* Error Alert */}
      {error && (
        <Alert severity="error" sx={{ mb: 4 }}>
          {error}
        </Alert>
      )}

      {/* Tabela de Ranking */}
      <Paper elevation={3} sx={{ p: 3, borderRadius: 2 }}>
        <Box sx={{ mb: 3, display: 'flex', justifyContent: 'flex-end' }}>
          <TextField
            label="Buscar Deputado"
            variant="outlined"
            size="small"
            value={searchTerm}
            onChange={handleSearch}
            InputProps={{
              endAdornment: <SearchIcon color="action" />
            }}
            sx={{ width: 300 }}
          />
        </Box>

        <TableContainer>
          <Table>
            <TableHead>
              <TableRow sx={{ backgroundColor: '#f5f5f5' }}>
                <TableCell sx={{ fontWeight: 'bold' }}>Posição</TableCell>
                <TableCell sx={{ fontWeight: 'bold' }}>Parlamentar</TableCell>
                <TableCell sx={{ fontWeight: 'bold' }}>Partido/UF</TableCell>
                <TableCell
                  align="right"
                  sx={{ fontWeight: 'bold', cursor: 'pointer' }}
                  onClick={() => handleSort('total_gasto')}
                >
                  <TableSortLabel
                    active={orderBy === 'total_gasto'}
                    direction={orderBy === 'total_gasto' ? orderDirection : 'asc'}
                  >
                    Total Gasto
                  </TableSortLabel>
                </TableCell>

              </TableRow>
            </TableHead>
            <TableBody>
              {!hasSearched ? (
                <TableRow>
                  <TableCell colSpan={5} align="center" sx={{ py: 10 }}>
                    <Box sx={{ color: '#999', textAlign: 'center' }}>
                      <TrendingUpIcon sx={{ fontSize: 60, mb: 2, opacity: 0.3 }} />
                      <Typography variant="h6">
                        Selecione os filtros e clique em "Buscar Ranking" para visualizar os resultados.
                      </Typography>
                    </Box>
                  </TableCell>
                </TableRow>
              ) : loading ? (
                <TableRow>
                  <TableCell colSpan={5} align="center" sx={{ py: 4 }}>
                    <CircularProgress />
                  </TableCell>
                </TableRow>
              ) : ranking.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} align="center" sx={{ py: 4 }}>
                    <Alert severity="info" sx={{ justifyContent: 'center' }}>
                      Nenhum parlamentar encontrado para os filtros selecionados.
                    </Alert>
                  </TableCell>
                </TableRow>
              ) : (
                ranking.map((deputy, index) => {
                  const isTopOne = index === 0 && page === 1;
                  const badge = getBadgeForDeputy(deputy, isTopOne);
                  const isNacional = badge?.scope === 'nacional';

                  return (
                    <TableRow
                      key={deputy.id || index}
                      sx={{ 
                        '&:hover': { backgroundColor: '#f9f9f9' },
                        backgroundColor: isTopOne ? 'rgba(0, 151, 57, 0.03)' : 'inherit'
                      }}
                    >
                      <TableCell>
                        <Chip
                          label={`#${(page - 1) * 10 + index + 1}`}
                          color={isTopOne ? "primary" : "default"}
                          size="small"
                          sx={{ 
                            fontWeight: 'bold',
                            backgroundColor: isTopOne ? (isNacional ? '#FFD700' : '#009739') : undefined,
                            color: isTopOne && isNacional ? '#000' : '#fff'
                          }}
                        />
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                          <Box sx={{ position: 'relative' }}>
                            <Avatar
                              src={deputy.ultimoStatus_urlFoto || deputy.urlFoto || deputy.foto}
                              alt={deputy.nome}
                              sx={{ 
                                width: 80, 
                                height: 80, 
                                border: isTopOne ? `3px solid ${isNacional ? '#FFD700' : '#009739'}` : '2px solid #eaeaea',
                                boxShadow: isTopOne ? 3 : 0
                              }}
                            />
                            {isTopOne && (
                              <Box sx={{
                                position: 'absolute',
                                bottom: -5,
                                right: -5,
                                backgroundColor: isNacional ? '#FFD700' : '#009739',
                                color: isNacional ? '#000' : '#fff',
                                borderRadius: '50%',
                                width: 24,
                                height: 24,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                fontSize: '12px',
                                fontWeight: 'bold',
                                border: '2px solid #fff'
                              }}>
                                {isNacional ? '👑' : '📍'}
                              </Box>
                            )}
                          </Box>
                          <Box>
                            <Typography variant="subtitle1" fontWeight="bold">
                              {deputy.nome}
                            </Typography>
                            {badge && (
                              <Tooltip 
                                title={
                                  <Box sx={{ p: 1 }}>
                                    <Typography variant="subtitle2" fontWeight="bold" sx={{ color: isNacional ? '#FFD700' : '#fff' }}>
                                      {isNacional ? '🏆 CAMPEÃO NACIONAL' : `📍 LÍDER EM ${filtrosAplicados.estado}`}
                                    </Typography>
                                    <Divider sx={{ my: 0.5, backgroundColor: 'rgba(255,255,255,0.2)' }} />
                                    <Typography variant="body2">{badge.descricao}</Typography>
                                  </Box>
                                } 
                                arrow
                              >
                                <Box sx={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', minHeight: '150px' }}>
                                    <Box
                                      sx={{
                                        width: 110,
                                        height: 110,
                                        borderRadius: '50%',
                                        overflow: 'hidden',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        backgroundColor: '#fff',
                                        border: isNacional ? '3px solid #FFD700' : '2px solid #009739',
                                        boxShadow: '0 4px 10px rgba(0,0,0,0.1)',
                                        mt: 1,
                                        cursor: 'pointer',
                                        transition: 'transform 0.2s',
                                        '&:hover': { transform: 'scale(1.1)' }
                                      }}
                                    >
                                      <Box
                                        component="img"
                                        src={`/badges/${badge.icone}.png`}
                                        alt={badge.titulo}
                                        sx={{
                                          width: '100%',
                                          height: '100%',
                                          objectFit: 'cover'
                                        }}
                                      />
                                    </Box>
                                  <Typography 
                                    variant="caption" 
                                    sx={{ 
                                      mt: 1, 
                                      fontWeight: 'bold', 
                                      color: isNacional ? '#D4AF37' : '#009739',
                                      textTransform: 'uppercase',
                                      backgroundColor: isNacional ? 'rgba(255, 215, 0, 0.1)' : 'rgba(0, 151, 57, 0.05)',
                                      px: 1,
                                      borderRadius: '4px',
                                      fontSize: '0.7rem',
                                      letterSpacing: '0.5px'
                                    }}
                                  >
                                    {isNacional ? '🏆 Título Nacional' : `📍 Líder em ${deputy.sgUF || deputy.estado}`}
                                  </Typography>
                                </Box>
                              </Tooltip>
                            )}
                          </Box>
                        </Box>
                      </TableCell>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Tooltip title={deputy.sgPartido || deputy.partido}>
                            <Box
                              component="img"
                              src={getPartidoLogo(deputy)}
                              onError={(e) => handlePartidoLogoError(e, deputy)}
                              alt="Partido"
                              sx={{ width: 45, height: 45, objectFit: 'contain' }}
                            />
                          </Tooltip>
                          <Tooltip title={deputy.sgUF || deputy.estado}>
                            <Box
                              component="img"
                              src={getEstadoLogo(deputy)}
                              alt="Estado"
                              sx={{ width: 35, height: 25, objectFit: 'contain', boxShadow: 1, borderRadius: '4px' }}
                            />
                          </Tooltip>
                          <Typography variant="body2" sx={{ ml: 1, fontWeight: 'bold', color: '#003366' }}>
                            {deputy.sgPartido || deputy.partido}/{deputy.sgUF || deputy.estado}
                          </Typography>
                        </Box>
                      </TableCell>
                      <TableCell align="right">
                        <Typography fontWeight="bold" color="error">
                          {formatarMoeda(deputy.total_gasto)}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Rodapé de transparência */}
      <Box
        sx={{
          mt: 4, mb: 2, p: 3,
          borderTop: '1px solid #e0e6ed',
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1,
        }}
      >
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'center' }}>
          📊 Dados extraídos do portal de Dados Abertos da Câmara dos Deputados.
          Os valores referem-se às cotas para exercício da atividade parlamentar (CEAP) declaradas pelos próprios deputados.
        </Typography>
        <Typography variant="caption" sx={{ textAlign: 'center' }}>
          <Box
            component="a"
            href="https://dadosabertos.camara.leg.br/swagger/api.html#api-Despesas"
            target="_blank"
            rel="noopener noreferrer"
            sx={{
              color: '#003366',
              fontWeight: 600,
              textDecoration: 'none',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 0.5,
              '&:hover': { textDecoration: 'underline', color: '#009739' },
            }}
          >
            🔗 dadosabertos.camara.leg.br — Acesse e baixe o CSV completo de despesas parlamentares
          </Box>
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'center', fontSize: '0.7rem' }}>
          Fonte primária: API de Dados Abertos da Câmara dos Deputados (camara.leg.br) · Atualização periódica
        </Typography>
      </Box>
    </Container>
  );
}

export default GastosRanking;

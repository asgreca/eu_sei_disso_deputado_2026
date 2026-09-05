import React, { useState, useEffect, useCallback } from 'react';
import { 
  Box, 
  Typography, 
  Grid, 
  Paper, 
  Table, 
  TableBody, 
  TableCell, 
  TableContainer, 
  TableHead, 
  TableRow, 
  Avatar,
  CircularProgress,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Button,
  Tooltip,
  IconButton,
  Card,
  CardContent,
  Chip
} from '@mui/material';
import { 
  Groups as GroupsIcon, 
  AccountBalanceWallet as WalletIcon, 
  TrendingUp as TrendingUpIcon,
  Launch as LaunchIcon,
  Search as SearchIcon,
  FilterList as FilterListIcon,
  Warning as WarningIcon
} from '@mui/icons-material';
import axios from '../config/axios';
import ReactECharts from 'echarts-for-react';
import FilterSelector from '../components/FilterSelector';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

// CORES DO MANUAL DE MARCA
const COLORS = {
  VERDE: '#009739',
  AMARELO: '#FFF81C',
  AZUL: '#003366',
  BRANCO: '#FFFFFF',
  CINZA: '#666666',
  AZUL_CLARO: '#4F81BD',
  CINZA_CLARO: '#E0E0E0'
};

const Assessores = () => {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');

  const [filtros, setFiltros] = useState({
    estado: 'Todos',
    partido: 'Todos',
    parlamentar: 'Todos',
  });
  const [parlamentarInfo, setParlamentarInfo] = useState(null);

  const handleFilterChange = (newFilters) => {
    setFiltros(newFilters);
  };

  const fetchData = async () => {
    if (filtros.parlamentar === 'Todos') return;
    setLoading(true);
    setParlamentarInfo(null);
    try {
      // 1. Detalhes do Parlamentar (Foto, Partido, UF)
      const detailsRes = await axios.get(`/api/parlamentares/detalhes?nome=${encodeURIComponent(filtros.parlamentar)}`);
      setParlamentarInfo(detailsRes.data);

      // 2. Análise de Assessores
      const response = await axios.get(`/api/assessores/analise?parlamentar=${encodeURIComponent(filtros.parlamentar)}`);
      if (response.data.success) {
        setData(response.data);
      }
    } catch (error) {
      console.error('Erro ao buscar dados de assessores:', error);
    } finally {
      setLoading(false);
    }
  };

  // FORMATAÇÃO
  const formatCurrency = (val) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(val);
  
  // LOGO HELPERS TRANSIÇÃO

  // HELPERS DE IMAGEM (Anti-Bloqueio Wikipedia)
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
    const partido = (info.partido || "").trim().toUpperCase();
    if (info.urlPartido) return normalizeWikiUrl(info.urlPartido);
    return PARTIDO_LOGOS_FALLBACK[partido] || '';
  };

  const getEstadoLogo = (info) => {
    if (!info) return '';
    if (info.urlEstado) return normalizeWikiUrl(info.urlEstado);
    const uf = (info.uf || "").trim().toUpperCase();
    
    // Tratamento especial para RN que falha no FlagCDN ou links quebrados
    if (uf === 'RN') return 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/30/Bandeira_do_Rio_Grande_do_Norte.svg/300px-Bandeira_do_Rio_Grande_do_Norte.svg.png';
    
    return uf ? `https://flagcdn.com/w160/br-${uf.toLowerCase()}.png` : '';
  };

  const handleImgError = (event, info, type) => {
    if (type === 'partido') {
      const partido = (info.partido || "").trim().toUpperCase();
      const fallback = PARTIDO_LOGOS_FALLBACK[partido];
      if (fallback && event.target.src !== fallback) {
        event.target.src = fallback;
      } else {
        event.target.style.display = 'none';
      }
    } else {
      event.target.style.display = 'none';
    }
  };

  // CONFIGURAÇÃO DOS GRÁFICOS
  const getTimelineOption = () => {
    if (!data || !data.timeline || data.timeline.length === 0) return {};
    return {
      title: { 
        text: 'Crescimento Acumulado do Gabinete', 
        textStyle: { fontFamily: 'Montserrat', color: COLORS.AZUL, fontSize: 16 },
        left: 'center'
      },
      tooltip: { 
        trigger: 'axis',
        formatter: (params) => {
          const item = params[0];
          return `<div style="font-family: Montserrat;">
            <b>${item.name}</b><br/>
            <span style="color:${COLORS.VERDE}">●</span> Equipe Total: <b>${item.value} assessores</b>
          </div>`;
        }
      },
      grid: { bottom: '15%', left: '10%', right: '5%' },
      xAxis: { 
        type: 'category', 
        data: data.timeline.map(t => t.mes_ano),
        axisLabel: { 
          fontFamily: 'Roboto Mono', 
          fontSize: 10,
          rotate: 45
        }
      },
      yAxis: { type: 'value', minInterval: 1 },
      series: [
        {
          data: data.timeline.map(t => t.total_acumulado),
          type: 'line',
          smooth: true,
          symbolSize: 8,
          areaStyle: { 
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [{ offset: 0, color: COLORS.VERDE }, { offset: 1, color: 'rgba(0, 151, 57, 0.1)' }]
            }
          },
          itemStyle: { color: COLORS.VERDE },
          lineStyle: { width: 3, type: 'dashed' }
        }
      ]
    };
  };

  return (
    <Box sx={{ flexGrow: 1, backgroundColor: '#F3F6FA', p: 3 }}>
      {/* TEXTO DE ABERTURA */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 800, color: COLORS.AZUL, fontFamily: 'Montserrat', mb: 1 }}>
          Raio-X da Estrutura de Gabinete
        </Typography>
        <Typography variant="body1" color="textSecondary" sx={{ maxWidth: 900, lineHeight: 1.6 }}>
          Nesta ferramenta você pode investigar e auditar a estrutura completa da equipe de qualquer parlamentar em exercício. 
          Descubra o tamanho do gabinete, identifique assessores comissionados, acesse a remuneração transparente e analise a evolução das contratações ao longo do mandato. 
          Utilize os filtros abaixo para pesquisar um deputado e revelar a ficha fotográfica e salarial da sua base operacional.
        </Typography>
      </Box>

      <FilterSelector
        requireSelection={true}
        requireAll={true} 
        onFiltersChange={handleFilterChange}
        fields={['estado', 'partido', 'parlamentar']}
        useCurrentParty={true}
      />

      <Box sx={{ mb: 4, display: 'flex', justifyContent: 'center' }}>
        <Button 
          variant="contained" 
          onClick={fetchData} 
          disabled={loading || filtros.estado === 'Todos' || filtros.partido === 'Todos' || filtros.parlamentar === 'Todos' || !filtros.parlamentar}
          startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <SearchIcon />}
          sx={{ 
            backgroundColor: COLORS.VERDE, 
            '&:hover': { backgroundColor: '#007a2d' }, 
            borderRadius: '50px', 
            height: '56px',
            px: 6,
            fontWeight: 'bold'
          }}
        >
          {loading ? 'Analisando...' : 'Executar Análise de Assessores'}
        </Button>
      </Box>

      {/* CABEÇALHO DO PARLAMENTAR (FICHA) */}
      {parlamentarInfo && (
        <Paper elevation={3} sx={{ p: 3, mb: 4, borderRadius: 4, backgroundColor: 'white', border: `1px solid ${COLORS.CINZA_CLARO}` }}>
          <Grid container spacing={3} alignItems="center">
            <Grid item>
              <Avatar 
                src={parlamentarInfo.urlFoto} 
                sx={{ width: 120, height: 120, border: `4px solid ${COLORS.VERDE}`, boxShadow: '0 4px 20px rgba(0,0,0,0.1)' }}
              >
                {parlamentarInfo.nome?.charAt(0)}
              </Avatar>
            </Grid>
            <Grid item xs={12} md={7}>
              <Box>
                <Typography variant="h3" fontWeight="bold" sx={{ color: COLORS.AZUL, letterSpacing: '-0.5px' }}>
                  {parlamentarInfo.nome}
                </Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 2 }}>
                  <Chip
                    avatar={<Avatar src={getPartidoLogo(parlamentarInfo)} />}
                    label={parlamentarInfo.partido}
                    sx={{
                      bgcolor: '#E8F5E9',
                      color: '#2E7D32',
                      fontWeight: 'bold',
                      px: 0.5,
                      fontSize: '0.9rem'
                    }}
                  />
                  <Chip
                    avatar={<Avatar src={getEstadoLogo(parlamentarInfo)} />}
                    label={parlamentarInfo.uf}
                    sx={{
                      bgcolor: '#E3F2FD',
                      color: '#1565C0',
                      fontWeight: 'bold',
                      px: 0.5,
                      fontSize: '0.9rem'
                    }}
                  />
                </Box>
                <Typography variant="body1" sx={{ mt: 1, color: '#444', fontWeight: 600 }}>
                  Análise de Rubrica: 👥 Estrutura de Gabinete
                </Typography>
              </Box>
            </Grid>

            <Grid item xs={12} md={3} sx={{ display: 'flex', justifyContent: { xs: 'center', md: 'flex-end' }, alignItems: 'center' }}>
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                <Box
                  component="img"
                  src={getPartidoLogo(parlamentarInfo)}
                  onError={(e) => handleImgError(e, parlamentarInfo, 'partido')}
                  alt="Logo Partido"
                  sx={{
                    height: 70,
                    width: 'auto',
                    maxWidth: 140,
                    objectFit: 'contain',
                    filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))'
                  }}
                />
                <Box
                  component="img"
                  src={getEstadoLogo(parlamentarInfo)}
                  onError={(e) => handleImgError(e, parlamentarInfo, 'estado')}
                  alt="Bandeira Estado"
                  sx={{
                    height: 40,
                    width: 'auto',
                    borderRadius: '4px',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.15)'
                  }}
                />
              </Box>
            </Grid>
          </Grid>
        </Paper>
      )}

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 10 }}>
          <CircularProgress sx={{ color: COLORS.VERDE }} />
        </Box>
      )}

      {data && !loading && (data.metricas.qtd_assessores > 0 ? (
        <Grid container spacing={3}>
          {/* CARDS DE MÉTRICAS */}
          <Grid item xs={12} md={4}>
            <Card sx={{ height: '100%', borderRadius: 4, boxShadow: '0 8px 32px rgba(0,0,0,0.05)', borderLeft: `6px solid ${COLORS.AZUL}` }}>
              <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Avatar sx={{ bgcolor: COLORS.AZUL + '15', color: COLORS.AZUL }}>
                  <WalletIcon />
                </Avatar>
                <Box>
                  <Typography variant="caption" color="textSecondary">Folha Mensal (Líquida)</Typography>
                  <Typography variant="h5" sx={{ fontFamily: 'Roboto Mono', fontWeight: 600, color: COLORS.AZUL }}>
                    {formatCurrency(data.metricas.total_mensal)}
                  </Typography>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} md={4}>
            <Card sx={{ 
              height: '100%',
              borderRadius: 4, 
              boxShadow: '0 8px 32px rgba(0,0,0,0.05)', 
              borderLeft: `6px solid ${data.metricas.qtd_assessores > data.media_geral ? COLORS.AMARELO : COLORS.VERDE}` 
            }}>
              <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Avatar sx={{ bgcolor: (data.metricas.qtd_assessores > data.media_geral ? COLORS.AMARELO : COLORS.VERDE) + '15', color: (data.metricas.qtd_assessores > data.media_geral ? COLORS.AZUL : COLORS.VERDE) }}>
                  <GroupsIcon />
                </Avatar>
                <Box>
                  <Typography variant="caption" color="textSecondary">Total de Assessores</Typography>
                  <Typography variant="h5" sx={{ fontFamily: 'Roboto Mono', fontWeight: 600, color: COLORS.AZUL }}>
                    {data.metricas.qtd_assessores}
                  </Typography>
                  <Typography variant="caption" sx={{ color: data.metricas.qtd_assessores > data.media_geral ? '#ED8B00' : COLORS.VERDE, fontWeight: 'bold' }}>
                    {data.metricas.qtd_assessores > data.media_geral ? '⚠ Acima' : '✅ Abaixo'} da média (Câmara: {data.media_geral})
                  </Typography>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} md={4}>
            <Card sx={{ height: '100%', borderRadius: 4, boxShadow: '0 8px 32px rgba(0,0,0,0.05)', borderLeft: `6px solid ${COLORS.AZUL_CLARO}` }}>
              <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Avatar sx={{ bgcolor: COLORS.AZUL_CLARO + '15', color: COLORS.AZUL_CLARO }}>
                  <TrendingUpIcon />
                </Avatar>
                <Box>
                  <Typography variant="caption" color="textSecondary">Média Salarial</Typography>
                  <Typography variant="h5" sx={{ fontFamily: 'Roboto Mono', fontWeight: 600, color: COLORS.AZUL }}>
                    {formatCurrency(data.metricas.media_salarial)}
                  </Typography>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} md={12}>
            <Paper sx={{ p: 3, borderRadius: 4, minHeight: 400, boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
              <ReactECharts option={getTimelineOption()} style={{ height: '350px' }} />
            </Paper>
          </Grid>

          {/* LISTA DE ASSESSORES EM FORMATO DE CARDS */}
          <Grid item xs={12}>
            <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Typography variant="h6" sx={{ fontFamily: 'Montserrat', fontWeight: 600, color: COLORS.AZUL }}>
                Equipe de Gabinete ({data.lista.length} pessoas)
              </Typography>
              <TextField 
                size="small"
                placeholder="Filtrar equipe..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                sx={{ width: 300, bgcolor: 'white', borderRadius: 2 }}
                InputProps={{ startAdornment: <SearchIcon sx={{ color: 'gray', mr: 1 }} /> }}
              />
            </Box>
            
            <Grid container spacing={2} alignItems="stretch">
              {data.lista
                .filter(a => a.nome_assessor.toLowerCase().includes(searchTerm.toLowerCase()) || a.cargo.toLowerCase().includes(searchTerm.toLowerCase()))
                .map((assessor, idx) => (
                <Grid item xs={12} sm={6} md={4} key={idx} sx={{ display: 'flex' }}>
                  <Card sx={{ 
                    borderRadius: 3, 
                    width: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    transition: '0.3s', 
                    '&:hover': { transform: 'translateY(-5px)', boxShadow: '0 12px 40px rgba(0,0,0,0.1)' } 
                  }}>
                    <CardContent sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                        <Avatar sx={{ bgcolor: COLORS.AZUL, width: 48, height: 48 }}>
                          <GroupsIcon />
                        </Avatar>
                        <Box sx={{ textAlign: 'right' }}>
                          <Chip 
                            label={assessor.origem || 'Comissionado'} 
                            size="small" 
                            variant="outlined"
                            sx={{ color: COLORS.VERDE, borderColor: COLORS.VERDE, fontWeight: 'bold', mb: 1 }} 
                          />
                          <Typography variant="caption" display="block" color="textSecondary">Admissão: <b>{assessor.data_admissao}</b></Typography>
                        </Box>
                      </Box>
                      
                      <Typography variant="subtitle1" sx={{ fontWeight: 700, color: COLORS.AZUL, mb: 0.5 }}>
                        {assessor.nome_assessor}
                      </Typography>
                      <Typography variant="body2" color="textSecondary" sx={{ mb: 2, flexGrow: 1 }}>
                        {assessor.cargo}
                      </Typography>
                      
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', pt: 2, borderTop: '1px solid #f0f0f0', mt: 'auto' }}>
                        <Box>
                          <Typography variant="caption" color="textSecondary">Salário Líquido</Typography>
                          <Typography variant="subtitle1" sx={{ fontFamily: 'Roboto Mono', fontWeight: 600, color: COLORS.VERDE }}>
                            {formatCurrency(assessor.salario_liquido)}
                          </Typography>
                        </Box>
                        <Tooltip title="Ver Transparência">
                          <IconButton 
                            component="a" 
                            href={assessor.link_remuneracao} 
                            target="_blank" 
                            sx={{ bgcolor: '#F0F7F2', '&:hover': { bgcolor: '#E3F0E8' } }}
                          >
                            <LaunchIcon sx={{ color: COLORS.VERDE }} />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          </Grid>
        </Grid>
      ) : (
        <Paper sx={{ p: 5, textAlign: 'center', borderRadius: 4, mt: 4 }}>
          <WarningIcon sx={{ fontSize: 60, color: COLORS.AMARELO, mb: 2 }} />
          <Typography variant="h6" color="textSecondary">
            Nenhum assessor encontrado para este parlamentar.
          </Typography>
          <Typography variant="body2" color="textSecondary">
            Isso pode ocorrer se o parlamentar não estiver em exercício no mandato atual ou se for um suplente.
          </Typography>
        </Paper>
      ))}
      
      {!data && !loading && (
        <Box sx={{ textAlign: 'center', py: 15, opacity: 0.5 }}>
          <FilterListIcon sx={{ fontSize: 80, mb: 2, color: COLORS.AZUL }} />
          <Typography variant="h5" sx={{ fontFamily: 'Montserrat' }}>
            Utilize os filtros acima para analisar a estrutura de um gabinete.
          </Typography>
        </Box>
      )}
    
      <DataSourceFooter
        sources={[{"label":"Portal da Transparência — Câmara","href":"https://www.camara.leg.br/transparencia/recursos-humanos/servidores","type":"camara"}]}
        note="Dados de servidores e assessores dos gabinetes obtidos do Portal de Transparência da Câmara dos Deputados."
      />
    </Box>
  );
};

// HELPER PARA CORES DE CARGOS
const ColorsForCargo = (cargo) => {
  if (cargo.includes('CHEFE')) return { bg: '#E3F2FD', text: '#1976D2' };
  if (cargo.includes('SECRETÁRIO')) return { bg: '#E8F5E9', text: '#2E7D32' };
  if (cargo.includes('ASSISTENTE')) return { bg: '#FFF3E0', text: '#E65100' };
  return { bg: '#F5F5F5', text: '#616161' };
};

export default Assessores;

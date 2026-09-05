import React, { useState, useEffect, useMemo } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Grid,
  CircularProgress,
  Alert,
  Avatar,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Stack,
  Breadcrumbs,
  Link,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Autocomplete,
  TextField,
  Tooltip
} from '@mui/material';
import {
  Gavel,
  Info,
  NavigateNext,
  Security,
  Groups,
  Business,
  Assessment,
  FilterAlt,
  PlayArrow,
  AttachMoney,
  GppBad,
  VerifiedUser
} from '@mui/icons-material';
import axios from '../config/axios';
import { API_HEADERS, API_BASE_URL } from '../config';
import { useNavigate } from 'react-router-dom';
import ReactECharts from 'echarts-for-react';
import FilterSelector from '../components/FilterSelector';
import { brandColors } from '../utils/chartOptions';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

// Proxy de imagens: evita bloqueio de hotlink do Wikimedia
const proxyImg = (url) => url ? `/api/proxy/imagem?url=${encodeURIComponent(url)}` : null;

// PARTIDO_LOGOS e ESTADO_LOGOS agora vêm do backend (URL_Partido, URL_Estado)
// O proxy abaixo serve como fallback por sigla caso o campo venha nulo
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
  if (info.URL_Partido) return normalizeWikiUrl(info.URL_Partido);
  return PARTIDO_LOGOS_FALLBACK[partido] || '';
};

const getEstadoLogo = (info) => {
  if (!info) return '';
  const estadoUrl = info.URL_Estado || info.bandeira_estado || info.url_estado || info.urlEstado;
  if (estadoUrl) return normalizeWikiUrl(estadoUrl);
  const uf = (info.uf || info.estado || info.sgUF || "").trim().toUpperCase();
  
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
    const fallback = getEstadoLogo(info);
    if (fallback && event.target.src !== fallback) {
      event.target.src = fallback;
    } else {
      event.target.style.display = 'none';
    }
  }
};

const formatCurrency = (value = 0) => {
  const num = Number(value);
  return (isNaN(num) ? 0 : num).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2 });
};

const buildSankeyOptions = (rankingItem, conflitos) => {
  if (!rankingItem || !conflitos || conflitos.length === 0) return {};

  const depName = rankingItem.nome;
  const nodesMap = new Map();
  const linksMap = new Map();

  const wrapText = (text, maxLength = 25) => {
    if (!text) return "";
    const words = String(text).split(" ");
    let line = "";
    let result = "";
    words.forEach(word => {
        if ((line + word).length > maxLength) {
            result += line.trim() + "\n";
            line = word + " ";
        } else {
            line += word + " ";
        }
    });
    return result + line.trim();
  };

  const addNode = (id, displayName, type) => {
    if (!nodesMap.has(id)) {
      let color = brandColors.azul;
      if (type === 'total') color = '#ED8B00'; // Laranja para o Pool de Orçamento
      if (type === 'tema') color = brandColors.azulClaro;
      if (type === 'subtema') color = brandColors.verdeClaro;
      if (type === 'limpo') color = brandColors.verde;   // Verde para o que é seguro
      if (type === 'empresa' || type === 'conflito') color = '#ED8B00'; 
      if (type === 'vinculo') color = brandColors.azul; 

      nodesMap.set(id, { 
        name: id, 
        label: { 
            formatter: wrapText(displayName),
            fontSize: 10,
            color: '#334155'
        },
        itemStyle: { color }
      });
    }
  };

  const addLink = (source, target, value) => {
    if (value <= 0) return;
    const linkId = `${source}->${target}`;
    if (linksMap.has(linkId)) {
      linksMap.get(linkId).value += value;
    } else {
      linksMap.set(linkId, { source, target, value });
    }
  };

  const totalEmpenhado = rankingItem.total_empenhado_mandato || 0;
  // Alteração: "Total Empenhado" -> "Valor da Emenda"
  const totalPoolId = `Valor da Emenda: ${formatCurrency(totalEmpenhado)}`;
  const depId = `Deputado: ${depName}`;
  
  // 1. Início: Deputado -> Pool
  addNode(depId, depName, 'deputado');
  addNode(totalPoolId, `Valor Total da Emenda (Mandato)\n${formatCurrency(totalEmpenhado)}`, 'total');
  addLink(depId, totalPoolId, totalEmpenhado);

  let somaConflitos = 0;
  conflitos.forEach(c => somaConflitos += (c.valor_emenda || 0));
  
  // 2. Fração Limpa: Pool -> Safe
  const fatiaLimpa = Math.max(0, totalEmpenhado - somaConflitos);
  if (fatiaLimpa > 0) {
    const limpoId = "Outras Emendas";
    addNode(limpoId, "Outras Emendas", 'limpo');
    addLink(totalPoolId, limpoId, fatiaLimpa);
  }

  // 3. Caminhos de Conflito (Hierárquico: Pool -> Tema -> Subtema -> Beneficiário -> Sócio -> Vínculo)
  conflitos.forEach(conf => {
    const val = conf.valor_emenda || 0;
    if (val <= 0) return;

    // Explicações: Área (Função) e Sub-Área (Subfunção)
    const temaNodeId = `Área (Função): ${conf.tema || 'Outros'}`;
    const subtemaNodeId = `Sub-Área (Subfunção): ${conf.subfuncao || 'N/A'}`;
    
    addNode(temaNodeId, conf.tema || 'Outros', 'tema');
    addNode(subtemaNodeId, conf.subfuncao || 'N/A', 'subtema');

    // Link: Pool -> Tema -> Subtema
    addLink(totalPoolId, temaNodeId, val);
    addLink(temaNodeId, subtemaNodeId, val);

    if (conf.tipo_fluxo === 'triangulacao') {
      const prefId = `Município Beneficiário: ${conf.nome_recebedor}`;
      const empId = `Empresa Intermediária: ${conf.entidade_intermediaria}`;
      const socioId = `Sócio presente no CNPJ: ${conf.socio_vinc_parlamentar}`;
      const vincId = `Vínculo com Deputado: ${conf.vinculo_com_quem} (${conf.tipo_vinculo})`;

      addNode(prefId, conf.nome_recebedor, 'conflito'); 
      addNode(empId, conf.entidade_intermediaria, 'empresa');
      addNode(socioId, conf.socio_vinc_parlamentar, 'conflito');
      addNode(vincId, vincId, 'vinculo'); // Usando vincId completo para o nó final

      addLink(subtemaNodeId, prefId, val);
      addLink(prefId, empId, val);
      addLink(empId, socioId, val);
      addLink(socioId, vincId, val);
    } else {
      const empId = `Beneficiário da Emenda: ${conf.nome_recebedor}`;
      addNode(empId, conf.nome_recebedor, 'empresa');
      addLink(subtemaNodeId, empId, val);

      // Derivação de Sócios (2ª e 3ª Derivada)
      const socios = conf.socios_detalhe || [];
      if (socios.length > 0) {
        socios.forEach(soc => {
          const sId = `Sócio presente no CNPJ: ${soc.nome}`;
          addNode(sId, soc.nome, 'conflito');
          addLink(empId, sId, val / socios.length); 
          
          if (soc.nome === conf.socio_vinc_parlamentar) {
              const vincIdFinal = `Vínculo com Deputado: ${conf.vinculo_com_quem} (${conf.tipo_vinculo})`;
              addNode(vincIdFinal, vincIdFinal, 'vinculo');
              addLink(sId, vincIdFinal, val / socios.length);
          }
        });
      } else if (conf.socio_vinc_parlamentar) {
        const sId = `Sócio presente no CNPJ: ${conf.socio_vinc_parlamentar}`;
        const vincId = `Vínculo com Deputado: ${conf.vinculo_com_quem} (${conf.tipo_vinculo})`;
        addNode(sId, conf.socio_vinc_parlamentar, 'conflito');
        addNode(vincId, vincId, 'vinculo');
        addLink(empId, sId, val);
        addLink(sId, vincId, val);
      }
    }
  });

  return {
    tooltip: { 
        trigger: 'item', 
        formatter: (params) => {
            if (params.dataType === 'node') {
                return `<b>${params.name}</b>`;
            }
            return `${params.data.source} ➔ ${params.data.target}<br/><b>${formatCurrency(params.data.value)}</b>`;
        }
    },
    series: [
      {
        type: 'sankey',
        layout: 'none',
        emphasis: { focus: 'adjacency' },
        nodeAlign: 'justify',
        nodeWidth: 20,
        nodeGap: 10,
        data: Array.from(nodesMap.values()),
        links: Array.from(linksMap.values()),
        lineStyle: { color: 'gradient', curveness: 0.5 },
        label: {
          color: brandColors.azul,
          fontFamily: 'Inter, sans-serif',
          fontSize: 10,
          fontWeight: 600,
          position: 'right'
        }
      }
    ]
  };
};

const ConflitosEmendas = () => {
  const navigate = useNavigate();
  const [data, setData] = useState({ ranking: [], detalhes: {} });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [sancoesData, setSancoesData] = useState({ resumo: { total_alertas: 0, total_ceis: 0, total_cepim: 0 }, alertas: [] });
  const [sancoesLoading, setSancoesLoading] = useState(false);
  const [sancoesAviso, setSancoesAviso] = useState(null);

  const [filters, setFilters] = useState({ estado: '', partido: '', nome: '' });
  const [hasSearched, setHasSearched] = useState(false);


  // "Todos" é o valor sentinela do FilterSelector para "sem filtro" — não deve virar query param
  const valorFiltro = (v) => (v && v !== 'Todos' ? v : null);

  const fetchConflitos = async () => {
    try {
      setLoading(true);
      setHasSearched(true);

      const params = new URLSearchParams();
      if (valorFiltro(filters.uf)) params.append('uf', valorFiltro(filters.uf));
      if (valorFiltro(filters.partido)) params.append('partido', valorFiltro(filters.partido));
      if (valorFiltro(filters.nome)) params.append('nome', valorFiltro(filters.nome));

      const url = `${API_BASE_URL}/api/emendas/conflitos-ranking?${params.toString()}`;
      console.log('🔍 Buscando conflitos:', url);

      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error(`Erro na API: ${response.status}`);

      const result = await response.json();
      setData(result);
      setError(null);
    } catch (err) {
      console.error('Erro ao buscar conflitos:', err);
      setError('Não foi possível carregar os dados de conformidade.');
    } finally {
      setLoading(false);
    }
  };

  // Alertas de sanções (CEIS/CEPIM — dados abertos da CGU) cruzados com emendas/contratos
  const fetchSancoes = async () => {
    try {
      setSancoesLoading(true);
      const params = new URLSearchParams();
      if (valorFiltro(filters.uf)) params.append('uf', valorFiltro(filters.uf));
      if (valorFiltro(filters.partido)) params.append('partido', valorFiltro(filters.partido));
      if (valorFiltro(filters.nome)) params.append('nome', valorFiltro(filters.nome));

      const url = `${API_BASE_URL}/api/integridade/alertas-sancoes?${params.toString()}`;
      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error(`Erro na API: ${response.status}`);

      const result = await response.json();
      setSancoesData(result);
      setSancoesAviso(result.aviso || null);
    } catch (err) {
      console.error('Erro ao buscar alertas de sanções CEIS/CEPIM:', err);
      // Falha silenciosa: esta seção é um complemento e não deve travar a página principal
    } finally {
      setSancoesLoading(false);
    }
  };

  const handleFilterChange = (newFilters) => {
    setFilters({
      uf: newFilters.estado,
      partido: newFilters.partido,
      nome: newFilters.parlamentar
    });
  };

  const handleExecute = () => {
    fetchConflitos();
    fetchSancoes();
  };

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      {/* Header e Breadcrumbs */}
      <Box sx={{ mb: 4 }}>
        <Breadcrumbs separator={<NavigateNext fontSize="small" />} aria-label="breadcrumb" sx={{ mb: 2 }}>
          <Link underline="hover" color="inherit" onClick={() => navigate('/')} sx={{ cursor: 'pointer' }}>
            Home
          </Link>
          <Typography color="text.primary">Conflito em Emendas</Typography>
        </Breadcrumbs>
        
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
          <Gavel sx={{ fontSize: 40, color: brandColors.azul }} />
          <Typography variant="h3" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
            Radar de Conformidade
          </Typography>
        </Box>
        <Typography variant="h6" sx={{ color: brandColors.cinza, fontWeight: 'normal' }}>
          Auditoria forense automatizada de vínculos societários em emendas parlamentares
        </Typography>
      </Box>

      <FilterSelector
        onFiltersChange={handleFilterChange}
        fields={['estado', 'partido', 'parlamentar']}
        sourceType="conformidade"
        requireSelection={true}
        requireAll={true}
      />

      <Box sx={{ mb: 4, display: 'flex', justifyContent: 'center' }}>
        <Button
          variant="contained"
          size="large"
          startIcon={<PlayArrow />}
          onClick={handleExecute}
          disabled={loading || (!filters.uf && !filters.partido && !filters.nome)}
          sx={{ 
            bgcolor: brandColors.verde, 
            '&:hover': { bgcolor: '#007A2E' },
            fontWeight: 'bold',
            borderRadius: '12px',
            px: 6,
            height: '56px'
          }}
        >
          Executar Auditoria de Conflitos
        </Button>
      </Box>

      {!hasSearched ? (
        <Box sx={{ py: 10, textAlign: 'center', bgcolor: '#F8FAFC', borderRadius: '24px', border: '2px dashed #E0E0E0' }}>
          <Assessment sx={{ fontSize: 60, color: brandColors.cinza, mb: 2, opacity: 0.5 }} />
          <Typography variant="h5" sx={{ color: brandColors.azul, fontWeight: 'bold', mb: 1 }}>
            Pronto para auditar?
          </Typography>
          <Typography variant="body1" sx={{ color: brandColors.cinza }}>
            Selecione filtros acima e clique em <b>Executar Filtro</b> para iniciar a varredura forense.
          </Typography>
        </Box>
      ) : (
        <Box>
          {/* Alerta de Metodologia / LGPD */}
          <Alert 
            severity="warning" 
            variant="filled"
            sx={{ 
              mb: 4, 
              borderRadius: '24px', 
              backgroundColor: '#ED8B00',
              p: 3,
              boxShadow: '0 8px 16px rgba(237, 139, 0, 0.2)'
            }}
            icon={<Info fontSize="large" sx={{ color: '#FFF' }} />}
          >
            <Typography variant="h6" sx={{ fontWeight: 'bold', mb: 0.5, color: '#FFF' }}>
              IMPORTANTE: NOTA DE CONFORMIDADE & LGPD
            </Typography>
            <Typography variant="body1" sx={{ color: '#FFF', opacity: 0.95, lineHeight: 1.5 }}>
              Este painel identifica matches entre <strong>nomes civis</strong> de sócios de empresas beneficiárias e a base de parlamentares/assessores. 
              Devido às restrições da LGPD (ausência de CPF público), homônimos são possíveis. 
              Estes pontos devem ser tratados como <strong>Risco Forense</strong> para investigação manual, não evidência de crime.
            </Typography>
          </Alert>

          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 10 }}>
              <CircularProgress size={60} thickness={4} sx={{ color: brandColors.verde }} />
            </Box>
          ) : error ? (
            <Alert severity="error" sx={{ borderRadius: '12px' }}>{error}</Alert>
          ) : data.ranking.length === 0 ? (
            <Paper sx={{ p: 4, textAlign: 'center', borderRadius: '16px' }}>
              <Typography variant="h6" color="text.secondary">
                Nenhum registro de conflito encontrado para os filtros selecionados.
              </Typography>
            </Paper>
          ) : (
            <Grid container spacing={4}>
          <Grid item xs={12}>
            {data.ranking.map((dep, idx) => (
              <Paper 
                key={idx} 
                sx={{ 
                  p: 0, 
                  mb: 6, 
                  borderRadius: '24px', 
                  overflow: 'hidden',
                  border: '1px solid #E0E0E0',
                  boxShadow: '0 4px 20px rgba(0,0,0,0.05)'
                }}
              >
                {/* Cabeçalho do Parlamentar */}
                <Paper 
                  elevation={3} 
                  sx={{ 
                    p: 4, 
                    mb: 4, 
                    bgcolor: '#FFFFFF', 
                    borderRadius: 4, 
                    border: '1px solid #e0e0e0',
                    transition: 'transform 0.2s, shadow 0.2s',
                    '&:hover': { transform: 'translateY(-4px)', boxShadow: 6 }
                  }}
                >
                  <Grid container spacing={3} alignItems="center">
                    
                    {/* Foto do Parlamentar */}
                    <Grid item xs={12} md={2} sx={{ display: 'flex', justifyContent: 'center' }}>
                      <Avatar
                        src={dep.ultimoStatus_urlFoto}
                        referrerPolicy="no-referrer"
                        sx={{
                          width: 140,
                          height: 140,
                          border: `4px solid ${brandColors.verde}`,
                          boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                        }}
                      >
                        {dep.nome ? dep.nome[0] : '?'}
                      </Avatar>
                    </Grid>

                    {/* Nome e Selos */}
                    <Grid item xs={12} md={10}>
                      <Box>
                        <Typography 
                          variant="h3" 
                          fontWeight="bold" 
                          sx={{ 
                            color: brandColors.azul, 
                            letterSpacing: '-0.5px',
                            fontSize: { xs: '1.8rem', md: '2.5rem' }
                          }}
                        >
                          {dep.nome}
                        </Typography>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mt: 2 }}>
                          <Tooltip title={dep.partido || ''}>
                            <Box
                              component="img"
                              src={getPartidoLogo(dep)}
                              onError={(e) => handleImgError(e, dep, 'partido')}
                              alt="Logo partido"
                              sx={{ maxHeight: 45, maxWidth: 80, objectFit: 'contain' }}
                            />
                          </Tooltip>
                          <Tooltip title={dep.uf || ''}>
                            <Box
                              component="img"
                              src={getEstadoLogo(dep)}
                              onError={(e) => handleImgError(e, dep, 'estado')}
                              alt="Bandeira estado"
                              sx={{ maxHeight: 30, maxWidth: 50, objectFit: 'contain', boxShadow: '0 2px 4px rgba(0,0,0,0.1)', borderRadius: '2px' }}
                            />
                          </Tooltip>
                        </Box>
                        <Typography variant="body1" sx={{ mt: 2, color: '#444', fontWeight: 600 }}>
                          🛑 Potenciais Conflitos: {dep.total_conflitos} {dep.total_conflitos === 1 ? 'Red Flag identificada' : 'Red Flags identificadas'}
                        </Typography>
                      </Box>
                    </Grid>

                  </Grid>
                </Paper>

                {/* Tabela Detalhada de Conflitos */}
                <Box sx={{ p: 2 }}>
                  <TableContainer component={Box}>
                    <Table>
                      <TableHead sx={{ bgcolor: '#FDFDFD' }}>
                        <TableRow>
                          <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Empresa Beneficiária</TableCell>
                          <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Sócio Identificado</TableCell>
                          <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Vínculo Detectado</TableCell>
                          <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }} align="right">Valor Emenda</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {data.detalhes[dep.nome]?.map((conf, cIdx) => (
                          <TableRow key={cIdx} sx={{ '&:hover': { bgcolor: '#F1F5F9' } }}>
                            <TableCell>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Business sx={{ color: brandColors.cinza, fontSize: 20 }} />
                                <Box>
                                  <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{conf.nome_recebedor}</Typography>
                                  <Typography variant="caption" color="text.secondary">Código: {conf.codigo_emenda}</Typography>
                                </Box>
                              </Box>
                            </TableCell>
                            <TableCell>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Groups sx={{ color: brandColors.cinza, fontSize: 20 }} />
                                <Typography variant="body2">{conf.socio_vinc_parlamentar}</Typography>
                              </Box>
                            </TableCell>
                            <TableCell>
                              <Chip 
                                size="small" 
                                icon={conf.tipo_vinculo === 'POLITICO' ? <Security /> : (conf.tipo_vinculo === 'DOADOR' ? <AttachMoney /> : <Groups />)}
                                label={conf.vinculo_com_quem}
                                variant="outlined"
                                sx={{ 
                                  fontWeight: 'bold',
                                  borderColor: conf.tipo_vinculo === 'POLITICO' ? '#EF4444' : (conf.tipo_vinculo === 'DOADOR' ? brandColors.azul : '#F59E0B'),
                                  color: conf.tipo_vinculo === 'POLITICO' ? '#B91C1C' : (conf.tipo_vinculo === 'DOADOR' ? brandColors.azul : '#92400E'),
                                  bgcolor: conf.tipo_vinculo === 'POLITICO' ? '#FEF2F2' : (conf.tipo_vinculo === 'DOADOR' ? '#E3F2FD' : '#FFFBEB')
                                }}
                              />
                            </TableCell>
                            <TableCell align="right">
                              <Typography variant="body2" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                                {formatCurrency(conf.valor_emenda)}
                              </Typography>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
                
                {/* Gráfico Sankey: Rastreio de Emendas */}
                {data.detalhes[dep.nome] && data.detalhes[dep.nome].length > 0 && (
                  <Box sx={{ p: 2, borderTop: '1px solid #E0E0E0' }}>
                    <Typography variant="h6" sx={{ fontWeight: 'bold', color: brandColors.azul, mb: 2 }}>
                      Fluxo do Capital (Sankey)
                    </Typography>
                    <Box sx={{ p: 2, bgcolor: '#FFF', borderRadius: '12px', border: '1px solid #E0E0E0' }}>
                      <ReactECharts
                        option={buildSankeyOptions(dep, data.detalhes[dep.nome])}
                        style={{ height: '400px', width: '100%' }}
                        opts={{ renderer: 'svg' }}
                      />
                    </Box>
                  </Box>
                )}

                <Box sx={{ p: 2, textAlign: 'center', bgcolor: '#F8FAFC' }}>
                   <Button 
                    variant="text" 
                    size="small" 
                    startIcon={<Assessment />}
                    onClick={() => navigate(`/gastos/emendas`, { state: { parlamentar: dep.nome, partido: dep.partido, estado: dep.uf } })}
                    sx={{ color: brandColors.verde, fontWeight: 'bold' }}
                   >
                     Ver Auditoria Completa do Parlamentar
                   </Button>
                </Box>
              </Paper>
            ))}
          </Grid>
        </Grid>
      )}
    </Box>
  )}

      {/* Alertas de Integridade — Sanções CGU (CEIS/CEPIM) cruzadas com emendas/contratos */}
      {hasSearched && (
        <Paper
          sx={{
            mt: 6,
            p: 0,
            borderRadius: '24px',
            overflow: 'hidden',
            border: '1px solid #E0E0E0',
            boxShadow: '0 4px 20px rgba(0,0,0,0.05)'
          }}
        >
          <Box sx={{ p: 4, pb: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
              <GppBad sx={{ fontSize: 32, color: '#B91C1C' }} />
              <Typography variant="h5" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                Alertas de Integridade — Sanções CGU (CEIS/CEPIM)
              </Typography>
            </Box>
            <Typography variant="body2" sx={{ color: brandColors.cinza }}>
              Cruzamento entre o <strong>CEIS</strong> (empresas inidôneas/suspensas) e o <strong>CEPIM</strong> (ONGs impedidas de convênio) —
              bases de dados abertos publicadas pela própria <strong>CGU</strong> no Portal da Transparência — com emendas parlamentares e
              contratos públicos, identificando casos em que a verba foi destinada enquanto a entidade estava sancionada.
            </Typography>
          </Box>

          {sancoesLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
              <CircularProgress size={40} thickness={4} sx={{ color: brandColors.verde }} />
            </Box>
          ) : sancoesAviso ? (
            <Box sx={{ p: 4, pt: 0 }}>
              <Alert severity="info" sx={{ borderRadius: '12px' }}>{sancoesAviso}</Alert>
            </Box>
          ) : sancoesData.alertas.length === 0 ? (
            <Box sx={{ px: 4, pb: 4, display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <VerifiedUser sx={{ color: brandColors.verde }} />
              <Typography variant="body1" sx={{ color: brandColors.cinza }}>
                Nenhum alerta de sanção encontrado para os filtros selecionados.
              </Typography>
            </Box>
          ) : (
            <Box sx={{ px: 2, pb: 2 }}>
              <Stack direction="row" spacing={2} sx={{ px: 2, mb: 2 }}>
                <Chip label={`${sancoesData.resumo.total_alertas} alertas no total`} sx={{ fontWeight: 'bold' }} />
                <Chip label={`${sancoesData.resumo.total_ceis} via CEIS`} variant="outlined" />
                <Chip label={`${sancoesData.resumo.total_cepim} via CEPIM`} variant="outlined" />
              </Stack>
              <TableContainer component={Box}>
                <Table>
                  <TableHead sx={{ bgcolor: '#FDFDFD' }}>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Base</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Entidade Sancionada</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>CNPJ</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Parlamentar</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Data do Repasse</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Período da Sanção</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {sancoesData.alertas.map((alerta, idx) => (
                      <TableRow key={idx} sx={{ '&:hover': { bgcolor: '#F1F5F9' } }}>
                        <TableCell>
                          <Chip
                            size="small"
                            label={alerta.tipo}
                            sx={{
                              fontWeight: 'bold',
                              bgcolor: alerta.tipo?.startsWith('CEIS') ? '#FEF2F2' : '#FFFBEB',
                              color: alerta.tipo?.startsWith('CEIS') ? '#B91C1C' : '#92400E'
                            }}
                          />
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{alerta.nome_entidade}</Typography>
                          <Typography variant="caption" color="text.secondary">{alerta.detalhes}</Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">{alerta.cnpj}</Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">{alerta.parlamentar || '—'}</Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">{alerta.data_evento || '—'}</Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {alerta.sancao_inicio || '—'} {alerta.sancao_fim ? `até ${alerta.sancao_fim}` : '(vigente)'}
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}
        </Paper>
      )}

      {/* Footer LGPD */}
      <Box sx={{ mt: 6, p: 3, bgcolor: '#EEF4FB', borderRadius: '16px' }}>
        <Typography variant="caption" sx={{ color: brandColors.cinza, display: 'block', textAlign: 'center' }}>
          ⚠️ Base de dados integrada do Portal da Transparência, Receita Federal e Câmara dos Deputados. 
          O uso destas informações deve respeitar os critérios de presunção de inocência e as normas da LGPD.
        </Typography>
      </Box>
    
      <DataSourceFooter
        sources={[{"label":"CEAP — Câmara dos Deputados","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Despesas","type":"camara"},{"label":"Emendas — Portal da Câmara","href":"https://dadosabertos.camara.leg.br","type":"camara"},{"label":"CNPJ — Receita Federal","href":"https://www.gov.br/receitafederal","type":"receita"},{"label":"CEIS/CEPIM — CGU","href":"https://portaldatransparencia.gov.br/sancoes","type":"cgu"}]}
        note="Cruzamento entre gastos CEAP, emendas parlamentares, quadro societário de empresas beneficiadas (CNPJ/Receita Federal) e as bases de sanções CEIS/CEPIM publicadas pela CGU."
      />
    </Container>
  );
};

export default ConflitosEmendas;

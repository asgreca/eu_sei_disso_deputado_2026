import React, { useState, useEffect, useRef } from 'react';
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
  CircularProgress,
  Alert,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material';
import axios from '../config/axios';
import { API_HEADERS } from '../config';
import FilterSelector from '../components/FilterSelector';
import EChartWrapper from '../components/EChartWrapper';
import { brandColors, createBarChartOption } from '../utils/chartOptions';

const MapaEleitoral = () => {
  const [filters, setFilters] = useState({
    estado: '',
    partido: '',
    parlamentar: ''
  });
  
  const [analysisData, setAnalysisData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const mapContainerRef = useRef(null);

  const handleFilterChange = (newFilters) => {
    setFilters(prev => {
      const updated = { ...prev, ...newFilters };
      if (newFilters.parlamentar !== undefined) {
        updated.parlamentar = newFilters.parlamentar;
      }
      return updated;
    });
  };

  const handleAnalyze = async () => {
    if (!filters.parlamentar) {
      setError('Selecione um parlamentar para visualizar o mapa eleitoral.');
      return;
    }

    setLoading(true);
    setError(null);
    setAnalysisData(null);

    try {
      // O endpoint precisa do nome do parlamentar na URL
      const nomeParlamentar = encodeURIComponent(filters.parlamentar);
        const response = await axios.get(`/api/mapa-eleitoral/votos/${nomeParlamentar}`, {
          headers: API_HEADERS,
          timeout: 180000,
          params: {
            estado: filters.estado || undefined,
            partido: filters.partido || undefined,
          },
        });
      
      if (response.data.error) {
        setError(response.data.error);
        return;
      }

      setAnalysisData(response.data);
      
      // Carregar mapa Folium se disponível
      if (response.data.mapa_html) {
        setTimeout(() => {
          renderFoliumMap(response.data.mapa_html);
        }, 100);
      } else {
        const pontosMapa = Array.isArray(response.data?.zonas) && response.data.zonas.length > 0
          ? response.data.zonas
          : response.data?.municipios;
        if (pontosMapa && pontosMapa.length > 0) {
          setTimeout(() => {
            loadMap(pontosMapa);
          }, 500);
        }
      }
    } catch (err) {
      setError('Erro ao executar análise: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const renderFoliumMap = (html) => {
    if (!mapContainerRef.current) return;

    mapContainerRef.current.innerHTML = html;

    const scriptElements = Array.from(mapContainerRef.current.querySelectorAll('script'));
    scriptElements.forEach((oldScript) => {
      const newScript = document.createElement('script');
      if (oldScript.src) {
        newScript.src = oldScript.src;
      } else {
        newScript.textContent = oldScript.textContent;
      }
      newScript.async = false;
      oldScript.parentNode?.replaceChild(newScript, oldScript);
    });
  };

  const loadMap = (municipios) => {
    if (!mapContainerRef.current || !municipios || municipios.length === 0) return;

    // Criar um mapa simples com estatísticas
    const mapDiv = document.createElement('div');
    mapDiv.style.cssText = `
      width: 100%;
      height: 600px;
      background: linear-gradient(135deg, #009739 0%, #003366 100%);
      border-radius: 12px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: white;
      position: relative;
      overflow: hidden;
    `;

    const title = document.createElement('h2');
    title.textContent = '🗺️ Mapa Eleitoral - Redutos';
    title.style.cssText = `
      margin: 0 0 30px 0;
      font-size: 2rem;
      text-align: center;
      text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
    `;

    const stats = document.createElement('div');
    stats.style.cssText = `
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 20px;
      width: 100%;
      max-width: 900px;
      padding: 0 20px;
    `;

    const totalVotos = municipios.reduce((sum, m) => sum + (m.total_votos || 0), 0);
    const municipiosUnicos = municipios.length;
    const municipioMaisVotos = municipios[0];
    const totalSessoes = municipios.reduce((sum, m) => sum + (m.sessoes || 0), 0);

    const statistics = [
      { label: 'Municípios', valor: municipiosUnicos, cor: brandColors.verde },
      { label: 'Total de Votos', valor: (totalVotos || 0).toLocaleString('pt-BR'), cor: '#4F81BD' },
      { label: 'Sessões Eleitorais', valor: (totalSessoes || 0).toLocaleString('pt-BR'), cor: '#FFF81C' },
      { label: 'Maior Reduto', valor: municipioMaisVotos?.municipio || 'N/A', cor: '#66BB6A' }
    ];

    statistics.forEach(stat => {
      const statDiv = document.createElement('div');
      statDiv.style.cssText = `
        background: rgba(255,255,255,0.1);
        padding: 20px;
        border-radius: 12px;
        text-align: center;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255,255,255,0.2);
      `;
      
      statDiv.innerHTML = `
        <div style="font-size: 2.5rem; font-weight: bold; color: ${stat.cor}; margin-bottom: 10px;">
          ${stat.valor}
        </div>
        <div style="font-size: 1rem; opacity: 0.9;">
          ${stat.label}
        </div>
      `;
      
      stats.appendChild(statDiv);
    });

    // Adicionar lista de top municípios
    const listDiv = document.createElement('div');
    listDiv.style.cssText = `
      margin-top: 30px;
      max-height: 250px;
      overflow-y: auto;
      width: 100%;
      max-width: 800px;
      padding: 0 20px;
    `;

    const topList = document.createElement('div');
    topList.style.cssText = `
      display: grid;
      gap: 10px;
    `;

    municipios.slice(0, 10).forEach((municipio, index) => {
      const item = document.createElement('div');
      item.style.cssText = `
        background: rgba(255,255,255,0.1);
        padding: 12px;
        border-radius: 8px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        backdrop-filter: blur(5px);
        border: 1px solid rgba(255,255,255,0.1);
      `;
      
      item.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px; flex: 1;">
          <span style="font-weight: bold; color: ${brandColors.amarelo}; font-size: 1.2rem;">
            #${index + 1}
          </span>
          <div>
            <div style="font-weight: 600;">${municipio.municipio || 'N/A'}, ${municipio.estado || 'N/A'}</div>
            <div style="font-size: 0.9rem; opacity: 0.8;">${municipio.sessoes || 0} sessões</div>
          </div>
        </div>
        <div style="color: ${brandColors.verde}; font-weight: bold; font-size: 1.1rem;">
          ${(municipio.total_votos || 0).toLocaleString('pt-BR')} votos
        </div>
      `;
      
      topList.appendChild(item);
    });

    listDiv.appendChild(topList);

    mapDiv.appendChild(title);
    mapDiv.appendChild(stats);
    mapDiv.appendChild(listDiv);

    // Limpar conteúdo anterior
    if (mapContainerRef.current) {
      mapContainerRef.current.innerHTML = '';
      mapContainerRef.current.appendChild(mapDiv);
    }
  };

  return (
    <Box sx={{ backgroundColor: '#FFFFFF', minHeight: '100vh', py: 3 }}>
      <Container maxWidth="xl">
        {/* Header */}
        <Typography variant="h3" sx={{ color: '#003366', mb: 4, fontWeight: 'bold' }}>
            🗺️ Mapa Eleitoral - Redutos
          </Typography>
        <Typography variant="body1" sx={{ color: '#666666', mb: 4 }}>
          Visualize geograficamente onde cada parlamentar teve mais votos nas eleições de 2022
        </Typography>

        {/* Filters */}
        <FilterSelector
          onFiltersChange={handleFilterChange}
          fields={['estado', 'partido', 'parlamentar']}
          showComissao={false}
          useCurrentParty={true}
        />

        {/* Execute Button */}
        <Box sx={{ mb: 3 }}>
          <Button
            variant="contained"
            onClick={handleAnalyze}
            disabled={loading}
            sx={{
              py: 1.5,
              px: 4,
              fontSize: '1.1rem',
              backgroundColor: brandColors.verde,
              borderRadius: '12px',
            }}
          >
            {loading ? <CircularProgress size={24} color="inherit" /> : '🗺️ Executar Análise Eleitoral'}
          </Button>
        </Box>

        {/* Error */}
        {error && (
          <Alert severity="error" sx={{ mb: 3 }}>
            {error}
          </Alert>
        )}

        {/* Loading */}
        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', my: 5 }}>
            <CircularProgress size={60} />
          </Box>
        )}

        {/* Results */}
        {analysisData && !loading && (
          <>
            {/* Parlamentarian Info */}
            {analysisData.info && (
              <Paper sx={{ p: 4, mb: 3, borderRadius: '12px' }}>
                <Grid container spacing={3} alignItems="center">
                  <Grid item xs={12} md={3}>
                    {analysisData.info.foto && (
                      <Avatar
                        src={analysisData.info.foto}
                        sx={{ width: 140, height: 140, mx: 'auto', border: '4px solid #009739' }}
                      />
                    )}
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#003366', mb: 2 }}>
                      {analysisData.info?.nome || 'N/A'}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                      <Chip label={analysisData.info?.partido || 'N/A'} sx={{ backgroundColor: '#e8f5e9', color: '#009739', fontWeight: 'bold' }} />
                      <Chip label={analysisData.info?.estado || 'N/A'} sx={{ backgroundColor: '#e3f2fd', color: '#003366', fontWeight: 'bold' }} />
                    </Box>
                  </Grid>
                  <Grid item xs={12} md={3}>
                    {analysisData.info.logoPartido && (
                      <Box component="img" src={analysisData.info.logoPartido} sx={{ maxWidth: '120px', display: 'block', mx: 'auto' }} />
                    )}
                  </Grid>
                </Grid>
              </Paper>
            )}

            {/* Electoral Stats */}
            {analysisData.stats && (
              <Grid container spacing={3} sx={{ mb: 4 }}>
                <Grid item xs={12} sm={6} md={4}>
                  <Card sx={{ borderRadius: '12px', backgroundColor: '#f8f9fa' }}>
                    <CardContent>
                      <Typography variant="h6" sx={{ color: '#666666', mb: 1 }}>
                        Total de Votos
                      </Typography>
                      <Typography variant="h3" sx={{ fontWeight: 'bold', color: '#009739' }}>
                        {(analysisData.stats?.total_votos || analysisData.stats?.totalVotos || 0).toLocaleString('pt-BR')}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={4}>
                  <Card sx={{ borderRadius: '12px', backgroundColor: '#f8f9fa' }}>
                    <CardContent>
                      <Typography variant="h6" sx={{ color: '#666666', mb: 1 }}>
                        Municípios
                      </Typography>
                      <Typography variant="h3" sx={{ fontWeight: 'bold', color: '#003366' }}>
                        {analysisData.stats?.total_municipios || analysisData.stats?.totalMunicipios || 0}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Card sx={{ borderRadius: '12px', backgroundColor: '#f8f9fa' }}>
                    <CardContent>
                      <Typography variant="h6" sx={{ color: '#666666', mb: 1 }}>
                        Sessões Eleitorais
                      </Typography>
                      <Typography variant="h3" sx={{ fontWeight: 'bold', color: '#4F81BD' }}>
                        {(analysisData.stats?.total_secoes || analysisData.stats?.totalSessoes || 0).toLocaleString('pt-BR')}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Card sx={{ borderRadius: '12px', backgroundColor: '#f8f9fa' }}>
                    <CardContent>
                      <Typography variant="h6" sx={{ color: '#666666', mb: 1 }}>
                        Principal Reduto
                      </Typography>
                      <Typography variant="h4" sx={{ fontWeight: 'bold', color: '#66BB6A' }}>
                        {analysisData.stats?.principal_reduto || 'N/A'}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>
            )}

            {/* Electoral Map */}
            <Box sx={{ mb: 4 }}>
              <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                🗺️ Mapa de Redutos Eleitorais
              </Typography>
              <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#FFFFFF', overflow: 'hidden' }}>
                <Box
                  ref={mapContainerRef}
                  sx={{
                    width: '100%',
                    minHeight: '600px',
                    borderRadius: '12px',
                  }}
                />
                <Alert severity="info" sx={{ mt: 2, borderRadius: '8px' }}>
                  <Typography variant="body2" sx={{ color: '#003366' }}>
                    <strong>ℹ️ Sobre as coordenadas:</strong> As coordenadas geográficas utilizadas neste mapa foram obtidas através de biblioteca de geocoding e podem conter erros. 
                    Alguns pontos podem estar localizados fora do estado do parlamentar ou em localizações imprecisas. 
                    Os dados são apresentados apenas para fins de visualização geográfica dos redutos eleitorais.
                  </Typography>
                </Alert>
              </Paper>
            </Box>

            {/* Top Municipalities Chart */}
            {analysisData.topMunicipios && analysisData.topMunicipios.length > 0 && (
              <Box sx={{ mb: 4 }}>
                <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                  🏆 Top 20 Municípios - Mais Votos
                </Typography>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#FFFFFF' }}>
                  <EChartWrapper
                    option={createBarChartOption(analysisData.topMunicipios)}
                    height="500px"
                  />
                </Paper>
              </Box>
            )}

            {/* Municipalities Table */}
            {analysisData.municipios && analysisData.municipios.length > 0 && (
              <Box sx={{ mb: 4 }}>
                <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                  📊 Detalhamento por Município
                </Typography>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#f8f9fa' }}>
                  <Typography variant="body2" sx={{ color: '#666666', mb: 2 }}>
                    Exibindo Top 20 municípios (de {analysisData.municipios.length} total)
                  </Typography>
                  <TableContainer>
                    <Table>
                      <TableHead>
                        <TableRow sx={{ backgroundColor: '#e8f5e9' }}>
                          <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>#</TableCell>
                          <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>Município</TableCell>
                          <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>UF</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 'bold', color: '#003366' }}>Total de Votos</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 'bold', color: '#003366' }}>Percentual (%)</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {analysisData.municipios.slice(0, 20).map((municipio, index) => (
                          <TableRow 
                            key={`${municipio.municipio}-${municipio.estado}-${index}`}
                            sx={{ 
                              '&:nth-of-type(odd)': { backgroundColor: '#FFFFFF' },
                              '&:hover': { backgroundColor: '#f0f0f0' }
                            }}
                          >
                            <TableCell sx={{ fontWeight: 'bold', color: '#009739' }}>
                              #{index + 1}
                            </TableCell>
                            <TableCell sx={{ fontWeight: municipio.municipio === analysisData.stats?.principal_reduto ? 'bold' : 'normal', color: municipio.municipio === analysisData.stats?.principal_reduto ? '#009739' : '#003366' }}>
                              {municipio.municipio || 'N/A'}
                            </TableCell>
                            <TableCell>{municipio.uf || municipio.estado || 'N/A'}</TableCell>
                            <TableCell align="right">
                              {(municipio.total_votos || 0).toLocaleString('pt-BR')}
                            </TableCell>
                            <TableCell align="right">
                              {municipio.percentual ? municipio.percentual.toFixed(2) : '0.00'}%
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Paper>
              </Box>
            )}
          </>
        )}

        {/* No Data */}
        {!loading && !analysisData && !error && (
          <Paper sx={{ p: 6, textAlign: 'center', borderRadius: '12px' }}>
            <Typography variant="h6" sx={{ color: '#666666', mb: 2 }}>
              🗺️ Visualização Eleitoral
            </Typography>
            <Typography variant="body2" sx={{ color: '#999999' }}>
              Selecione um parlamentar para visualizar seus redutos eleitorais
          </Typography>
        </Paper>
        )}
      </Container>
    </Box>
  );
};

export default MapaEleitoral;


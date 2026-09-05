import React, { useState } from 'react';
import {
  Box,
  Container,
  Typography,
  TextField,
  Button,
  Paper,
  Grid,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  LinearProgress,
  Alert,
  IconButton,
  Tooltip,
  Avatar,
} from '@mui/material';
import axios from '../config/axios';
import FilterSelector from '../components/FilterSelector';
import { Search as SearchIcon, ContentCopy as ContentCopyIcon } from '@mui/icons-material';
import { brandColors } from '../utils/chartOptions';
import ProgressoSemantica from '../components/ProgressoSemantica';
import ReactMarkdown from 'react-markdown';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

const BuscaSemantica = () => {
  const [tema, setTema] = useState('');
  const [filtros, setFiltros] = useState({
    estado: 'Todos',
    partido: 'Todos',
    parlamentar: '',
    dataInicio: '2023-01-01',
    dataFim: new Date().toISOString().split('T')[0]
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState('');
  const [percent, setPercent] = useState(0);
  const [results, setResults] = useState(null);
  const [showMoreReport, setShowMoreReport] = useState(false);
  const [showMoreFrases, setShowMoreFrases] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const getParlamentaresList = (res) => {
    const a = Array.isArray(res?.parlamentares_envolvidos) ? res.parlamentares_envolvidos : [];
    const b = Array.isArray(res?.parlamentares_citantes) ? res.parlamentares_citantes : [];
    const seen = new Set();
    const merged = [];
    [...a, ...b].forEach((p) => { if (p && !seen.has(p)) { seen.add(p); merged.push(p); } });
    return merged;
  };
  const getParlamentaresCount = (res) => getParlamentaresList(res).length;

  const getPartidoLogo = (partido, urlOriginal) => {
    const sigla = String(partido || '').trim().toUpperCase();
    return PARTIDO_LOGOS_FALLBACK[sigla] || urlOriginal || '';
  };

  const stripMarkdown = (text) => {
    if (!text) return '';
    let t = text;
    t = t.replace(/^#{1,6}\s+/gm, '');
    t = t.replace(/\*\*(.*?)\*\*/g, '$1');
    t = t.replace(/\*(.*?)\*/g, '$1');
    t = t.replace(/`{1,3}([\s\S]*?)`{1,3}/g, '$1');
    t = t.replace(/^---+$/gm, '');
    return t;
  };

  const normalizeReport = (text) => {
    if (!text) return '';
    let t = text;
    // garantir quebras antes de marcadores/ícones e títulos comuns
    t = t.replace(/\s*(📊|🎯|🏛️|🎭|📅|📋|🌐|🗺️|💡|⚠️)\s*/g, "\n\n$1 ");
    // quebras antes de seções típicas (sem ícone)
    t = t.replace(/\s*(SUMÁRIO EXECUTIVO|PARLAMENTARES MAIS ATIVOS|COMISSÕES QUE MAIS COBRIRAM O ASSUNTO|INTERAÇÕES DOCUMENTADAS ENTRE PARLAMENTARES|ANÁLISE TEMPORAL DETALHADA|PROPOSTAS LEGISLATIVAS E AÇÕES CONCRETAS|ANÁLISE POR PARTIDO|ANÁLISE REGIONAL|INSIGHTS E PADRÕES IDENTIFICADOS|SÍNTESE TÉCNICA)\s*:/gi, "\n\n$1:\n");
    // garantir quebra antes de listas e itens numerados
    t = t.replace(/\s-\s/g, "\n- ");
    t = t.replace(/\s(\d+\.)\s/g, "\n$1 ");
    t = t.replace(/\n{3,}/g, "\n\n");
    // inserir quebra após pontos finais que estão colados em novo bloco
    t = t.replace(/\.\s+(?=[A-ZÁÉÍÓÚÃÕ])/g, ".\n\n");
    return t.trim();
  };

  const handleSearch = async () => {
    if (!tema.trim()) {
      setError('Por favor, digite um tema para iniciar a auditoria técnica.');
      return;
    }

    setLoading(true);
    setError('');
    setResults(null);
    setShowMoreReport(false);
    setShowMoreFrases(false);
    setProgress('🔍 Iniciando busca semântica...');

    try {
      const payload = {
        tema: tema.trim(),
        data_inicio: filtros.dataInicio,
        data_fim: filtros.dataFim,
        ...(filtros.partido && filtros.partido !== 'Todos' && { partido: filtros.partido.trim() }),
        ...(filtros.estado && filtros.estado !== 'Todos' && { estado: filtros.estado.trim() }),
        ...(filtros.parlamentar && filtros.parlamentar !== 'Todos' && { parlamentar: filtros.parlamentar }),
      };

      const response = await axios.post(`/api/busca-semantica/buscar`, payload);
      const baseResults = response.data;
      
      if (!baseResults.discursos || baseResults.discursos.length === 0) {
        setResults(baseResults);
        setPercent(100);
        setProgress('');
        setLoading(false);
        setError(`Não foram encontrados discursos relevantes sobre o tema "${tema}" com os filtros aplicados. Nenhuma análise foi gerada.`);
        return;
      }

      setResults(baseResults);
      setPercent(10);
      setProgress('🧠 Iniciando auditoria técnica com IA...');

      try {
        const autoKeywords = ((Array.isArray(baseResults?.keywords) ? baseResults.keywords : [])
          .concat(String(tema || '').split(/[^\p{L}\p{N}]+/u).filter(Boolean)))
          .map((k) => (k || '').toString().toLowerCase())
          .filter((v, i, a) => v && a.indexOf(v) === i)
          .slice(0, 30);
        
        const relPayload = {
          tema: tema.trim(),
          discursos: Array.isArray(baseResults?.discursos)
            ? baseResults.discursos  // Não filtrar por citações - usar todos os discursos encontrados
            : [],
          ids_encontrados: Array.isArray(baseResults?.ids_encontrados) ? baseResults.ids_encontrados : [],
          data_inicio: filtros.dataInicio,
          data_fim: filtros.dataFim,
          keywords: autoKeywords,
          min_keyword_hits: 2,
        };

        const relInit = await axios.post(`/api/busca-semantica/gerar-relatorio`, relPayload);
        const { session_id } = relInit.data;
        setSessionId(session_id);

        if (session_id) {
          // Iniciar polling de progresso
          const pollInterval = setInterval(async () => {
            try {
              const pollRes = await axios.get(`/api/busca-semantica/progress/${session_id}`);
              const { status, mensagem, percent: p, result } = pollRes.data;
              
              setPercent(p);
              setProgress(mensagem);

              if (status === 'completo' && result) {
                clearInterval(pollInterval);

                console.log('✅ Status completo! Result recebido:', result);
                console.log('  • estatisticas:', result.estatisticas);
                console.log('  • parlamentares_envolvidos:', result.parlamentares_envolvidos);

                const texto = result.relatorio || '';
                setResults((prev) => {
                  const merged = {
                    ...(prev || baseResults),
                    relatorio: texto,
                    odiograma: result.odiograma,
                    estatisticas: result.estatisticas || {},
                    parlamentares_envolvidos: result.parlamentares_envolvidos || [],
                    parlamentares_citantes: result.parlamentares_citantes || [],
                    parlamentares_detalhados: result.parlamentares_detalhados || [],
                    total_citacoes: result.total_citacoes || 0,
                    discursos_com_citacoes: result.discursos_com_citacoes || 0,
                  };
                  console.log('  • merged.estatisticas:', merged.estatisticas);
                  return merged;
                });
                setLoading(false);
              } else if (status === 'erro') {
                clearInterval(pollInterval);
                setError(mensagem || 'Erro ao gerar relatório');
                setLoading(false);
              }
            } catch (pollErr) {
              console.error('Erro no polling:', pollErr);
              clearInterval(pollInterval);
              setLoading(false);
            }
          }, 2000); // Polling a cada 2 segundos
        } else {
          setLoading(false);
        }
      } catch (e) {
        console.error('Falha ao iniciar relatório LLM:', e);
        setProgress('⚠️ Falha ao iniciar auditoria');
        setLoading(false);
      }
    } catch (err) {
      setError('Erro ao executar busca: ' + err.message);
      setProgress('❌ Erro na análise');
      setLoading(false);
    }
  };

  const copyText = (text) => {
    navigator.clipboard.writeText(text);
  };

  const formatReport = (text) => {
    if (!text) return '';

    const sections = text.split(/(?=\d+\.\s+[A-ZÁÊÇÕ][A-ZÁÊÇÕ\s]+:)/);

    return sections.map((section, index) => {
      if (!section.trim()) return null;

      const match = section.match(/^(\d+\.\s+[A-ZÁÊÇÕ][A-ZÁÊÇÕ\s]+:)/);
      if (match) {
        const title = match[1];
        const content = section.replace(title, '').trim();

        return (
          <Box key={index} sx={{ mb: 3 }}>
            <Typography
              variant="h6"
              sx={{
                color: brandColors.azul,
                fontWeight: 'bold',
                mb: 2,
                borderBottom: '3px solid',
                borderColor: brandColors.verde,
                pb: 1,
              }}
            >
              {title}
            </Typography>
            <Typography variant="body1" sx={{ lineHeight: 1.8, color: '#003366', textAlign: 'justify' }}>
              {content.split('\n\n').map((para, pIndex) => (
                <Box key={pIndex} sx={{ mb: 2 }}>
                  {para.trim()}
                </Box>
              ))}
            </Typography>
          </Box>
        );
      }

      return (
        <Typography key={index} variant="body1" sx={{ mb: 2, lineHeight: 1.8, color: '#003366' }}>
          {section.trim()}
        </Typography>
      );
    }).filter(Boolean);
  };

  const downloadReportPdf = () => {
    try {
      const text = results?.relatorio || results?.relatorio_analitico || '';
      const htmlSafe = (text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const win = window.open('', '_blank');
      if (!win) return;
      win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Relatório - Busca Semântica</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=Montserrat:wght@600;700&display=swap" rel="stylesheet">
        <style>
          body { font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; color: #003366; margin: 24px; }
          h1,h2,h3 { font-family: Montserrat, Inter, Arial, sans-serif; }
          pre { white-space: pre-wrap; line-height: 1.5; font-size: 14px; }
        </style>
      </head><body>
        <h2 style="margin:0 0 8px 0;">${(tema || '').toUpperCase()}</h2>
        <div style="color:#666; margin:0 0 16px 0;">Relatório Técnico Detalhado • Período: ${dataInicio} a ${dataFim}</div>
        <pre>${htmlSafe}</pre>
      </body></html>`);
      win.document.close();
      win.focus();
      win.print();
    } catch (e) {
      console.error('Erro ao gerar PDF:', e);
    }
  };

  return (
    <Box sx={{ backgroundColor: '#FFFFFF', minHeight: '100vh', py: 3 }}>
      <Container maxWidth="xl">
        <Box sx={{ mb: 4, backgroundColor: 'white', p: 3, borderRadius: '16px', display: 'flex', alignItems: 'center', gap: 4 }}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="h3" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
              🔍 Busca Semântica Parlamentar
            </Typography>
            <Typography variant="body1" sx={{ color: '#666666' }}>
              Analise discursos parlamentares usando inteligência artificial para encontrar temas específicos e gerar relatórios detalhados.
            </Typography>
          </Box>
          <Box
            component="img"
            src="/Busca_Semantica_Parlamentar.png"
            alt="Ilustração Busca Semântica"
            sx={{
              maxHeight: '220px',
              width: 'auto',
              borderRadius: '8px',
              display: { xs: 'none', md: 'block' }
            }}
          />
        </Box>

        {/* Tema de Busca - Topo */}
        <Paper elevation={1} sx={{ p: 3, mb: 3, borderRadius: '12px' }}>
          <TextField
            fullWidth
            label="Tema de Busca"
            value={tema}
            onChange={(e) => setTema(e.target.value)}
            placeholder="Ex: energia solar, meio ambiente, educação..."
            sx={{ backgroundColor: '#FFFFFF', borderRadius: '8px' }}
          />
        </Paper>

        {/* Filtros Intercambiáveis - Modelo Gastos Detalhamento */}
        <FilterSelector 
          onFiltersChange={(newFilters) => setFiltros(prev => ({ ...prev, ...newFilters }))}
          fields={['estado', 'partido', 'parlamentar']}
          useCurrentParty={true}
        />

        {/* Datas e Botão de Busca */}
        <Paper elevation={1} sx={{ p: 3, mb: 3, borderRadius: '12px' }}>
          <Grid container spacing={3} alignItems="center">
            <Grid item xs={12} md={6}>
              <Box sx={{ display: 'flex', gap: 2 }}>
                <TextField
                  fullWidth
                  label="Data Início"
                  type="date"
                  value={filtros.dataInicio}
                  onChange={(e) => setFiltros(prev => ({ ...prev, dataInicio: e.target.value }))}
                  InputLabelProps={{ shrink: true }}
                />
                <TextField
                  fullWidth
                  label="Data Fim"
                  type="date"
                  value={filtros.dataFim}
                  onChange={(e) => setFiltros(prev => ({ ...prev, dataFim: e.target.value }))}
                  InputLabelProps={{ shrink: true }}
                />
              </Box>
            </Grid>

            <Grid item xs={12} md={6}>
              <Button
                variant="contained"
                size="large"
                fullWidth
                onClick={handleSearch}
                disabled={loading}
                startIcon={
                  loading ? (
                    <CircularProgress size={30} color="inherit" />
                  ) : (
                    <Box
                      component="img"
                      src="/expressions/antunes_angry.png"
                      alt="IA Antunes"
                      sx={{
                        height: 40,
                        width: 40,
                        borderRadius: '50%',
                        border: '2px solid #FFF',
                        objectFit: 'cover',
                        objectPosition: 'center 15%',
                        mr: 1,
                        bgcolor: '#FFF'
                      }}
                    />
                  )
                }
                sx={{
                  bgcolor: '#003366',
                  '&:hover': { bgcolor: '#004488' },
                  py: 1.5,
                  fontSize: '1.1rem',
                  borderRadius: 2,
                  textTransform: 'none'
                }}
              >
                {loading ? 'Analisando...' : 'Auditoria com Antunes'}
              </Button>
            </Grid>
          </Grid>
        </Paper>

        {/* Progress */}
        {loading && sessionId && (
          <ProgressoSemantica session_id={sessionId} tema={tema} polling={true} />
        )}

        {loading && !sessionId && (
          <Alert severity="info" sx={{ mb: 3 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <CircularProgress size={20} />
              <Typography>{progress}</Typography>
            </Box>
          </Alert>
        )}

        {/* Error */}
        {error && (
          <Alert severity="error" sx={{ mb: 3 }}>
            {error}
          </Alert>
        )}

        {/* Results */}
        {results && (
          <Grid container spacing={3}>
            {/* Statistics */}
            {(results.estatisticas || results.total_discursos !== undefined) && (
              <Grid item xs={12}>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#f8f9fa' }}>
                  <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                    📊 Estatísticas da Análise
                  </Typography>
                  <Grid container spacing={3}>
                    <Grid item xs={6} sm={3}>
                      <Box sx={{ textAlign: 'center', p: 2, bgcolor: '#E8F5E9', borderRadius: '8px' }}>
                        <Typography variant="h4" sx={{ color: '#009739', fontWeight: 'bold' }}>
                          {results.estatisticas?.total_discursos ?? results.total_discursos ?? 0}
                        </Typography>
                        <Typography variant="body2" sx={{ color: '#666666' }}>
                          Discursos Encontrados
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Box sx={{ textAlign: 'center', p: 2, bgcolor: '#E3F2FD', borderRadius: '8px' }}>
                        <Typography variant="h4" sx={{ color: '#003366', fontWeight: 'bold' }}>
                          {results.estatisticas?.discursos_relevantes ?? results.discursos_com_citacoes ?? 0}
                        </Typography>
                        <Typography variant="body2" sx={{ color: '#666666' }}>
                          Discursos Relevantes
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Box sx={{ textAlign: 'center', p: 2, bgcolor: '#FFF9E6', borderRadius: '8px' }}>
                        <Typography variant="h4" sx={{ color: '#FFF81C', fontWeight: 'bold' }}>
                          {getParlamentaresCount(results)}
                        </Typography>
                        <Typography variant="body2" sx={{ color: '#666666' }}>
                          Parlamentares
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid item xs={6} sm={3}>
                      <Box sx={{ textAlign: 'center', p: 2, bgcolor: '#E8F5E9', borderRadius: '8px' }}>
                        <Typography variant="h4" sx={{ color: '#4F81BD', fontWeight: 'bold' }}>
                          {results.estatisticas?.total_citacoes ?? results.total_citacoes ?? 0}
                        </Typography>
                        <Typography variant="body2" sx={{ color: '#666666' }}>
                          Citações
                        </Typography>
                      </Box>
                    </Grid>
                  </Grid>

                </Paper>
              </Grid>
            )}

            {/* Parlamentares Detalhados com Foto e Logo */}
            {(results.parlamentares_detalhados?.length > 0) && (
              <Grid item xs={12}>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#FFFFFF' }}>
                  <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold', mb: 3 }}>
                    👥 Parlamentares Envolvidos — Análise Individual
                  </Typography>
                  <Grid container spacing={2}>
                    {results.parlamentares_detalhados.slice(0, 20).map((p, idx) => (
                      <Grid item xs={12} sm={6} md={4} key={p.nome || idx}>
                        <Card sx={{ 
                          borderRadius: '12px', 
                          border: `2px solid ${p.posicao === 'FAVORÁVEL' ? '#009739' : p.posicao === 'CONTRÁRIO' ? '#ED8B00' : '#4F81BD'}`,
                          height: '100%',
                          transition: 'transform 0.2s, box-shadow 0.2s',
                          '&:hover': { transform: 'translateY(-4px)', boxShadow: '0 8px 25px rgba(0,0,0,0.15)' }
                        }}>
                          <CardContent sx={{ p: 2 }}>
                            {/* Header: Foto + Nome + Logo Partido */}
                            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1.5, gap: 1.5 }}>
                              <Avatar 
                                src={p.foto} 
                                alt={p.nome}
                                sx={{ width: 56, height: 56, border: '2px solid #e0e0e0' }}
                                onError={(e) => { e.target.src = 'https://www.camara.leg.br/tema/assets/images/foto-deputado-sem-foto.png'; }}
                              />
                              <Box sx={{ flex: 1, minWidth: 0 }}>
                                <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: '#003366', lineHeight: 1.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {p.nome}
                                </Typography>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.3 }}>
                                  {getPartidoLogo(p.partido, p.logo_partido) && (
                                    <img src={getPartidoLogo(p.partido, p.logo_partido)} alt={p.partido} style={{ height: 18, width: 'auto', objectFit: 'contain' }} onError={(e) => { e.target.style.display = 'none'; }} />
                                  )}
                                  <Typography variant="caption" sx={{ color: '#666' }}>
                                    {p.partido}/{p.estado}
                                  </Typography>
                                </Box>
                              </Box>
                            </Box>
                            {/* Posição */}
                            <Chip 
                              label={p.posicao} 
                              size="small" 
                              sx={{ 
                                mb: 1, 
                                fontWeight: 'bold',
                                bgcolor: p.posicao === 'FAVORÁVEL' ? '#E8F5E9' : p.posicao === 'CONTRÁRIO' ? '#FFF3E0' : '#E3F2FD',
                                color: p.posicao === 'FAVORÁVEL' ? '#009739' : p.posicao === 'CONTRÁRIO' ? '#ED8B00' : '#003366',
                              }}
                            />
                            <Typography variant="caption" sx={{ display: 'block', color: '#888', mb: 0.5 }}>
                              {p.total_discursos} discurso{p.total_discursos > 1 ? 's' : ''}
                            </Typography>
                            {/* Datas e Comissões */}
                            {p.datas?.length > 0 && (
                              <Typography variant="caption" sx={{ display: 'block', color: '#555', mb: 0.3 }}>
                                📅 {p.datas.join(', ')}
                              </Typography>
                            )}
                            {p.comissoes?.length > 0 && (
                              <Typography variant="caption" sx={{ display: 'block', color: '#555', mb: 1 }}>
                                🏛️ {p.comissoes.join(', ')}
                              </Typography>
                            )}
                            {/* Resumo */}
                            {p.resumo && (
                              <Typography variant="body2" sx={{ color: '#333', fontSize: '0.8rem', lineHeight: 1.4, mb: 1 }}>
                                {p.resumo.length > 500 ? p.resumo.slice(0, 500) + '...' : p.resumo}
                              </Typography>
                            )}
                            {/* Citações */}
                            {p.citacoes?.length > 0 && (
                              <Box sx={{ mt: 1, p: 1, bgcolor: '#f8f9fa', borderRadius: '6px', borderLeft: '3px solid #003366' }}>
                                <Typography variant="caption" sx={{ fontStyle: 'italic', color: '#444', display: 'block' }}>
                                  "{p.citacoes[0]?.length > 200 ? p.citacoes[0].slice(0, 200) + '...' : p.citacoes[0]}"
                                </Typography>
                              </Box>
                            )}
                          </CardContent>
                        </Card>
                      </Grid>
                    ))}
                  </Grid>
                </Paper>
              </Grid>
            )}
            {/* Fallback: lista simples se não houver dados detalhados */}
            {(!results.parlamentares_detalhados || results.parlamentares_detalhados.length === 0) && getParlamentaresCount(results) > 0 && (
              <Grid item xs={12}>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#FFFFFF' }}>
                  <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                    👤 Parlamentares envolvidos (Top 20)
                  </Typography>
                  <Grid container spacing={1}>
                    {getParlamentaresList(results).slice(0, 20).map((nome) => (
                      <Grid item key={nome}>
                        <Chip label={nome} size="small" sx={{ fontWeight: 600 }} />
                      </Grid>
                    ))}
                  </Grid>
                </Paper>
              </Grid>
            )}

            {/* Report */}
            {(results.relatorio || results.relatorio_analitico) && (
              <Grid item xs={12}>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#FFFFFF' }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold' }}>
                      📋 Relatório Completo
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                      <Button size="small" variant="outlined" onClick={downloadReportPdf}>📄 Baixar PDF</Button>
                      <Tooltip title="Copiar relatório">
                        <IconButton onClick={() => copyText(results.relatorio || results.relatorio_analitico || '')} size="small">
                          <ContentCopyIcon />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </Box>

                  {/* Cabeçalho claro do relatório */}
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold' }}>
                      {tema.trim() ? tema.toUpperCase() : 'PANORAMA GERAL DE ATUAÇÃO'}
                    </Typography>
                    <Typography variant="subtitle2" sx={{ color: '#666' }}>
                      Relatório Técnico Detalhado • Período: {filtros.dataInicio} a {filtros.dataFim}
                    </Typography>
                  </Box>




                  <Box sx={{
                    maxHeight: showMoreReport ? 'none' : '800px',
                    overflowY: showMoreReport ? 'visible' : 'auto',
                    p: 3,
                    bgcolor: '#f8f9fa',
                    borderRadius: '8px',
                    lineHeight: 1.6,
                    color: '#1a1a2e',
                    fontSize: '0.95rem',
                    '& h1': { color: '#003366', fontSize: '1.5rem', fontWeight: 'bold', borderBottom: '2px solid #003366', pb: 1, mb: 2, mt: 3 },
                    '& h2': { color: '#003366', fontSize: '1.25rem', fontWeight: 'bold', borderBottom: '1px solid #e0e0e0', pb: 0.5, mb: 1.5, mt: 2.5 },
                    '& h3': { color: '#1a3a5c', fontSize: '1.1rem', fontWeight: 600, mb: 1, mt: 2 },
                    '& p': { mb: 1.5, textAlign: 'justify' },
                    '& ul, & ol': { pl: 3, mb: 1.5 },
                    '& li': { mb: 0.5 },
                    '& blockquote': { borderLeft: '4px solid #003366', pl: 2, ml: 0, my: 1.5, py: 0.5, bgcolor: '#eef2f7', borderRadius: '0 8px 8px 0', fontStyle: 'italic' },
                    '& table': { width: '100%', borderCollapse: 'collapse', mb: 2, fontSize: '0.85rem' },
                    '& th': { bgcolor: '#003366', color: '#fff', p: 1, textAlign: 'left', fontWeight: 'bold', border: '1px solid #ddd' },
                    '& td': { p: 1, border: '1px solid #ddd', bgcolor: '#fff' },
                    '& tr:nth-of-type(even) td': { bgcolor: '#f5f7fa' },
                    '& strong': { color: '#003366' },
                    '& hr': { border: 'none', borderTop: '1px solid #ddd', my: 2 },
                  }}>
                    <ReactMarkdown>
                      {showMoreReport
                        ? (results.relatorio || results.relatorio_analitico || '')
                        : ((results.relatorio || results.relatorio_analitico || '').slice(0, 8000) + (((results.relatorio || results.relatorio_analitico || '').length > 8000) ? '\n\n---\n\n*Clique em "Mostrar mais" para ver o relatório completo...*' : ''))}
                    </ReactMarkdown>
                  </Box>
                  {(results.relatorio || results.relatorio_analitico) && (results.relatorio || results.relatorio_analitico).length > 5000 && (
                    <Box sx={{ mt: 2, textAlign: 'right' }}>
                      <Button size="small" variant="outlined" onClick={() => setShowMoreReport(!showMoreReport)}>
                        {showMoreReport ? 'Mostrar menos' : 'Mostrar mais'}
                      </Button>
                    </Box>
                  )}
                </Paper>
              </Grid>
            )}

            {/* Impactful Phrases */}
            {results.frases_impactantes && results.frases_impactantes.length > 0 && (
              <Grid item xs={12}>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#FFFFFF' }}>
                  <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                    💬 Frases Impactantes dos Parlamentares
                  </Typography>
                  <Typography variant="body2" sx={{ color: '#666666', mb: 3 }}>
                    Declarações marcantes dos parlamentares sobre o tema pesquisado.
                  </Typography>

                  <Grid container spacing={2}>
                    {(showMoreFrases ? results.frases_impactantes : results.frases_impactantes.slice(0, 10)).map((frase, index) => (
                      <Grid item xs={12} md={6} key={index}>
                        <Card sx={{ borderRadius: '12px', border: '1px solid #e0e0e0' }}>
                          <CardContent>
                            <Box sx={{ display: 'flex', gap: 2 }}>
                              {frase.foto && (
                                <Box
                                  component="img"
                                  src={frase.foto}
                                  alt={frase.parlamentar}
                                  sx={{
                                    width: 60,
                                    height: 60,
                                    borderRadius: '50%',
                                    objectFit: 'cover',
                                    border: '2px solid #009739'
                                  }}
                                />
                              )}

                              <Box sx={{ flex: 1 }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                                  <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: '#003366' }}>
                                    {frase.parlamentar}
                                  </Typography>
                                  {getPartidoLogo(frase.partido, frase.logo_partido) && (
                                    <Box component="img" src={getPartidoLogo(frase.partido, frase.logo_partido)} sx={{ width: 20, height: 20, borderRadius: '50%', objectFit: 'contain' }} />
                                  )}
                                  {frase.bandeira_estado && (
                                    <Box component="img" src={frase.bandeira_estado} sx={{ width: 30, height: 20 }} />
                                  )}
                                </Box>

                                <Typography variant="body2" sx={{ fontStyle: 'italic', mb: 1, color: '#666666' }}>
                                  {frase.frase}
                                </Typography>

                                <Typography variant="caption" sx={{ color: '#999999' }}>
                                  {frase.comissao} • {frase.data}
                                </Typography>
                              </Box>
                            </Box>
                          </CardContent>
                        </Card>
                      </Grid>
                    ))}
                  </Grid>
                  {results.frases_impactantes.length > 10 && (
                    <Box sx={{ mt: 2, textAlign: 'right' }}>
                      <Button size="small" variant="outlined" onClick={() => setShowMoreFrases(!showMoreFrases)}>
                        {showMoreFrases ? 'Mostrar menos' : 'Mostrar mais frases'}
                      </Button>
                    </Box>
                  )}
                </Paper>
              </Grid>
            )}

            {/* Pares de citação entre parlamentares (amostra) - renderizar somente se houver pares */}
            {(() => {
              if (!Array.isArray(results?.discursos) || results.discursos.length === 0) return null;
              const contagem = {};
              results.discursos.forEach((d) => {
                const citante = d?.Parlamentar;
                const lista = Array.isArray(d?.citacoes) ? d.citacoes : [];
                lista.forEach((c) => {
                  const citado = c?.parlamentar_alvo || c?.destinatario || null;
                  if (citante && citado) {
                    const chave = `${citante} -> ${citado}`;
                    contagem[chave] = (contagem[chave] || 0) + 1;
                  }
                });
              });
              const pares = Object.entries(contagem).sort((a, b) => b[1] - a[1]).slice(0, 10);
              if (pares.length === 0) return null;
              return (
                <Grid item xs={12}>
                  <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#FFFFFF' }}>
                    <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                      🔗 Citações entre parlamentares (amostra)
                    </Typography>
                    <Grid container spacing={1}>
                      {pares.map(([pair, count]) => (
                        <Grid item key={pair} xs={12} sm={6} md={4}>
                          <Box sx={{ p: 1.5, border: '1px solid #e0e0e0', borderRadius: '8px', bgcolor: '#fafafa' }}>
                            <Typography variant="body2" sx={{ color: '#003366', fontWeight: 600 }}>{pair}</Typography>
                            <Typography variant="caption" sx={{ color: '#777' }}>{count} citação(ões)</Typography>
                          </Box>
                        </Grid>
                      ))}
                    </Grid>
                  </Paper>
                </Grid>
              );
            })()}
          </Grid>
        )}

        {/* No Data */}
        {!loading && !results && !error && (
          <Paper sx={{ p: 6, textAlign: 'center', borderRadius: '12px' }}>
            <Typography variant="h6" sx={{ color: '#666666' }}>
              Digite um tema e execute a busca para ver os resultados.
            </Typography>
          </Paper>
        )}
      
      <DataSourceFooter
        sources={[{"label":"Notas Taquigráficas — Câmara","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Eventos","type":"camara"}]}
        note="Busca por similaridade semântica em base de discursos parlamentares (2023–2026) via embeddings OpenAI text-embedding-ada-002."
      />
    </Container>
    </Box>
  );
};

export default BuscaSemantica;



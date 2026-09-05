import React, { useState, useEffect } from 'react';
import {
  Box,
  Container,
  Typography,
  LinearProgress,
  Paper,
  Card,
  CardContent,
  Chip,
  Grid,
  List,
  ListItem,
  ListItemText,
  Divider,
} from '@mui/material';
import { brandColors } from '../utils/chartOptions';
import { API_HEADERS } from '../config';

const ProgressoSemantica = ({ session_id, tema, polling = true }) => {
  const [progresso, setProgresso] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!polling || !session_id) return;

    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`/api/busca-semantica/progress/${session_id}`, { headers: API_HEADERS });
        const data = await response.json();
        setProgresso(data);
        setLoading(false);

        if (data.status === 'completo') {
          clearInterval(pollInterval);
        }
      } catch (err) {
        console.error('Erro ao buscar progresso:', err);
      }
    }, 500); // Atualizar a cada 500ms para ser responsivo

    return () => clearInterval(pollInterval);
  }, [session_id, polling]);

  if (loading) {
    return (
      <Box sx={{ textAlign: 'center', py: 4 }}>
        <Typography>Carregando progresso...</Typography>
      </Box>
    );
  }

  if (!progresso) {
    return null;
  }

  const fases = progresso.fases || {};
  const tempoFormatado = formatarTempo(progresso.tempo_decorrido);

  return (
    <Box sx={{ backgroundColor: '#FFFFFF', py: 3 }}>
      <Container maxWidth="lg">
        {/* Header */}
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
            ⚡ Auditoria em Andamento
          </Typography>
          <Typography variant="body2" sx={{ color: '#666666' }}>
            Tema: <strong>{tema}</strong> • Tempo: <strong>{tempoFormatado}</strong>
          </Typography>
        </Box>

        {/* Barra de Progresso Global */}
        <Paper sx={{ p: 3, mb: 4, borderRadius: '12px', backgroundColor: '#f8f9fa' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
            <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold', flex: 1 }}>
              Progresso Geral
            </Typography>
            <Typography variant="h5" sx={{ color: brandColors.verde, fontWeight: 'bold' }}>
              {Math.round(progresso.percent)}%
            </Typography>
          </Box>
          <LinearProgress
            variant="determinate"
            value={progresso.percent}
            sx={{
              height: 12,
              borderRadius: 6,
              backgroundColor: '#e0e0e0',
              '& .MuiLinearProgress-bar': {
                backgroundColor: brandColors.verde,
                borderRadius: 6,
              },
            }}
          />
        </Paper>

        {/* Fases em Grid */}
        <Grid container spacing={3} sx={{ mb: 4 }}>
          {Object.entries(fases).map(([key, fase]) => (
            <Grid item xs={12} sm={6} md={3} key={key}>
              <Card
                sx={{
                  borderRadius: '12px',
                  border: `2px solid ${getFaseBorderColor(fase.status)}`,
                  backgroundColor: getFaseBackground(fase.status),
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                }}
              >
                <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                  <Typography variant="subtitle2" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                    {fase.nome}
                  </Typography>

                  {/* Status Indicator */}
                  <Box sx={{ mb: 2 }}>
                    {fase.status === 'concluida' && (
                      <Chip label="✅ Concluída" size="small" sx={{ backgroundColor: '#E8F5E9', color: '#009739' }} />
                    )}
                    {fase.status === 'em_progresso' && (
                      <Chip label="⏳ Em Progresso" size="small" sx={{ backgroundColor: '#FFF3E0', color: '#F57C00' }} />
                    )}
                    {fase.status === 'nao_iniciada' && (
                      <Chip label="⏸️ Aguardando" size="small" sx={{ backgroundColor: '#F5F5F5', color: '#666' }} />
                    )}
                  </Box>

                  {/* Progress Bar da Fase */}
                  <LinearProgress
                    variant="determinate"
                    value={fase.percent}
                    sx={{
                      height: 6,
                      borderRadius: 3,
                      backgroundColor: '#e0e0e0',
                      mb: 1.5,
                      '& .MuiLinearProgress-bar': {
                        backgroundColor: brandColors.verde,
                      },
                    }}
                  />
                  <Typography variant="caption" sx={{ color: '#666', display: 'block', mb: 2 }}>
                    {fase.percent}% completo
                  </Typography>

                  {/* Estatísticas */}
                  <Box sx={{ backgroundColor: '#fff', p: 1, borderRadius: '6px', fontSize: '0.75rem', marginTop: 'auto' }}>
                    {Object.entries(fase.estatisticas).map(([stat, valor]) => (
                      <Box key={stat} sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                        <span style={{ color: '#666' }}>{formatarNomeEstat(stat)}:</span>
                        <strong style={{ color: '#003366' }}>{formatarValor(valor)}</strong>
                      </Box>
                    ))}
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>

        {/* Mensagens Detalhadas */}
        <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#f8f9fa' }}>
          <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
            📋 Detalhes da Fase {progresso.fase_atual}
          </Typography>

          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 3 }}>
            {/* Fase Atual Detalhada */}
            {fases[`fase_${progresso.fase_atual}`] && (
              <>
                <Box>
                  <Typography variant="subtitle2" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                    🔄 Processos em Andamento
                  </Typography>
                  <List dense>
                    {fases[`fase_${progresso.fase_atual}`].mensagens.slice(-5).map((msg, idx) => (
                      <ListItem key={idx} sx={{ py: 0.5 }}>
                        <ListItemText
                          primary={msg}
                          primaryTypographyProps={{
                            variant: 'body2',
                            sx: { color: '#003366', fontSize: '0.85rem' },
                          }}
                        />
                      </ListItem>
                    ))}
                  </List>
                </Box>

                <Box>
                  <Typography variant="subtitle2" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                    📊 Métricas
                  </Typography>
                  <Box sx={{ backgroundColor: '#fff', p: 2, borderRadius: '8px' }}>
                    {Object.entries(fases[`fase_${progresso.fase_atual}`].estatisticas).map(
                      ([stat, valor]) => (
                        <Box
                          key={stat}
                          sx={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            mb: 1,
                            pb: 1,
                            borderBottom: '1px solid #eee',
                          }}
                        >
                          <Typography variant="body2" sx={{ color: '#666' }}>
                            {formatarNomeEstat(stat)}:
                          </Typography>
                          <Typography variant="body2" sx={{ color: '#003366', fontWeight: 'bold' }}>
                            {formatarValor(valor)}
                          </Typography>
                        </Box>
                      )
                    )}
                  </Box>
                </Box>
              </>
            )}
          </Box>
        </Paper>

        {/* Status Geral */}
        <Box sx={{ mt: 3, p: 2, backgroundColor: '#E8F5E9', borderRadius: '8px', border: '1px solid #009739' }}>
          <Typography variant="body2" sx={{ color: '#003366' }}>
            <strong>Status:</strong> {progresso.status === 'completo' ? '✅ CONCLUÍDO' : '⏳ PROCESSANDO'}
            {progresso.status === 'completo' && (
              <> em {progresso.tempo_total}s</>
            )}
          </Typography>
        </Box>
      </Container>
    </Box>
  );
};

// Funções Auxiliares
function formatarTempo(segundos) {
  if (!segundos) return '0s';
  if (segundos < 60) return `${Math.round(segundos)}s`;
  const minutos = Math.floor(segundos / 60);
  const secs = segundos % 60;
  return `${minutos}m ${Math.round(secs)}s`;
}

function formatarNomeEstat(nome) {
  const nomes = {
    palavras_chave_geradas: 'Palavras-chave',
    discursos_encontrados: 'Discursos',
    parlamentares_encontrados: 'Parlamentares',
    tempo_decorrido: 'Tempo',
    lotes_totais: 'Total Lotes',
    lotes_processados: 'Lotes OK',
    discursos_validados: 'Validados',
    discursos_rejeitados: 'Rejeitados',
    score_medio: 'Score Médio',
    discursos_favoraveis: 'Favoráveis',
    discursos_contrarios: 'Contrários',
    discursos_neutros: 'Neutros',
    embeddings_gerados: 'Discursos analisados',
    secoes_geradas: 'Seções',
    frases_extraidas: 'Frases',
  };
  return nomes[nome] || nome;
}

function formatarValor(valor) {
  if (typeof valor === 'number') {
    if (valor > 100) return valor.toFixed(0);
    return valor.toFixed(1);
  }
  return valor;
}

function getFaseBorderColor(status) {
  switch (status) {
    case 'concluida':
      return '#009739';
    case 'em_progresso':
      return '#F57C00';
    case 'nao_iniciada':
      return '#CCCCCC';
    default:
      return '#CCCCCC';
  }
}

function getFaseBackground(status) {
  switch (status) {
    case 'concluida':
      return '#F0FFF0';
    case 'em_progresso':
      return '#FFFAF0';
    case 'nao_iniciada':
      return '#FAFAFA';
    default:
      return '#FFFFFF';
  }
}

export default ProgressoSemantica;

import React, { useEffect, useState, useCallback } from 'react';
import {
  Box, Typography, Grid, Paper, CircularProgress,
  Chip, Divider, Table, TableBody, TableCell,
  TableHead, TableRow, LinearProgress,
} from '@mui/material';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from 'recharts';
import api from '../config/axios';

const COLORS = {
  azul:   '#003366',
  verde:  '#009739',
  laranja:'#ED8B00',
  cinza:  '#f0f4f8',
};

const StatCard = ({ label, value, sub, color = COLORS.azul }) => (
  <Paper elevation={2} sx={{ p: 3, borderRadius: 3, borderTop: `4px solid ${color}` }}>
    <Typography variant="body2" color="text.secondary">{label}</Typography>
    <Typography variant="h3" fontWeight={700} sx={{ color, mt: 0.5 }}>{value?.toLocaleString('pt-BR') ?? '—'}</Typography>
    {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
  </Paper>
);

const PAGE_LABELS = {
  '/':                         'Home',
  '/gastos/detalhamento':      'Gastos · Detalhamento',
  '/gastos/passagens':         'Gastos · Passagens',
  '/gastos/ranking':           'Gastos · Ranking',
  '/gastos/emendas':           'Emendas',
  '/analise/imprensa':         'Análise · Imprensa',
  '/analise/chat':             'Chat Parlamentar',
  '/mapa/eleitoral':           'Mapa Eleitoral',
  '/mapa/partidario':          'Mapa Partidário',
  '/comissoes/atuacao':        'Comissões · Atuação',
  '/comissoes/presenca':       'Comissões · Presença',
  '/votos/geral':              'Votações · Geral',
  '/votos/parlamentar':        'Votações · Parlamentar',
  '/conexoes/sociograma':      'Sociograma',
  '/busca/semantica':          'Busca Semântica',
  '/parlamentar/assessores':   'Assessores',
};

export default function PainelAislan() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState(null);

  const carregar = useCallback(async () => {
    try {
      setLoading(true);
      const { data } = await api.get('/api/admin/stats', {
        headers: { 'X-Admin-Key': 'AISLAN_ADMIN_2025' },
      });
      setStats(data);
      setErro(null);
    } catch (e) {
      setErro('Não foi possível carregar as estatísticas.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  if (loading) return (
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: 10 }}>
      <CircularProgress />
    </Box>
  );

  if (erro) return (
    <Box sx={{ mt: 6, textAlign: 'center' }}>
      <Typography color="error">{erro}</Typography>
    </Box>
  );

  const maxPage = Math.max(...(stats.top_pages?.map(p => p.visitas) ?? [1]));

  return (
    <Box sx={{ pb: 6 }}>
      {/* Header */}
      <Box sx={{ mb: 4, display: 'flex', alignItems: 'center', gap: 2 }}>
        <Box>
          <Typography variant="h4" fontWeight={700} sx={{ color: COLORS.azul }}>
            Painel Administrativo
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Acesso restrito · eu sei disso deputado
          </Typography>
        </Box>
        <Chip label="AISLAN" size="small" sx={{ ml: 'auto', bgcolor: COLORS.azul, color: '#fff', fontWeight: 700 }} />
      </Box>

      <Divider sx={{ mb: 4 }} />

      {/* Cards de resumo */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid item xs={6} md={3}>
          <StatCard label="Total de acessos" value={stats.total_visitas} color={COLORS.azul} />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard label="Últimas 24h" value={stats.ultimas_24h} color={COLORS.verde} />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard label="Últimos 7 dias" value={stats.ultimos_7_dias} color={COLORS.laranja} />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard label="IPs únicos (30d)" value={stats.ips_unicos_30d} sub="visitantes distintos" color={COLORS.azul} />
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        {/* Gráfico de acessos diários */}
        <Grid item xs={12} md={8}>
          <Paper elevation={2} sx={{ p: 3, borderRadius: 3 }}>
            <Typography variant="h6" fontWeight={700} sx={{ color: COLORS.azul, mb: 2 }}>
              Acessos diários — últimos 30 dias
            </Typography>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={stats.por_dia}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
                <XAxis dataKey="dia" tick={{ fontSize: 11 }} tickFormatter={d => d?.slice(5)} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => [v, 'Acessos']} labelFormatter={l => `Data: ${l}`} />
                <Line type="monotone" dataKey="visitas" stroke={COLORS.verde} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>

        {/* Gráfico por hora */}
        <Grid item xs={12} md={4}>
          <Paper elevation={2} sx={{ p: 3, borderRadius: 3 }}>
            <Typography variant="h6" fontWeight={700} sx={{ color: COLORS.azul, mb: 2 }}>
              Acessos por hora do dia
            </Typography>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={stats.por_hora}>
                <XAxis dataKey="hora" tick={{ fontSize: 10 }} tickFormatter={h => `${h}h`} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip formatter={(v) => [v, 'Acessos']} labelFormatter={l => `${l}h`} />
                <Bar dataKey="visitas" fill={COLORS.azul} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>

        {/* Páginas mais acessadas */}
        <Grid item xs={12}>
          <Paper elevation={2} sx={{ p: 3, borderRadius: 3 }}>
            <Typography variant="h6" fontWeight={700} sx={{ color: COLORS.azul, mb: 2 }}>
              Páginas mais acessadas
            </Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 700, color: COLORS.azul }}>#</TableCell>
                  <TableCell sx={{ fontWeight: 700, color: COLORS.azul }}>Página</TableCell>
                  <TableCell sx={{ fontWeight: 700, color: COLORS.azul }} align="right">Acessos</TableCell>
                  <TableCell sx={{ fontWeight: 700, color: COLORS.azul }} width="35%">Proporção</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {stats.top_pages?.map((p, i) => (
                  <TableRow key={p.path} hover>
                    <TableCell sx={{ color: '#999', fontWeight: 600 }}>{i + 1}</TableCell>
                    <TableCell>
                      <Typography variant="body2" fontWeight={600}>
                        {PAGE_LABELS[p.path] ?? p.path}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">{p.path}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Chip label={p.visitas.toLocaleString('pt-BR')} size="small"
                        sx={{ bgcolor: i === 0 ? COLORS.verde : '#f0f0f0', color: i === 0 ? '#fff' : '#333', fontWeight: 700 }} />
                    </TableCell>
                    <TableCell>
                      <LinearProgress
                        variant="determinate"
                        value={(p.visitas / maxPage) * 100}
                        sx={{ height: 6, borderRadius: 3,
                          '& .MuiLinearProgress-bar': { bgcolor: i === 0 ? COLORS.verde : COLORS.azul } }}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}

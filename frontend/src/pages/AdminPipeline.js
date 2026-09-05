import React, { useState, useEffect, useRef } from 'react';
import {
    Box,
    Typography,
    Container,
    Paper,
    Grid,
    Button,
    CircularProgress,
    Alert,
    Card,
    CardContent,
    Divider,
    Chip,
    IconButton,
    TextField,
    MenuItem,
    Stack,
} from '@mui/material';
import {
    PlayArrow as PlayIcon,
    Terminal as TerminalIcon,
    Refresh as RefreshIcon,
    Settings as SettingsIcon,
    History as HistoryIcon,
    Schedule as ScheduleIcon,
    DeleteOutline as DeleteIcon,
} from '@mui/icons-material';
import api from '../config/axios';
import { brandColors } from '../utils/chartOptions';

const getContrastColor = (color) => (
    color === brandColors.amarelo || color === brandColors.verdeClaro
        ? brandColors.azul
        : brandColors.branco
);

const weekDays = [
    { value: 0, label: 'Segunda' },
    { value: 1, label: 'Terça' },
    { value: 2, label: 'Quarta' },
    { value: 3, label: 'Quinta' },
    { value: 4, label: 'Sexta' },
    { value: 5, label: 'Sábado' },
    { value: 6, label: 'Domingo' },
];

const defaultSchedule = { day: 4, time: '10:00', enabled: true };

const formatSchedule = (schedule) => {
    if (!schedule) return 'Sem agenda';
    const day = weekDays.find((item) => item.value === Number(schedule.day))?.label || 'Dia indefinido';
    return `${day} às ${schedule.time}${schedule.enabled === false ? ' (pausado)' : ''}`;
};

const AdminPipeline = () => {
    const [status, setStatus] = useState({ running: false, last_log: '' });
    const [loading, setLoading] = useState(false);
    const [loadingStage, setLoadingStage] = useState(null);
    const [scheduleLoading, setScheduleLoading] = useState(null);
    const [error, setError] = useState(null);
    const [success, setSuccess] = useState(null);
    const [statusError, setStatusError] = useState(false);
    const [schedules, setSchedules] = useState({});
    const [scheduleDrafts, setScheduleDrafts] = useState({});
    const logRef = useRef(null);

    const stages = [
        { id: 'all', name: 'Pipeline Completo', desc: 'Executa todos os estágios em sequência.', color: brandColors.azul },
        { id: 'core', name: 'Core & Bases', desc: 'Atualiza o Tabelão mestre parlamentar.', color: brandColors.azul },
        { id: 'legislativo', name: 'Atividade Legislativa', desc: 'Votos, Projetos de Lei, Presenças e Assessores.', color: brandColors.verde },
        { id: 'noticias', name: 'Notícias & IA', desc: 'Coleta, Rigor Fuzz e Auditoria Profunda GPT-4.', color: brandColors.amarelo },
        { id: 'discursos', name: 'Discursos & Grafos', desc: 'A fábrica de conexões: Transforma discursos em grafos de influência.', color: brandColors.azulClaro },
        { id: 'auditoria', name: 'Auditoria & OSINT', desc: 'Emendas, Empresas Deep, Processos STF e Voos.', color: brandColors.verdeClaro },
    ];

    const fetchStatus = async () => {
        try {
            const response = await api.get('/api/admin/pipeline/status');
            setStatus(response.data);
            const schedulesByStage = (response.data.schedules || []).reduce((acc, schedule) => {
                acc[schedule.stage] = schedule;
                return acc;
            }, {});
            setSchedules(schedulesByStage);
            setScheduleDrafts((current) => {
                const next = { ...current };
                stages.forEach((stage) => {
                    if (!next[stage.id]) {
                        next[stage.id] = schedulesByStage[stage.id] || defaultSchedule;
                    }
                });
                return next;
            });
            setStatusError(false);
        } catch (err) {
            console.error('Erro ao buscar status do pipeline:', err);
            setStatusError(true);
        }
    };

    useEffect(() => {
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        if (logRef.current) {
            logRef.current.scrollTop = logRef.current.scrollHeight;
        }
    }, [status.last_log]);

    const handleExec = async (stageId) => {
        setLoading(true);
        setLoadingStage(stageId);
        setError(null);
        setSuccess(null);
        try {
            const response = await api.post(`/api/admin/pipeline/exec/${stageId}`);
            if (response.data.status === 'success') {
                setSuccess(response.data.message);
                fetchStatus();
            } else {
                setError(response.data.message);
            }
        } catch (err) {
            const detail = err.response?.data?.detail || err.response?.data?.message;
            setError(detail || 'Erro ao disparar execução do pipeline. Verifique se o backend está no ar.');
        } finally {
            setLoading(false);
            setLoadingStage(null);
        }
    };

    const updateScheduleDraft = (stageId, field, value) => {
        setScheduleDrafts((current) => ({
            ...current,
            [stageId]: {
                ...(current[stageId] || defaultSchedule),
                [field]: value,
            },
        }));
    };

    const handleSaveSchedule = async (stageId) => {
        const draft = scheduleDrafts[stageId] || defaultSchedule;
        setScheduleLoading(stageId);
        setError(null);
        setSuccess(null);
        try {
            const response = await api.post(`/api/admin/pipeline/schedule/${stageId}`, {
                enabled: true,
                day: Number(draft.day),
                time: draft.time,
            });
            const schedulesByStage = (response.data.schedules || []).reduce((acc, schedule) => {
                acc[schedule.stage] = schedule;
                return acc;
            }, {});
            setSchedules(schedulesByStage);
            setSuccess(response.data.message || 'Agendamento salvo.');
        } catch (err) {
            const detail = err.response?.data?.detail || err.response?.data?.message;
            setError(detail || 'Erro ao salvar agendamento.');
        } finally {
            setScheduleLoading(null);
        }
    };

    const handleDeleteSchedule = async (stageId) => {
        setScheduleLoading(stageId);
        setError(null);
        setSuccess(null);
        try {
            const response = await api.delete(`/api/admin/pipeline/schedule/${stageId}`);
            const schedulesByStage = (response.data.schedules || []).reduce((acc, schedule) => {
                acc[schedule.stage] = schedule;
                return acc;
            }, {});
            setSchedules(schedulesByStage);
            setSuccess(response.data.message || 'Agendamento removido.');
        } catch (err) {
            const detail = err.response?.data?.detail || err.response?.data?.message;
            setError(detail || 'Erro ao remover agendamento.');
        } finally {
            setScheduleLoading(null);
        }
    };

    return (
        <Container maxWidth="xl" sx={{ pb: 8 }}>
            <Box sx={{ mb: 4, display: 'flex', alignItems: 'center', gap: 2 }}>
                <SettingsIcon sx={{ fontSize: 40, color: brandColors.azul }} />
                <Box>
                    <Typography variant="h4" fontWeight="bold" color={brandColors.azul}>
                        Maestro de Dados: Painel de Controle
                    </Typography>
                    <Typography variant="body1" color="textSecondary">
                        Orquestração e monitoramento em tempo real do pipeline de inteligência parlamentar.
                    </Typography>
                </Box>
            </Box>

            <Grid container spacing={3}>
                {/* Cards de Comando */}
                <Grid item xs={12} md={7}>
                    <Grid container spacing={2}>
                        {stages.map((stage) => (
                            <Grid item xs={12} sm={stage.id === 'all' ? 12 : 6} key={stage.id}>
                                <Card elevation={3} sx={{ 
                                    borderLeft: `6px solid ${stage.color}`,
                                    opacity: status.running ? 0.7 : 1,
                                    transition: 'transform 0.2s',
                                    backgroundColor: brandColors.branco,
                                    '&:hover': { transform: status.running ? 'none' : 'scale(1.02)' }
                                }}>
                                    <CardContent>
                                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                            <Box>
                                                <Typography variant="h6" fontWeight="bold" color={brandColors.azul}>
                                                    {stage.name}
                                                </Typography>
                                                <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
                                                    {stage.desc}
                                                </Typography>
                                            </Box>
                                            <Chip 
                                                label={stage.id.toUpperCase()} 
                                                size="small" 
                                                sx={{
                                                    backgroundColor: stage.color,
                                                    color: getContrastColor(stage.color),
                                                    fontWeight: 'bold'
                                                }}
                                            />
                                        </Box>
                                        <Button
                                            variant="contained"
                                            fullWidth
                                            startIcon={loadingStage === stage.id ? <CircularProgress size={20} color="inherit" /> : <PlayIcon />}
                                            disabled={status.running || loading}
                                            onClick={() => handleExec(stage.id)}
                                            sx={{ 
                                                backgroundColor: stage.color,
                                                color: getContrastColor(stage.color),
                                                fontWeight: 'bold',
                                                '&:hover': { backgroundColor: stage.color, filter: 'brightness(90%)' }
                                            }}
                                        >
                                            {status.running ? 'Pipeline em execução' : 'Executar esta etapa agora'}
                                        </Button>

                                        <Divider sx={{ my: 2 }} />

                                        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems="stretch">
                                            <TextField
                                                select
                                                size="small"
                                                label="Dia"
                                                value={scheduleDrafts[stage.id]?.day ?? defaultSchedule.day}
                                                onChange={(event) => updateScheduleDraft(stage.id, 'day', Number(event.target.value))}
                                                sx={{ flex: 1 }}
                                            >
                                                {weekDays.map((day) => (
                                                    <MenuItem key={day.value} value={day.value}>
                                                        {day.label}
                                                    </MenuItem>
                                                ))}
                                            </TextField>
                                            <TextField
                                                size="small"
                                                label="Horário"
                                                type="time"
                                                value={scheduleDrafts[stage.id]?.time || defaultSchedule.time}
                                                onChange={(event) => updateScheduleDraft(stage.id, 'time', event.target.value)}
                                                InputLabelProps={{ shrink: true }}
                                                inputProps={{ step: 300 }}
                                                sx={{ width: { xs: '100%', sm: 120 } }}
                                            />
                                        </Stack>

                                        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                                            <Button
                                                variant="outlined"
                                                fullWidth
                                                startIcon={scheduleLoading === stage.id ? <CircularProgress size={16} /> : <ScheduleIcon />}
                                                disabled={scheduleLoading === stage.id}
                                                onClick={() => handleSaveSchedule(stage.id)}
                                                sx={{
                                                    borderColor: brandColors.verde,
                                                    color: brandColors.verde,
                                                    fontWeight: 'bold',
                                                    '&:hover': {
                                                        borderColor: brandColors.verde,
                                                        backgroundColor: 'rgba(0, 151, 57, 0.08)',
                                                    },
                                                }}
                                            >
                                                Agendar
                                            </Button>
                                            <IconButton
                                                aria-label={`Remover agenda de ${stage.name}`}
                                                disabled={!schedules[stage.id] || scheduleLoading === stage.id}
                                                onClick={() => handleDeleteSchedule(stage.id)}
                                                sx={{
                                                    border: `1px solid ${brandColors.cinzaClaro}`,
                                                    borderRadius: 1,
                                                    color: schedules[stage.id] ? brandColors.laranjaEscuro : brandColors.cinza,
                                                }}
                                            >
                                                <DeleteIcon />
                                            </IconButton>
                                        </Stack>

                                        <Typography variant="caption" color="textSecondary" sx={{ display: 'block', mt: 1 }}>
                                            Agenda: {formatSchedule(schedules[stage.id])}
                                        </Typography>
                                    </CardContent>
                                </Card>
                            </Grid>
                        ))}
                    </Grid>
                </Grid>

                {/* Console de Logs */}
                <Grid item xs={12} md={5}>
                    <Paper elevation={6} sx={{ 
                        height: '100%', 
                        backgroundColor: '#082744',
                        color: brandColors.branco,
                        p: 0,
                        borderRadius: '8px',
                        overflow: 'hidden',
                        display: 'flex',
                        flexDirection: 'column'
                    }}>
                        <Box sx={{ 
                            p: 1.5, 
                            backgroundColor: brandColors.azul,
                            display: 'flex', 
                            justifyContent: 'space-between', 
                            alignItems: 'center' 
                        }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <TerminalIcon fontSize="small" />
                                <Typography variant="subtitle2" fontWeight="bold">Console do Maestro</Typography>
                            </Box>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                {status.running && (
                                    <Chip 
                                        label="RODANDO" 
                                        size="small" 
                                        sx={{
                                            height: 20,
                                            fontSize: '0.6rem',
                                            fontWeight: 'bold',
                                            backgroundColor: brandColors.verde,
                                            color: brandColors.branco
                                        }}
                                    />
                                )}
                                <IconButton size="small" onClick={fetchStatus} sx={{ color: brandColors.branco }}>
                                    <RefreshIcon fontSize="inherit" />
                                </IconButton>
                            </Box>
                        </Box>
                        <Box 
                            ref={logRef}
                            sx={{ 
                                p: 2, 
                                flexGrow: 1, 
                                overflowY: 'auto', 
                                fontFamily: 'monospace', 
                                fontSize: '0.8rem',
                                whiteSpace: 'pre-wrap',
                                color: '#EAF2F8'
                            }}
                        >
                            {statusError
                                ? '> Servidor indisponível: não foi possível consultar o Maestro. Rode ./subir.sh e confira backend.log.'
                                : (status.last_log || '> Aguardando execução. Quando o pipeline iniciar, os logs aparecerão aqui...')}
                        </Box>
                    </Paper>
                </Grid>
            </Grid>

            {/* Alertas */}
            <Box sx={{ mt: 3 }}>
                {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
                {success && <Alert severity="success" onClose={() => setSuccess(null)}>{success}</Alert>}
                {status.running && (
                    <Alert severity="info" sx={{ mt: 2 }}>
                        Status: O pipeline está em execução no servidor. Você pode fechar esta aba e os scripts continuarão rodando.
                    </Alert>
                )}
            </Box>

            {/* Instruções de Agendamento */}
            <Paper elevation={2} sx={{ mt: 4, p: 3, backgroundColor: brandColors.branco, border: `1px solid ${brandColors.cinzaClaro}` }}>
                <Typography variant="h6" fontWeight="bold" color={brandColors.azul} gutterBottom>
                    <HistoryIcon sx={{ mr: 1, verticalAlign: 'middle' }} />
                    Agendamentos Ativos no Servidor
                </Typography>
                {Object.keys(schedules).length ? (
                    <Grid container spacing={1}>
                        {Object.entries(schedules).map(([stageId, schedule]) => {
                            const stage = stages.find((item) => item.id === stageId);
                            return (
                                <Grid item xs={12} sm={6} md={4} key={stageId}>
                                    <Box sx={{
                                        border: `1px solid ${brandColors.cinzaClaro}`,
                                        borderLeft: `5px solid ${stage?.color || brandColors.azul}`,
                                        borderRadius: 2,
                                        p: 1.5,
                                    }}>
                                        <Typography variant="subtitle2" fontWeight="bold" color={brandColors.azul}>
                                            {stage?.name || stageId}
                                        </Typography>
                                        <Typography variant="body2" color="textSecondary">
                                            {formatSchedule(schedule)}
                                        </Typography>
                                        {schedule.last_run_at && (
                                            <Typography variant="caption" color="textSecondary">
                                                Última execução agendada: {schedule.last_run_at}
                                            </Typography>
                                        )}
                                    </Box>
                                </Grid>
                            );
                        })}
                    </Grid>
                ) : (
                    <Alert severity="info">
                        Nenhum agendamento configurado. Escolha o dia e horário em uma etapa acima e clique em “Agendar”.
                    </Alert>
                )}
            </Paper>
        </Container>
    );
};

export default AdminPipeline;

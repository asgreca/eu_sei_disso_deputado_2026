import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Container,
  Typography,
  Grid,
  Paper,
  TextField,
  IconButton,
  Avatar,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Divider,
  Chip,
  CircularProgress,
  Tooltip,
} from '@mui/material';
import {
  Send as SendIcon,
  SmartToy as BotIcon,
  Person as UserIcon,
  History as HistoryIcon,
  Source as SourceIcon,
  ErrorOutline as ErrorIcon,
  DeleteOutline as DeleteIcon,
} from '@mui/icons-material';
import axios from 'axios';
import api from '../config/axios';
import ReactMarkdown from 'react-markdown';
import { brandColors } from '../utils/chartOptions';
import DataSourceFooter from '../components/DataSourceFooter';

const ChatParlamentar = () => {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sources, setSources] = useState([]);
  
  const messagesEndRef = useRef(null);

  // Carregar histórico do localStorage
  useEffect(() => {
    const savedHistory = localStorage.getItem('chat_parlamentar_history');
    if (savedHistory) {
      setHistory(JSON.parse(savedHistory));
    }
    
    // Iniciar com uma mensagem de boas-vindas do Dr. Antunes.
    setMessages([
      {
        role: 'assistant',
        content: 'Olá, eu sou o Antunes. Pergunte em linguagem normal: **“o que se fala sobre taxar o Pix?”**, **“o deputado Fulano falou sobre a fila do INSS?”** ou **“quem criticou regulação de redes sociais?”**. Eu busco nos discursos oficiais e, quando houver evidência, respondo com data, local da fala e um trecho verificável.',
        timestamp: new Date().toLocaleTimeString()
      }
    ]);
  }, []);

  // Rolar para o fim quando houver novas mensagens
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage = {
      role: 'user',
      content: input,
      timestamp: new Date().toLocaleTimeString()
    };

    const currentInput = input;
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);
    setSources([]);

    // Adiciona mensagem vazia do assistente que vai ser preenchida via streaming
    const assistantId = Date.now();
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: '',
      timestamp: new Date().toLocaleTimeString(),
      sources: [],
      _id: assistantId,
      _streaming: true,
    }]);

    try {
      const { API_KEY } = await import('../config');
      const res = await fetch('/api/chat-parlamentar/conversa', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify({
          message: currentInput,
          history: messages.slice(-10).map(m => ({
            role: m.role,
            content: m.role === 'assistant' ? (m.content || '').slice(0, 2500) : m.content
          }))
        })
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullText = '';
      let msgSources = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop(); // guarda linha incompleta

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.type === 'sources') {
              msgSources = evt.sources || [];
              setSources(msgSources);
              setMessages(prev => prev.map(m =>
                m._id === assistantId ? { ...m, sources: msgSources } : m
              ));
            } else if (evt.type === 'token') {
              fullText += evt.token;
              setMessages(prev => prev.map(m =>
                m._id === assistantId ? { ...m, content: fullText } : m
              ));
            } else if (evt.type === 'done') {
              setMessages(prev => prev.map(m =>
                m._id === assistantId ? { ...m, _streaming: false } : m
              ));
            } else if (evt.type === 'error') {
              throw new Error(evt.message);
            }
          } catch (_) {}
        }
      }

      // Atualizar histórico de sessões
      const newHistoryItem = {
        title: currentInput.slice(0, 30) + (currentInput.length > 30 ? '...' : ''),
        date: new Date().toLocaleDateString(),
        id: Date.now()
      };
      const updatedHistory = [newHistoryItem, ...history.slice(0, 9)];
      setHistory(updatedHistory);
      localStorage.setItem('chat_parlamentar_history', JSON.stringify(updatedHistory));

    } catch (error) {
      console.error('Erro no chat:', error);
      setMessages(prev => prev.map(m =>
        m._id === assistantId
          ? { ...m, content: '⚠️ Erro de conexão: ' + (error.message || 'Verifique o servidor.'), _streaming: false }
          : m
      ));
    } finally {
      setLoading(false);
    }
  };

  const clearHistory = () => {
    localStorage.removeItem('chat_parlamentar_history');
    setHistory([]);
  };

  return (
    <Box sx={{ 
      backgroundColor: '#f4f7f9', 
      minHeight: 'calc(100vh - 64px)', 
      display: 'flex',
      flexDirection: 'column'
    }}>
      <Container maxWidth="xl" sx={{ flexGrow: 1, py: 3, display: 'flex', gap: 3 }}>
        
        {/* Sidebar - Histórico */}
        <Box sx={{ 
          width: 300, 
          display: { xs: 'none', md: 'flex' }, 
          flexDirection: 'column',
          gap: 2
        }}>
          <Paper sx={{ p: 2, borderRadius: '16px', flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
              <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
                <HistoryIcon /> Sessões Recentes
              </Typography>
              <IconButton onClick={clearHistory} size="small" color="error">
                <DeleteIcon fontSize="small" />
              </IconButton>
            </Box>
            <Divider sx={{ mb: 2 }} />
            <List sx={{ flexGrow: 1, overflowY: 'auto' }}>
              {history.length === 0 ? (
                <Typography variant="body2" sx={{ color: '#999', textAlign: 'center', mt: 4 }}>
                  Nenhuma auditoria recente.
                </Typography>
              ) : (
                history.map((item) => (
                  <ListItem key={item.id} button sx={{ borderRadius: '8px', mb: 1 }}>
                    <ListItemIcon sx={{ minWidth: 36 }}>
                      <SourceIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText 
                      primary={item.title} 
                      secondary={item.date}
                      primaryTypographyProps={{ variant: 'body2', noWrap: true, fontWeight: 500 }}
                      secondaryTypographyProps={{ variant: 'caption' }}
                    />
                  </ListItem>
                ))
              )}
            </List>
          </Paper>

          {/* Dr. Antunes Info */}
          <Paper sx={{ p: 2, borderRadius: '16px', backgroundColor: '#eef2f6' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
              <Avatar src="/antunes_icon.png" sx={{ width: 48, height: 48, border: '2px solid #003366' }} />
              <Box>
                <Typography variant="subtitle2" sx={{ fontWeight: 'bold', color: '#003366' }}>
                  Dr. Antunes
                </Typography>
                <Typography variant="caption" sx={{ color: '#666' }}>
                  Auditor Forense Sênior
                </Typography>
              </Box>
            </Box>
            <Typography variant="caption" sx={{ fontStyle: 'italic', color: '#555' }}>
              "Meticulosidade não é opção, é obrigação. Sem evidência, é apenas ruído."
            </Typography>
          </Paper>
        </Box>

        {/* Chat Principal */}
        <Box sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
          
          <Paper sx={{ 
            flexGrow: 1, 
            borderRadius: '16px', 
            display: 'flex', 
            flexDirection: 'column',
            overflow: 'hidden',
            backgroundColor: 'white',
            boxShadow: '0 4px 20px rgba(0,0,0,0.05)'
          }}>
            {/* Header do Chat */}
            <Box sx={{ 
              p: 2, 
              backgroundColor: '#003366', 
              color: 'white', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'space-between'
            }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <BotIcon />
                <Box>
                  <Typography variant="subtitle1" sx={{ fontWeight: 'bold', lineHeight: 1.2 }}>
                    Canal de Auditoria Forense
                  </Typography>
                  <Typography variant="caption" sx={{ opacity: 0.8 }}>
                    Consulta a discursos oficiais com data, reunião e trechos verificáveis
                  </Typography>
                </Box>
              </Box>
              <Chip 
                label="Dr. Antunes Online" 
                size="small" 
                sx={{ backgroundColor: '#009739', color: 'white', fontWeight: 'bold' }} 
              />
            </Box>

            {/* Mensagens */}
            <Box sx={{ 
              flexGrow: 1, 
              p: 3, 
              overflowY: 'auto', 
              display: 'flex', 
              flexDirection: 'column', 
              gap: 2,
              backgroundColor: '#f8fafc'
            }}>
              {messages.map((msg, index) => (
                <Box 
                  key={index} 
                  sx={{ 
                    display: 'flex', 
                    flexDirection: 'column',
                    alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '85%',
                    alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start'
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                    {msg.role === 'assistant' && <Avatar size="small" src="/antunes_icon.png" sx={{ width: 24, height: 24 }} />}
                    <Typography variant="caption" sx={{ color: '#999', fontWeight: 500 }}>
                      {msg.role === 'user' ? 'Você' : 'Dr. Antunes'} • {msg.timestamp}
                    </Typography>
                    {msg.role === 'user' && <Avatar size="small" sx={{ width: 24, height: 24, backgroundColor: '#003366' }}><UserIcon sx={{ fontSize: 16 }} /></Avatar>}
                  </Box>
                  <Paper sx={{ 
                    p: 2, 
                    borderRadius: msg.role === 'user' ? '16px 4px 16px 16px' : '4px 16px 16px 16px',
                    backgroundColor: msg.role === 'user' ? '#003366' : 'white',
                    color: msg.role === 'user' ? 'white' : '#333',
                    border: msg.role === 'assistant' ? '1px solid #e0e6ed' : 'none',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.02)'
                  }}>
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                    {msg._streaming && (
                      <Box component="span" sx={{
                        display: 'inline-block', width: 2, height: '1em',
                        bgcolor: '#003366', ml: '2px', verticalAlign: 'text-bottom',
                        animation: 'blink 0.7s step-end infinite',
                        '@keyframes blink': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0 } }
                      }} />
                    )}
                  </Paper>
                  
                  {/* Fontes integradas na resposta se for do assistente */}
                  {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
                    <Box sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                      <Tooltip title="Fontes consultadas para este parecer">
                        <Chip 
                          icon={<SourceIcon sx={{ fontSize: '14px !important' }} />} 
                          label={`${msg.sources.length} Evidências`} 
                          size="small" 
                          variant="outlined"
                          sx={{ fontSize: '10px' }}
                        />
                      </Tooltip>
                    </Box>
                  )}
                </Box>
              ))}
              {loading && (
                <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
                  <Avatar src="/antunes_icon.png" sx={{ width: 24, height: 24 }} />
                  <Box sx={{ backgroundColor: 'white', p: 2, borderRadius: '4px 16px 16px 16px', border: '1px solid #e0e6ed' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                      <CircularProgress size={16} thickness={5} sx={{ color: '#003366' }} />
                      <Typography variant="body2" sx={{ color: '#666', fontStyle: 'italic' }}>
                        Processando auditoria...
                      </Typography>
                    </Box>
                  </Box>
                </Box>
              )}
              <div ref={messagesEndRef} />
            </Box>

            {/* Input */}
            <Box sx={{ p: 2, borderTop: '1px solid #e0e6ed', backgroundColor: 'white' }}>
              <Grid container spacing={1} alignItems="center">
                <Grid item xs>
                  <TextField 
                    fullWidth 
                    size="small" 
                    placeholder="Ex.: o que se fala sobre taxar o Pix? / Fulano falou sobre fila do INSS?" 
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && handleSend()}
                    disabled={loading}
                    sx={{
                      '& .MuiOutlinedInput-root': {
                        borderRadius: '12px',
                        backgroundColor: '#f8fafc'
                      }
                    }}
                  />
                </Grid>
                <Grid item>
                  <IconButton 
                    onClick={handleSend} 
                    disabled={loading || !input.trim()} 
                    sx={{ 
                      backgroundColor: '#003366', 
                      color: 'white',
                      '&:hover': { backgroundColor: '#002244' },
                      '&.Mui-disabled': { backgroundColor: '#ccc' }
                    }}
                  >
                    <SendIcon />
                  </IconButton>
                </Grid>
              </Grid>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
                {[
                  'o que se fala sobre taxar o Pix?',
                  'cite se algum parlamentar falou sobre fila do INSS',
                  'quem defendeu ou criticou regulação das redes sociais?'
                ].map((example) => (
                  <Chip
                    key={example}
                    label={example}
                    size="small"
                    variant="outlined"
                    onClick={() => setInput(example)}
                    disabled={loading}
                    sx={{
                      color: '#003366',
                      borderColor: '#b8c7d9',
                      backgroundColor: '#f8fafc',
                      '&:hover': { backgroundColor: '#e8f1fb' }
                    }}
                  />
                ))}
              </Box>
            </Box>
          </Paper>

          {/* Aviso Legal */}
          <Box sx={{ px: 2, pb: 2, textAlign: 'center' }}>
            <Typography variant="caption" sx={{ color: '#999', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
              <ErrorIcon sx={{ fontSize: 12 }} /> As respostas do Dr. Antunes são geradas via IA fundamentada em discursos oficiais. Conferência em registros taquigráficos é recomendada para fins judiciais.
            </Typography>
          </Box>
        </Box>
      
      <DataSourceFooter
        sources={[{"label":"Notas Taquigráficas — Câmara","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Eventos","type":"camara"},{"label":"Discursos — Portal da Câmara","href":"https://www.camara.leg.br","type":"camara"}]}
        note="Respostas geradas por IA (GPT-4o-mini) com base em discursos parlamentares oficiais (2023–2026). Verificar citações na fonte primária antes de uso jornalístico ou jurídico."
      />
    </Container>
    </Box>
  );
};

export default ChatParlamentar;

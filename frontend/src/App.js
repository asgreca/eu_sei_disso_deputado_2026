import React, { useEffect, useRef } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Box, Container } from '@mui/material';

import Navbar from './components/Navbar';
import HomePage from './pages/HomePage';
import GastosDetalhamento from './pages/GastosDetalhamento';
import PassagensAereas from './pages/PassagensAereas';
import GastosRanking from './pages/GastosRanking';
import AnaliseImprensa from './pages/AnaliseImprensa';
import MapaEleitoral from './pages/MapaEleitoral';
import MapaEleitoral2 from './pages/MapaEleitoral2';
import MapaPartidario from './pages/MapaPartidario';
import EmendasParlamentares from './pages/EmendasParlamentares';
import ConflitosEmendas from './pages/ConflitosEmendas';
import ChatParlamentar from './pages/ChatParlamentar';
import Sociograma from './pages/Odiograma';
import AtuacaoComissoes from './pages/AtuacaoComissoes';
import AuditoriaImprensaV2 from './pages/AuditoriaImprensaV2';
import BuscaSemantica from './pages/BuscaSemantica';
import PresencaParlamentar from './pages/PresencaParlamentar';
import VotacoesGeral from './pages/VotacoesGeral';
import VotacaoDetalhe from './pages/VotacaoDetalhe';
import VotacoesParlamentar from './pages/VotacoesParlamentar';
import Assessores from './pages/Assessores';
import AdminPipeline from './pages/AdminPipeline';
import PainelAislan from './pages/PainelAislan';

const KONAMI = 'AISLAN';

const App = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const bufferRef = useRef('');

  useEffect(() => {
    const handler = (e) => {
      // Ignorar quando está digitando em inputs
      const tag = e.target?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return;

      bufferRef.current = (bufferRef.current + e.key).slice(-KONAMI.length);
      if (bufferRef.current.toUpperCase() === KONAMI) {
        bufferRef.current = '';
        navigate('/aislan');
      }
    };
    window.addEventListener('keypress', handler);
    return () => window.removeEventListener('keypress', handler);
  }, [navigate]);

  useEffect(() => {
    if (window.gtag) {
      window.gtag('config', process.env.REACT_APP_GOOGLE_ANALYTICS_ID, {
        page_path: location.pathname,
        page_title: document.title,
      });
    }
  }, [location]);

  return (
    <Box sx={{ backgroundColor: '#F3F6FA', minHeight: '100vh' }}>
      <Navbar />
      <Container maxWidth="xl" sx={{ py: 4 }}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/gastos/detalhamento" element={<GastosDetalhamento />} />
          <Route path="/gastos/passagens" element={<PassagensAereas />} />
          <Route path="/gastos/ranking" element={<GastosRanking />} />
          <Route path="/analise/imprensa-antigo" element={<AnaliseImprensa />} />
          <Route path="/analise/imprensa" element={<AuditoriaImprensaV2 />} />
          <Route path="/votos/geral" element={<VotacoesGeral />} />
          <Route path="/votos/parlamentar" element={<VotacoesParlamentar />} />
          <Route path="/votos/detalhe/:id" element={<VotacaoDetalhe />} />
          <Route path="/mapa/eleitoral" element={<MapaEleitoral />} />
          <Route path="/mapa/eleitoral2" element={<MapaEleitoral2 />} />
          <Route path="/mapa/partidario" element={<MapaPartidario />} />
          <Route path="/gastos/emendas" element={<EmendasParlamentares />} />
          <Route path="/gastos/conflitos" element={<ConflitosEmendas />} />
          <Route path="/parlamentar/assessores" element={<Assessores />} />
          <Route path="/analise/chat" element={<ChatParlamentar />} />
          <Route path="/conexoes/sociograma" element={<Sociograma />} />
          <Route path="/comissoes/atuacao" element={<AtuacaoComissoes />} />
          <Route path="/comissoes/presenca" element={<PresencaParlamentar />} />
          <Route path="/busca/semantica" element={<BuscaSemantica />} />
          <Route path="/manifesto" element={<Navigate to="/" replace />} />
          <Route path="/admin" element={<AdminPipeline />} />
          <Route path="/aislan" element={<PainelAislan />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Container>
    </Box>
  );
};

export default App;

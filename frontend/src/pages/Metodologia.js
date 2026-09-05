import React, { useState } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Grid,
  Chip,
  Divider,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Breadcrumbs,
  Link,
} from '@mui/material';
import {
  ExpandMore,
  NavigateNext,
  Public,
  Storage,
  Gavel,
  Insights,
  Security,
  AutoAwesome,
  VerifiedUser,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { brandColors } from '../utils/chartOptions';

const SectionTitle = ({ icon, children }) => (
  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
    {icon}
    <Typography variant="h4" sx={{ fontWeight: 'bold', color: brandColors.azul, fontSize: { xs: '1.5rem', md: '2rem' } }}>
      {children}
    </Typography>
  </Box>
);

const fontesCGU = [
  {
    fonte: 'CEIS — Cadastro de Empresas Inidôneas e Suspensas',
    dados: 'Empresas e pessoas físicas impedidas de contratar com a administração pública.',
    uso: 'Cruzado com fornecedores de emendas, contratos públicos e da cota parlamentar (CEAP).',
    href: 'https://portaldatransparencia.gov.br/download-de-dados/ceis',
  },
  {
    fonte: 'CEPIM — Cadastro de Entidades sem Fins Lucrativos Impedidas',
    dados: 'ONGs e associações impedidas de celebrar convênios com o poder público.',
    uso: 'Cruzado com entidades beneficiadas por emendas parlamentares.',
    href: 'https://portaldatransparencia.gov.br/download-de-dados/cepim',
  },
  {
    fonte: 'Portal da Transparência — Emendas e Convênios',
    dados: 'Emendas parlamentares individuais e de bancada, convênios e repasses federais.',
    uso: 'Base do módulo "Emendas Parlamentares" e do rastreamento emenda → convênio → fornecedor.',
    href: 'https://portaldatransparencia.gov.br/emendas',
  },
];

const fontesOutras = [
  { fonte: 'API de Dados Abertos da Câmara dos Deputados', dados: 'Gastos de gabinete (CEAP), discursos, proposições, comissões, presença, votações, dados cadastrais.', href: 'https://dadosabertos.camara.leg.br' },
  { fonte: 'TSE — Dados Abertos', dados: 'Resultados eleitorais 2022 por seção de votação, geolocalização de urnas.', href: 'https://dadosabertos.tse.jus.br' },
  { fonte: 'Receita Federal — Dados Abertos de CNPJ', dados: 'Quadro societário de empresas beneficiadas por gastos e emendas.', href: 'https://dados.rfb.gov.br' },
  { fonte: 'IBGE', dados: 'Dados censitários e indicadores municipais usados nos mapas.', href: 'https://www.ibge.gov.br' },
];

const funcionalidades = [
  {
    titulo: 'Detalhamento de Gastos (CEAP)',
    resumo: 'Consumo dos dados de reembolso de gabinete de cada deputado, com detecção de notas fiscais atípicas.',
    detalhe:
      'Coletamos as notas da Cota para Exercício da Atividade Parlamentar via API da Câmara e as organizamos por fornecedor, categoria e mês. Um algoritmo de desvio-padrão sinaliza valores muito acima da média histórica do próprio fornecedor/categoria como "atípicos", para investigação — não como acusação automática.',
  },
  {
    titulo: 'Fornecedores da Cota Parlamentar Sancionados (CEIS/CEPIM)',
    resumo: 'Cruza os fornecedores pagos com a CEAP de um deputado com as bases de sanções da própria CGU.',
    detalhe:
      'Para cada fornecedor identificado por CNPJ nos gastos de CEAP, verificamos se ele consta no CEIS ou no CEPIM. Isso é feito por comparação exata de CNPJ (normalizado, sem pontuação). Disclaimer explícito na tela: gasto de CEAP é ressarcimento, não licitação — não há obrigação legal de o parlamentar consultar essas bases antes de escolher um fornecedor (diferente de convênios/emendas). O alerta é de transparência, não de irregularidade.',
  },
  {
    titulo: 'Emendas Parlamentares e Alertas de Integridade',
    resumo: 'Rastreia o fluxo emenda → convênio → fornecedor → sócios, e cruza com CEIS/CEPIM.',
    detalhe:
      'As emendas de cada deputado são coletadas via Portal da Transparência (mantido pela CGU). Documentos de pagamento (notas de empenho, ordens bancárias) trazem o CNPJ do beneficiário, que cruzamos com CEIS/CEPIM para identificar repasses a entidades sancionadas — e com a Receita Federal para mapear sócios em comum com o próprio parlamentar, seus assessores ou doadores de campanha.',
  },
  {
    titulo: 'Sociograma de Conexões Financeiras',
    resumo: 'Grafo mostrando fornecedores compartilhados entre deputados.',
    detalhe:
      'A partir dos gastos de CEAP, identificamos fornecedores usados por múltiplos parlamentares e construímos um grafo (deputado → fornecedor → outros deputados). Fornecedores sancionados no CEIS/CEPIM aparecem destacados em vermelho, com um nó de sanção conectado explicitamente no grafo.',
  },
  {
    titulo: 'Odiograma — Redes de Citações em Discursos',
    resumo: 'Mapeia quem cita quem em discursos no plenário, com classificação de sentimento.',
    detalhe:
      'Discursos são coletados da Câmara, processados com um modelo de linguagem (LLM) para extrair citações nominais a outros parlamentares e classificar o tom (apoio, crítica, neutro, questionador). O resultado alimenta um grafo de relacionamento.',
  },
  {
    titulo: 'Mapa Eleitoral e Mapa Partidário',
    resumo: 'Geolocalização de votos por seção eleitoral, cruzada com dados do TSE.',
    detalhe:
      'Usamos os resultados eleitorais de 2022 do TSE, agregados por local de votação, para mostrar redutos eleitorais e a força de cada parlamentar/partido território a território.',
  },
  {
    titulo: 'Presença Parlamentar',
    resumo: 'Frequência em sessões do Plenário e reuniões de comissões.',
    detalhe:
      'Consolidamos os registros oficiais de presença da Câmara por deputado, comissão e período, com evolução mensal e ranking por órgão.',
  },
  {
    titulo: 'Análise de Imprensa',
    resumo: 'Monitoramento de menções a parlamentares na mídia.',
    detalhe:
      'Coleta automática de notícias públicas mencionando cada deputado, para medir presença e tom da cobertura midiática.',
  },
  {
    titulo: 'Busca Semântica, Chat Parlamentar e Robô Antunes',
    resumo: 'Assistentes de IA para explorar os dados em linguagem natural.',
    detalhe:
      'Utilizamos busca vetorial (ChromaDB) sobre discursos e documentos, e um modelo de linguagem (atualmente gpt-5.4-mini) para responder perguntas e gerar relatórios de auditoria automatizados. Todo relatório gerado por IA traz o aviso de que exige validação humana e jurídica antes de qualquer uso formal.',
  },
];

export default function Metodologia() {
  const navigate = useNavigate();
  const [expandido, setExpandido] = useState(false);

  const handleAccordion = (painel) => (event, isExpanded) => {
    setExpandido(isExpanded ? painel : false);
  };

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Breadcrumbs separator={<NavigateNext fontSize="small" />} sx={{ mb: 2 }}>
        <Link underline="hover" color="inherit" onClick={() => navigate('/')} sx={{ cursor: 'pointer' }}>
          Home
        </Link>
        <Typography color="text.primary">Metodologia</Typography>
      </Breadcrumbs>

      <Box sx={{ mb: 5 }}>
        <Typography variant="h3" sx={{ fontWeight: 'bold', color: brandColors.azul, mb: 1, fontSize: { xs: '2rem', md: '2.75rem' } }}>
          Eu Sei Disso, Deputado!
        </Typography>
        <Typography variant="h6" sx={{ color: brandColors.cinza, fontWeight: 'normal', mb: 2 }}>
          Metodologia, fontes de dados e reúso de dados abertos da CGU
        </Typography>
        <Typography variant="body1" sx={{ color: '#444', maxWidth: 820 }}>
          Este projeto é um sistema de auditoria e transparência parlamentar que integra dados abertos da
          Câmara dos Deputados, TSE, Receita Federal, IBGE e, de forma central, da própria{' '}
          <strong>Controladoria-Geral da União (CGU)</strong> — para cruzar gastos, emendas e contratos de
          parlamentares brasileiros com as bases oficiais de sanções e transparência. Desenvolvido como
          Trabalho de Conclusão de Curso na UNIVESP.
        </Typography>
      </Box>

      {/* Fontes CGU */}
      <Paper sx={{ p: { xs: 3, md: 4 }, mb: 4, borderRadius: '24px', border: `2px solid ${brandColors.verde}22`, boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
        <SectionTitle icon={<Gavel sx={{ fontSize: 34, color: brandColors.verde }} />}>
          Dados Abertos da CGU Utilizados
        </SectionTitle>
        <Typography variant="body2" sx={{ color: brandColors.cinza, mb: 3 }}>
          A CGU é a fonte de dados mais diretamente ligada à missão deste projeto: identificar riscos de
          integridade no uso de recursos públicos por parlamentares.
        </Typography>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Fonte</TableCell>
                <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>O que é</TableCell>
                <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Como usamos</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {fontesCGU.map((f, i) => (
                <TableRow key={i} sx={{ '&:hover': { bgcolor: '#F8FAFC' } }}>
                  <TableCell>
                    <Link href={f.href} target="_blank" rel="noopener noreferrer" sx={{ fontWeight: 'bold' }}>
                      {f.fonte}
                    </Link>
                  </TableCell>
                  <TableCell sx={{ color: '#444' }}>{f.dados}</TableCell>
                  <TableCell sx={{ color: '#444' }}>{f.uso}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Outras fontes */}
      <Paper sx={{ p: { xs: 3, md: 4 }, mb: 4, borderRadius: '24px', border: '1px solid #E0E0E0', boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
        <SectionTitle icon={<Public sx={{ fontSize: 34, color: brandColors.azul }} />}>
          Outras Fontes de Dados Abertos
        </SectionTitle>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Fonte</TableCell>
                <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>O que fornece</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {fontesOutras.map((f, i) => (
                <TableRow key={i} sx={{ '&:hover': { bgcolor: '#F8FAFC' } }}>
                  <TableCell>
                    <Link href={f.href} target="_blank" rel="noopener noreferrer" sx={{ fontWeight: 'bold' }}>
                      {f.fonte}
                    </Link>
                  </TableCell>
                  <TableCell sx={{ color: '#444' }}>{f.dados}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Metodologia por funcionalidade */}
      <Paper sx={{ p: { xs: 3, md: 4 }, mb: 4, borderRadius: '24px', border: '1px solid #E0E0E0', boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
        <SectionTitle icon={<Insights sx={{ fontSize: 34, color: brandColors.azul }} />}>
          Metodologia por Funcionalidade
        </SectionTitle>
        {funcionalidades.map((f, i) => (
          <Accordion
            key={i}
            expanded={expandido === `painel-${i}`}
            onChange={handleAccordion(`painel-${i}`)}
            sx={{ mb: 1, borderRadius: '12px !important', overflow: 'hidden', '&:before': { display: 'none' }, border: '1px solid #EEE' }}
          >
            <AccordionSummary expandIcon={<ExpandMore />} sx={{ '&:hover': { bgcolor: '#F8FAFC' } }}>
              <Box>
                <Typography sx={{ fontWeight: 'bold', color: brandColors.azul }}>{f.titulo}</Typography>
                <Typography variant="body2" sx={{ color: brandColors.cinza }}>{f.resumo}</Typography>
              </Box>
            </AccordionSummary>
            <AccordionDetails sx={{ borderTop: '1px solid #EEE', pt: 2 }}>
              <Typography variant="body2" sx={{ color: '#444', lineHeight: 1.7 }}>{f.detalhe}</Typography>
            </AccordionDetails>
          </Accordion>
        ))}
      </Paper>

      {/* Stack tecnico */}
      <Paper sx={{ p: { xs: 3, md: 4 }, mb: 4, borderRadius: '24px', border: '1px solid #E0E0E0', boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
        <SectionTitle icon={<Storage sx={{ fontSize: 34, color: brandColors.azul }} />}>
          Arquitetura e Tecnologias
        </SectionTitle>
        <Grid container spacing={3}>
          <Grid item xs={12} md={4}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', color: brandColors.verde, mb: 1 }}>Backend</Typography>
            <Typography variant="body2" sx={{ color: '#444' }}>
              Python, FastAPI, SQLite, DuckDB (dados eleitorais), ChromaDB (busca vetorial), Pandas.
            </Typography>
          </Grid>
          <Grid item xs={12} md={4}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', color: brandColors.verde, mb: 1 }}>Frontend</Typography>
            <Typography variant="body2" sx={{ color: '#444' }}>
              React, Material-UI, ECharts, Leaflet (mapas), Recharts.
            </Typography>
          </Grid>
          <Grid item xs={12} md={4}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', color: brandColors.verde, mb: 1 }}>Inteligência Artificial</Typography>
            <Typography variant="body2" sx={{ color: '#444' }}>
              Modelo de linguagem para classificação de sentimento, geração de relatórios de auditoria e busca semântica.
            </Typography>
          </Grid>
        </Grid>
      </Paper>

      {/* Disclaimers e integridade */}
      <Paper sx={{ p: { xs: 3, md: 4 }, mb: 4, borderRadius: '24px', border: `2px solid ${brandColors.laranjaEscuro}33`, boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
        <SectionTitle icon={<Security sx={{ fontSize: 34, color: brandColors.laranjaEscuro }} />}>
          Limites, Disclaimers e Uso Responsável
        </SectionTitle>
        <Alert severity="warning" variant="outlined" sx={{ mb: 2, borderRadius: '12px' }}>
          <strong>Nenhum alerta deste sistema é, por si só, evidência de irregularidade ou ilegalidade.</strong>{' '}
          São cruzamentos automatizados de dados públicos que apontam pontos de atenção para investigação
          humana, jornalística ou institucional — nunca uma conclusão definitiva.
        </Alert>
        <Alert severity="info" variant="outlined" sx={{ mb: 2, borderRadius: '12px' }}>
          Cruzamentos por nome civil (sócios, doadores, assessores) podem gerar homônimos, já que o CPF de
          pessoas físicas não é público. Todo resultado deve ser tratado como <strong>risco forense</strong>,
          sujeito a verificação manual, em respeito à LGPD e à presunção de inocência.
        </Alert>
        <Alert severity="info" variant="outlined" sx={{ borderRadius: '12px' }}>
          Relatórios gerados por inteligência artificial (Robô Antunes) são um ponto de partida para
          investigação, não uma peça pronta para uso jurídico — exigem revisão humana antes de qualquer
          encaminhamento formal.
        </Alert>
      </Paper>

      {/* Rodapé / autoria */}
      <Box sx={{ textAlign: 'center', py: 4 }}>
        <VerifiedUser sx={{ fontSize: 32, color: brandColors.verde, mb: 1 }} />
        <Typography variant="body2" sx={{ color: brandColors.cinza }}>
          Projeto open source. Trabalho de Conclusão de Curso — UNIVESP.
        </Typography>
        <Typography variant="body2" sx={{ color: brandColors.cinza }}>
          Autor: Aislan Greca
        </Typography>
        <Chip
          icon={<AutoAwesome sx={{ fontSize: 16 }} />}
          label="Inscrito no 2º Concurso de Reúso de Dados Abertos da CGU"
          sx={{ mt: 2, bgcolor: `${brandColors.verde}15`, color: brandColors.verde, fontWeight: 'bold' }}
        />
      </Box>
    </Container>
  );
}

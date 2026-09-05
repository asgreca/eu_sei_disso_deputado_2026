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
    uso: 'Cruzado com entidades beneficiadas por emendas parlamentares e com fornecedores da cota parlamentar (CEAP).',
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
  { fonte: 'API de Dados Abertos da Câmara dos Deputados', dados: 'Gastos de gabinete (CEAP), discursos, proposições votadas, comissões, presença, votações nominais, dados cadastrais dos deputados.', href: 'https://dadosabertos.camara.leg.br' },
  { fonte: 'TSE — Dados Abertos', dados: 'Resultados eleitorais 2022 por seção de votação, geolocalização de urnas, e prestação de contas de campanha (doações recebidas pelos candidatos).', href: 'https://dadosabertos.tse.jus.br' },
  { fonte: 'Receita Federal — Dados Abertos de CNPJ', dados: 'Quadro societário de empresas beneficiadas por gastos e emendas.', href: 'https://dados.rfb.gov.br' },
  { fonte: 'IBGE — Setores Censitários', dados: 'Polígonos de setores censitários e indicadores socioeconômicos, cruzados espacialmente com as seções eleitorais para caracterizar redutos no Mapa Eleitoral.', href: 'https://www.ibge.gov.br' },
  { fonte: 'Câmara dos Deputados — Portal da Transparência RH', dados: 'Quadro de secretários parlamentares (assessores de gabinete): lotação, salário e data de admissão.', href: 'https://www.camara.leg.br/transparencia/recursos-humanos/funcionarios' },
];

const funcionalidades = [
  {
    titulo: 'Detalhamento de Gastos (CEAP)',
    resumo: 'Consumo dos dados de reembolso de gabinete de cada deputado, com detecção de notas fiscais atípicas.',
    detalhe:
      'Coletamos as notas da Cota para Exercício da Atividade Parlamentar via API da Câmara e as organizamos por fornecedor, categoria e mês. Uma nota é sinalizada como "atípica" quando seu valor ultrapassa a média + 2 desvios-padrão de todos os gastos já registrados naquela mesma categoria (rubrica), somando todos os deputados — um limite estatístico, não uma acusação automática.',
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
    titulo: 'Votações — Geral e por Parlamentar',
    resumo: 'Como cada deputado votou em cada proposição, e o quanto isso esteve alinhado com a pauta do Governo.',
    detalhe:
      'Coletamos os votos nominais registrados pela Câmara em cada votação e classificamos, projeto a projeto, se ele era ou não de interesse do Governo (pauta do Executivo). O "índice de alinhamento" mostrado no site é o percentual de vezes em que o voto do deputado acompanhou essa pauta governista — não a orientação do partido do próprio deputado. Um modelo de linguagem apoia a classificação de tema e contexto das votações mais complexas.',
  },
  {
    titulo: 'Atuação em Comissões',
    resumo: 'Relatório de atuação de um deputado dentro de uma comissão específica, a partir dos discursos.',
    detalhe:
      'A partir das notas taquigráficas e discursos feitos por um deputado dentro de uma comissão, geramos um relatório de atuação — do que ele efetivamente discutiu e defendeu naquele órgão, com apoio de IA para resumir o conteúdo. É uma funcionalidade distinta da Presença Parlamentar: aqui o foco é o conteúdo da atuação, não a frequência.',
  },
  {
    titulo: 'Presença Parlamentar',
    resumo: 'Frequência em sessões do Plenário e reuniões de comissões.',
    detalhe:
      'Consolidamos os registros oficiais de presença da Câmara por deputado, comissão e período, com evolução mensal e ranking por órgão. Um modelo de linguagem pode gerar uma análise das reuniões que o deputado perdeu, resumindo o que foi discutido em sua ausência.',
  },
  {
    titulo: 'Assessores de Gabinete',
    resumo: 'Quadro de secretários parlamentares e custo de folha de cada gabinete.',
    detalhe:
      'Coletamos, na página de Recursos Humanos da Câmara, o nome, a lotação, o salário e a data de admissão dos secretários parlamentares de cada gabinete. Esses nomes são comparados (por correspondência exata, normalizada) com o quadro societário de empresas beneficiadas por emendas do mesmo deputado, sinalizando quando um assessor de gabinete aparece como sócio de uma empresa beneficiada.',
  },
  {
    titulo: 'Passagens Aéreas e Investigação de Passageiros (OSINT)',
    resumo: 'Detalhamento de trechos aéreos pagos com a cota parlamentar, com investigação de possíveis acompanhantes.',
    detalhe:
      'Além de detalhar as passagens aéreas custeadas pela CEAP (mesma regra de detecção de valores atípicos), o sistema permite investigar um nome de passageiro específico: cruza esse nome com bases públicas e faz uma varredura OSINT (fontes abertas na web) para checar se aparece associado a esse deputado, útil para identificar viagens de terceiros custeadas com dinheiro público.',
  },
  {
    titulo: 'Análise de Imprensa',
    resumo: 'Monitoramento de menções a parlamentares na mídia, com pontuação de sentimento por notícia.',
    detalhe:
      'Coletamos automaticamente notícias públicas mencionando cada deputado e atribuímos uma pontuação de sentimento a cada uma. A partir desse conjunto, um modelo de linguagem gera um dossiê de auditoria sobre o potencial midiático e a cobertura recebida pelo parlamentar.',
  },
  {
    titulo: 'Busca Semântica, Chat Parlamentar e Robô Antunes',
    resumo: 'IA para explorar os dados em linguagem natural e para gerar relatórios de auditoria automatizados nas demais telas.',
    detalhe:
      'Utilizamos busca vetorial (ChromaDB) sobre discursos e documentos para a Busca Semântica e o Chat Parlamentar. O "Robô Antunes" é o mesmo modelo de linguagem (atualmente gpt-5.4-mini) aplicado, em várias telas do site (Gastos, Emendas, Comissões, Presença, Imprensa), à geração de relatórios de auditoria a partir dos dados já filtrados. Todo relatório gerado por IA traz o aviso de que exige validação humana e jurídica antes de qualquer uso formal.',
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

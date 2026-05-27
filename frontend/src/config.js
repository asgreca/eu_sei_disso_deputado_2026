/**
 * Configuração centralizada da API
 * Lê do .env automaticamente
 */

// URL base da API (local ou remoto)
export const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// API Key para autenticação
export const API_KEY = process.env.REACT_APP_API_KEY || 'camara_dash_2025_secure_key_f8218282a4707045fd28f6af485b3eae';

// Headers padrão para todas as requisições
export const API_HEADERS = {
  'Content-Type': 'application/json',
  'X-API-Key': API_KEY
};

// Configuração do axios (use isso em todos os arquivos)
export const axiosConfig = {
  baseURL: API_BASE_URL,
  headers: API_HEADERS
};

// Mensagem de erro amigável
export const handleApiError = (error) => {
  if (error.response?.status === 401 || error.response?.status === 403) {
    return 'Erro de autenticação. Verifique a configuração da API Key.';
  }
  return error.response?.data?.detail || error.message || 'Erro ao conectar com a API';
};

console.log('🔧 Configuração da API:');
console.log('   URL:', API_BASE_URL);
console.log('   Auth:', API_KEY ? '✅ API Key configurada' : '⚠️ API Key ausente');

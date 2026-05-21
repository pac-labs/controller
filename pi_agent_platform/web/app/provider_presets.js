const PROVIDER_PRESETS = {
  'openai': {name:'openai', type:'openai', base_url:'https://api.openai.com/v1', api_key_env:'OPENAI_API_KEY'},
  'openai-codex': {name:'openai-codex', type:'openai-codex', base_url:'https://api.openai.com/v1', api_key_env:'OPENAI_API_KEY'},
  'anthropic': {name:'anthropic', type:'anthropic', base_url:'https://api.anthropic.com/v1', api_key_env:'ANTHROPIC_API_KEY'},
  'minimax': {name:'minimax', type:'minimax', base_url:'https://api.minimax.io/anthropic/v1', api_key_env:'MINIMAX_API_KEY'},
  'gemini': {name:'gemini', type:'gemini', base_url:'https://generativelanguage.googleapis.com/v1beta', api_key_env:'GEMINI_API_KEY'},
  'groq': {name:'groq', type:'groq', base_url:'https://api.groq.com/openai/v1', api_key_env:'GROQ_API_KEY'},
  'openrouter': {name:'openrouter', type:'openrouter', base_url:'https://openrouter.ai/api/v1', api_key_env:'OPENROUTER_API_KEY'},
  'deepseek': {name:'deepseek', type:'deepseek', base_url:'https://api.deepseek.com/v1', api_key_env:'DEEPSEEK_API_KEY'},
  'mistral': {name:'mistral', type:'mistral', base_url:'https://api.mistral.ai/v1', api_key_env:'MISTRAL_API_KEY'},
  'lmstudio': {name:'lmstudio', type:'lmstudio', base_url:'http://localhost:1234/v1', api_key_env:''},
  'ollama': {name:'ollama', type:'ollama', base_url:'http://localhost:11434', api_key_env:''},
  'vllm': {name:'vllm', type:'vllm', base_url:'http://localhost:8000/v1', api_key_env:''},
  'custom-openai': {name:'custom-openai', type:'openai-compatible', base_url:'', api_key_env:''},
  'custom-anthropic': {name:'custom-anthropic', type:'anthropic-compatible', base_url:'', api_key_env:''},
};
function applyProviderPreset(key) {
  const preset = PROVIDER_PRESETS[key];
  if (!preset) return;
  if (!providerName.value.trim()) providerName.value = preset.name;
  providerType.value = preset.type;
  providerBaseUrl.value = preset.base_url || '';
  providerApiKeyEnv.value = preset.api_key_env || '';
  if (!providerTimeout.value) providerTimeout.value = 30;
  setModalStatus('providerModalStatus', `${preset.name} preset loaded`);
}

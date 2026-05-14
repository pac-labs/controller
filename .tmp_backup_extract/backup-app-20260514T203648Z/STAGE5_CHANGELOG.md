# Stage 5 changelog

## Added

- Provider registry for OpenAI, OpenAI-compatible servers, LM Studio, Ollama and vLLM.
- Model capability cards: `runs_on`, context window, output budget, tool/json/vision/streaming flags.
- Context profiles with token budgets and output/history/file-context reservations.
- Effective context calculation endpoint using the safe minimum of model and selected profile.
- Provider health test endpoints.
- Model smoke-test endpoints for OpenAI-compatible, LM Studio, vLLM and Ollama style APIs.
- Web UI panels for providers and models, including test buttons.
- One-command Linux installer: `./install.sh`.
- GitHub Actions workflow to produce a single-file Linux binary using PyInstaller.

## Important notes

- The Pi host is the PAC. Models can run on OpenAI, LM Studio on your desktop, Ollama on another server, vLLM on a GPU host, etc.
- Declaring a large context window in this PAC does not force the model server to support it. Configure the model server too.
- The effective context is deliberately conservative: model context window and selected profile budget are combined using the minimum.

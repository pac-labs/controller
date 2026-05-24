// Focused session UI helpers extracted from sessions.js.

function slashCommandHelpText() {
  const commands = (sessionSlashCommands && sessionSlashCommands.length) ? sessionSlashCommands : Object.values(SESSION_SLASH_COMMANDS);
  return commands.map(c => `${c.label} - ${c.description}`).join('\n');
}

function isHelpSlashCommand(raw) {
  return String(raw || '').trim().toLowerCase() === '/help';
}

function appendText(parent, tag, className, text) {
  if (text == null || text === '') return null;
  const el = document.createElement(tag);
  if (className) el.className = className;
  el.textContent = String(text);
  parent.appendChild(el);
  return el;
}

function normalizeAssistantText(text) {
  const normalized = String(text || '')
    .replace(/\$\\rightarrow\$/g, '→')
    .replace(/\$\\leftarrow\$/g, '←')
    .replace(/\{\\rightarrow\}/g, '→')
    .replace(/\{\\leftarrow\}/g, '←')
    .replace(/<\|tool_call\>[\s\S]*?<tool_call\|>/g, '')
    .replace(/<\|tool_call[\s\S]*$/g, '')
    .replace(/^\s*call:(?:tool_call:)?[A-Za-z0-9_:-]+\s*[\[{][\s\S]*$/gm, '')
    .replace(/\r\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  const blockLike = (line) => /^\s*(?:[-*+]\s+|\d+\.\s+|#{1,6}\s+|>\s+|```|~~~|\|)/.test(line);
  const lines = normalized.split('\n');
  const rebuilt = [];
  let paragraph = '';
  const flushParagraph = () => {
    if (!paragraph) return;
    rebuilt.push(paragraph);
    paragraph = '';
  };
  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      if (rebuilt[rebuilt.length - 1] !== '') rebuilt.push('');
      return;
    }
    if (blockLike(line)) {
      flushParagraph();
      rebuilt.push(line);
      return;
    }
    if (!paragraph) {
      paragraph = trimmed;
      return;
    }
    paragraph += ` ${trimmed}`;
  });
  flushParagraph();
  return rebuilt.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}


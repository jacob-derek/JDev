/* A small, dependency-free Markdown renderer for the formats used in the study. */
(function (global) {
  'use strict';

  const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[ch]);

  const slugify = (value) => value.toLowerCase().trim()
    .replace(/<[^>]*>/g, '')
    .replace(/&[a-z]+;/gi, '')
    .replace(/[^\p{L}\p{N}_ -]/gu, '')
    .replace(/\s+/g, '-');

  function inline(source, context) {
    const codeSpans = [];
    let text = source.replace(/`([^`]+)`/g, (_, code) => {
      const token = `\u0000CODE${codeSpans.length}\u0000`;
      codeSpans.push(`<code>${escapeHTML(code)}</code>`);
      return token;
    });
    text = escapeHTML(text);

    text = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, target) => {
      const href = context.resolveLink(target.trim(), true);
      return `<img src="${escapeHTML(href)}" alt="${alt}" loading="lazy">`;
    });
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, target) => {
      const href = context.resolveLink(target.trim(), false);
      const isExternal = /^https?:\/\//i.test(href);
      const attrs = isExternal ? ' target="_blank" rel="noopener noreferrer"' : '';
      return `<a href="${escapeHTML(href)}"${attrs}>${label}</a>`;
    });
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/__(.+?)__/g, '<strong>$1</strong>')
      .replace(/\*(?!\s)(.+?)(?<!\s)\*/g, '<em>$1</em>')
      .replace(/_(?!\s)(.+?)(?<!\s)_/g, '<em>$1</em>')
      .replace(/~~(.+?)~~/g, '<del>$1</del>');
    return text.replace(/\u0000CODE(\d+)\u0000/g, (_, index) => codeSpans[Number(index)] || '');
  }

  const isTableDivider = (line) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const splitTableRow = (line) => {
    let content = line.trim();
    if (content.startsWith('|')) content = content.slice(1);
    if (content.endsWith('|')) content = content.slice(0, -1);
    return content.split(/(?<!\\)\|/).map((cell) => cell.replace(/\\\|/g, '|').trim());
  };
  const isListStart = (line) => /^\s*(?:[-+*]|\d+[.)])\s+/.test(line);

  function renderList(lines, start, context) {
    const first = lines[start].match(/^(\s*)([-+*]|\d+[.)])\s+(.*)$/);
    const indent = first[1].replace(/\t/g, '    ').length;
    const ordered = /^\d/.test(first[2]);
    const tag = ordered ? 'ol' : 'ul';
    const items = [];
    let index = start;
    let current = null;

    while (index < lines.length) {
      const line = lines[index];
      const match = line.match(/^(\s*)([-+*]|\d+[.)])\s+(.*)$/);
      const lineIndent = match ? match[1].replace(/\t/g, '    ').length : -1;
      if (!line.trim()) {
        let look = index + 1;
        while (look < lines.length && !lines[look].trim()) look++;
        const nextMatch = lines[look] && lines[look].match(/^(\s*)([-+*]|\d+[.)])\s+/);
        const nextIndent = nextMatch ? nextMatch[1].replace(/\t/g, '    ').length : -1;
        if (nextIndent > indent) { if (current) current.push(''); index++; continue; }
        break;
      }
      if (match && lineIndent === indent && (/^\d/.test(match[2]) === ordered)) {
        current = [match[3]];
        items.push(current);
      } else if (match && lineIndent <= indent) {
        break;
      } else if (current && lineIndent > indent) {
        current.push(line.replace(/^\s+/, (spaces) => ' '.repeat(Math.max(0, spaces.replace(/\t/g, '    ').length - indent - 2))));
      } else if (current && !match) {
        current.push(line.trim());
      } else {
        break;
      }
      index++;
    }
    const body = items.map((item) => `<li>${renderBlocks(item, context)}</li>`).join('');
    return { html: `<${tag}>${body}</${tag}>`, next: index };
  }

  function renderBlocks(lines, context) {
    const output = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index++; continue; }

      const fence = line.match(/^\s*```\s*([\w+-]*)\s*$/);
      if (fence) {
        const language = (fence[1] || 'text').toLowerCase();
        const body = [];
        index++;
        while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) body.push(lines[index++]);
        if (index < lines.length) index++;
        const code = body.join('\n');
        if (language === 'mermaid') {
          output.push(`<div class="diagram-block"><div class="diagram-heading"><span>System diagram</span><button type="button" class="diagram-source-toggle">Show source</button></div><div class="mermaid">${escapeHTML(code)}</div><details class="diagram-source"><summary>Diagram source</summary><pre><code>${escapeHTML(code)}</code></pre></details></div>`);
        } else {
          output.push(`<pre><span class="code-label">${escapeHTML(language)}</span><code class="language-${escapeHTML(language)}">${escapeHTML(code)}</code></pre>`);
        }
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
      if (heading) {
        const level = heading[1].length;
        const rendered = inline(heading[2], context);
        const id = slugify(heading[2].replace(/`([^`]*)`/g, '$1').replace(/!?\[([^\]]+)\]\([^)]+\)/g, '$1')) || `section-${index}`;
        output.push(`<h${level} id="${escapeHTML(id)}">${rendered}<a class="heading-anchor" href="#${escapeHTML(id)}" aria-label="Link to this section">#</a></h${level}>`);
        index++;
        continue;
      }

      if (/^\s*(---+|___+|\*\*\*+)\s*$/.test(line)) { output.push('<hr>'); index++; continue; }

      if (/^\s*>/.test(line)) {
        const quote = [];
        while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(lines[index++].replace(/^\s*>\s?/, ''));
        output.push(`<blockquote>${renderBlocks(quote, context)}</blockquote>`);
        continue;
      }

      if (line.includes('|') && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
        const headers = splitTableRow(line);
        const alignments = splitTableRow(lines[index + 1]).map((cell) => cell.startsWith(':') && cell.endsWith(':') ? 'center' : cell.endsWith(':') ? 'right' : 'left');
        index += 2;
        const rows = [];
        while (index < lines.length && lines[index].includes('|') && lines[index].trim()) rows.push(splitTableRow(lines[index++]));
        const th = headers.map((cell, col) => `<th style="text-align:${alignments[col] || 'left'}">${inline(cell, context)}</th>`).join('');
        const tbody = rows.map((row) => `<tr>${headers.map((_, col) => `<td style="text-align:${alignments[col] || 'left'}">${inline(row[col] || '', context)}</td>`).join('')}</tr>`).join('');
        output.push(`<div class="table-scroll"><table><thead><tr>${th}</tr></thead><tbody>${tbody}</tbody></table></div>`);
        continue;
      }

      if (isListStart(line)) {
        const list = renderList(lines, index, context);
        output.push(list.html);
        index = Math.max(index + 1, list.next);
        continue;
      }

      const paragraph = [line.trim()];
      index++;
      while (index < lines.length && lines[index].trim() &&
        !/^\s*```/.test(lines[index]) && !/^#{1,6}\s/.test(lines[index]) &&
        !/^\s*>/.test(lines[index]) && !isListStart(lines[index]) &&
        !(lines[index].includes('|') && index + 1 < lines.length && isTableDivider(lines[index + 1])) &&
        !/^\s*(---+|___+|\*\*\*+)\s*$/.test(lines[index])) {
        paragraph.push(lines[index++].trim());
      }
      output.push(`<p>${inline(paragraph.join('\n').replace(/\n/g, ' '), context)}</p>`);
    }
    return output.join('\n');
  }

  function render(markdown, context) {
    const lines = markdown.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').split('\n');
    return renderBlocks(lines, context);
  }

  global.StudyMarkdown = { render, slugify, escapeHTML };
})(window);

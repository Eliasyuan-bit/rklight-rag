// In-page reader for evidence links emitted by the LightRAG query API.
(() => {
  const pathPattern = /^\/query\/references\/([A-Za-z0-9_.:-]{1,200})(?:\/view)?$/;
  const referenceId = (href) => {
    try {
      const url = new URL(href, location.href);
      return url.origin === location.origin ? pathPattern.exec(url.pathname)?.[1] : null;
    } catch (_) { return null; }
  };
  const viewUrl = (id) => `/query/references/${encodeURIComponent(id)}/view#cited-passage`;

  const style = document.createElement('style');
  style.textContent = `
    #rk-ref-shade{display:none;position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,.24)}
    #rk-ref-reader{--rk-bg:var(--background,#fff);--rk-fg:var(--foreground,#222);--rk-muted:var(--muted-foreground,#666);--rk-line:var(--border,#ddd);--rk-accent:var(--primary,#222);--rk-tint:var(--muted,#f6f6f6);display:none;position:fixed;top:0;right:0;bottom:0;z-index:9999;width:min(720px,100vw);background:var(--rk-bg);color:var(--rk-fg);box-shadow:-16px 0 48px rgba(0,0,0,.13);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;flex-direction:column}
    #rk-ref-reader *{box-sizing:border-box}
    #rk-ref-reader .rk-head{display:flex;gap:16px;align-items:flex-start;padding:24px 28px 20px;border-bottom:1px solid var(--rk-line)}
    #rk-ref-reader .rk-doc-icon{display:grid;place-items:center;flex:none;width:38px;height:42px;border:1px solid var(--rk-line);border-radius:var(--radius,10px);background:var(--rk-tint);color:var(--rk-fg);font-size:12px;font-weight:750;letter-spacing:.04em}
    #rk-ref-reader .rk-title{flex:1;min-width:0}
    #rk-ref-reader .rk-eyebrow{display:block;color:var(--rk-muted);font-size:11px;font-weight:700;letter-spacing:.12em;margin-bottom:5px}
    #rk-ref-reader strong{display:block;font-size:19px;line-height:1.35;overflow-wrap:anywhere;letter-spacing:-.02em}
    #rk-ref-reader small{display:block;color:var(--rk-muted);margin-top:5px;font-size:12px}
    #rk-ref-reader button{font:inherit;cursor:pointer;color:inherit}
    #rk-ref-reader .rk-close{flex:none;display:grid;place-items:center;width:34px;height:34px;border:1px solid var(--rk-line);border-radius:var(--radius,10px);background:transparent;font-size:20px;line-height:1}
    #rk-ref-reader .rk-close:hover,#rk-ref-reader .rk-close:focus-visible{background:var(--rk-tint);outline-color:var(--ring,var(--rk-accent))}
    #rk-ref-reader .rk-evidence{padding:17px 28px 18px;border-bottom:1px solid var(--rk-line);background:var(--rk-bg)}
    #rk-ref-reader .rk-evidence-label{font-size:11px;font-weight:750;letter-spacing:.08em;color:var(--rk-muted);margin-bottom:10px}
    #rk-ref-reader .rk-hits{display:grid;gap:8px;max-height:184px;overflow-y:auto;scrollbar-width:thin}
    #rk-ref-reader .rk-hit{display:grid;grid-template-columns:26px minmax(0,1fr);gap:9px;width:100%;text-align:left;border:1px solid var(--rk-line);border-radius:var(--radius,10px);background:var(--rk-bg);padding:10px 12px}
    #rk-ref-reader .rk-hit:hover{border-color:var(--rk-accent)}
    #rk-ref-reader .rk-hit[aria-current=true]{border-color:var(--rk-accent);background:var(--rk-tint);box-shadow:inset 3px 0 var(--rk-accent)}
    #rk-ref-reader .rk-hit-number{display:grid;place-items:center;width:23px;height:23px;border-radius:7px;background:var(--rk-tint);color:var(--rk-fg);font-size:11px;font-weight:700}
    #rk-ref-reader .rk-hit-copy{display:block;min-width:0}
    #rk-ref-reader .rk-hit-section{display:block;font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    #rk-ref-reader .rk-hit-excerpt{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;color:var(--rk-muted);font-size:12px;line-height:1.5;margin-top:2px;overflow-wrap:anywhere}
    #rk-ref-reader .rk-tools{display:flex;gap:12px;align-items:center;min-height:45px;padding:8px 28px;border-bottom:1px solid var(--rk-line);color:var(--rk-muted);font-size:12px}
    #rk-ref-reader .rk-tools a{margin-left:auto;flex:none;color:var(--rk-fg);text-decoration:none;font-weight:600}
    #rk-ref-reader .rk-tools a:hover{text-decoration:underline}
    #rk-ref-reader .rk-tools details{max-width:45%;overflow-wrap:anywhere}
    #rk-ref-reader .rk-tools summary{cursor:pointer}
    #rk-ref-reader .rk-tools details[open] > div{position:absolute;z-index:2;left:28px;max-width:min(480px,calc(100% - 56px));margin-top:12px;padding:10px 14px;background:var(--rk-bg);border:1px solid var(--rk-line);border-radius:var(--radius,10px);box-shadow:0 8px 22px rgba(0,0,0,.12)}
    #rk-ref-reader .rk-body{display:flex;flex:1;min-height:0;flex-direction:column;background:var(--rk-bg)}
    #rk-ref-reader .rk-body-label{padding:13px 28px 10px;color:var(--rk-muted);font-size:11px;font-weight:750;letter-spacing:.08em}
    #rk-ref-reader iframe{flex:1;width:100%;border:0;background:var(--rk-bg)}
    @media(max-width:760px){#rk-ref-reader{width:100vw}#rk-ref-reader .rk-head{padding:16px 18px}#rk-ref-reader .rk-evidence{padding:13px 18px}#rk-ref-reader .rk-tools{padding:8px 18px}#rk-ref-reader .rk-body-label{padding:10px 18px}#rk-ref-reader .rk-hits{max-height:148px}}
  `;
  document.head.appendChild(style);

  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  const shade = element('div');
  shade.id = 'rk-ref-shade';
  const reader = element('aside');
  reader.id = 'rk-ref-reader';
  reader.setAttribute('role', 'dialog');
  reader.setAttribute('aria-modal', 'false');
  reader.setAttribute('aria-label', '引用文档阅读栏');
  const header = element('header', 'rk-head');
  const icon = element('span', 'rk-doc-icon', 'MD');
  const titleBox = element('div', 'rk-title');
  const eyebrow = element('span', 'rk-eyebrow', '引用来源 · 文档阅读');
  const title = element('strong');
  const subtitle = element('small');
  titleBox.append(eyebrow, title, subtitle);
  const close = element('button', 'rk-close', '×');
  close.type = 'button';
  close.setAttribute('aria-label', '关闭引用阅读栏');
  header.append(icon, titleBox, close);
  const evidence = element('section', 'rk-evidence');
  const evidenceLabel = element('div', 'rk-evidence-label', '本次回答引用的原文');
  const hits = element('nav', 'rk-hits');
  hits.setAttribute('aria-label', '同一文档的引用段落');
  evidence.append(evidenceLabel, hits);
  const tools = element('div', 'rk-tools');
  const note = element('span', '', '知识库入库版本');
  const details = element('details');
  const summary = element('summary', '', '检索详情');
  const detailText = element('div');
  details.append(summary, detailText);
  const openFull = element('a', '', '打开整页 ↗');
  openFull.target = '_blank';
  openFull.rel = 'noopener';
  tools.append(note, details, openFull);
  const frame = element('iframe');
  frame.title = '引用 Markdown 文档';
  frame.referrerPolicy = 'same-origin';
  frame.addEventListener('load', () => {
    // The standalone page has its own sticky heading. In the drawer that
    // heading would duplicate ours and consume space above the evidence.
    try {
      const page = frame.contentDocument;
      if (!page?.getElementById('cited-passage')) return;
      // A framed document must follow the WebUI's switch, not the device's
      // OS color preference (the standalone page still follows the OS).
      const dark = document.documentElement.classList.contains('dark');
      page.documentElement.classList.toggle('rk-dark', dark);
      page.documentElement.classList.toggle('rk-light', !dark);
      page.querySelector('header')?.remove();
      const main = page.querySelector('main');
      if (main) main.style.paddingTop = '6px';
      page.getElementById('cited-passage').scrollIntoView({block: 'start'});
      page.addEventListener('keydown', (event) => { if (event.key === 'Escape') hide(); });
    } catch (_) { /* keep the standalone page when framing is restricted */ }
  });
  const body = element('div', 'rk-body');
  body.append(element('div', 'rk-body-label', '原文上下文'), frame);
  reader.append(header, evidence, tools, body);
  document.body.append(shade, reader);

  let serial = 0;
  let previousFocus = null;
  const hide = () => {
    serial += 1;
    reader.style.display = shade.style.display = 'none';
    frame.removeAttribute('src');
    previousFocus?.focus();
    previousFocus = null;
  };
  close.addEventListener('click', hide);
  shade.addEventListener('click', hide);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && reader.style.display === 'flex') hide();
  });
  const select = (reference, buttons) => {
    for (const [id, button] of buttons) button.setAttribute('aria-current', String(id === reference.chunk_id));
    frame.src = openFull.href = viewUrl(reference.chunk_id);
    detailText.textContent = `入库路径：${reference.file_path || '未知'} · Chunk ID：${reference.chunk_id}`;
    details.open = false;
  };
  const excerpt = (content) => String(content || '')
    .split('\n').map((line) => line.trim())
    .filter((line) => line && !line.startsWith('<!--') && !line.startsWith('```') && !/^#{1,6}\s/.test(line))
    .join(' ').replace(/\s+/g, ' ').replace(/^[-*]>?\s/, '').replace(/[`*_]/g, '').slice(0, 160);
  const preview = async (id) => {
    const response = await fetch(`/query/references/${encodeURIComponent(id)}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  };
  const show = async (link, selectedId) => {
    const request = ++serial;
    previousFocus = link;
    reader.style.display = 'flex';
    shade.style.display = 'block';
    title.textContent = '正在加载引用…';
    subtitle.textContent = '';
    hits.replaceChildren();
    frame.removeAttribute('src');
    openFull.removeAttribute('href');
    close.focus();
    const list = link.closest('ul, ol');
    const bundled = new URL(link.href, location.href).searchParams.get('hits')
      ?.split(',').filter((id) => pathPattern.test(`/query/references/${id}/view`)).slice(0, 32) || [];
    const ids = [...new Set([selectedId, ...bundled, ...[...(list?.querySelectorAll('a[href]') || [])]
      .map((anchor) => referenceId(anchor.href)).filter(Boolean)])];
    try {
      const results = await Promise.allSettled(ids.map(preview));
      if (request !== serial) return;
      const previews = results.filter((item) => item.status === 'fulfilled').map((item) => item.value);
      const selected = previews.find((item) => item.chunk_id === selectedId);
      if (!selected) throw new Error('引用段落无法读取');
      const related = previews.filter((item) => item.source_group_id === selected.source_group_id);
      title.textContent = selected.display_name || '引用文档';
      subtitle.textContent = `${related.length} 处引用 · 点击段落可切换位置`;
      const buttons = new Map();
      for (const [index, item] of related.entries()) {
        const button = element('button', 'rk-hit');
        button.type = 'button';
        button.append(
          element('span', 'rk-hit-number', String(index + 1)),
          (() => {
            const copy = element('span', 'rk-hit-copy');
            copy.append(
              element('span', 'rk-hit-section', item.section || `引用位置 ${index + 1}`),
              element('span', 'rk-hit-excerpt', excerpt(item.content) || '查看该位置的原文')
            );
            return copy;
          })()
        );
        button.addEventListener('click', () => select(item, buttons));
        buttons.set(item.chunk_id, button);
        hits.appendChild(button);
      }
      select(selected, buttons);
    } catch (error) {
      if (request !== serial) return;
      title.textContent = '引用加载失败';
      subtitle.textContent = String(error);
    }
  };
  document.addEventListener('click', (event) => {
    const link = event.target.closest?.('a[href]');
    const id = link && referenceId(link.href);
    if (!id) return;
    event.preventDefault();
    show(link, id);
  });
})();

// Lightweight shared FIFO indicator. No DOM observers or fetch interception:
// the WebUI timer remains entirely owned by the upstream React application.
(() => {
  // One-time migration to the tuned mixed-retrieval defaults. Subsequent
  // manual choices remain untouched.
  const defaultsKey = 'rk3588-rag-defaults-mix-v2';
  if (!localStorage.getItem(defaultsKey)) {
    try {
      const storageKey = 'settings-storage';
      const stored = JSON.parse(localStorage.getItem(storageKey) || '{"state":{},"version":23}');
      stored.state ||= {};
      stored.state.querySettings = {
        ...(stored.state.querySettings || {}),
        mode: 'mix',
        top_k: 6,
        chunk_top_k: 3,
        max_entity_tokens: 500,
        max_relation_tokens: 300,
        max_total_tokens: 3000,
        enable_rerank: true,
        stream: true,
      };
      localStorage.setItem(storageKey, JSON.stringify(stored));
      localStorage.setItem(defaultsKey, '1');
    } catch (_) { /* an invalid client store falls back to upstream defaults */ }
  }

  const id = 'rk3588-query-status-banner';
  const style = document.createElement('style');
  style.textContent = `#${id}{display:none;margin:0;padding:0;border:0;background:transparent;color:inherit;font:inherit;line-height:inherit}`;
  document.head.appendChild(style);
  const banner = document.createElement('span');
  banner.id = id;
  document.body.appendChild(banner);

  const place = () => {
    const candidates = [...document.querySelectorAll('body *')].filter((node) => {
      const text = (node.textContent || '').trim();
      return /^(响应时间|Response time)/.test(text) &&
        ![...node.children].some((child) => /^(响应时间|Response time)/.test((child.textContent || '').trim()));
    });
    const anchor = candidates.at(-1);
    if (anchor && anchor.parentElement) anchor.insertAdjacentElement('afterend', banner);
  };
  const poll = async () => {
    try {
      const response = await fetch('/query/status', {cache: 'no-store'});
      if (!response.ok) return;
      const state = await response.json();
      if (!state.busy) {
        banner.style.display = 'none';
        return;
      }
      place();
      banner.textContent = state.queue_length ? `知识库繁忙，${state.queue_length} 条请求排队` : '知识库繁忙，正在生成回答';
      banner.style.display = 'inline';
    } catch (_) { /* status is informational only */ }
  };
  poll();
  window.setInterval(poll, 2000);
})();

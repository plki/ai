/**
 * Cloudflare Pages Function：OpenAI 兼容 API 的 SSE 流式中转
 *
 * 前端直接把 baseUrl / apiKey / model / messages 发给本函数，
 * 由本函数转发给上游 API 并流式回传 SSE，避免浏览器跨域（CORS）问题。
 * API Key 只保存在用户自己的浏览器 localStorage 中，不进 Cloudflare 持久存储。
 */

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

function json(status, obj) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...CORS, 'Content-Type': 'application/json; charset=utf-8' },
  });
}

export async function onRequest(context) {
  const { request } = context;

  // CORS 预检
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS });
  }
  if (request.method !== 'POST') {
    return json(405, { ok: false, error: '仅支持 POST' });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json(400, { ok: false, error: '请求体不是合法 JSON' });
  }

  const baseUrl = (body.baseUrl || 'https://api.openai.com/v1').replace(/\/+$/, '');
  const apiKey = (body.apiKey || '').trim();
  const model = (body.model || '').trim();
  const messages = Array.isArray(body.messages) ? body.messages : [];

  if (!apiKey) return json(400, { ok: false, error: '请先填写 API Key' });
  if (!model) return json(400, { ok: false, error: '请先填写模型名' });
  if (!messages.length) return json(400, { ok: false, error: '消息不能为空' });

  let upstream;
  try {
    upstream = await fetch(`${baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({ model, messages, stream: true }),
    });
  } catch (e) {
    return json(502, { ok: false, error: `连接上游失败: ${e.message || e}` });
  }

  if (!upstream.ok) {
    let detail = `HTTP ${upstream.status}`;
    try {
      const t = await upstream.text();
      if (t) detail += `: ${t.slice(0, 500)}`;
    } catch {}
    return json(502, { ok: false, error: `上游 API 返回错误 ${detail}` });
  }

  // 原样透传 SSE 流
  return new Response(upstream.body, {
    status: 200,
    headers: {
      ...CORS,
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    },
  });
}

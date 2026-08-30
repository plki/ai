/**
 * Cloudflare Pages Function：拉取 OpenAI 兼容 API 的模型列表
 * 用于顶栏模型下拉框。可返回空列表（前端允许手动输入模型名）。
 */

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

export async function onRequest(context) {
  const { request } = context;
  const url = new URL(request.url);
  const baseUrl = (url.searchParams.get('base_url') || '').replace(/\/+$/, '');
  const apiKey = url.searchParams.get('api_key') || '';

  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
  if (!baseUrl || !apiKey) {
    return new Response(JSON.stringify({ ok: true, models: [] }), {
      status: 200,
      headers: { ...CORS, 'Content-Type': 'application/json' },
    });
  }

  try {
    const resp = await fetch(`${baseUrl}/models`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    if (!resp.ok) {
      return new Response(JSON.stringify({ ok: true, models: [] }), {
        status: 200,
        headers: { ...CORS, 'Content-Type': 'application/json' },
      });
    }
    const data = await resp.json();
    const models = (data.data || []).map((m) => m.id).filter(Boolean);
    return new Response(JSON.stringify({ ok: true, models }), {
      status: 200,
      headers: { ...CORS, 'Content-Type': 'application/json' },
    });
  } catch {
    return new Response(JSON.stringify({ ok: true, models: [] }), {
      status: 200,
      headers: { ...CORS, 'Content-Type': 'application/json' },
    });
  }
}
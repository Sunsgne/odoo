let rpcId = 1;

export async function rpc(url, params) {
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      method: "call",
      id: rpcId++,
      params,
    }),
  });
  const payload = await response.json();
  if (payload.error) {
    const data = payload.error.data || {};
    throw new Error(data.message || payload.error.message || "请求失败");
  }
  return payload.result;
}

export function call(model, method, args = [], kwargs = {}) {
  return rpc(`/web/dataset/call_kw/${model}/${method}`, {
    model,
    method,
    args,
    kwargs,
  });
}

export function who() {
  return rpc("/zenlenet/console/who", {});
}

export function authenticate(db, login, password) {
  return rpc("/web/session/authenticate", { db, login, password });
}

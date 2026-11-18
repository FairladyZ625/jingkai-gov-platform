const timeoutMs = 8000;

class ConnectionError extends Error {}

function createHttp(base) {
  const cookies = new Map();
  return {
    async request(method, path, body) {
      const headers = { accept: 'application/json' };
      if (cookies.size) headers.cookie = [...cookies.values()].join('; ');
      if (body !== undefined) headers['content-type'] = 'application/json';
      const signal = AbortSignal.timeout(timeoutMs);
      let response;
      let responseBody;
      try {
        response = await fetch(base + path, {
          method, headers, signal, redirect: 'manual',
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        responseBody = await response.text();
      } catch {
        throw new ConnectionError(`无法访问后端 ${base}（请求 ${method} ${path}，超时上限 ${timeoutMs / 1000} 秒）`);
      }
      for (const cookie of response.headers.getSetCookie()) {
        const pair = cookie.split(';', 1)[0];
        const name = pair.slice(0, pair.indexOf('='));
        if (name) cookies.set(name, pair);
      }
      try {
        return { status: response.status, body: JSON.parse(responseBody) };
      } catch {
        throw new Error(`HTTP ${response.status} 响应不是 JSON`);
      }
    },
  };
}

module.exports = { createHttp, ConnectionError };

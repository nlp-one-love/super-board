// Contract source: tests/fixtures/gitea-28.2-contract.json, not a live server.
// Deliberately narrow: only board snapshot/move, all unmodelled calls return 501.
const http = require('http');
const names = ['Backlog', 'Ready', 'Building', 'QA', 'Review', 'Blocked', 'Done'];
// Local-only fallback: this environment's Postman dataset backend is unavailable.
// One process/session; never deploy this handler as a shared hosted mock.
const state = new Map();
http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://localhost');
  const page = Number(u.searchParams.get('page') || 1);
  const path = u.pathname;
  console.log(JSON.stringify({method: req.method, path}));
  const prefix = '/api/v1/repos/acme/demo/projects/7';
  const column = state.get('gitea.column') || 2;
  const send = (status, data) => {
    res.writeHead(status, {'Content-Type': 'application/json'});
    res.end(data === undefined ? '' : JSON.stringify(data));
  };
  if (req.method === 'GET' && path === prefix + '/columns') {
    return send(200, page === 1 ? names.map((title, i) => ({id: i + 1, project_id: 7, title})) : []);
  }
  const list = path.match(/\/columns\/(\d+)\/issues$/);
  if (req.method === 'GET' && path.startsWith(prefix) && list) {
    return send(200, page === 1 && Number(list[1]) === column ? [{
      id: 9001, number: 11, title: 'Local contract task', body: '## Blocked by\n- None\n',
      state: 'open', labels: [], assignees: [], html_url: 'https://example.invalid/issues/11'
    }] : []);
  }
  if (req.method === 'POST' && path === prefix + '/issues/9001/move') {
    let body = req.body;
    if (!body) {
      let raw = ''; for await (const chunk of req) raw += chunk;
      try { body = JSON.parse(raw); } catch { return send(422, {message: 'Invalid body'}); }
    }
    if (!Number.isInteger(body.column_id) || body.column_id < 1 || body.column_id > 7) {
      return send(422, {message: 'Unknown column'});
    }
    state.set('gitea.column', body.column_id);
    return send(204);
  }
  return send(501, {message: 'Endpoint not modelled by local board simulation'});
}).listen(process.env.PORT || 4917);

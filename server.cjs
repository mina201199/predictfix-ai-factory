const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
http.createServer((req, res) => {
  const files = { '/': ['index.html', 'text/html'], '/index.html': ['index.html', 'text/html'], '/factory.js': ['factory.js', 'text/javascript'], '/factory.css': ['factory.css', 'text/css'] };
  const file = files[req.url];
  if (file) {
    res.writeHead(200, { 'Content-Type': file[1] + '; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(fs.readFileSync(path.join(__dirname, file[0])));
  } else { res.writeHead(404); res.end('Not found'); }
}).listen(8080, '127.0.0.1', () => console.log('Vulkrion demo: http://127.0.0.1:8080'));

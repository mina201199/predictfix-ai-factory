// Standalone static preview; no connection to the factory API or database.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../sites/predictfix-mobile/dist');
const port = Number(process.env.MOBILE_DEMO_PORT || 8096);
const files = {'/':['index.html','text/html'], '/index.html':['index.html','text/html'], '/app.css':['app.css','text/css'], '/app.js':['app.js','text/javascript']};
http.createServer((req,res)=>{
  const file=files[new URL(req.url,'http://localhost').pathname];
  if(!file){res.writeHead(404);return res.end('Not found');}
  res.writeHead(200,{'Content-Type':file[1]+'; charset=utf-8','Cache-Control':'no-store'});
  res.end(fs.readFileSync(path.join(root,file[0])));
}).listen(port,'127.0.0.1',()=>console.log('PredictFix mobile demo: http://127.0.0.1:'+port));

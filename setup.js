const http = require('http')
const fs = require('fs')
const path = require('path')
const { exec } = require('child_process')

const PORT = 3000
const HOST = '127.0.0.1'
const PROJECT_ROOT = __dirname

// --- File generation templates ---

function generateCaddyfile(subdomain, domain) {
  return `{
    auto_https off
}

${subdomain}.${domain} {
    tls /etc/caddy/certs/origin.pem /etc/caddy/certs/origin-key.pem

    header Access-Control-Allow-Origin "*"
    header Access-Control-Allow-Methods "POST, OPTIONS"
    header Access-Control-Allow-Headers "*"

    @options method OPTIONS
    respond @options 204

    handle /api/embed/*/stream-chat {
        reverse_proxy pii-proxy:8000 {
            flush_interval -1
        }
    }

    handle {
        reverse_proxy anythingllm:3001
    }
}
`
}

function generateCaddyCompose(volumePath) {
  return `services:
  caddy:
    image: caddy:2-alpine
    container_name: caddy
    restart: unless-stopped
    ports:
      - '80:80'
      - '443:443'
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./certs:/etc/caddy/certs:ro
      - ${volumePath}/caddy:/data
    networks:
      - caddy-net

networks:
  caddy-net:
    external: true
`
}

function generateAnythingllmCompose(volumePath) {
  return `services:
  anythingllm:
    image: mintplexlabs/anythingllm
    container_name: anythingllm
    restart: unless-stopped
    cap_add:
      - SYS_ADMIN
    volumes:
      - ${volumePath}/anythingllm:/app/server/storage
    environment:
      - STORAGE_DIR=/app/server/storage
    networks:
      - caddy-net

networks:
  caddy-net:
    external: true
`
}

function generateMiddlewareCompose() {
  return `services:
  pii-proxy:
    build: ./pii-proxy
    container_name: pii-proxy
    restart: unless-stopped
    expose:
      - '8000'
    environment:
      - ANYTHINGLLM_BASE_URL=http://anythingllm:3001
      - LOG_LEVEL=info
      - SESSION_TTL_HOURS=24
      - SCRUB_SCORE_THRESHOLD=0.35
    networks:
      - caddy-net

networks:
  caddy-net:
    external: true
`
}

function generateRootCompose() {
  return `include:
  - path: caddy/docker-compose.yml
  - path: anythingllm/docker-compose.yml
  - path: middleware/docker-compose.yml

networks:
  caddy-net:
    driver: bridge
`
}

// --- Path safety ---

function safePath(relativePath) {
  const resolved = path.resolve(PROJECT_ROOT, relativePath)
  if (!resolved.startsWith(PROJECT_ROOT + path.sep) && resolved !== PROJECT_ROOT) {
    return null
  }
  return resolved
}

// --- HTTP server ---

const server = http.createServer((req, res) => {
  // Serve the setup UI
  if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) {
    const htmlPath = path.join(PROJECT_ROOT, 'setup.html')
    fs.readFile(htmlPath, (err, data) => {
      if (err) {
        res.writeHead(500, { 'Content-Type': 'text/plain' })
        res.end('Failed to load setup.html')
        return
      }
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(data)
    })
    return
  }

  // Write config files
  if (req.method === 'POST' && req.url === '/api/write-files') {
    let body = ''
    req.on('data', (chunk) => {
      body += chunk
    })
    req.on('end', () => {
      try {
        const config = JSON.parse(body)
        const { subdomain, domain, volumePath } = config

        if (!subdomain || !domain || !volumePath) {
          res.writeHead(400, { 'Content-Type': 'application/json' })
          res.end(JSON.stringify({ error: 'Missing required fields: subdomain, domain, volumePath' }))
          return
        }

        const files = {
          'caddy/Caddyfile': generateCaddyfile(subdomain, domain),
          'caddy/docker-compose.yml': generateCaddyCompose(volumePath),
          'anythingllm/docker-compose.yml': generateAnythingllmCompose(volumePath),
          'middleware/docker-compose.yml': generateMiddlewareCompose(),
          'docker-compose.yml': generateRootCompose()
        }

        const results = {}

        for (const [relPath, content] of Object.entries(files)) {
          const absPath = safePath(relPath)
          if (!absPath) {
            results[relPath] = { ok: false, error: 'Path rejected (outside project root)' }
            continue
          }

          try {
            const dir = path.dirname(absPath)
            if (!fs.existsSync(dir)) {
              fs.mkdirSync(dir, { recursive: true })
            }
            fs.writeFileSync(absPath, content, 'utf8')
            results[relPath] = { ok: true }
            console.log(`  ✓ Wrote ${relPath}`)
          } catch (writeErr) {
            results[relPath] = { ok: false, error: writeErr.message }
            console.error(`  ✗ Failed ${relPath}: ${writeErr.message}`)
          }
        }

        const allOk = Object.values(results).every((r) => r.ok)
        console.log(allOk ? '\n  All files written successfully.\n' : '\n  Some files failed — see above.\n')

        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ results }))
      } catch (parseErr) {
        res.writeHead(400, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: 'Invalid JSON' }))
      }
    })
    return
  }

  // 404
  res.writeHead(404, { 'Content-Type': 'text/plain' })
  res.end('Not found')
})

server.listen(PORT, HOST, () => {
  const url = `http://${HOST}:${PORT}`
  console.log(`\n  Pixel Assist Setup Tool`)
  console.log(`  ───────────────────────`)
  console.log(`  Running at ${url}`)
  console.log(`  Project root: ${PROJECT_ROOT}\n`)

  // Auto-open browser (macOS)
  const openCmd = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'start' : 'xdg-open'
  exec(`${openCmd} ${url}`)
})

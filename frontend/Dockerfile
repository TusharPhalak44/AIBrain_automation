# Multi-stage Dockerfile for XM Global MT5 Trading Portal V2 Frontend + Nginx
# Stage 1: Build Vite + React + TypeScript bundle
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies cleanly using lockfile
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy frontend source and build with relative API/WS paths (proxied by Nginx)
COPY frontend/ ./
ENV VITE_API_URL=""
RUN npm run build

# Stage 2: Serve static assets & reverse-proxy /api and /ws via Nginx
FROM nginx:1.27-alpine

# Remove default nginx config
RUN rm -f /etc/nginx/conf.d/default.conf

# Copy production Nginx config and built SPA assets
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/nginx-health || exit 1

CMD ["nginx", "-g", "daemon off;"]


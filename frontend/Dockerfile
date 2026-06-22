# syntax=docker/dockerfile:1
# Multi-stage build: compile the Vite SPA, then serve the static output through
# Nginx, which also reverse-proxies /api to the FastAPI `backend` container.

# --- Build stage -----------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

# Install deps from the lockfile first so this layer caches independently of src.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# API base is relative (/api/v1) by default, so nothing host-specific is baked
# into the bundle — the same image runs on any host/IP.
RUN npm run build

# --- Runtime stage ---------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# Replace the stock server block with our SPA + API reverse-proxy config.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Ship the compiled assets to Nginx's web root.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

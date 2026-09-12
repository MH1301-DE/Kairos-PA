# syntax=docker/dockerfile:1
FROM node:22-slim AS builder
WORKDIR /build
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY --from=builder /build/build ./build

# Runtime env (set via docker-compose/.env, not baked into the image):
#   PORT   -- adapter-node listens here, defaults to 3000
#   ORIGIN -- required by SvelteKit's form-action CSRF check behind a
#             reverse proxy, e.g. https://kairos.example.com
EXPOSE 3000
CMD ["node", "build/index.js"]

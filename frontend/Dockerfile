# FairClip Web — Next.js 14
# Build context: the frontend/ directory
# Set FAIRCLIP_BACKEND at build time (it is baked into the Next.js rewrites):
#   docker build --build-arg FAIRCLIP_BACKEND=http://api:8000 -t fairclip-web .
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:20-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG FAIRCLIP_BACKEND=http://127.0.0.1:8000
ENV FAIRCLIP_BACKEND=$FAIRCLIP_BACKEND
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./
COPY --from=build /app/next.config.mjs ./
EXPOSE 3000
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]

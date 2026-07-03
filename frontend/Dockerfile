# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS builder
WORKDIR /app

ENV NODE_ENV=development \
    CI=true

COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .

ENV NODE_ENV=production
RUN npm run build


FROM nginx:1.27-alpine AS runtime

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -q -O - http://127.0.0.1/healthz >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]

FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY app ./app
COPY next.config.mjs postcss.config.mjs ./
RUN npm run build

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
USER node
CMD ["sh", "-c", "npm start -- --hostname 0.0.0.0 --port ${PORT:-8080}"]

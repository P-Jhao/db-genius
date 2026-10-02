FROM node:24-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.1.3 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG VITE_API_BASE_URL=/api
ARG VITE_GITHUB_REPO=https://github.com/spcodhu/db-genius
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_GITHUB_REPO=$VITE_GITHUB_REPO
RUN pnpm build
FROM nginx:1.30.5-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

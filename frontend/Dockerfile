# ---- base: install deps ----
FROM node:20-alpine AS base
WORKDIR /app
COPY package.json ./
# No yarn.lock is committed in this repo — plain install rather than
# --frozen-lockfile. Recommend generating and committing yarn.lock for
# reproducible builds once this is stable.
RUN yarn install

# ---- dev: hot-reload dev server (used by docker-compose.yml) ----
FROM base AS dev
COPY . .
EXPOSE 3000
CMD ["yarn", "start"]

# ---- build: compile static production assets ----
FROM base AS build
COPY . .
# CRA/craco bakes REACT_APP_* vars into the JS bundle at build time,
# so this has to be a build ARG, not a runtime env var.
ARG REACT_APP_BACKEND_URL
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
RUN yarn build

# ---- production: serve the static build via nginx ----
FROM nginx:alpine AS production
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

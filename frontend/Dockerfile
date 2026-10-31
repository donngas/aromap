# Keep target names/ports in sync with Compose.
FROM node:24-alpine AS dependencies

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

FROM dependencies AS development
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM dependencies AS build
COPY . .
RUN npm run build

FROM nginx:stable-alpine AS production
ENV API_PROXY_TARGET=http://backend:8000 \
    FRONTEND_MAX_BODY_SIZE=12m \
    NGINX_ENVSUBST_FILTER="^(API_PROXY_TARGET|FRONTEND_MAX_BODY_SIZE)$"
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

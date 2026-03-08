FROM node:20-alpine

WORKDIR /app

COPY frontend/web-dashboard/package*.json ./
RUN npm ci

COPY frontend/web-dashboard ./

EXPOSE 5173
CMD ["npm", "run", "dev"]

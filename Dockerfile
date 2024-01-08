# Basisafbeelding voor Node.js
FROM node:14

# Werkdirectory instellen
WORKDIR /usr/src/app

# Kopieer package.json en package-lock.json (indien beschikbaar)
COPY package*.json ./

# Installeer Node.js dependencies
RUN npm install

# Kopieer de rest van je applicatiecode
COPY . .

# Stel de poort in waarop je app zal draaien
EXPOSE 3000

# CMD-instructie voor het starten van je app
CMD [ "node", "app.js" ]

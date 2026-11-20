# PostgreSQL 16 + pgvector (imagem oficial do pgvector) + PostGIS 3
# Nota: a imagem postgis/postgis:16-3.5 usa Debian bullseye, cujo repositório
# do PostgreSQL já foi retirado; por isso parte-se da imagem do pgvector.
FROM pgvector/pgvector:pg16
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      postgresql-16-postgis-3 \
      postgresql-16-postgis-3-scripts \
 && rm -rf /var/lib/apt/lists/*

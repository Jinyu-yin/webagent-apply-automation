FROM python:3.12 AS builder

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --user --no-cache-dir -r requirements.txt


# ----- 生产阶段 -----

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && \
    apt-get install -y --no-install-recommends libmariadb3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /data/WebAgent

COPY --from=builder /root/.local /root/.local
COPY . .

ENV PATH="/root/.local/bin:$PATH"

RUN sed -i 's/\r//g' ./start.sh && \
    chmod +x ./start.sh

EXPOSE 7754

ENTRYPOINT ["./start.sh"]

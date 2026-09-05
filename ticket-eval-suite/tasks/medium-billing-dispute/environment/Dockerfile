FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==8.4.1

RUN mkdir -p /workspace
COPY ticket.json /workspace/ticket.json
COPY transactions.csv /workspace/transactions.csv
COPY company_policy.md /workspace/company_policy.md

WORKDIR /workspace
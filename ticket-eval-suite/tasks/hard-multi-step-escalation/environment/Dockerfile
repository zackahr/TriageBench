FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==8.4.1 pyyaml==6.0.2

RUN mkdir -p /workspace
COPY outage_ticket.json /workspace/outage_ticket.json
COPY user_response.txt /workspace/user_response.txt
COPY config.yaml /workspace/config.yaml
COPY company_policy.md /workspace/company_policy.md

WORKDIR /workspace
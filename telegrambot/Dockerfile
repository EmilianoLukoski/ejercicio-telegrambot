FROM python:3.11-slim

WORKDIR /app

ENV TZ="America/Argentina/Buenos_Aires"

COPY ./requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

COPY . /app

CMD ["python", "telegrambot.py"]
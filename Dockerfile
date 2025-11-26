FROM python:3.11-alpine
WORKDIR /app
COPY proxy.py .
RUN pip install requests
EXPOSE 9000
CMD ["python","proxy.py"]

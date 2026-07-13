# Railway deployment image — extends the public Traccar image to template in our
# config at startup (Postgres backing, forward-to-backend). Local dev (docker-compose)
# uses traccar/traccar.xml directly (H2, unchanged) and does NOT use this Dockerfile.
FROM traccar/traccar:latest

COPY traccar.xml.template /opt/traccar/conf/traccar.xml.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /opt/traccar
ENTRYPOINT ["/entrypoint.sh"]

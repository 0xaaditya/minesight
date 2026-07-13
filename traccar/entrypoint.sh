#!/bin/sh
# Substitutes DB/forward-URL placeholders in the templated config using Railway
# environment variables, so no secret is ever baked into the image or committed to
# git. sed uses '#' as the delimiter since URLs contain '/'.
set -e

sed -e "s#__DB_URL__#${DB_URL}#g" \
    -e "s#__DB_USER__#${DB_USER}#g" \
    -e "s#__DB_PASSWORD__#${DB_PASSWORD}#g" \
    -e "s#__FORWARD_URL__#${FORWARD_URL}#g" \
    /opt/traccar/conf/traccar.xml.template > /opt/traccar/conf/traccar.xml

exec /opt/traccar/jre/bin/java -jar tracker-server.jar conf/traccar.xml

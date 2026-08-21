FROM nginx:alpine
RUN apk add --no-cache gettext
COPY nginx.conf.template /etc/nginx/conf.d/default.conf.template
COPY index.html /usr/share/nginx/html/index.html
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
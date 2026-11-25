# Go images bake the binary at build time.
# `isuctl deploy` replaces ./src with `git archive` of --branch, then
# `docker compose build` + `up -d --wait`. Editing a file in the running
# container does not change the process until that rebuild.
FROM golang:1.23-bookworm AS build
WORKDIR /src
COPY src/ ./
RUN if [ -f go.mod ]; then \
      go build -o /out/app .; \
    else \
      printf '#!/bin/sh\nexec sleep infinity\n' > /out/app && chmod +x /out/app; \
    fi

FROM debian:bookworm-slim
COPY --from=build /out/app /usr/local/bin/app
COPY --from=build /src /home/isucon/webapp
WORKDIR /home/isucon/webapp
EXPOSE 8080
CMD ["/usr/local/bin/app"]

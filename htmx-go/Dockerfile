# Build stage
FROM golang:1.24-alpine AS builder

WORKDIR /app

# Install dependencies
RUN apk add --no-cache git

# Initialize Go module if needed
COPY . .
RUN if [ ! -f go.mod ]; then \
      go mod init htmx-go && \
      go get github.com/ethereum/go-ethereum && \
      go get github.com/gorilla/mux && \
      go mod tidy; \
    fi

# Create necessary directories
RUN mkdir -p templates static

# Build the application
RUN go build -ldflags="-s -w" -o powder-app backend.go

# Runtime stage
FROM alpine:3.17

WORKDIR /app

# Install CA certificates for HTTPS
RUN apk add --no-cache ca-certificates

# Copy the compiled application
COPY --from=builder /app/powder-app /app/
COPY --from=builder /app/templates /app/templates
COPY --from=builder /app/static /app/static

# Expose the port
EXPOSE 5000

# Run the application
CMD ["/app/powder-app"]

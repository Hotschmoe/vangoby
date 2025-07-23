# Multi-stage build for Go application
FROM golang:1.21-alpine AS builder

# Install git and ca-certificates for dependency fetching
RUN apk add --no-cache git ca-certificates

# Set working directory
WORKDIR /app

# Copy go module files
COPY go.mod ./

# Copy source code
COPY main.go ./

# Download dependencies and generate go.sum
RUN go mod tidy

# Build the application with optimizations
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o vangoby .

# Final stage: minimal runtime image
FROM alpine:latest

# Install ca-certificates for HTTPS requests
RUN apk --no-cache add ca-certificates

# Create app directory and user
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup

WORKDIR /app

# Copy the binary from builder stage
COPY --from=builder /app/vangoby .

# Copy the HTML file (needed for serving the frontend)
COPY src/index.html src/

# Change ownership to non-root user
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:5000/node-status || exit 1

# Run the application
CMD ["./vangoby"]
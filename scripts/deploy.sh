#!/usr/bin/env bash
set -e

echo "=========================================="
echo "🚀 Running ws-agent Deployment..."
echo "=========================================="

PREV_COMMIT=$(git rev-parse HEAD@{1} 2>/dev/null || echo "")
NEW_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "")

if [ -n "$PREV_COMMIT" ] && [ "$PREV_COMMIT" != "$NEW_COMMIT" ]; then
  CHANGED_FILES=$(git diff --name-only "$PREV_COMMIT" "$NEW_COMMIT" 2>/dev/null || true)
else
  CHANGED_FILES=""
fi

echo "📄 Changed files since last pull:"
echo "${CHANGED_FILES:-"(no file diff detected)"}"

echo "🔨 Building and restarting container with Docker Compose..."
docker compose up -d --build

echo "⏳ Waiting 5s for container to initialize..."
sleep 5

echo "🔍 Checking container status..."
if docker compose ps | grep -q "Up\|running"; then
  echo "✅ Container is running!"
  echo ""
  echo "=========================================="
  echo "🚀 Deployment completed successfully!"
  echo "=========================================="
else
  echo "❌ Container failed to start. Recent logs:"
  docker compose logs --tail=50
  exit 1
fi
